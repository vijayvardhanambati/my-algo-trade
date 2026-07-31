"""
Credit spread (option selling) module — Phase 3.

Strategy:
  Low VIX (11-13) = market is calm/sideways = premiums decaying = good for SELLING.

  BULL regime → Bull Put Spread:
    SELL ATM PE (collect premium)
    BUY  ATM-spread_width PE (cap downside risk)
    Profit when NIFTY stays flat or goes UP.

  BEAR regime → Bear Call Spread:
    SELL ATM CE (collect premium)
    BUY  ATM+spread_width CE (cap upside risk)
    Profit when NIFTY stays flat or goes DOWN.

Exit rules:
  - Target : spread value drops to 30% of entry credit (kept 70% of premium)
  - Stop   : spread value reaches 2× entry credit (spread doubled against us)
  - EOD    : force-close at 2:45 PM regardless

Capital required (NIFTY, 100-pt spread, 1 lot):
  Max loss = 100 × 75 = ₹7,500 per spread (margin blocked)
  Max gain = net_credit × 75 (premium collected)
"""

import logging
from datetime import date, datetime
from kiteconnect import KiteConnect

from config import UNDERLYING, CAPITAL, OPTIONS_DAILY_TARGET_PCT, TRADING_MODE
from options_trader import _LOT_SIZE, _get_nfo_instruments, get_option_ltp

logger = logging.getLogger(__name__)

_STRIKE_GAP    = {"NIFTY": 50,  "BANKNIFTY": 100}
_SPREAD_WIDTH  = {"NIFTY": 100, "BANKNIFTY": 200}   # points between short and long leg

SPREAD_TARGET_PCT = 25   # exit when 25% of credit is kept, then re-enter immediately
SPREAD_SL_MULT    = 1.3  # exit when spread grows 30% beyond entry credit (~tight SL)
SPREAD_ENTRY_CUTOFF = "12:00"  # no new spreads after this time — not enough theta left
DAILY_TARGET      = CAPITAL * OPTIONS_DAILY_TARGET_PCT / 100


def _find_strike(kite: KiteConnect, direction: str, strike: float) -> dict:
    ltp_key = "NSE:NIFTY 50" if UNDERLYING == "NIFTY" else "NSE:NIFTY BANK"
    df      = _get_nfo_instruments(kite)
    today   = date.today()

    rows = df[
        (df["name"] == UNDERLYING) &
        (df["instrument_type"] == direction) &
        (df["strike"] == float(strike)) &
        (df["expiry"] >= today)
    ]
    if rows.empty:
        raise ValueError(f"No {UNDERLYING} {direction} at strike {strike}")
    nearest = rows.loc[rows["expiry"].idxmin()]
    return {
        "tradingsymbol": nearest["tradingsymbol"],
        "strike":        strike,
        "expiry":        nearest["expiry"],
    }


class CreditSpreadPosition:
    def __init__(self, spread_type: str, short_leg: dict, long_leg: dict,
                 entry_credit: float, lots: int):
        self.spread_type  = spread_type   # "BULL_PUT" or "BEAR_CALL"
        self.short_leg    = short_leg     # sold option (collecting premium)
        self.long_leg     = long_leg      # bought option (hedge)
        self.entry_credit = entry_credit  # net premium received per unit
        self.lots         = lots
        self.lot_size     = _LOT_SIZE.get(UNDERLYING, 75)

    def current_spread_value(self, kite: KiteConnect) -> float:
        short_ltp = get_option_ltp(kite, self.short_leg["tradingsymbol"])
        long_ltp  = get_option_ltp(kite, self.long_leg["tradingsymbol"])
        return short_ltp - long_ltp

    def pnl(self, current_spread_value: float) -> float:
        return (self.entry_credit - current_spread_value) * self.lots * self.lot_size

    def pct_kept(self, current_spread_value: float) -> float:
        if self.entry_credit <= 0:
            return 0.0
        return ((self.entry_credit - current_spread_value) / self.entry_credit) * 100


