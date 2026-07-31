# Kite Algo Trader — Complete Reference Guide

---

## Table of Contents

1. Project Overview
2. Architecture & Files
3. Trading Logic Explained
4. Google Cloud VM Setup
5. Daily Workflow
6. Configuration Reference
7. File Update Workflow (Local → GitHub → VM)
8. Common VM Commands
9. Switching Trading Modes
10. Monitoring Profits & Logs
11. Troubleshooting
12. Important Warnings

---

## 1. Project Overview

This is an automated options trading bot for Indian markets built on top of the Zerodha Kite Connect API.

- **What it trades:** BANKNIFTY CE (Call) and PE (Put) options
- **Exchange:** NFO (National Futures & Options)
- **Product type:** MIS (Margin Intraday Square-off) — all positions auto-close by 3:30 PM
- **Capital used:** ₹3,000 per options trade (configurable)
- **Stop Loss:** 40% of premium paid
- **Target:** 50% of premium paid
- **Square-off time:** 2:45 PM IST (bot exits before market close)
- **Mode:** Starts in PAPER mode (logs trades but places no real orders)

### Why Google Cloud VM?

MassMutual's Palo Alto GlobalProtect VPN blocks `api.kite.trade` at the TLS level.
The corporate firewall intercepts SSL handshakes, making it impossible to run the bot
on any machine connected to the corporate network. The Google Cloud VM has no such
restriction and runs 24/7.

---

## 2. Architecture & Files

```
/root/my-algo-trade/
├── main.py                  — Main bot loop (runs every 5 minutes)
├── auth.py                  — Zerodha login, token management
├── config.py                — All configuration variables
├── market_data.py           — Fetch OHLCV, VIX, index data from Kite
├── news_sentiment.py        — RSS news sentiment (ET + Moneycontrol)
├── options_trader.py        — CE/PE entry, SL/target monitoring, square-off
├── order_manager.py         — Equity order management (legacy, kept for compatibility)
├── ledger.py                — Trade history logging
├── costs.py                 — Brokerage/tax cost calculations
├── backtest.py              — Backtesting engine
├── refresh_token.py         — Daily token refresh script
├── bot.log                  — Persistent log file (all trades, signals, errors)
├── token.json               — Cached Zerodha access token
├── .env                     — Secrets (API keys, access token, trading mode)
└── strategies/
    ├── __init__.py          — Exports all strategies
    ├── base.py              — BaseStrategy class, Signal enum, TradeSignal dataclass
    ├── ma_crossover.py      — EMA fast/slow crossover strategy
    ├── rsi_strategy.py      — RSI overbought/oversold strategy
    ├── vwap_breakout.py     — VWAP breakout strategy
    ├── candlestick.py       — Candlestick pattern detection
    ├── supertrend.py        — Supertrend (ATR-based) strategy
    └── market_regime.py     — Bull/Bear market regime detection
```

### .env file (NEVER commit this to GitHub)

```
KITE_API_KEY=9k1q9x97flyommet
KITE_API_SECRET=3fbq201k17ibaxa8fqvtjffu4hhuht9z
KITE_ACCESS_TOKEN=<refreshed daily>
TRADING_MODE=paper
```

---

## 3. Trading Logic Explained

The bot runs every 5 minutes. Before entering any trade it passes through 5 gates.
ALL gates must pass before an options position is opened.

