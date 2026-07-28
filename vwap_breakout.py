import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


class VWAPBreakoutStrategy(BaseStrategy):
    """
    For instruments with real volume: price breaks above/below VWAP.
    For indices (zero/null volume): falls back to price vs EMA20 crossover.
    """

    def __init__(self, symbol: str, volume_multiplier: float = 1.5):
        super().__init__(symbol)
        self.volume_multiplier = volume_multiplier

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = df.copy()
        price = df["close"].iloc[-1]

        total_volume = df["volume"].sum()
        if pd.isna(total_volume) or total_volume == 0:
            return self._ema_fallback(df, price)

        typical = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()

        if df["vwap"].isna().all():
            return self._ema_fallback(df, price)

        avg_volume = df["volume"].rolling(20).mean()
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        high_volume = curr["volume"] > avg_volume.iloc[-1] * self.volume_multiplier

        if prev["close"] <= prev["vwap"] and curr["close"] > curr["vwap"] and high_volume:
            return TradeSignal(self.symbol, Signal.BUY, f"Price broke above VWAP {curr['vwap']:.2f}", price)

        if prev["close"] >= prev["vwap"] and curr["close"] < curr["vwap"] and high_volume:
            return TradeSignal(self.symbol, Signal.SELL, f"Price broke below VWAP {curr['vwap']:.2f}", price)

        return TradeSignal(self.symbol, Signal.HOLD, f"Price {price:.2f} near VWAP {curr['vwap']:.2f}", price)

    def _ema_fallback(self, df: pd.DataFrame, price: float) -> TradeSignal:
        ema20 = df["close"].ewm(span=20, adjust=False).mean()
        prev_close = df["close"].iloc[-2]
        curr_close = df["close"].iloc[-1]
        prev_ema   = ema20.iloc[-2]
        curr_ema   = ema20.iloc[-1]

        if prev_close <= prev_ema and curr_close > curr_ema:
            return TradeSignal(self.symbol, Signal.BUY, f"Price crossed above EMA20 {curr_ema:.2f} (index fallback)", price)
        if prev_close >= prev_ema and curr_close < curr_ema:
            return TradeSignal(self.symbol, Signal.SELL, f"Price crossed below EMA20 {curr_ema:.2f} (index fallback)", price)
        if curr_close > curr_ema:
            return TradeSignal(self.symbol, Signal.BUY, f"Price above EMA20 {curr_ema:.2f} (index fallback)", price)
        return TradeSignal(self.symbol, Signal.SELL, f"Price below EMA20 {curr_ema:.2f} (index fallback)", price)
