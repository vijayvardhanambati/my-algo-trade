#!/bin/bash
# Run this once on your Oracle Cloud VM after SSH-ing in.
# Usage: bash setup.sh

set -e

echo "=== Updating system packages ==="
sudo apt-get update -y && sudo apt-get upgrade -y

echo "=== Installing Python 3.12 and dependencies ==="
sudo apt-get install -y python3.12 python3.12-venv python3-pip git

echo "=== Creating virtual environment ==="
python3.12 -m venv venv
source venv/bin/activate

echo "=== Installing Python packages ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Setting up systemd service ==="
sudo cp kite-trader.service /etc/systemd/system/kite-trader.service
sudo systemctl daemon-reload
sudo systemctl enable kite-trader

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy your .env file:  nano .env"
echo "  2. Authenticate:         source venv/bin/activate && python refresh_token.py"
echo "  3. Start the bot:        sudo systemctl start kite-trader"
echo "  4. Check status:         sudo systemctl status kite-trader"
echo "  5. Watch logs:           sudo journalctl -u kite-trader -f"