```
Every 5 minutes
     │
     ▼
[1] Market open? (9:20 AM – 3:15 PM IST)
     │ No → sleep
     ▼
[2] Existing position? → monitor SL/target → exit if hit
     │
     ▼
[3] Square-off time? (2:45 PM) → close all → stop
     │
     ▼
[GATE 1] India VIX ≤ 20?
     │ No → skip (too volatile)
     ▼
[GATE 2] Market Regime (NIFTY 50 daily EMA20 vs EMA50)
     │ EMA20 > EMA50 → bull | EMA20 < EMA50 → bear
     │ Neutral → skip
     ▼
[GATE 3] News Sentiment (ET + Moneycontrol RSS)
     │ Bearish news in bull regime → skip
     │ Bullish news in bear regime → skip
     ▼
[GATE 4] 5-Indicator Consensus on BANKNIFTY (5-min candles)
     │ Strategies: MA Crossover, RSI, VWAP, Candlestick, Supertrend
     │ Need 3/5 indicators to agree
     ▼
[GATE 5] Regime + Consensus match?
     │ Bull regime + 3/5 BUY  → Enter CE (Call option)
     │ Bear regime + 3/5 SELL → Enter PE (Put option)
     ▼
[ENTRY] Buy ATM option via Kite NFO
     │ Monitor every 5 min
     │ Exit if: premium drops 40% (SL) OR gains 50% (target)
     ▼
[EXIT] Sell option, log P&L
```

### Indicators explained

| Indicator | Bullish signal | Bearish signal |
|---|---|---|
| MA Crossover | EMA9 crosses above EMA21 | EMA9 crosses below EMA21 |
| RSI | RSI < 40 (oversold, expect bounce) | RSI > 60 (overbought, expect drop) |
| VWAP | Price crosses above VWAP | Price crosses below VWAP |
| Candlestick | Bullish Engulfing, Hammer, Morning Star | Bearish Engulfing, Shooting Star, Evening Star |
| Supertrend | Direction flips to +1 (bullish) | Direction flips to -1 (bearish) |

### Options basics

- **CE (Call option)** — Profit when BANKNIFTY goes UP
- **PE (Put option)** — Profit when BANKNIFTY goes DOWN
- **ATM (At The Money)** — Strike closest to current BANKNIFTY price
- **Premium** — Price you pay to buy the option (e.g., ₹250 per unit)
- **Lot size** — BANKNIFTY = 15 units per lot | NIFTY = 50 units per lot
- **MIS** — Intraday product, automatically squared off by exchange at 3:30 PM

---

## 4. Google Cloud VM Setup

### VM Details

- **Provider:** Google Cloud
- **User:** root
- **Project path:** /root/my-algo-trade
- **Python:** via venv at /root/my-algo-trade/venv
- **Timezone:** Asia/Kolkata (IST)
- **Service name:** kite-trader (systemd)

### Systemd service file location

```
/etc/systemd/system/kite-trader.service
```

### Service file contents

```ini
[Unit]
Description=Kite Algo Trader
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/my-algo-trade
ExecStart=/root/my-algo-trade/venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/root/my-algo-trade/.env

[Install]
WantedBy=multi-user.target
```

### First-time VM setup steps (for reference if VM is rebuilt)

```bash
# 1. Set timezone
timedatectl set-timezone Asia/Kolkata

# 2. Install system dependencies
apt update && apt install -y python3 python3-pip python3-venv unzip curl

# 3. Download project from GitHub
mkdir -p /root/my-algo-trade
cd /root/my-algo-trade
curl -L https://github.com/vijayvardhanambati/my-algo-trade/archive/main.zip -o main.zip
unzip main.zip
mv my-algo-trade-main/* .
rm -rf my-algo-trade-main main.zip

# 4. Create virtual environment and install packages
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Create .env file
cat > .env << 'EOF'
KITE_API_KEY=9k1q9x97flyommet
KITE_API_SECRET=3fbq201k17ibaxa8fqvtjffu4hhuht9z
KITE_ACCESS_TOKEN=
TRADING_MODE=paper
EOF

# 6. Login and get first access token
python refresh_token.py

# 7. Create and enable systemd service
# (paste service file content as shown above)
systemctl daemon-reload
systemctl enable kite-trader
systemctl start kite-trader
```

---

## 5. Daily Workflow

### Every morning before 9:20 AM IST — MANDATORY

The Zerodha access token expires every day. Without refreshing it, all API calls fail.

