import logging
import schedule
import time
from datetime import datetime

from auth import login
from config import (
    MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF_TIME,
    TRADING_MODE, MAX_VIX, UNDERLYING,
)
from market_data import get_index_data, get_vix
from news_sentiment import get_sentiment
from options_trader import OptionsManager
from strategies import (
    MACrossoverStrategy,
    RSIStrategy,
    VWAPBreakoutStrategy,
    CandlestickStrategy,
    SupertrendStrategy,
    get_market_regime,
)
from strategies.base import Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
)
logger = logging.getLogger(__name__)

# Candles needed: 5-min bars over last 5 days gives ~375 candles — plenty for all indicators
_INDEX_MAP = {
    "BANKNIFTY": "NIFTY BANK",
    "NIFTY":     "NIFTY 50",
}


def is_market_open() -> bool:
    now = datetime.now().strftime("%H:%M")
    return MARKET_OPEN <= now < MARKET_CLOSE


def is_square_off_time() -> bool:
    now = datetime.now().strftime("%H:%M")
    return now >= SQUARE_OFF_TIME


def run_options_bot(kite, options_manager: OptionsManager):
    now_str = datetime.now().strftime("%H:%M")

    if not is_market_open():
        logger.info(f"[BOT] Market closed ({now_str}) — sleeping")
        return

    # Always monitor any open position first
    if options_manager.has_position():
        options_manager.monitor_and_exit()

    if is_square_off_time():
        logger.info("[BOT] Square-off time reached — closing all positions")
        options_manager.square_off()
        options_manager.daily_summary()
        return

    # Don't open a new position if we already have one
    if options_manager.has_position():
        return

    # ── Gate 1: India VIX ─────────────────────────────────────────────────
    try:
        vix = get_vix(kite)
        logger.info(f"[VIX] India VIX = {vix:.2f} (limit: {MAX_VIX})")
        if vix > MAX_VIX:
            logger.info(f"[VIX] VIX too high ({vix:.2f} > {MAX_VIX}) — no trade today")
            return
    except Exception as e:
        logger.warning(f"[VIX] Could not fetch VIX: {e} — skipping VIX gate")

    # ── Gate 2: Market regime (NIFTY 50 EMA20 vs EMA50 daily) ─────────────
    regime = get_market_regime(kite)
    logger.info(f"[REGIME] Market regime: {regime.upper()}")
    if regime == "neutral":
        logger.info("[REGIME] Undetermined regime — skipping")
        return

    # ── Gate 3: News sentiment ─────────────────────────────────────────────
    sentiment = get_sentiment()
    logger.info(f"[NEWS] Sentiment: {sentiment.upper()}")

    # Sentiment must not directly contradict the regime
    if regime == "bull" and sentiment == "bearish":
        logger.info("[NEWS] Bearish sentiment contradicts bull regime — skipping")
        return
    if regime == "bear" and sentiment == "bullish":
        logger.info("[NEWS] Bullish sentiment contradicts bear regime — skipping")
        return

    # ── Gate 4: Multi-indicator consensus on the underlying ────────────────
    index_name = _INDEX_MAP.get(UNDERLYING, "NIFTY BANK")
    try:
        df = get_index_data(kite, index_name, interval="5minute", days=5)
    except Exception as e:
        logger.error(f"[DATA] Cannot fetch {index_name} data: {e}")
        return

    strategies = [
        MACrossoverStrategy(UNDERLYING),
        RSIStrategy(UNDERLYING),
        VWAPBreakoutStrategy(UNDERLYING),
        CandlestickStrategy(UNDERLYING),
        SupertrendStrategy(UNDERLYING),
    ]

    signal_map = {}
    signals    = []
    for strat in strategies:
        try:
            sig = strat.generate_signal(df)
            signal_map[strat.__class__.__name__] = sig
            signals.append(sig)
            logger.info(f"[{strat.__class__.__name__}] {sig.signal.value} — {sig.reason}")
        except Exception as e:
            logger.warning(f"[{strat.__class__.__name__}] Error: {e}")

    if not signals:
        logger.warning("[CONSENSUS] No signals generated — skipping")
        return

    buy_votes  = sum(1 for s in signals if s.signal == Signal.BUY)
    sell_votes = sum(1 for s in signals if s.signal == Signal.SELL)
    total      = len(signals)

    logger.info(f"[CONSENSUS] BUY: {buy_votes}/{total} | SELL: {sell_votes}/{total} | Regime: {regime}")

    # Supertrend veto — if Supertrend strongly disagrees, block the trade
    st_sig = signal_map.get("SupertrendStrategy")

    # Need 2/5 indicators in agreement (Option A: looser entry, tighter VIX filter)
    threshold = 2

    if regime == "bull" and buy_votes >= threshold:
        if st_sig and st_sig.signal == Signal.SELL:
            logger.info("[VETO] Supertrend bearish — blocking CE entry despite bull regime")
            return
        reason = f"Bull regime + {buy_votes}/{total} indicators agree BUY + {sentiment} sentiment"
        logger.info(f"[SIGNAL] Entering CE (Call) — {reason}")
        options_manager.enter("CE", reason)

    elif regime == "bear" and sell_votes >= threshold:
        if st_sig and st_sig.signal == Signal.BUY:
            logger.info("[VETO] Supertrend bullish — blocking PE entry despite bear regime")
            return
        reason = f"Bear regime + {sell_votes}/{total} indicators agree SELL + {sentiment} sentiment"
        logger.info(f"[SIGNAL] Entering PE (Put) — {reason}")
        options_manager.enter("PE", reason)

    else:
        logger.info(f"[CONSENSUS] No consensus — need {threshold}/{total}, got BUY:{buy_votes} SELL:{sell_votes}")


def main():
    logger.info("=" * 60)
    logger.info(f"  KITE OPTIONS BOT — {TRADING_MODE.upper()} MODE")
    logger.info(f"  Underlying: {UNDERLYING}")
    logger.info(f"  Max VIX: {MAX_VIX}  |  Square-off: {SQUARE_OFF_TIME} IST")
    logger.info("=" * 60)

    kite            = login()
    options_manager = OptionsManager(kite)

    # Run every 5 minutes during market hours
    schedule.every(5).minutes.do(run_options_bot, kite=kite, options_manager=options_manager)

    # Run once immediately on startup
    run_options_bot(kite, options_manager)

    logger.info("[BOT] Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == "__main__":
    main()
