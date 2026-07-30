import logging
import schedule
import time
from datetime import datetime

from auth import login
from config import (
    MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF_TIME, TRADING_MODE, UNDERLYING,
    VIX_NO_TRADE_BELOW, VIX_SELLER_MAX, VIX_BUYER_MAX,
    MORNING_SESSION_START, MORNING_SESSION_END,
    AFTERNOON_SESSION_START, AFTERNOON_SESSION_END,
)
from market_data import get_index_data, get_vix
from news_sentiment import get_sentiment
from options_trader import OptionsManager
from spread_trader import SpreadManager
from strategies import (
    MACrossoverStrategy, RSIStrategy, VWAPBreakoutStrategy,
    CandlestickStrategy, SupertrendStrategy, get_market_regime,
)
from strategies.base import Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
)
logger = logging.getLogger(__name__)

_INDEX_MAP = {"BANKNIFTY": "NIFTY BANK", "NIFTY": "NIFTY 50"}


def is_market_open() -> bool:
    now = datetime.now().strftime("%H:%M")
    return MARKET_OPEN <= now < MARKET_CLOSE


def is_square_off_time() -> bool:
    return datetime.now().strftime("%H:%M") >= SQUARE_OFF_TIME


def is_good_trading_window() -> bool:
    now = datetime.now().strftime("%H:%M")
    return (MORNING_SESSION_START <= now <= MORNING_SESSION_END or
            AFTERNOON_SESSION_START <= now <= AFTERNOON_SESSION_END)


def _get_signals(kite):
    """Run all 5 indicators and return (signal_map, buy_votes, sell_votes, total)."""
    index_name = _INDEX_MAP.get(UNDERLYING, "NIFTY 50")
    df = get_index_data(kite, index_name, interval="5minute", days=5)

    strategies = [
        MACrossoverStrategy(UNDERLYING),
        RSIStrategy(UNDERLYING),
        VWAPBreakoutStrategy(UNDERLYING),
        CandlestickStrategy(UNDERLYING),
        SupertrendStrategy(UNDERLYING),
    ]

    signal_map, signals = {}, []
    for strat in strategies:
        try:
            sig = strat.generate_signal(df)
            signal_map[strat.__class__.__name__] = sig
            signals.append(sig)
            logger.info(f"[{strat.__class__.__name__}] {sig.signal.value} — {sig.reason}")
        except Exception as e:
            logger.warning(f"[{strat.__class__.__name__}] Error: {e}")

    buy_votes  = sum(1 for s in signals if s.signal == Signal.BUY)
    sell_votes = sum(1 for s in signals if s.signal == Signal.SELL)
    return signal_map, buy_votes, sell_votes, len(signals)


def run_buyer_mode(kite, options_manager: OptionsManager, regime: str, sentiment: str):
    """Enter CE/PE options — best when VIX is 13–18 (enough movement)."""
    if options_manager.has_position():
        return
    if options_manager.daily_target_reached():
        return

    try:
        signal_map, buy_votes, sell_votes, total = _get_signals(kite)
    except Exception as e:
        logger.error(f"[BUYER] Cannot fetch signals: {e}")
        return

    logger.info(f"[CONSENSUS] BUY: {buy_votes}/{total} | SELL: {sell_votes}/{total} | Regime: {regime}")
    st_sig    = signal_map.get("SupertrendStrategy")
    threshold = 2

    if regime == "bull" and buy_votes >= threshold:
        if st_sig and st_sig.signal == Signal.SELL:
            logger.info("[VETO] Supertrend bearish — blocking CE entry")
            return
        reason = f"BUYER | Bull + {buy_votes}/{total} BUY + {sentiment}"
        logger.info(f"[SIGNAL] Entering CE — {reason}")
        options_manager.enter("CE", reason)

    elif regime == "bear" and sell_votes >= threshold:
        if st_sig and st_sig.signal == Signal.BUY:
            logger.info("[VETO] Supertrend bullish — blocking PE entry")
            return
        reason = f"BUYER | Bear + {sell_votes}/{total} SELL + {sentiment}"
        logger.info(f"[SIGNAL] Entering PE — {reason}")
        options_manager.enter("PE", reason)

    else:
        logger.info(f"[CONSENSUS] No consensus — need {threshold}/{total}, got BUY:{buy_votes} SELL:{sell_votes}")