```bash
# SSH into VM
ssh root@<your-vm-ip>

# Go to project
cd /root/my-algo-trade

# Activate venv
source venv/bin/activate

# Refresh token (follow the URL prompt, paste redirect URL)
python refresh_token.py

# Restart bot with new token
systemctl restart kite-trader

# Confirm it's running
systemctl status kite-trader
```

### How refresh_token.py works

1. Prints a Zerodha login URL
2. You open it in your browser and log in
3. Browser redirects to http://127.0.0.1:5000/?request_token=XXXXX (page will fail — that's expected)
4. Copy the full URL from browser address bar
5. Paste it into the terminal
6. Token is saved to token.json and .env automatically

### During market hours — optional monitoring

```bash
# Watch live logs
journalctl -u kite-trader -f

# Check today's trade exits
grep "OPTIONS EXIT" /root/my-algo-trade/bot.log | grep "$(date +%Y-%m-%d)"

# Check bot status
systemctl status kite-trader
```

### After market hours

The bot automatically stops entering new trades after 2:45 PM and squares off
any open positions. No manual action needed.

---

## 6. Configuration Reference

File: `/root/my-algo-trade/config.py`

| Variable | Default | Description |
|---|---|---|
| TRADING_MODE | paper | "paper" = log only, "live" = real orders |
| UNDERLYING | BANKNIFTY | Which index options to trade (BANKNIFTY or NIFTY) |
| OPTIONS_CAPITAL | 3000 | Max rupees per options trade |
| OPTIONS_SL_PCT | 40 | Exit if premium drops this % (stop loss) |
| OPTIONS_TARGET_PCT | 50 | Exit if premium gains this % (target) |
| MAX_VIX | 20 | Skip trading if India VIX exceeds this |
| MARKET_OPEN | 09:20 | Bot starts looking for trades |
| MARKET_CLOSE | 15:15 | Bot stops all activity |
| SQUARE_OFF_TIME | 14:45 | Force-exit all positions by this time |
| CAPITAL | 20000 | Equity trading capital (legacy) |
| DAILY_PROFIT_TARGET | 1000 | Daily profit target for ledger |

### How to change any setting directly on VM

```bash
# Edit config.py
cat > /root/my-algo-trade/config.py << 'EOF'
# paste updated config here
EOF

# Restart bot
systemctl restart kite-trader
```

---

## 7. File Update Workflow (Local → GitHub → VM)

Since the corporate VPN blocks GitHub pushes from the work machine for personal accounts,
the workflow is:

```
Edit file locally (Windows)
         ↓
Upload to GitHub (vijayvardhanambati/my-algo-trade) via web browser or personal machine
         ↓
Download on VM using curl
         ↓
Restart bot
```

### Curl commands for each file

```bash
cd /root/my-algo-trade

# Core files
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/main.py -o main.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/config.py -o config.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/market_data.py -o market_data.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/news_sentiment.py -o news_sentiment.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/options_trader.py -o options_trader.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/auth.py -o auth.py

# Strategy files
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/__init__.py -o strategies/__init__.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/candlestick.py -o strategies/candlestick.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/supertrend.py -o strategies/supertrend.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/market_regime.py -o strategies/market_regime.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/ma_crossover.py -o strategies/ma_crossover.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/rsi_strategy.py -o strategies/rsi_strategy.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/strategies/vwap_breakout.py -o strategies/vwap_breakout.py

# Restart after downloading
systemctl restart kite-trader
journalctl -u kite-trader -f
```

---

## 8. Common VM Commands

### Bot control

```bash
# Start bot
systemctl start kite-trader

# Stop bot
systemctl stop kite-trader

# Restart bot
systemctl restart kite-trader

# Check if running
systemctl status kite-trader

# Enable auto-start on VM reboot
systemctl enable kite-trader

# Disable auto-start
systemctl disable kite-trader
```

### Logs

```bash
# Watch live logs (Ctrl+C to exit)
journalctl -u kite-trader -f

# Last 50 lines
journalctl -u kite-trader -n 50

# All logs today
journalctl -u kite-trader --since today

# Persistent log file
cat /root/my-algo-trade/bot.log

# Clear old log file
> /root/my-algo-trade/bot.log
```

