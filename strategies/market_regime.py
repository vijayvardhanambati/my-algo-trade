import pandas as pd
from market_data import get_index_data


def get_market_regime(kite) -> str:
    """
    Classify market as 'bull' or 'bear' using NIFTY 50 daily EMA20/EMA50.
    Returns 'bull' when EMA20 > EMA50, else 'bear'.
    """
    try:
        df = get_index_data(kite, "NIFTY 50", interval="day", days=60)
        close = df["close"]
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        if ema20.iloc[-1] > ema50.iloc[-1]:
            return "bull"
        return "bear"
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[REGIME] Could not determine market regime: {e}")
        return "neutral"
