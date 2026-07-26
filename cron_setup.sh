#!/bin/bash
# Adds a cron job that sends a reminder to refresh the Kite token every morning at 8:45 AM IST.
# IST = UTC+5:30, so 8:45 IST = 03:15 UTC

CRON_JOB="15 3 * * 1-5 echo 'Kite token needs refresh. Run: cd /home/ubuntu/kite-algo-trader && source venv/bin/activate && python refresh_token.py && sudo systemctl restart kite-trader' | wall"

(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
echo "Cron job added. You'll get a system message at 8:45 AM IST (Mon-Fri) to refresh the token."
crontab -l