### Checking files on VM

```bash
# See all project files
ls -la /root/my-algo-trade/
ls -la /root/my-algo-trade/strategies/

# Check current config
cat /root/my-algo-trade/config.py

# Check .env (trading mode, token)
cat /root/my-algo-trade/.env

# Check current token
cat /root/my-algo-trade/token.json
```

### Python environment

```bash
# Activate venv
source /root/my-algo-trade/venv/bin/activate

# Run bot manually (useful for testing)
cd /root/my-algo-trade
python main.py

# Run token refresh
python refresh_token.py

# Install new package
pip install <package-name>
```

---

## 9. Switching Trading Modes

### Switch to PAPER mode (safe, no real orders)

```bash
sed -i 's/TRADING_MODE=.*/TRADING_MODE=paper/' /root/my-algo-trade/.env
systemctl restart kite-trader
```

### Switch to LIVE mode (real money orders)

```bash
sed -i 's/TRADING_MODE=.*/TRADING_MODE=live/' /root/my-algo-trade/.env
systemctl restart kite-trader
```

### Confirm which mode is active

```bash
grep TRADING_MODE /root/my-algo-trade/.env
```

Look for this line in the logs after restart:
```
KITE OPTIONS BOT — PAPER MODE
```
or
```
KITE OPTIONS BOT — LIVE MODE
```

---

## 10. Monitoring Profits & Logs

### What a successful trade looks like in the logs

```
[BOT] Market open (10:15) — running analysis
[VIX] India VIX = 14.32 (limit: 20) ✓
[REGIME] Market regime: BULL
[NEWS] Sentiment: BULLISH
[MACrossoverStrategy] BUY — EMA9 crossed above EMA21
[RSIStrategy] BUY — RSI=38.4 (oversold)
[VWAPBreakoutStrategy] BUY — Price broke above VWAP
[CandlestickStrategy] BUY — Bullish Engulfing
[SupertrendStrategy] HOLD — Supertrend bullish (no flip)
[CONSENSUS] BUY: 4/5 | SELL: 0/5 | Regime: bull
[SIGNAL] Entering CE (Call) — Bull regime + 4/5 indicators agree BUY
[OPTIONS PAPER] BUY CE | BANKNIFTY27JUL25C52000 | Strike: 52000 | Expiry: 2025-07-31 | Premium: ₹245.00 | Lots: 1 | Underlying: ₹51823.45
...
[OPTIONS] BANKNIFTY27JUL25C52000 | Entry: ₹245.00 | Current: ₹367.50 | PnL: +₹1837.50 (+50.0%)
[OPTIONS EXIT] CE | BANKNIFTY27JUL25C52000 | Exit: ₹367.50 | P&L: +₹1837.50 (+50.0%) | Reason: Target hit
```

### See today's closed trades

```bash
grep "OPTIONS EXIT" /root/my-algo-trade/bot.log | grep "$(date +%Y-%m-%d)"
```

### See all P&L lines

```bash
grep "P&L:" /root/my-algo-trade/bot.log
```

### Authoritative P&L source (live mode only)

Zerodha Kite dashboard → https://kite.zerodha.com → P&L tab (top right)
Shows every trade with entry price, exit price, and realized P&L.
In paper mode, this will show nothing — only the bot logs matter.

---

## 11. Troubleshooting

### Bot keeps crashing (restart loop)

```bash
# Check what error is causing the crash
journalctl -u kite-trader -n 30
```

Common errors and fixes:

**ImportError: cannot import name 'X' from 'config'**
→ The VM has an old config.py. Re-download it:
```bash
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/main/config.py -o /root/my-algo-trade/config.py
systemctl restart kite-trader
```

**ModuleNotFoundError: No module named 'strategies.candlestick'**
→ New strategy files not downloaded. Run all strategy curl commands from Section 7.

