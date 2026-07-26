import os
from dotenv import load_dotenv

load_dotenv()

API_KEY      = os.environ["KITE_API_KEY"]
API_SECRET   = os.environ["KITE_API_SECRET"]
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")
TRADING_MODE = os.environ.get("TRADING_MODE", "paper")

CAPITAL       = 20000
QUANTITY      = 1
STOP_LOSS_PCT = 0.5
TARGET_PCT    = 1.5

WATCHLIST = ["HDFCBANK", "ICICIBANK", "RELIANCE"]

MARKET_OPEN     = "09:20"
MARKET_CLOSE    = "15:15"
SQUARE_OFF_TIME = "15:00"
