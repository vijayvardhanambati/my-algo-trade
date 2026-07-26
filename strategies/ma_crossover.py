import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


class MACrossoverStrategy(BaseStrategy):
    """Buy when fast EMA crosses above slow EMA; sell on crossunder."""

    def __init__(self, symbol: str, fast: int = 9, slow: int = 21):
        super().__init__(symbol)
        self.fast = fast
        self.slow = slow

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow, adjust=False).mean()

        prev = df.iloc[-2]
        curr = df.iloc[-1]
        price = curr["close"]

        if prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]:
            return TradeSignal(self.symbol, Signal.BUY, f"EMA{self.fast} crossed above EMA{self.slow}", price)

        if prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]:
            return TradeSignal(self.symbol, Signal.SELL, f"EMA{self.fast} crossed below EMA{self.slow}", price)

        return TradeSignal(self.symbol, Signal.HOLD, "No crossover", price)
