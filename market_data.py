import pandas as pd
from kiteconnect import KiteConnect
from datetime import datetime, timedelta


def get_ohlcv(kite: KiteConnect, symbol: str, interval: str = "minute", days: int = 1) -> pd.DataFrame:
    """Fetch historical OHLCV data for a symbol."""
    instrument = _get_instrument_token(kite, symbol)
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)

    records = kite.historical_data(instrument, from_date, to_date, interval)
    df = pd.DataFrame(records)
    df.set_index("date", inplace=True)
    df.index = pd.to_datetime(df.index)
    return df[["open", "high", "low", "close", "volume"]]


def get_ltp(kite: KiteConnect, symbol: str) -> float:
    """Get last traded price."""
    quote = kite.ltp(f"NSE:{symbol}")
    return quote[f"NSE:{symbol}"]["last_price"]


def _get_instrument_token(kite: KiteConnect, symbol: str) -> int:
    instruments = kite.instruments("NSE")
    for inst in instruments:
        if inst["tradingsymbol"] == symbol:
            return inst["instrument_token"]
    raise ValueError(f"Instrument not found: {symbol}")
