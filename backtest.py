"""Replays the exact production strategies over historical NSE data using the
same charges/tax model as paper trading, to measure real (not assumed) edge.

Run this on the machine where Kite auth already works (needs historical data
access on your API key):

    python backtest.py [days]

Writes every simulated trade to backtest_trades.csv and prints a summary:
per-day P&L distribution, win rate, target hit-rate, and a breakdown by
which strategy generated each trade.
"""

import sys
import logging
from datetime import datetime, timedelta

from auth import login
from strategies import MACrossoverStrategy, RSIStrategy, VWAPBreakoutStrategy
from strategies.base import Signal, TradeSignal
from order_manager import OrderManager
from ledger import PaperLedger
from config import WATCHLIST, DAILY_PROFIT_TARGET, MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF_TIME

logging.basicConfig(level=logging.WARNING, format="%(message)s")  # quiet during replay
logger = logging.getLogger(__name__)

WARMUP_BARS = 21  # slow EMA / RSI(14) / 20-period volume rolling all need this much history
LEDGER_FILE = "backtest_trades.csv"


def fetch_history(kite, symbol: str, days: int):
    instruments = kite.instruments("NSE")
    token = next(i["instrument_token"] for i in instruments if i["tradingsymbol"] == symbol)
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    records = kite.historical_data(token, from_date, to_date, "5minute")

    import pandas as pd
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df


def run_backtest(days: int):
    kite = login()
    ledger = PaperLedger(path=LEDGER_FILE)
    order_manager = OrderManager(kite=None)
    order_manager.ledger = ledger  # reuse OrderManager's BUY/SELL bookkeeping, backtest-only ledger

    print(f"Fetching {days} days of 5-minute history for {WATCHLIST}...")
    history = {sym: fetch_history(kite, sym, days) for sym in WATCHLIST}

    all_dates = sorted({d.date() for df in history.values() for d in df["date"]})
    print(f"Replaying {len(all_dates)} trading sessions...\n")

    for day in all_dates:
        day_bars = {sym: df[df["date"].dt.date == day].reset_index(drop=True) for sym, df in history.items()}
        max_len = max((len(b) for b in day_bars.values()), default=0)

        for i in range(max_len):
            for symbol in WATCHLIST:
                bars = day_bars[symbol]
                if i >= len(bars):
                    continue

                bar_time = bars["date"].iloc[i].strftime("%H:%M")
                if bar_time < MARKET_OPEN or bar_time >= MARKET_CLOSE:
                    continue

                df_so_far = bars.iloc[: i + 1].set_index("date")[["open", "high", "low", "close", "volume"]]

                if bar_time >= SQUARE_OFF_TIME:
                    position = order_manager.positions.get(symbol)
                    if position:
                        close_price = df_so_far["close"].iloc[-1]
                        order_manager.execute(TradeSignal(symbol, Signal.SELL, "EOD square-off (backtest)", close_price))
                    continue

                if len(df_so_far) < WARMUP_BARS:
                    continue

                for strategy in [MACrossoverStrategy(symbol), RSIStrategy(symbol), VWAPBreakoutStrategy(symbol)]:
                    try:
                        signal = strategy.generate_signal(df_so_far)
                    except Exception:
                        continue
                    if signal.signal != Signal.HOLD:
                        order_manager.execute(signal)

    print_report(ledger, len(all_dates))


def print_report(ledger: PaperLedger, num_days: int):
    rows = ledger._read_rows()
    if not rows:
        print("No trades were generated over this period — strategies never fired (check warmup/data).")
        return

    from collections import defaultdict
    daily = defaultdict(float)
    for r in rows:
        daily[r["date"]] += float(r["net_after_tax"])

    values = list(daily.values())
    n = len(values)
    total = sum(values)
    avg = total / n
    values_sorted = sorted(values)
    median = values_sorted[n // 2]
    days_hit = sum(1 for v in values if v >= DAILY_PROFIT_TARGET)
    winning_days = sum(1 for v in values if v > 0)

    wins = [float(r["net_pnl"]) for r in rows if float(r["net_pnl"]) > 0]
    losses = [float(r["net_pnl"]) for r in rows if float(r["net_pnl"]) <= 0]

    print("=" * 60)
    print(f"BACKTEST REPORT - {num_days} sessions replayed, {n} trading days had activity")
    print("=" * 60)
    print(f"Total trades: {len(rows)}  (wins: {len(wins)}, losses: {len(losses)}, "
          f"win rate: {len(wins)/len(rows)*100:.1f}%)")
    print(f"Total net-after-tax P&L over period: Rs {total:.2f}")
    print(f"Avg net-after-tax P&L / active day:  Rs {avg:.2f}")
    print(f"Median net-after-tax P&L / active day: Rs {median:.2f}")
    print(f"Best day: Rs {max(values):.2f}   Worst day: Rs {min(values):.2f}")
    print(f"Days with positive P&L: {winning_days}/{n} ({winning_days/n*100:.1f}%)")
    print(f"Days hitting Rs {DAILY_PROFIT_TARGET} target: {days_hit}/{n} ({days_hit/n*100:.1f}%)")
    print()

    print("Note: per-strategy attribution isn't broken out - all 3 strategies share one")
    print("ledger since that's exactly how they run in production (one shared position slot).")
    print("If a specific strategy looks worth isolating, say so and it can be split out.")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    run_backtest(days)
