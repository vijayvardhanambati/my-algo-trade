import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class RSIStrategy(BaseStrategy):
    """Buy on RSI oversold recovery; sell on RSI overbought rejection."""

    def __init__(self, symbol: str, period: int = 14, oversold: int = 40, overbought: int = 60):
        super().__init__(symbol)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = df.copy()
        df["rsi"] = _rsi(df["close"], length=self.period)

        prev_rsi = df["rsi"].iloc[-2]
        curr_rsi = df["rsi"].iloc[-1]
        price = df["close"].iloc[-1]

        if prev_rsi < self.oversold and curr_rsi >= self.oversold:
            return TradeSignal(self.symbol, Signal.BUY, f"RSI recovered above {self.oversold} (was {prev_rsi:.1f})", price)

        if prev_rsi > self.overbought and curr_rsi <= self.overbought:
            return TradeSignal(self.symbol, Signal.SELL, f"RSI dropped below {self.overbought} (was {prev_rsi:.1f})", price)

        return TradeSignal(self.symbol, Signal.HOLD, f"RSI at {curr_rsi:.1f}", price)
