import logging
import pandas as pd
from datetime import date, datetime
from kiteconnect import KiteConnect
from config import UNDERLYING, OPTIONS_CAPITAL, OPTIONS_SL_PCT, OPTIONS_TARGET_PCT, TRADING_MODE

logger = logging.getLogger(__name__)

_LOT_SIZE = {"BANKNIFTY": 15, "NIFTY": 50}
_instruments_cache: dict = {}


def _get_nfo_instruments(kite: KiteConnect) -> pd.DataFrame:
    today = date.today().isoformat()
    if _instruments_cache.get("date") == today:
        return _instruments_cache["df"]
    logger.info("[OPTIONS] Fetching NFO instruments list (cached daily)...")
    instruments = kite.instruments("NFO")
    df = pd.DataFrame(instruments)
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    _instruments_cache["date"] = today
    _instruments_cache["df"] = df
    return df


def get_atm_option(kite: KiteConnect, direction: str) -> dict:
    """Find nearest-expiry ATM CE or PE for the configured underlying."""
    ltp_key = "NSE:NIFTY BANK" if UNDERLYING == "BANKNIFTY" else "NSE:NIFTY 50"
    quote         = kite.ltp([ltp_key])
    current_price = quote[ltp_key]["last_price"]

    strike_gap = 100 if UNDERLYING == "BANKNIFTY" else 50
    atm_strike = round(current_price / strike_gap) * strike_gap

    df    = _get_nfo_instruments(kite)
    today = date.today()

    def _find(strike):
        return df[
            (df["name"] == UNDERLYING) &
            (df["instrument_type"] == direction) &
            (df["strike"] == float(strike)) &
            (df["expiry"] >= today)
        ]

    options = _find(atm_strike)

    # Try adjacent strikes if ATM not found
    if options.empty:
        for offset in [strike_gap, -strike_gap, 2 * strike_gap, -2 * strike_gap]:
            options = _find(atm_strike + offset)
            if not options.empty:
                atm_strike += offset
                break

    if options.empty:
        raise ValueError(f"No {UNDERLYING} {direction} found near strike {atm_strike}")

    nearest = options.loc[options["expiry"].idxmin()]
    return {
        "instrument_token": int(nearest["instrument_token"]),
        "tradingsymbol":    nearest["tradingsymbol"],
        "strike":           atm_strike,
        "expiry":           nearest["expiry"],
        "option_type":      direction,
        "underlying_price": current_price,
    }


def get_option_ltp(kite: KiteConnect, tradingsymbol: str) -> float:
    key   = f"NFO:{tradingsymbol}"
    quote = kite.ltp([key])
    return quote[key]["last_price"]


class OptionsPosition:
    def __init__(self, option_info: dict, entry_premium: float, lots: int):
        self.option_info    = option_info
        self.entry_premium  = entry_premium
        self.lots           = lots
        self.tradingsymbol  = option_info["tradingsymbol"]
        self.option_type    = option_info["option_type"]
        self.lot_size       = _LOT_SIZE.get(UNDERLYING, 15)

    def pnl(self, current_premium: float) -> float:
        return (current_premium - self.entry_premium) * self.lots * self.lot_size

    def pct_change(self, current_premium: float) -> float:
        return ((current_premium - self.entry_premium) / self.entry_premium) * 100


