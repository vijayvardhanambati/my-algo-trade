import numpy as np
import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


class ADXStrategy(BaseStrategy):
    """
    Average Directional Index (ADX) trend-strength filter.

    ADX < 20  → market is choppy/sideways → HOLD  (hard veto on entry)
    ADX >= 20 → trending market:
        +DI > -DI → BUY  (uptrend confirmed)
        -DI > +DI → SELL (downtrend confirmed)

    Weighted 2× in the consensus vote because entering a ranging market
    is the single biggest cause of option-buying losses.
    """

    PERIOD = 14
    TREND_THRESHOLD = 20

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < self.PERIOD + 5:
            return TradeSignal(self.symbol, Signal.HOLD,
                               "ADX: not enough data", df["close"].iloc[-1])

        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        # True Range
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=self.PERIOD, adjust=False).mean()

        # Directional movement
        up   = high.diff()
        down = -low.diff()

        plus_dm  = np.where((up > down) & (up > 0),   up,   0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)

        plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(
                       span=self.PERIOD, adjust=False).mean() / atr.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
                       span=self.PERIOD, adjust=False).mean() / atr.replace(0, np.nan)

        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx     = 100 * (plus_di - minus_di).abs() / di_sum
        adx    = dx.ewm(span=self.PERIOD, adjust=False).mean()

        adx_val = adx.iloc[-1]
        pdi     = plus_di.iloc[-1]
        mdi     = minus_di.iloc[-1]
        price   = close.iloc[-1]

        if adx_val < self.TREND_THRESHOLD:
            return TradeSignal(self.symbol, Signal.HOLD,
                f"ADX={adx_val:.1f} <{self.TREND_THRESHOLD} — choppy, no trend", price)

        if pdi > mdi:
            return TradeSignal(self.symbol, Signal.BUY,
                f"ADX={adx_val:.1f} +DI={pdi:.1f} >-DI={mdi:.1f} — uptrend", price)

        return TradeSignal(self.symbol, Signal.SELL,
            f"ADX={adx_val:.1f} -DI={mdi:.1f} >+DI={pdi:.1f} — downtrend", price)
