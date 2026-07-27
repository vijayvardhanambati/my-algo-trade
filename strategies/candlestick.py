import pandas as pd
from .base import BaseStrategy, TradeSignal, Signal


def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _upper_wick(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_wick(row) -> float:
    return min(row["open"], row["close"]) - row["low"]


def _is_bullish(row) -> bool:
    return row["close"] > row["open"]


def _is_bearish(row) -> bool:
    return row["close"] < row["open"]


class CandlestickStrategy(BaseStrategy):
    """Detects bullish and bearish candlestick reversal patterns."""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 3:
            return TradeSignal(self.symbol, Signal.HOLD, "Not enough candles", df["close"].iloc[-1])

        p2    = df.iloc[-3]
        prev  = df.iloc[-2]
        curr  = df.iloc[-1]
        price = curr["close"]

        # Bullish Engulfing
        if (_is_bearish(prev) and _is_bullish(curr) and
                curr["open"] < prev["close"] and curr["close"] > prev["open"]):
            return TradeSignal(self.symbol, Signal.BUY, "Bullish Engulfing", price)

        # Bearish Engulfing
        if (_is_bullish(prev) and _is_bearish(curr) and
                curr["open"] > prev["close"] and curr["close"] < prev["open"]):
            return TradeSignal(self.symbol, Signal.SELL, "Bearish Engulfing", price)

        b = _body(curr)
        if b > 0:
            # Hammer — long lower wick, small upper wick (bullish reversal)
            if _lower_wick(curr) >= 2 * b and _upper_wick(curr) <= 0.3 * b:
                return TradeSignal(self.symbol, Signal.BUY, "Hammer", price)

            # Shooting Star — long upper wick, small lower wick (bearish reversal)
            if _upper_wick(curr) >= 2 * b and _lower_wick(curr) <= 0.3 * b:
                return TradeSignal(self.symbol, Signal.SELL, "Shooting Star", price)

        # Morning Star — 3-candle bullish reversal
        if (_is_bearish(p2) and
                _body(prev) < _body(p2) * 0.3 and
                _is_bullish(curr) and
                curr["close"] > (p2["open"] + p2["close"]) / 2):
            return TradeSignal(self.symbol, Signal.BUY, "Morning Star", price)

        # Evening Star — 3-candle bearish reversal
        if (_is_bullish(p2) and
                _body(prev) < _body(p2) * 0.3 and
                _is_bearish(curr) and
                curr["close"] < (p2["open"] + p2["close"]) / 2):
            return TradeSignal(self.symbol, Signal.SELL, "Evening Star", price)

        # Doji — indecision
        candle_range = curr["high"] - curr["low"]
        if candle_range > 0 and _body(curr) <= 0.1 * candle_range:
            return TradeSignal(self.symbol, Signal.HOLD, "Doji — indecision", price)

        return TradeSignal(self.symbol, Signal.HOLD, "No pattern", price)
