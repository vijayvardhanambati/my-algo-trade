import json
import logging
import os
import time
from datetime import date, datetime

from auth import login
from config import (
    MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF_TIME, TRADING_MODE,
    VIX_NO_TRADE_BELOW, VIX_SELLER_MAX, VIX_BUYER_MAX,
    WATCHLIST, UNDERLYING,
)
from market_data import get_candles, get_vix
from news_sentiment import get_sentiment
from options_trader import OptionsManager
from spread_trader import SpreadManager
from strategies import (
    MACrossoverStrategy, RSIStrategy, VWAPBreakoutStrategy,
    CandlestickStrategy, SupertrendStrategy, ADXStrategy, get_market_regime,
)
from strategies.base import Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
)
logger = logging.getLogger(__name__)

MONITOR_INTERVAL = 5    # seconds — how often to check open positions
SCAN_INTERVAL    = 300  # seconds — how often to scan for new entries (5 minutes)

# Weighted consensus — more reliable indicators count more.
# ADX also acts as a hard veto: if it returns HOLD (choppy market), the symbol is skipped.
_WEIGHTS = {
    "SupertrendStrategy":   2,  # reliable trend-following
    "RSIStrategy":          2,  # momentum confirmation
    "ADXStrategy":          2,  # trend strength (HOLD = hard veto)
    "VWAPBreakoutStrategy": 1,
    "CandlestickStrategy":  1,
    "MACrossoverStrategy":  1,
}
_MAX_VOTES   = sum(_WEIGHTS.values())   # 9
THRESHOLD    = 4                        # need 4/9 weighted votes to enter
HISTORY_FILE = "trade_history.json"


# ---------------------------------------------------------------------------
# Day-over-day performance tracking
# ---------------------------------------------------------------------------

def _load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_daily_record(options_manager: "OptionsManager", spread_manager: "SpreadManager"):
    """Persist today's results before daily_summary() resets trade_log."""
    s_log = spread_manager.trade_log
    o_log = options_manager.trade_log
    record = {
        "date":           date.today().isoformat(),
        "spread_trades":  len(s_log),
        "spread_wins":    sum(1 for t in s_log if t["pnl"] > 0),
        "spread_pnl":     round(sum(t["pnl"] for t in s_log), 2),
        "options_trades": len(o_log),
        "options_wins":   sum(1 for t in o_log if t["pnl"] > 0),
        "options_pnl":    round(sum(t["pnl"] for t in o_log), 2),
        "total_pnl":      round(sum(t["pnl"] for t in s_log + o_log), 2),
    }
    history = [r for r in _load_history() if r["date"] != record["date"]]
    history.append(record)
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history[-30:], f, indent=2)
        logger.info(f"[BOT] Day saved — total P&L today: ₹{record['total_pnl']:+.0f}")
    except Exception as e:
        logger.warning(f"[BOT] Could not save history: {e}")


def _display_history():
    """Print last 7 sessions on startup so the operator sees recent performance."""
    history = _load_history()
    if not history:
        return
    last_n    = history[-7:]
    s_trades  = sum(r["spread_trades"] for r in last_n)
    s_wins    = sum(r["spread_wins"]   for r in last_n)
    total_pnl = sum(r["total_pnl"]     for r in last_n)
    win_rate  = (s_wins / s_trades * 100) if s_trades else 0
    logger.info(f"[HISTORY] Last {len(last_n)} session(s) | Spread win rate: {win_rate:.0f}% | Cumulative P&L: ₹{total_pnl:+.0f}")
    for r in last_n[-5:]:
        logger.info(
            f"[HISTORY]   {r['date']} | "
            f"Spreads {r['spread_trades']} ({r['spread_wins']}W) ₹{r['spread_pnl']:+.0f} | "
            f"Options {r['options_trades']} ({r['options_wins']}W) ₹{r['options_pnl']:+.0f} | "
            f"Total ₹{r['total_pnl']:+.0f}"
        )


def is_market_open() -> bool:
    return MARKET_OPEN <= datetime.now().strftime("%H:%M") < MARKET_CLOSE


def is_square_off_time() -> bool:
    return datetime.now().strftime("%H:%M") >= SQUARE_OFF_TIME



def _score_symbol(kite, symbol: str):
    """
    Run all 6 strategies on one symbol with weighted voting.
    Returns (signal_map, buy_votes, sell_votes, max_possible_votes).
    Reliable indicators (Supertrend, RSI, ADX) count 2× vs 1× for others.
    """
    df = get_candles(kite, symbol)
    strategies = [
        MACrossoverStrategy(symbol),
        RSIStrategy(symbol),
        VWAPBreakoutStrategy(symbol),
        CandlestickStrategy(symbol),
        SupertrendStrategy(symbol),
        ADXStrategy(symbol),
    ]
    signal_map = {}
    buy_votes = sell_votes = 0
    for strat in strategies:
        name   = strat.__class__.__name__
        weight = _WEIGHTS.get(name, 1)
        try:
            sig = strat.generate_signal(df)
            signal_map[name] = sig
            if sig.signal == Signal.BUY:
                buy_votes  += weight
            elif sig.signal == Signal.SELL:
                sell_votes += weight
            logger.info(f"  [{symbol}][{name}] {sig.signal.value} (w={weight}) — {sig.reason}")
        except Exception as e:
            logger.warning(f"  [{symbol}][{name}] Error: {e}")
    return signal_map, buy_votes, sell_votes, _MAX_VOTES


