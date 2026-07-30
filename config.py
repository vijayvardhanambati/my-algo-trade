import os
from dotenv import load_dotenv

load_dotenv()

API_KEY      = os.environ["KITE_API_KEY"]
API_SECRET   = os.environ["KITE_API_SECRET"]
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")
TRADING_MODE = os.environ.get("TRADING_MODE", "paper")

# ── Capital ────────────────────────────────────────────────────────────────────
CAPITAL         = 100000
QUANTITY        = 1
# Per-trade allocation: 20% of capital = ₹20,000
# Max loss at 30% SL = ₹6,000 = 6% of capital per trade
# Worst case (2 consecutive losses) = ₹12,000 = 12% drawdown in one day
OPTIONS_CAPITAL = 20000

# ── Options risk management ────────────────────────────────────────────────────
OPTIONS_SL_PCT           = 40   # exit if premium drops 40%  (allow room to breathe)
OPTIONS_TARGET_PCT       = 60   # exit if premium gains 60%  (big wins cover losses)
OPTIONS_DAILY_TARGET_PCT = 5    # stop trading once daily P&L = 5% of capital = ₹1250

# ── VIX zones (determines buyer vs seller mode) ────────────────────────────────
# VIX < 11       → no trade (too quiet, no movement, no premium worth selling)
# VIX 11–13      → SELLER mode: credit spreads (theta decay favours sellers)
# VIX 13–18      → BUYER mode: buy CE/PE (enough movement for directional trades)
# VIX > 18       → no trade (too volatile, gaps can blow up both strategies)
VIX_NO_TRADE_BELOW = 11   # below this: skip
VIX_SELLER_MAX     = 13   # sell spreads when VIX is between 11 and 13
VIX_BUYER_MAX      = 18   # buy options when VIX is between 13 and 18
MAX_VIX            = 18   # kept for backward compatibility
MIN_VIX            = 11   # kept for backward compatibility

# ── Underlying (used for SELLER / spread mode only) ───────────────────────────
UNDERLYING = "NIFTY"

# ── Buyer-mode watchlist ───────────────────────────────────────────────────────
# Any NSE F&O symbol can be listed here.  The bot scores every symbol with all
# 5 strategies each scan cycle and trades the one with the highest consensus.
# Symbols must match the NFO "name" field (i.e. the root symbol, not the option
# tradingsymbol).  Remove any symbol whose options you don't want traded.
WATCHLIST = [
    "NIFTY",
    "BANKNIFTY",
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "BAJFINANCE",
]

# ── Equity strategy parameters (kept for ledger/costs compatibility) ───────────
STOP_LOSS_PCT       = 0.5
TARGET_PCT          = 1.5
DAILY_PROFIT_TARGET = 1250
TAX_RATE            = 0.42
LEVERAGE_MULTIPLIER = 5

# ── Market hours (IST) ─────────────────────────────────────────────────────────
MARKET_OPEN     = "09:20"
MARKET_CLOSE    = "15:15"
SQUARE_OFF_TIME = "14:45"

# ── Best trading windows (most volatility and volume) ─────────────────────────
MORNING_SESSION_START = "09:30"
MORNING_SESSION_END   = "11:30"
AFTERNOON_SESSION_START = "13:30"
AFTERNOON_SESSION_END   = "14:30"
