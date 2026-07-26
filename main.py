import logging
import schedule
import time
from datetime import datetime

from auth import login
from market_data import get_ohlcv
from order_manager import OrderManager
from strategies import MACrossoverStrategy, RSIStrategy, VWAPBreakoutStrategy
from strategies.base import Signal, TradeSignal
from config import WATCHLIST, MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF_TIME, TRADING_MODE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
)
logger = logging.getLogger(__name__)


def is_market_open() -> bool:
    now = datetime.now().strftime("%H:%M")
    return MARKET_OPEN <= now < MARKET_CLOSE


def run_strategies(kite, order_manager: OrderManager):
    if not is_market_open():
        logger.info("Market closed, skipping.")
        return

    now = datetime.now().strftime("%H:%M")
    if now >= SQUARE_OFF_TIME:
        logger.info("Square-off time reached.")
        order_manager.square_off_all()
        return

    for symbol in WATCHLIST:
        try:
            df = get_ohlcv(kite, symbol, interval="5minute", days=1)

            strategies = [
                MACrossoverStrategy(symbol),
                RSIStrategy(symbol),
                VWAPBreakoutStrategy(symbol),
            ]

            signals = [s.generate_signal(df) for s in strategies]

            for sig, strat in zip(signals, strategies):
                logger.info(f"[{strat.__class__.__name__}] {symbol}: {sig.signal.value} — {sig.reason}")

            buy_votes  = sum(1 for s in signals if s.signal == Signal.BUY)
            sell_votes = sum(1 for s in signals if s.signal == Signal.SELL)
            price      = signals[0].price

            if buy_votes >= 2:
                logger.info(f"[CONSENSUS] {symbol}: BUY — {buy_votes}/3 strategies agree")
                order_manager.execute(TradeSignal(symbol, Signal.BUY, f"{buy_votes}/3 agree BUY", price))
            elif sell_votes >= 2:
                logger.info(f"[CONSENSUS] {symbol}: SELL — {sell_votes}/3 strategies agree")
                order_manager.execute(TradeSignal(symbol, Signal.SELL, f"{sell_votes}/3 agree SELL", price))
            else:
                logger.info(f"[CONSENSUS] {symbol}: No consensus — skipping")

        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")


def main():
    logger.info(f"Starting bot in {TRADING_MODE.upper()} mode")
    kite = login()
    order_manager = OrderManager(kite)

    schedule.every(1).minutes.do(run_strategies, kite=kite, order_manager=order_manager)

    logger.info(f"Watching: {WATCHLIST}")
    logger.info("Bot running. Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    main()