def find_best_signal(kite, regime: str):
    """
    Score every symbol in WATCHLIST and return the one with the strongest consensus.
    Returns (symbol, direction, reason) or (None, None, "") if nothing qualifies.
    Applies Supertrend veto: if Supertrend opposes the direction, that symbol is skipped.
    """
    candidates = []
    logger.info(f"[SCAN] Scoring {len(WATCHLIST)} symbols (regime={regime.upper()}) ...")

    for symbol in WATCHLIST:
        try:
            signal_map, buy_votes, sell_votes, total = _score_symbol(kite, symbol)

            # Hard veto 1: ADX < 20 means choppy market — skip regardless of other signals
            adx_sig = signal_map.get("ADXStrategy")
            if adx_sig and adx_sig.signal == Signal.HOLD:
                logger.info(f"  [VETO] {symbol}: ADX choppy — no trend, skipping")
                continue

            # Hard veto 2: Supertrend must not oppose the trade direction
            st_sig = signal_map.get("SupertrendStrategy")

            if regime == "bull" and buy_votes >= THRESHOLD:
                if st_sig and st_sig.signal == Signal.SELL:
                    logger.info(f"  [VETO] {symbol}: Supertrend bearish — CE blocked")
                    continue
                candidates.append((symbol, "CE", buy_votes, total))

            elif regime == "bear" and sell_votes >= THRESHOLD:
                if st_sig and st_sig.signal == Signal.BUY:
                    logger.info(f"  [VETO] {symbol}: Supertrend bullish — PE blocked")
                    continue
                candidates.append((symbol, "PE", sell_votes, total))

        except Exception as e:
            logger.warning(f"  [SCAN] {symbol}: {e}")

    if not candidates:
        return None, None, ""

    candidates.sort(key=lambda x: x[2], reverse=True)
    symbol, direction, votes, total = candidates[0]
    reason = f"{symbol} | {direction} | {votes}/{total} consensus | {regime.upper()} regime"
    logger.info(f"[WINNER] {reason}")
    return symbol, direction, reason


def monitor_positions(options_manager: OptionsManager, spread_manager: SpreadManager):
    """Called every 5 seconds when a position is open — checks SL/target only."""
    if options_manager.has_position():
        options_manager.monitor_and_exit()
    if spread_manager.has_position():
        spread_manager.monitor_and_exit()


def run_buyer_mode(kite, options_manager: OptionsManager, regime: str, sentiment: str):
    if options_manager.has_position():
        return

    symbol, direction, reason = find_best_signal(kite, regime)
    if symbol is None:
        logger.info(f"[BUYER] No qualifying signal across {len(WATCHLIST)} symbols — {regime.upper()} regime")
        return

    if regime == "bull" and sentiment == "bearish":
        logger.info(f"[NEWS] Bearish sentiment — skipping {symbol} CE")
        return
    if regime == "bear" and sentiment == "bullish":
        logger.info(f"[NEWS] Bullish sentiment — skipping {symbol} PE")
        return

    options_manager.enter(direction, f"BUYER | {reason} | {sentiment}", symbol)


def run_seller_mode(kite, spread_manager: SpreadManager, sentiment: str):
    if spread_manager.has_position():
        return

    logger.info(f"[SELLER] Scoring {UNDERLYING} across all strategies ...")
    signal_map, buy_votes, sell_votes, total = _score_symbol(kite, UNDERLYING)

    # ADX hard veto: choppy/trendless market → no credit spreads
    adx_sig = signal_map.get("ADXStrategy")
    if adx_sig and adx_sig.signal == Signal.HOLD:
        logger.info("[SELLER] ADX choppy — no clear trend, skipping spread entry")
        return

    # News sentiment adds 1 vote to tip the balance when signals are mixed
    if sentiment == "bullish":
        buy_votes += 1
    elif sentiment == "bearish":
        sell_votes += 1
    logger.info(
        f"[SELLER] Final votes — bull:{buy_votes} bear:{sell_votes} / {total + 1} "
        f"(need {THRESHOLD}+ with clear lead) | news={sentiment}"
    )

    st_sig = signal_map.get("SupertrendStrategy")

    if buy_votes >= THRESHOLD and buy_votes > sell_votes:
        if st_sig and st_sig.signal == Signal.SELL:
            logger.info("[SELLER] Supertrend bearish — blocking BULL_PUT despite bullish consensus")
            return
        spread_manager.enter(
            "bull",
            f"SELLER | {buy_votes}/{total + 1} bull votes | {sentiment} news | BULL_PUT"
        )
    elif sell_votes >= THRESHOLD and sell_votes > buy_votes:
        if st_sig and st_sig.signal == Signal.BUY:
            logger.info("[SELLER] Supertrend bullish — blocking BEAR_CALL despite bearish consensus")
            return
        spread_manager.enter(
            "bear",
            f"SELLER | {sell_votes}/{total + 1} bear votes | {sentiment} news | BEAR_CALL"
        )
    else:
        logger.info(
            f"[SELLER] No clear edge — bull:{buy_votes} bear:{sell_votes} — skipping"
        )


