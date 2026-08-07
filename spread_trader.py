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
  - Target : kept% reaches 20% → exit and re-enter immediately if before 1:30 PM
  - Trail  : once 15% is kept, exit if kept% drops 5 pts from its peak (locks profit)
  - Stop   : spread value reaches 1.3× entry credit (tight SL)
  - EOD    : force-close at 2:45 PM regardless

Capital required (NIFTY, 100-pt spread, 1 lot):
  Max loss = 100 × 75 = ₹7,500 per spread (margin blocked)
  Max gain = net_credit × 75 (premium collected)
"""

import logging
from datetime import date, datetime
from kiteconnect import KiteConnect

from config import UNDERLYING, CAPITAL, OPTIONS_DAILY_TARGET_PCT, TRADING_MODE
from market_data import get_candles
from options_trader import _LOT_SIZE, _get_nfo_instruments, get_option_ltp
from strategies import SupertrendStrategy, ADXStrategy
from strategies.base import Signal

logger = logging.getLogger(__name__)

_STRIKE_GAP    = {"NIFTY": 50,  "BANKNIFTY": 100}
_SPREAD_WIDTH  = {"NIFTY": 100, "BANKNIFTY": 200}

SPREAD_TARGET_PCT         = 20      # exit when 20% of premium is kept (was 25)
SPREAD_SL_MULT            = 1.15    # secondary SL: spread grows 15% above credit
SPREAD_MAX_LOSS_ABS       = 800     # primary SL: exit if P&L < -₹800 (stops fast)
SPREAD_ENTRY_CUTOFF       = "14:00" # no new spreads within 45 min of EOD square-off
SPREAD_MIN_ENTRY_TIME     = "10:00" # wait 30 min after open for volatility to settle
SPREAD_DAILY_MAX_LOSS     = 1500    # hard stop: no more spreads if day loss > ₹1,500
TRAIL_ACTIVATION          = 15      # start trailing once 15% of credit is kept
TRAIL_PULLBACK            = 5       # exit if kept% drops 5 pts from peak (was 8)
SPREAD_ZOMBIE_TIMEOUT     = 60      # exit if negative after this many minutes in a trade
TRAIL_COOLDOWN_MIN        = 30      # wait this many minutes before re-entry after a trail exit
SIGNAL_CHECK_INTERVAL_SEC = 300     # re-evaluate Supertrend+ADX every 5 min while in a trade
DAILY_TARGET              = CAPITAL * OPTIONS_DAILY_TARGET_PCT / 100


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
        self.lot_size      = _LOT_SIZE.get(UNDERLYING, 75)
        self.peak_pct_kept = 0.0   # trailing high-water mark
        self.entry_time    = datetime.now()

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
        self.daily_pnl: float      = 0.0
        self.daily_entries: int    = 0
        self.sl_hit_direction: str = ""   # "bull" or "bear" — blocks re-entry in same direction after SL
        self.last_trail_exit_time: datetime | None = None
        self.last_signal_check: datetime | None    = None

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

    def enter(self, regime: str, reason: str, buy_votes: int = 0, sell_votes: int = 0, total_votes: int = 9):
        if self.has_position():
            logger.info("[SPREAD] Already in a spread position — skipping")
            return
        now_str = datetime.now().strftime("%H:%M")
        if now_str < SPREAD_MIN_ENTRY_TIME:
            logger.info(f"[SPREAD] Waiting for market to settle — entry opens at {SPREAD_MIN_ENTRY_TIME} (now {now_str})")
            return
        if now_str >= SPREAD_ENTRY_CUTOFF:
            logger.info(f"[SPREAD] Entry cutoff {SPREAD_ENTRY_CUTOFF} reached ({now_str}) — no new spreads")
            return
        if self.sl_hit_direction and self.sl_hit_direction == regime:
            logger.warning(
                f"[SPREAD] {self.sl_hit_direction.upper()} direction already blocked today — "
                f"waiting for market to flip before re-entering {regime.upper()}"
            )
            return
        if self.sl_hit_direction and self.sl_hit_direction != regime:
            logger.info(
                f"[SPREAD] Pivoting — {self.sl_hit_direction.upper()} blocked, "
                f"market flipped to {regime.upper()} — entering opposite spread"
            )
        if self.last_trail_exit_time is not None:
            mins_since_trail = (datetime.now() - self.last_trail_exit_time).total_seconds() / 60
            if mins_since_trail < TRAIL_COOLDOWN_MIN:
                regime_votes = buy_votes if regime == "bull" else sell_votes
                if regime_votes >= 6:
                    logger.info(
                        f"[SPREAD] Trail cooldown overridden — strong {regime.upper()} signal "
                        f"({regime_votes}/{total_votes} votes) after {mins_since_trail:.0f}min — "
                        f"re-entering immediately"
                    )
                else:
                    remaining = TRAIL_COOLDOWN_MIN - mins_since_trail
                    logger.info(
                        f"[SPREAD] Trail exit {mins_since_trail:.0f}min ago — "
                        f"cooling down, re-entry in {remaining:.0f}min "
                        f"(bypassed early if {regime.upper()} votes ≥ 6)"
                    )
                    return
        if self.daily_pnl <= -SPREAD_DAILY_MAX_LOSS:
            logger.warning(f"[SPREAD] Daily loss limit ₹{SPREAD_DAILY_MAX_LOSS} hit (P&L ₹{self.daily_pnl:.0f}) — no more spreads today")
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
            self.daily_entries += 1
            logger.info(f"[SPREAD] Trade #{self.daily_entries} today")

        except Exception as e:
            logger.error(f"[SPREAD] Enter failed: {e}")

    def monitor_and_exit(self, force_reason: str = ""):
        if not self.has_position():
            return
        try:
            current_spread = self.position.current_spread_value(self.kite)
            pnl            = self.position.pnl(current_spread)
            pct_kept       = self.position.pct_kept(current_spread)

            # Update trailing high-water mark
            if pct_kept > self.position.peak_pct_kept:
                self.position.peak_pct_kept = pct_kept

            peak       = self.position.peak_pct_kept
            trail_stop = peak - TRAIL_PULLBACK if peak >= TRAIL_ACTIVATION else None
            trail_str  = f" | Trail@{trail_stop:.1f}%" if trail_stop is not None else ""

            logger.info(
                f"[SPREAD] {self.position.spread_type} | "
                f"Credit: ₹{self.position.entry_credit:.2f} | "
                f"Current: ₹{current_spread:.2f} | "
                f"Kept: {pct_kept:.1f}% (peak {peak:.1f}%){trail_str} | "
                f"P&L: ₹{pnl:+.2f}"
            )

            if force_reason:
                self._exit(current_spread, force_reason)
            elif pct_kept >= SPREAD_TARGET_PCT:
                self._exit(current_spread, f"Target — kept {pct_kept:.1f}%")
            elif pnl <= -SPREAD_MAX_LOSS_ABS:
                self._exit(current_spread, f"SL — P&L ₹{pnl:.0f} exceeded -₹{SPREAD_MAX_LOSS_ABS} limit")
            elif current_spread >= self.position.entry_credit * SPREAD_SL_MULT:
                self._exit(current_spread, f"SL — spread {SPREAD_SL_MULT:.2f}× entry credit")
            elif (
                (datetime.now() - self.position.entry_time).total_seconds() / 60 >= SPREAD_ZOMBIE_TIMEOUT
                and pct_kept < 0
            ):
                mins = (datetime.now() - self.position.entry_time).total_seconds() / 60
                self._exit(current_spread,
                           f"Time stop — {mins:.0f}min in trade, never profitable (kept {pct_kept:.1f}%)")
            elif trail_stop is not None and pct_kept <= trail_stop:
                self._exit(current_spread,
                           f"Trail — peak {peak:.1f}% → fell to {pct_kept:.1f}%")

            if self.has_position():
                self._maybe_check_signals(current_spread, pct_kept)

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

        if "SL" in reason or "Time stop" in reason or "Signal reversal" in reason:
            self.sl_hit_direction = "bull" if self.position.spread_type == "BULL_PUT" else "bear"
            opposite = "BEAR_CALL" if self.sl_hit_direction == "bull" else "BULL_PUT"
            logger.warning(
                f"[SPREAD] {reason.split(' —')[0]} on {self.position.spread_type} — market not cooperating with "
                f"{self.sl_hit_direction.upper()} bias. Will pivot to {opposite} if regime flips."
            )
        if "Trail" in reason:
            self.last_trail_exit_time = datetime.now()
            logger.info("[SPREAD] Trail stop fired — 30-min cooldown (bypassed early if 6+ votes in new direction)")

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

    def _maybe_check_signals(self, current_spread: float, pct_kept: float) -> None:
        """Re-run Supertrend + ADX every 5 min while in a trade; exit early if both flip against position."""
        now = datetime.now()
        if (self.last_signal_check is not None and
                (now - self.last_signal_check).total_seconds() < SIGNAL_CHECK_INTERVAL_SEC):
            return
        self.last_signal_check = now
        try:
            df      = get_candles(self.kite, UNDERLYING)
            st      = SupertrendStrategy(UNDERLYING).generate_signal(df)
            adx     = ADXStrategy(UNDERLYING).generate_signal(df)
            is_bull = self.position.spread_type == "BULL_PUT"

            st_dir  = "BUY" if st.signal  == Signal.BUY  else ("SELL" if st.signal  == Signal.SELL  else "HOLD")
            adx_dir = "BUY" if adx.signal == Signal.BUY  else ("SELL" if adx.signal == Signal.SELL  else "HOLD")
            logger.info(
                f"[SPREAD] Intraday check — Supertrend:{st_dir} ADX:{adx_dir} "
                f"| {self.position.spread_type} | kept:{pct_kept:.1f}%"
            )

            if is_bull:
                if st.signal == Signal.SELL and adx.signal == Signal.SELL:
                    if pct_kept < 0:
                        self._exit(current_spread,
                                   f"Signal reversal — bearish (ST+ADX) while BULL_PUT losing (kept {pct_kept:.1f}%)")
                    else:
                        logger.warning(
                            f"[SPREAD] Bearish signals while in BULL_PUT — monitoring closely (kept {pct_kept:.1f}%)"
                        )
            else:
                if st.signal == Signal.BUY and adx.signal == Signal.BUY:
                    if pct_kept < 0:
                        self._exit(current_spread,
                                   f"Signal reversal — bullish (ST+ADX) while BEAR_CALL losing (kept {pct_kept:.1f}%)")
                    else:
                        logger.warning(
                            f"[SPREAD] Bullish signals while in BEAR_CALL — monitoring closely (kept {pct_kept:.1f}%)"
                        )
        except Exception as e:
            logger.debug(f"[SPREAD] Intraday signal check failed: {e}")

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
        self.trade_log            = []
        self.daily_pnl            = 0.0
        self.daily_entries        = 0
        self.sl_hit_direction     = ""
        self.last_trail_exit_time = None
        self.last_signal_check    = None
