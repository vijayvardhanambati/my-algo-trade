import logging
import pandas as pd
from market_data import get_index_data

logger = logging.getLogger(__name__)


def get_market_regime(kite) -> str:
    """
    Classify intraday market regime using NIFTY 50 on 1-hour candles.
    Uses EMA9 vs EMA21 — faster than daily EMA20/50, catches intraday turns.
    Returns 'bull', 'bear', or 'neutral'.
    """
    try:
        df = get_index_data(kite, "NIFTY 50", interval="60minute", days=10)
        close = df["close"]
        ema9  = close.ewm(span=9,  adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()

        curr_bull = ema9.iloc[-1] > ema21.iloc[-1]
        prev_bull = ema9.iloc[-2] > ema21.iloc[-2]

        if curr_bull:
            regime = "bull"
        else:
            regime = "bear"

        # Log the actual values so we can see how close they are
        gap_pct = abs(ema9.iloc[-1] - ema21.iloc[-1]) / ema21.iloc[-1] * 100
        logger.info(
            f"[REGIME] EMA9={ema9.iloc[-1]:.1f} EMA21={ema21.iloc[-1]:.1f} "
            f"Gap={gap_pct:.2f}% → {regime.upper()}"
            + (" (just flipped)" if curr_bull != prev_bull else "")
        )
        return regime

    except Exception as e:
        logger.warning(f"[REGIME] Could not determine market regime: {e}")
        return "neutral"