class SpreadManager:
    """Manages credit spread positions for low-VIX selling mode."""

    def __init__(self, kite: KiteConnect):
        self.kite       = kite
        self.position: CreditSpreadPosition | None = None
        self.trade_log: list = []
        self.daily_pnl: float = 0.0

    def has_position(self) -> bool:
        return self.position is not None

    def daily_target_reached(self) -> bool:
        if self.daily_pnl >= DAILY_TARGET:
            logger.info(
                f"[SPREAD] Daily target reached ₹{self.daily_pnl:+.2f} "
                f"(target ₹{DAILY_TARGET:.0f}) — no more trades today"
            )
            return True
        return False

    def enter(self, regime: str, reason: str):
        if self.has_position():
            logger.info("[SPREAD] Already in a spread position — skipping")
            return
        if self.daily_target_reached():
            return
        now_str = datetime.now().strftime("%H:%M")
        if now_str >= SPREAD_ENTRY_CUTOFF:
            logger.info(f"[SPREAD] Entry cutoff {SPREAD_ENTRY_CUTOFF} passed ({now_str}) — no new spreads today")
            return

        try:
            ltp_key = "NSE:NIFTY 50" if UNDERLYING == "NIFTY" else "NSE:NIFTY BANK"
            spot    = self.kite.ltp([ltp_key])[ltp_key]["last_price"]

            gap   = _STRIKE_GAP.get(UNDERLYING, 50)
            width = _SPREAD_WIDTH.get(UNDERLYING, 100)
            atm   = round(spot / gap) * gap
            lot_size = _LOT_SIZE.get(UNDERLYING, 75)

            if regime == "bull":
                # Bull Put Spread: sell OTM PE, buy further-OTM PE
                short_strike = atm - gap          # 1 strike below ATM
                long_strike  = atm - gap - width  # 2-3 strikes below ATM
                spread_type  = "BULL_PUT"
                option_type  = "PE"
            else:
                # Bear Call Spread: sell OTM CE, buy further-OTM CE
                short_strike = atm + gap          # 1 strike above ATM
                long_strike  = atm + gap + width  # 2-3 strikes above ATM
                spread_type  = "BEAR_CALL"
                option_type  = "CE"

            short_leg = _find_strike(self.kite, option_type, short_strike)
            long_leg  = _find_strike(self.kite, option_type, long_strike)

            short_ltp = get_option_ltp(self.kite, short_leg["tradingsymbol"])
            long_ltp  = get_option_ltp(self.kite, long_leg["tradingsymbol"])
            net_credit = short_ltp - long_ltp

            if net_credit <= 0:
                logger.warning(f"[SPREAD] Net credit is ₹{net_credit:.2f} — skipping")
                return

            # Allocate 25% of capital to spreads; each lot requires width×lot_size margin
            spread_capital = CAPITAL * 0.25
            margin_per_lot = width * lot_size
            lots = max(1, int(spread_capital / margin_per_lot))

            max_risk   = (width - net_credit) * lots * lot_size
            max_profit = net_credit * lots * lot_size

            logger.info(
                f"[SPREAD {'PAPER' if TRADING_MODE == 'paper' else 'LIVE'}] "
                f"{spread_type} | {short_leg['tradingsymbol']} ↔ {long_leg['tradingsymbol']} | "
                f"Expiry: {short_leg['expiry']} | "
                f"Credit: ₹{net_credit:.2f}/unit | "
                f"Max profit: ₹{max_profit:.0f} | Max risk: ₹{max_risk:.0f} | "
                f"Spot: ₹{spot:.2f} | Reason: {reason}"
            )

            if TRADING_MODE != "paper":
                # Sell short leg
                self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=short_leg["tradingsymbol"],
                    exchange=self.kite.EXCHANGE_NFO,
                    transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                    quantity=lots * lot_size,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY,
                )
                # Buy long leg (hedge)
                self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=long_leg["tradingsymbol"],
                    exchange=self.kite.EXCHANGE_NFO,
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    quantity=lots * lot_size,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY,
                )

            self.position = CreditSpreadPosition(spread_type, short_leg, long_leg, net_credit, lots)

        except Exception as e:
            logger.error(f"[SPREAD] Enter failed: {e}")

    def monitor_and_exit(self, force_reason: str = ""):
        if not self.has_position():
            return
        try:
            current_spread = self.position.current_spread_value(self.kite)
            pnl            = self.position.pnl(current_spread)
            pct_kept       = self.position.pct_kept(current_spread)

            logger.info(
                f"[SPREAD] {self.position.spread_type} | "
                f"Entry credit: ₹{self.position.entry_credit:.2f} | "
                f"Current spread: ₹{current_spread:.2f} | "
                f"Kept: {pct_kept:.1f}% | P&L: ₹{pnl:+.2f}"
            )

            if force_reason:
                self._exit(current_spread, force_reason)
            elif pct_kept >= SPREAD_TARGET_PCT:
                self._exit(current_spread, f"Target hit — kept {pct_kept:.1f}% of credit")
            elif current_spread >= self.position.entry_credit * SPREAD_SL_MULT:
                self._exit(current_spread, f"Stop loss — spread at {SPREAD_SL_MULT}× entry credit")

        except Exception as e:
            logger.error(f"[SPREAD] Monitor error: {e}")

    def _exit(self, exit_spread_value: float, reason: str):
        pnl      = self.position.pnl(exit_spread_value)
        pct_kept = self.position.pct_kept(exit_spread_value)
        lot_size = _LOT_SIZE.get(UNDERLYING, 75)

        logger.info(
            f"[SPREAD EXIT] {self.position.spread_type} | "
            f"Entry credit: ₹{self.position.entry_credit:.2f} | "
            f"Exit spread: ₹{exit_spread_value:.2f} | "
            f"P&L: ₹{pnl:+.2f} | Kept {pct_kept:.1f}% of credit | Reason: {reason}"
        )

        if TRADING_MODE != "paper":
            try:
                # Buy back short leg (close short)
                self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=self.position.short_leg["tradingsymbol"],
                    exchange=self.kite.EXCHANGE_NFO,
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    quantity=self.position.lots * lot_size,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY,
                )
                # Sell long leg (close hedge)
                self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=self.position.long_leg["tradingsymbol"],
                    exchange=self.kite.EXCHANGE_NFO,
                    transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                    quantity=self.position.lots * lot_size,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY,
                )
            except Exception as e:
                logger.error(f"[SPREAD] Exit orders failed: {e}")

        self.daily_pnl += pnl
        self.trade_log.append({
            "time":        datetime.now().strftime("%H:%M"),
            "type":        self.position.spread_type,
            "short":       self.position.short_leg["tradingsymbol"],
            "long":        self.position.long_leg["tradingsymbol"],
            "credit":      self.position.entry_credit,
            "exit_spread": exit_spread_value,
            "pnl":         pnl,
            "pct_kept":    pct_kept,
            "reason":      reason,
            "daily_pnl":   self.daily_pnl,
        })
        logger.info(f"[SPREAD] Daily P&L so far: ₹{self.daily_pnl:+.2f} / target ₹{DAILY_TARGET:.0f}")
        self.position = None

    def square_off(self):
        if self.has_position():
            try:
                current_spread = self.position.current_spread_value(self.kite)
                self._exit(current_spread, "End-of-day square-off")
            except Exception as e:
                logger.error(f"[SPREAD] Square-off failed: {e}")
                self.position = None

    def daily_summary(self):
        sep = "=" * 60
        if not self.trade_log:
            return
        total     = len(self.trade_log)
        wins      = [t for t in self.trade_log if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in self.trade_log)
        win_rate  = len(wins) / total * 100 if total else 0
        logger.info(sep)
        logger.info("  SPREAD TRADES (selling mode):")
        logger.info(f"  Spreads : {total} | Wins: {len(wins)} | Win rate: {win_rate:.1f}% | P&L: ₹{total_pnl:+.2f}")
        for i, t in enumerate(self.trade_log, 1):
            result = "WIN " if t["pnl"] > 0 else "LOSS"
            logger.info(
                f"  {i}. [{result}] {t['time']} | {t['type']} | "
                f"Credit ₹{t['credit']:.2f} → Exit spread ₹{t['exit_spread']:.2f} | "
                f"P&L ₹{t['pnl']:+.2f} (kept {t['pct_kept']:.1f}%) | {t['reason']}"
            )
        logger.info(sep)
        self.trade_log = []
        self.daily_pnl = 0.0
