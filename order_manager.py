import logging
from kiteconnect import KiteConnect
from strategies.base import Signal, TradeSignal
from config import QUANTITY, STOP_LOSS_PCT, TARGET_PCT, TRADING_MODE

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.positions: dict[str, str] = {}  # symbol -> "LONG" | "SHORT"

    def execute(self, signal: TradeSignal):
        symbol = signal.symbol
        in_position = self.positions.get(symbol)

        if signal.signal == Signal.HOLD:
            return

        if signal.signal == Signal.BUY and not in_position:
            self._place_order(symbol, "BUY", signal.price)
            self.positions[symbol] = "LONG"
            logger.info(f"[{symbol}] BUY @ {signal.price:.2f} | {signal.reason}")

        elif signal.signal == Signal.SELL and in_position == "LONG":
            self._place_order(symbol, "SELL", signal.price)
            del self.positions[symbol]
            logger.info(f"[{symbol}] SELL @ {signal.price:.2f} | {signal.reason}")

    def square_off_all(self):
        """Close all open positions — called before market close."""
        for symbol, side in list(self.positions.items()):
            order = "SELL" if side == "LONG" else "BUY"
            logger.info(f"[{symbol}] Squaring off {side} position via {order}")
            self._place_order(symbol, order, price=None)
            del self.positions[symbol]

    def _place_order(self, symbol: str, transaction: str, price: float | None):
        if TRADING_MODE == "paper":
            logger.info(f"[PAPER] {transaction} {QUANTITY} x {symbol} @ {price or 'MARKET'}")
            return

        params = dict(
            tradingsymbol=symbol,
            exchange=self.kite.EXCHANGE_NSE,
            transaction_type=transaction,
            quantity=QUANTITY,
            order_type=self.kite.ORDER_TYPE_MARKET,
            product=self.kite.PRODUCT_MIS,  # intraday
            validity=self.kite.VALIDITY_DAY,
        )

        if price and transaction == "BUY":
            sl_price = round(price * (1 - STOP_LOSS_PCT / 100), 2)
            target_price = round(price * (1 + TARGET_PCT / 100), 2)
            logger.info(f"SL: {sl_price} | Target: {target_price}")

        order_id = self.kite.place_order(variety=self.kite.VARIETY_REGULAR, **params)
        logger.info(f"Order placed: {order_id}")
