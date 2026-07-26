import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


class VWAPBreakoutStrategy(BaseStrategy):
    """Buy when price breaks above VWAP with volume confirmation; sell on breakdown."""

    def __init__(self, symbol: str, volume_multiplier: float = 1.5):
        super().__init__(symbol)
        self.volume_multiplier = volume_multiplier

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = df.copy()
        typical = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()
        avg_volume = df["volume"].rolling(20).mean()

        prev = df.iloc[-2]
        curr = df.iloc[-1]
        price = curr["close"]

        high_volume = curr["volume"] > avg_volume.iloc[-1] * self.volume_multiplier

        if prev["close"] <= prev["vwap"] and curr["close"] > curr["vwap"] and high_volume:
            return TradeSignal(self.symbol, Signal.BUY, f"Price broke above VWAP {curr['vwap']:.2f} with volume", price)

        if prev["close"] >= prev["vwap"] and curr["close"] < curr["vwap"] and high_volume:
            return TradeSignal(self.symbol, Signal.SELL, f"Price broke below VWAP {curr['vwap']:.2f} with volume", price)

        return TradeSignal(self.symbol, Signal.HOLD, f"Price {price:.2f} near VWAP {curr['vwap']:.2f}", price)