def scan_for_entry(kite, options_manager: OptionsManager, spread_manager: SpreadManager):
    """Called every 5 minutes when no position is open — looks for trade setups."""
    now_str = datetime.now().strftime("%H:%M")

    if not is_market_open():
        logger.info(f"[BOT] Market closed ({now_str})")
        return

    if is_square_off_time():
        return

    try:
        vix = get_vix(kite)
        logger.info(f"[VIX] India VIX = {vix:.2f}")
    except Exception as e:
        logger.warning(f"[VIX] Could not fetch: {e}")
        return

    if vix < VIX_NO_TRADE_BELOW:
        logger.info(f"[VIX] Too low ({vix:.2f}) — skipping")
        return
    if vix > VIX_BUYER_MAX:
        logger.info(f"[VIX] Too high ({vix:.2f}) — skipping")
        return

    if VIX_NO_TRADE_BELOW <= vix < VIX_SELLER_MAX:
        logger.info(f"[MODE] SELLER (VIX={vix:.2f})")
        sentiment = get_sentiment()
        logger.info(f"[NEWS] Sentiment: {sentiment.upper()}")
        run_seller_mode(kite, spread_manager, sentiment)

    elif VIX_SELLER_MAX <= vix <= VIX_BUYER_MAX:
        logger.info(f"[MODE] BUYER (VIX={vix:.2f})")
        regime = get_market_regime(kite)
        if regime == "neutral":
            logger.info("[REGIME] Neutral — skipping")
            return
        sentiment = get_sentiment()
        logger.info(f"[NEWS] Sentiment: {sentiment.upper()}")
        if regime == "bull" and sentiment == "bearish":
            logger.info("[NEWS] Contradicts bull regime — skipping")
            return
        if regime == "bear" and sentiment == "bullish":
            logger.info("[NEWS] Contradicts bear regime — skipping")
            return
        run_buyer_mode(kite, options_manager, regime, sentiment)


def main():
    logger.info("=" * 60)
    logger.info(f"  KITE OPTIONS BOT — {TRADING_MODE.upper()} MODE")
    logger.info(f"  Watchlist  : {', '.join(WATCHLIST)}")
    logger.info(f"  VIX < {VIX_NO_TRADE_BELOW}   → no trade")
    logger.info(f"  VIX {VIX_NO_TRADE_BELOW}–{VIX_SELLER_MAX}  → SELLER mode (credit spreads)")
    logger.info(f"  VIX {VIX_SELLER_MAX}–{VIX_BUYER_MAX} → BUYER mode  (CE/PE buying)")
    logger.info(f"  VIX > {VIX_BUYER_MAX}   → no trade")
    logger.info(f"  Monitoring : every {MONITOR_INTERVAL}s when in trade | every {SCAN_INTERVAL}s when idle")
    logger.info(f"  Square-off : {SQUARE_OFF_TIME} IST")
    logger.info("=" * 60)

    kite            = login()
    _display_history()
    options_manager = OptionsManager(kite)
    spread_manager  = SpreadManager(kite)

    last_scan = 0
    eod_done  = False

    logger.info("[BOT] Running. Press Ctrl+C to stop.")

    while True:
        # EOD block — runs once per day, handles close + save + summary
        if is_square_off_time():
            if not eod_done:
                if options_manager.has_position() or spread_manager.has_position():
                    logger.info("[BOT] Square-off time — force-closing all positions")
                    options_manager.square_off()
                    spread_manager.square_off()
                _save_daily_record(options_manager, spread_manager)
                options_manager.daily_summary()
                spread_manager.daily_summary()
                eod_done = True
            time.sleep(300)
            continue

        eod_done = False  # reset each morning

        has_position = options_manager.has_position() or spread_manager.has_position()

        if has_position:
            # In a trade — monitor every 5 seconds for SL/target/trail
            monitor_positions(options_manager, spread_manager)
            # Position just closed → scan immediately for re-entry
            if not (options_manager.has_position() or spread_manager.has_position()):
                logger.info("[BOT] Position closed — scanning immediately for next entry")
                last_scan = 0
            time.sleep(MONITOR_INTERVAL)
        else:
            # No trade — scan for entry every 5 minutes
            now = time.time()
            if now - last_scan >= SCAN_INTERVAL:
                scan_for_entry(kite, options_manager, spread_manager)
                last_scan = now
            time.sleep(15)


if __name__ == "__main__":
    main()