class OptionsManager:
    """Handles entry, monitoring, and exit of options positions."""

    COOLDOWN_MINUTES = 60  # wait this long after a stop loss before re-entering

    def __init__(self, kite: KiteConnect):
        self.kite            = kite
        self.position: OptionsPosition | None = None
        self.trade_log: list = []
        self._last_loss_time: datetime | None = None

    def has_position(self) -> bool:
        return self.position is not None

    def _in_cooldown(self) -> bool:
        if self._last_loss_time is None:
            return False
        elapsed = (datetime.now() - self._last_loss_time).total_seconds() / 60
        if elapsed < self.COOLDOWN_MINUTES:
            remaining = int(self.COOLDOWN_MINUTES - elapsed)
            logger.info(f"[OPTIONS] Cooldown active — {remaining} min left after last stop loss")
            return True
        return False

    def enter(self, direction: str, reason: str):
        if self.has_position():
            logger.info(f"[OPTIONS] Already in a position — skipping new {direction}")
            return
        if self._in_cooldown():
            return

        try:
            option   = get_atm_option(self.kite, direction)
            premium  = get_option_ltp(self.kite, option["tradingsymbol"])
            lot_size = _LOT_SIZE.get(UNDERLYING, 15)

            if premium <= 0:
                logger.warning(f"[OPTIONS] Invalid premium {premium} — skipping")
                return

            lots = max(1, int(OPTIONS_CAPITAL / (premium * lot_size)))

            logger.info(
                f"[OPTIONS {'PAPER' if TRADING_MODE == 'paper' else 'LIVE'}] "
                f"BUY {direction} | {option['tradingsymbol']} | "
                f"Strike: {option['strike']} | Expiry: {option['expiry']} | "
                f"Premium: ₹{premium:.2f} | Lots: {lots} | "
                f"Underlying: ₹{option['underlying_price']:.2f} | "
                f"Reason: {reason}"
            )

            if TRADING_MODE != "paper":
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=option["tradingsymbol"],
                    exchange=self.kite.EXCHANGE_NFO,
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    quantity=lots * lot_size,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY,
                )
                logger.info(f"[OPTIONS] Order placed: {order_id}")

            self.position = OptionsPosition(option, premium, lots)

        except Exception as e:
            logger.error(f"[OPTIONS] Enter failed: {e}")

    def monitor_and_exit(self, force_reason: str = ""):
        if not self.has_position():
            return
        try:
            current = get_option_ltp(self.kite, self.position.tradingsymbol)
            pct     = self.position.pct_change(current)
            pnl     = self.position.pnl(current)

            logger.info(
                f"[OPTIONS] {self.position.tradingsymbol} | "
                f"Entry: ₹{self.position.entry_premium:.2f} | "
                f"Current: ₹{current:.2f} | "
                f"PnL: ₹{pnl:+.2f} ({pct:+.1f}%)"
            )

            if force_reason:
                self._exit(current, force_reason)
            elif pct <= -OPTIONS_SL_PCT:
                self._last_loss_time = datetime.now()
                self._exit(current, f"Stop loss hit ({pct:.1f}%)")
            elif pct >= OPTIONS_TARGET_PCT:
                self._exit(current, f"Target hit ({pct:.1f}%)")

        except Exception as e:
            logger.error(f"[OPTIONS] Monitor error: {e}")

    def _exit(self, exit_premium: float, reason: str):
        pnl = self.position.pnl(exit_premium)
        pct = self.position.pct_change(exit_premium)
        lot_size = _LOT_SIZE.get(UNDERLYING, 15)

        logger.info(
            f"[OPTIONS EXIT] {self.position.option_type} | "
            f"{self.position.tradingsymbol} | "
            f"Exit: ₹{exit_premium:.2f} | "
            f"P&L: ₹{pnl:+.2f} ({pct:+.1f}%) | "
            f"Reason: {reason}"
        )

        if TRADING_MODE != "paper":
            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=self.position.tradingsymbol,
                    exchange=self.kite.EXCHANGE_NFO,
                    transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                    quantity=self.position.lots * lot_size,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY,
                )
                logger.info(f"[OPTIONS] Exit order placed: {order_id}")
            except Exception as e:
                logger.error(f"[OPTIONS] Exit order failed: {e}")

        self.trade_log.append({
            "time":            datetime.now().strftime("%H:%M"),
            "type":            self.position.option_type,
            "symbol":          self.position.tradingsymbol,
            "entry":           self.position.entry_premium,
            "exit":            exit_premium,
            "pnl":             pnl,
            "pct":             pct,
            "reason":          reason,
        })
        self.position = None

    def daily_summary(self):
        sep = "=" * 60
        logger.info(sep)
        logger.info(f"  DAILY SUMMARY — {date.today().strftime('%d %b %Y')}")
        logger.info(sep)

        if not self.trade_log:
            logger.info("  No trades taken today.")
            logger.info(sep)
            return

        total    = len(self.trade_log)
        wins     = [t for t in self.trade_log if t["pnl"] > 0]
        losses   = [t for t in self.trade_log if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in self.trade_log)
        win_rate  = (len(wins) / total * 100) if total else 0

        logger.info(f"  Trades taken  : {total}")
        logger.info(f"  Winners       : {len(wins)}")
        logger.info(f"  Losers        : {len(losses)}")
        logger.info(f"  Win rate      : {win_rate:.1f}%")
        logger.info(f"  Total P&L     : ₹{total_pnl:+.2f}")
        logger.info(sep)
        logger.info("  Trade-by-trade breakdown:")
        for i, t in enumerate(self.trade_log, 1):
            result = "WIN " if t["pnl"] > 0 else "LOSS"
            logger.info(
                f"  {i}. [{result}] {t['time']} | {t['type']} | {t['symbol']} | "
                f"Entry ₹{t['entry']:.2f} → Exit ₹{t['exit']:.2f} | "
                f"P&L ₹{t['pnl']:+.2f} ({t['pct']:+.1f}%) | {t['reason']}"
            )
        logger.info(sep)
        self.trade_log = []  # reset for next day

    def square_off(self):
        if self.has_position():
            try:
                current = get_option_ltp(self.kite, self.position.tradingsymbol)
                self._exit(current, "End-of-day square-off")
            except Exception as e:
                logger.error(f"[OPTIONS] Square-off failed: {e}")
                self.position = None
