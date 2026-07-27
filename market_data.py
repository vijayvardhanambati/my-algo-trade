import pandas as pd
from kiteconnect import KiteConnect
from datetime import datetime, timedelta

# Instrument tokens for indices (fixed, never change)
_INDEX_TOKENS = {
    "NIFTY 50":   256265,
    "NIFTY BANK": 260105,
    "INDIA VIX":  264969,
}


def get_ohlcv(kite: KiteConnect, symbol: str, interval: str = "5minute", days: int = 1) -> pd.DataFrame:
    """Fetch OHLCV for a stock symbol."""
    token     = _get_instrument_token(kite, symbol)
    to_date   = datetime.now()
    from_date = to_date - timedelta(days=days)
    records   = kite.historical_data(token, from_date, to_date, interval)
    if not records:
        raise ValueError(f"No data returned for {symbol} — market may be closed or holiday")
    df = pd.DataFrame(records)
    df.set_index("date", inplace=True)
    df.index = pd.to_datetime(df.index)
    return df[["open", "high", "low", "close", "volume"]]


def get_index_data(kite: KiteConnect, index: str, interval: str = "5minute", days: int = 5) -> pd.DataFrame:
    """Fetch OHLCV for a market index using fixed instrument tokens."""
    token = _INDEX_TOKENS.get(index)
    if not token:
        raise ValueError(f"Unknown index: {index}. Use: {list(_INDEX_TOKENS.keys())}")
    to_date   = datetime.now()
    from_date = to_date - timedelta(days=days)
    records   = kite.historical_data(token, from_date, to_date, interval)
    if not records:
        raise ValueError(f"No data returned for {index}")
    df = pd.DataFrame(records)
    df.set_index("date", inplace=True)
    df.index = pd.to_datetime(df.index)
    return df[["open", "high", "low", "close", "volume"]]


def get_vix(kite: KiteConnect) -> float:
    """Get India VIX current value."""
    quote = kite.ltp(["NSE:INDIA VIX"])
    return quote["NSE:INDIA VIX"]["last_price"]


def get_ltp(kite: KiteConnect, symbol: str) -> float:
    """Get last traded price for an NSE equity."""
    quote = kite.ltp(f"NSE:{symbol}")
    return quote[f"NSE:{symbol}"]["last_price"]


def _get_instrument_token(kite: KiteConnect, symbol: str) -> int:
    instruments = kite.instruments("NSE")
    for inst in instruments:
        if inst["tradingsymbol"] == symbol:
            return inst["instrument_token"]
    raise ValueError(f"Instrument not found: {symbol}")
