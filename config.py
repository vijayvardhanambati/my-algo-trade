import os
from dotenv import load_dotenv

load_dotenv()

API_KEY      = os.environ["KITE_API_KEY"]
API_SECRET   = os.environ["KITE_API_SECRET"]
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")
TRADING_MODE = os.environ.get("TRADING_MODE", "paper")

# Capital
CAPITAL          = 20000
QUANTITY         = 1
OPTIONS_CAPITAL  = 3000   # max rupees per options trade

# Options risk management
OPTIONS_SL_PCT     = 40   # exit if premium drops 40%
OPTIONS_TARGET_PCT = 50   # exit if premium gains 50%
MAX_VIX            = 15   # skip trading if India VIX > this

# Underlying for options
UNDERLYING = "BANKNIFTY"  # BANKNIFTY or NIFTY

# Equity strategy parameters (kept for ledger/costs compatibility)
STOP_LOSS_PCT       = 0.5
TARGET_PCT          = 1.5
DAILY_PROFIT_TARGET = 1000
TAX_RATE            = 0.42
LEVERAGE_MULTIPLIER = 5

# Market hours (IST)
MARKET_OPEN     = "09:20"
MARKET_CLOSE    = "15:15"
SQUARE_OFF_TIME = "14:45"  # exit options by 2:45 PM
