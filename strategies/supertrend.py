import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


def _compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    n     = len(df)

    # ATR via Wilder's smoothing
    tr = [high[0] - low[0]]
    for i in range(1, n):
        tr.append(max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        ))

    atr = [0.0] * n
    atr[period - 1] = sum(tr[:period]) / period
    alpha = 1 / period
    for i in range(period, n):
        atr[i] = alpha * tr[i] + (1 - alpha) * atr[i - 1]

    hl2         = [(high[i] + low[i]) / 2 for i in range(n)]
    upper_basic = [hl2[i] + multiplier * atr[i] for i in range(n)]
    lower_basic = [hl2[i] - multiplier * atr[i] for i in range(n)]

    final_upper = upper_basic[:]
    final_lower = lower_basic[:]
    direction   = [1] * n

    for i in range(1, n):
        final_lower[i] = (lower_basic[i]
                          if lower_basic[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]
                          else final_lower[i - 1])

        final_upper[i] = (upper_basic[i]
                          if upper_basic[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]
                          else final_upper[i - 1])

        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

    return pd.Series(direction, index=df.index)


class SupertrendStrategy(BaseStrategy):
    """Buy when Supertrend turns bullish; sell when it turns bearish."""

    def __init__(self, symbol: str, period: int = 10, multiplier: float = 3.0):
        super().__init__(symbol)
        self.period     = period
        self.multiplier = multiplier

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < self.period + 5:
            return TradeSignal(self.symbol, Signal.HOLD, "Not enough data for Supertrend", df["close"].iloc[-1])

        direction = _compute_supertrend(df, self.period, self.multiplier)
        curr_dir  = direction.iloc[-1]
        prev_dir  = direction.iloc[-2]
        price     = df["close"].iloc[-1]

        if curr_dir == 1 and prev_dir == -1:
            return TradeSignal(self.symbol, Signal.BUY, "Supertrend flipped bullish", price)
        if curr_dir == -1 and prev_dir == 1:
            return TradeSignal(self.symbol, Signal.SELL, "Supertrend flipped bearish", price)
        if curr_dir == 1:
            return TradeSignal(self.symbol, Signal.BUY, "Supertrend bullish", price)
        return TradeSignal(self.symbol, Signal.SELL, "Supertrend bearish", price)