def run_seller_mode(kite, spread_manager: SpreadManager, regime: str):
    """Enter credit spreads — best when VIX is 11–13 (low vol, theta decay)."""
    if spread_manager.has_position():
        return
    if spread_manager.daily_target_reached():
        return

    # For credit spreads we only need regime — no need for 5-indicator consensus
    # Spread profits from INACTION, not from a big move, so fewer filters needed
    if regime == "neutral":
        logger.info("[SELLER] Neutral regime — skipping spread entry")
        return

    reason = f"SELLER | {regime.upper()} regime, low VIX — selling credit spread"
    logger.info(f"[SIGNAL] Entering {regime.upper()} credit spread")
    spread_manager.enter(regime, reason)


def run_bot(kite, options_manager: OptionsManager, spread_manager: SpreadManager):
    now_str = datetime.now().strftime("%H:%M")

    if not is_market_open():
        logger.info(f"[BOT] Market closed ({now_str}) — sleeping")
        return

    # Monitor open positions every cycle regardless of time window
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
        return

    if options_manager.has_position() or spread_manager.has_position():
        return

    if not is_good_trading_window():
        logger.info(f"[BOT] Outside active window ({now_str}) — monitoring only")
        return

    # ── Get VIX and decide mode ────────────────────────────────────────────────
    try:
        vix = get_vix(kite)
        logger.info(f"[VIX] India VIX = {vix:.2f}")
    except Exception as e:
        logger.warning(f"[VIX] Could not fetch VIX: {e}")
        return

    if vix < VIX_NO_TRADE_BELOW:
        logger.info(f"[VIX] Too low ({vix:.2f} < {VIX_NO_TRADE_BELOW}) — market too quiet")
        return
    if vix > VIX_BUYER_MAX:
        logger.info(f"[VIX] Too high ({vix:.2f} > {VIX_BUYER_MAX}) — too volatile")
        return

    # ── Regime (used by both modes) ────────────────────────────────────────────
    regime = get_market_regime(kite)
    if regime == "neutral":
        logger.info("[REGIME] Neutral — skipping")
        return

    # ── Route to correct mode based on VIX ────────────────────────────────────
    if VIX_NO_TRADE_BELOW <= vix < VIX_SELLER_MAX:
        logger.info(f"[MODE] SELLER (VIX={vix:.2f}, range {VIX_NO_TRADE_BELOW}–{VIX_SELLER_MAX})")
        run_seller_mode(kite, spread_manager, regime)

    elif VIX_SELLER_MAX <= vix <= VIX_BUYER_MAX:
        logger.info(f"[MODE] BUYER (VIX={vix:.2f}, range {VIX_SELLER_MAX}–{VIX_BUYER_MAX})")
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
    logger.info(f"  Underlying : {UNDERLYING}")
    logger.info(f"  VIX < {VIX_NO_TRADE_BELOW}   → no trade")
    logger.info(f"  VIX {VIX_NO_TRADE_BELOW}–{VIX_SELLER_MAX}  → SELLER mode (credit spreads, 70–80% win rate)")
    logger.info(f"  VIX {VIX_SELLER_MAX}–{VIX_BUYER_MAX} → BUYER mode  (CE/PE buying, 50–65% win rate)")
    logger.info(f"  VIX > {VIX_BUYER_MAX}   → no trade")
    logger.info(f"  Windows    : {MORNING_SESSION_START}–{MORNING_SESSION_END} | {AFTERNOON_SESSION_START}–{AFTERNOON_SESSION_END}")
    logger.info(f"  Square-off : {SQUARE_OFF_TIME} IST")
    logger.info("=" * 60)

    kite            = login()
    options_manager = OptionsManager(kite)
    spread_manager  = SpreadManager(kite)

    schedule.every(5).minutes.do(run_bot, kite=kite,
                                 options_manager=options_manager,
                                 spread_manager=spread_manager)
    run_bot(kite, options_manager, spread_manager)

    logger.info("[BOT] Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == "__main__":
    main()