**TokenException: Incorrect `api_key` or `access_token`**
→ Token expired. Run refresh_token.py before 9:20 AM:
```bash
cd /root/my-algo-trade && source venv/bin/activate && python refresh_token.py
systemctl restart kite-trader
```

**ValueError: No data returned — market may be closed or holiday**
→ Normal on weekends and market holidays. Bot will resume next trading day automatically.

**ValueError: No BANKNIFTY CE found near strike XXXXX**
→ Options instruments list issue. Usually self-resolves on next 5-minute cycle.
→ If persistent: check NFO segment is enabled on your Zerodha account.

### Bot is running but not trading

Check these in order:
1. Is it market hours? (9:20 AM – 3:15 PM IST, weekdays only)
2. Is VIX above 20? (check `grep "VIX" bot.log`)
3. Is regime neutral? (check `grep "REGIME" bot.log`)
4. Are indicators agreeing? (check `grep "CONSENSUS" bot.log`)

### VM unreachable / SSH not working

1. Go to Google Cloud Console → VM Instances
2. Click on your VM → Start if stopped
3. Use the browser-based SSH from the console as a fallback

### Bot ran but placed no order in live mode

1. Check F&O is enabled on Zerodha: kite.zerodha.com → Account → Segments
2. Check margin available for MIS options trading
3. Look for "Order placed" or "Exit order placed" in logs — if absent, order failed silently

---

## 12. Important Warnings

### Financial risk

- Options trading is high risk. Premiums can go to zero.
- The 40% stop loss means you can lose ₹1,200 on a ₹3,000 position in one trade.
- The bot can make multiple trades per day. Maximum daily loss depends on how many
  trades it takes.
- Run in PAPER mode for at least 1–2 weeks before going live. Watch how signals
  behave across different market conditions.
- Never put money you cannot afford to lose into this.

### Token security

- The .env file contains your Zerodha API credentials.
- NEVER commit .env to GitHub. It is in .gitignore for this reason.
- If you accidentally expose your API key, immediately regenerate it from:
  https://developers.kite.trade → Apps → Regenerate secret

### Access token expiry

- Zerodha access tokens expire at midnight every day.
- If refresh_token.py is not run before 9:20 AM, the bot will fail to fetch
  any market data and will crash on the first API call.
- Consider setting a phone alarm for 9:00 AM on trading days as a reminder.

### Market holidays

- The bot handles market holidays gracefully (returns "no data" and sleeps).
- NSE holiday list: https://www.nseindia.com/resources/exchange-communication-holidays

### Lot size and capital

- BANKNIFTY lot size = 15 units
- If BANKNIFTY option premium = ₹300, one lot costs ₹300 × 15 = ₹4,500
- With OPTIONS_CAPITAL = ₹3,000, the bot buys 0 lots if premium > ₹200
- Increase OPTIONS_CAPITAL in config.py if you want to participate at higher premiums

### What "paper mode" means exactly

- No orders are sent to Zerodha in paper mode
- The bot still fetches real market data and runs all analysis
- Signals and hypothetical P&L are logged as if trades were real
- This is the safest way to validate the strategy before risking real money

---

## API & Account Details

| Item | Value |
|---|---|
| Kite API Key | 9k1q9x97flyommet |
| Kite Dashboard | https://kite.zerodha.com |
| Kite Developer Portal | https://developers.kite.trade |
| GitHub Repo | https://github.com/vijayvardhanambati/my-algo-trade |
| Google Cloud Console | https://console.cloud.google.com |

---

*Last updated: July 2025*

# Pull all files from the upgrades branch
cd /root/my-algo-trade

curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/main.py -o main.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/config.py -o config.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/options_trader.py -o options_trader.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/spread_trader.py -o spread_trader.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/market_data.py -o market_data.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/strategies/__init__.py -o strategies/__init__.py
curl https://raw.githubusercontent.com/vijayvardhanambati/my-algo-trade/upgrades/strategies/adx.py -o strategies/adx.py

systemctl restart kite-trader
journalctl -u kite-trader -f
