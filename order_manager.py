import logging
from datetime import date
from kiteconnect import KiteConnect
from strategies.base import Signal, TradeSignal
from market_data import get_ltp
from ledger import PaperLedger
from config import QUANTITY, CAPITAL, STOP_LOSS_PCT, TARGET_PCT, TRADING_MODE

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.positions: dict[str, dict] = {}  # symbol -> {"side", "entry_price", "quantity"}
        self.ledger = PaperLedger() if TRADING_MODE == "paper" else None
        self._summary_logged_on: str | None = None

    def execute(self, signal: TradeSignal):
        symbol = signal.symbol
        position = self.positions.get(symbol)

        if signal.signal == Signal.HOLD:
            return

        if signal.signal == Signal.BUY and not position:
            if TRADING_MODE == "paper" and self.positions:
                deployed_in = next(iter(self.positions))
                logger.info(f"[{symbol}] Skipping BUY — capital already deployed in {deployed_in}")
                return

            quantity = self._position_size(signal.price)
            self._place_order(symbol, "BUY", signal.price, quantity)
            self.positions[symbol] = {"side": "LONG", "entry_price": signal.price, "quantity": quantity}
            logger.info(f"[{symbol}] BUY {quantity} @ {signal.price:.2f} | {signal.reason}")

        elif signal.signal == Signal.SELL and position and position["side"] == "LONG":
            self._place_order(symbol, "SELL", signal.price, position["quantity"])
            del self.positions[symbol]
            logger.info(f"[{symbol}] SELL {position['quantity']} @ {signal.price:.2f} | {signal.reason}")

            if TRADING_MODE == "paper":
                self.ledger.record_trade(symbol, position["entry_price"], signal.price, position["quantity"])

    def square_off_all(self):
        """Close all open positions — called before market close."""
        for symbol, position in list(self.positions.items()):
            order = "SELL" if position["side"] == "LONG" else "BUY"
            price = None
            if TRADING_MODE == "paper":
                try:
                    price = get_ltp(self.kite, symbol)
                except Exception as e:
                    logger.error(f"[{symbol}] Could not fetch LTP for square-off: {e}")

            logger.info(f"[{symbol}] Squaring off {position['side']} position via {order}")
            self._place_order(symbol, order, price, position["quantity"])

            if TRADING_MODE == "paper" and price is not None:
                self.ledger.record_trade(symbol, position["entry_price"], price, position["quantity"])

            del self.positions[symbol]

        today = date.today().isoformat()
        if TRADING_MODE == "paper" and self._summary_logged_on != today:
            self.ledger.log_daily_summary(today)
            self._summary_logged_on = today

    def _position_size(self, price: float) -> int:
        if TRADING_MODE == "paper":
            return max(1, int(CAPITAL // price))
        return QUANTITY

    def _place_order(self, symbol: str, transaction: str, price: float | None, quantity: int):
        if TRADING_MODE == "paper":
            logger.info(f"[PAPER] {transaction} {quantity} x {symbol} @ {price or 'MARKET'}")
            return

        params = dict(
            tradingsymbol=symbol,
            exchange=self.kite.EXCHANGE_NSE,
            transaction_type=transaction,
            quantity=quantity,
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
