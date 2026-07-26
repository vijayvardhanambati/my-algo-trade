import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["KITE_API_KEY"]
API_SECRET = os.environ["KITE_API_SECRET"]
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")
TRADING_MODE = os.environ.get("TRADING_MODE", "paper")  # paper | live

# Trading parameters
QUANTITY = 1           # number of shares per trade (LIVE mode only)
STOP_LOSS_PCT = 0.5    # 0.5% stop loss
TARGET_PCT = 1.0       # 1.0% target

# Paper-mode capital & goal tracking
CAPITAL = 25_000               # rupees available; paper mode sizes one full-capital position at a time
DAILY_PROFIT_TARGET = 1_000    # rupees, net of charges and tax
TAX_RATE = 0.42                # applied to net profit for goal-tracking display only (real tax is filed annually)
LEVERAGE_MULTIPLIER = 5        # side-metric only in the paper ledger — never used for real order sizing

# Instruments to trade (NSE symbols)
WATCHLIST = ["RELIANCE", "INFY", "TCS"]

# Market hours (IST)
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:15"
SQUARE_OFF_TIME = "15:00"  # square off all positions before close
