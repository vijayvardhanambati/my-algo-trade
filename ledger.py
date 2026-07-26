"""Paper-trading P&L ledger: logs every simulated round-trip with realistic
Zerodha charges and tax applied, and reports daily performance against
DAILY_PROFIT_TARGET so the strategies can be judged on real numbers instead
of assumptions.
"""

import csv
import logging
import os
from datetime import date

from config import DAILY_PROFIT_TARGET, TAX_RATE, LEVERAGE_MULTIPLIER
from costs import calculate_charges

logger = logging.getLogger(__name__)

LEDGER_FILE = "paper_trades.csv"
FIELDS = [
    "date", "symbol", "buy_price", "sell_price", "quantity",
    "gross_pnl", "charges", "net_pnl", "tax", "net_after_tax",
]


class PaperLedger:
    def __init__(self, path: str = LEDGER_FILE):
        self.path = path
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="") as f:
                csv.writer(f).writerow(FIELDS)

    def record_trade(self, symbol: str, buy_price: float, sell_price: float, quantity: int) -> float:
        buy_value = buy_price * quantity
        sell_value = sell_price * quantity
        charges = calculate_charges(buy_value, sell_value)

        gross_pnl = sell_value - buy_value
        net_pnl = gross_pnl - charges["total"]
        tax = max(net_pnl, 0) * TAX_RATE  # only profits are taxed; losses aren't offset here
        net_after_tax = net_pnl - tax

        with open(self.path, "a", newline="") as f:
            csv.writer(f).writerow([
                date.today().isoformat(), symbol, buy_price, sell_price, quantity,
                round(gross_pnl, 2), charges["total"], round(net_pnl, 2),
                round(tax, 2), round(net_after_tax, 2),
            ])

        logger.info(
            f"[LEDGER] {symbol} gross={gross_pnl:.2f} charges={charges['total']:.2f} "
            f"net={net_pnl:.2f} tax={tax:.2f} net_after_tax={net_after_tax:.2f}"
        )
        return net_after_tax

    def log_daily_summary(self, for_date: str | None = None):
        for_date = for_date or date.today().isoformat()
        rows = self._read_rows()
        today_rows = [r for r in rows if r["date"] == for_date]

        if not today_rows:
            logger.info(f"[LEDGER] No paper trades recorded for {for_date}.")
            return

        gross = sum(float(r["gross_pnl"]) for r in today_rows)
        charges = sum(float(r["charges"]) for r in today_rows)
        net = sum(float(r["net_pnl"]) for r in today_rows)
        tax = sum(float(r["tax"]) for r in today_rows)
        net_after_tax = sum(float(r["net_after_tax"]) for r in today_rows)
        hypothetical_leveraged = net_after_tax * LEVERAGE_MULTIPLIER
        hit_target = net_after_tax >= DAILY_PROFIT_TARGET

        logger.info(
            f"[SUMMARY {for_date}] trades={len(today_rows)} gross={gross:.2f} "
            f"charges={charges:.2f} tax={tax:.2f} net_after_tax={net_after_tax:.2f} "
            f"target={DAILY_PROFIT_TARGET} hit={'YES' if hit_target else 'NO'} "
            f"(at {LEVERAGE_MULTIPLIER}x leverage would be ~{hypothetical_leveraged:.2f}, "
            f"not used for real sizing, shown for reference only)"
        )

        all_days = sorted({r["date"] for r in rows})
        if len(all_days) > 1:
            daily_totals = {
                d: sum(float(r["net_after_tax"]) for r in rows if r["date"] == d)
                for d in all_days
            }
            days_hit = sum(1 for v in daily_totals.values() if v >= DAILY_PROFIT_TARGET)
            avg_daily = sum(daily_totals.values()) / len(daily_totals)
            logger.info(
                f"[TRACK RECORD] {len(all_days)} days logged | "
                f"{days_hit}/{len(all_days)} hit the Rs {DAILY_PROFIT_TARGET} target | "
                f"avg net_after_tax/day = {avg_daily:.2f}"
            )

    def _read_rows(self) -> list[dict]:
        with open(self.path, newline="") as f:
            return list(csv.DictReader(f))
