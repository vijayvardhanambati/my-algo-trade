from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import pandas as pd


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    symbol: str
    signal: Signal
    reason: str
    price: float


class BaseStrategy(ABC):
    def __init__(self, symbol: str):
        self.symbol = symbol

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        """Given OHLCV DataFrame, return a TradeSignal."""
        ...
