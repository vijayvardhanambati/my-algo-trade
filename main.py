import logging
import time
from datetime import datetime

from auth import login
from config import (
    MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF_TIME, TRADING_MODE,
    VIX_NO_TRADE_BELOW, VIX_SELLER_MAX, VIX_BUYER_MAX,
    MORNING_SESSION_START, MORNING_SESSION_END,
    AFTERNOON_SESSION_START, AFTERNOON_SESSION_END,
    WATCHLIST,
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
_MAX_VOTES = sum(_WEIGHTS.values())   # 9
THRESHOLD  = 4                        # need 4/9 weighted votes to enter


def is_market_open() -> bool:
    return MARKET_OPEN <= datetime.now().strftime("%H:%M") < MARKET_CLOSE


def is_square_off_time() -> bool:
    return datetime.now().strftime("%H:%M") >= SQUARE_OFF_TIME


def is_good_trading_window() -> bool:
    now = datetime.now().strftime("%H:%M")
    return (MORNING_SESSION_START <= now <= MORNING_SESSION_END or
            AFTERNOON_SESSION_START <= now <= AFTERNOON_SESSION_END)


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
    """Called every 5 seconds when a position is open."""
    if options_manager.has_position():
        options_manager.monitor_and_exit()
    if spread_manager.has_position():
        spread_manager.monitor_and_exit()

    if is_square_off_time():
        logger.info("[BOT] Square-off time — closing everything")
        options_manager.square_off()
        spread_manager.square_off()
        options_manager.daily_summary()
        spread_manager.daily_summary()


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


def run_seller_mode(spread_manager: SpreadManager, regime: str):
    if spread_manager.has_position():
        return
    if regime == "neutral":
        return
    spread_manager.enter(regime, f"SELLER | {regime.upper()} regime, low VIX")


def scan_for_entry(kite, options_manager: OptionsManager, spread_manager: SpreadManager):
    """Called every 5 minutes when no position is open — looks for trade setups."""
    now_str = datetime.now().strftime("%H:%M")

    if not is_market_open():
        logger.info(f"[BOT] Market closed ({now_str})")
        return

    if is_square_off_time():
        return

    if not is_good_trading_window():
        logger.info(f"[BOT] Outside active window ({now_str}) — waiting")
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

    regime = get_market_regime(kite)
    if regime == "neutral":
        logger.info("[REGIME] Neutral — skipping")
        return

    if VIX_NO_TRADE_BELOW <= vix < VIX_SELLER_MAX:
        logger.info(f"[MODE] SELLER (VIX={vix:.2f})")
        run_seller_mode(spread_manager, regime)

    elif VIX_SELLER_MAX <= vix <= VIX_BUYER_MAX:
        logger.info(f"[MODE] BUYER (VIX={vix:.2f})")
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
    options_manager = OptionsManager(kite)
    spread_manager  = SpreadManager(kite)

    last_scan = 0  # timestamp of last entry scan

    logger.info("[BOT] Running. Press Ctrl+C to stop.")

    while True:
        has_position = options_manager.has_position() or spread_manager.has_position()

        if has_position:
            # In a trade — monitor every 5 seconds for SL/target
            monitor_positions(options_manager, spread_manager)
            # If position just closed, scan immediately for the next trade
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
            time.sleep(15)  # short sleep so we notice when a new position opens quickly


if __name__ == "__main__":
    main()
