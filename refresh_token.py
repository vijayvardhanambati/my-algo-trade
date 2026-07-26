"""
Run this every morning before market open to refresh the Kite access token.
The token expires daily at midnight IST.

On Oracle Cloud VM:
    source venv/bin/activate
    python refresh_token.py
    sudo systemctl restart kite-trader
"""
import os
import json
from urllib.parse import urlparse, parse_qs
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["KITE_API_KEY"]
API_SECRET = os.environ["KITE_API_SECRET"]
TOKEN_FILE = "token.json"


def update_env(key: str, value: str):
    env_path = ".env"
    lines = open(env_path).readlines() if os.path.exists(env_path) else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


kite = KiteConnect(api_key=API_KEY)
login_url = kite.login_url()

print("\n" + "=" * 60)
print("DAILY TOKEN REFRESH")
print("=" * 60)
print(f"\n1. Open this URL in your local browser:\n\n   {login_url}\n")
print("2. Log in with your Zerodha credentials.")
print("3. After login, copy the FULL redirect URL from your browser")
print("   (it will look like: http://127.0.0.1:5000/?request_token=xxx...)")
print("4. Paste the URL below and press Enter:\n")

redirected_url = input("Paste redirect URL: ").strip()
params = parse_qs(urlparse(redirected_url).query)
request_token = params.get("request_token", [None])[0]

if not request_token:
    print("\nERROR: Could not find request_token in the URL.")
    exit(1)

data = kite.generate_session(request_token, api_secret=API_SECRET)
access_token = data["access_token"]

with open(TOKEN_FILE, "w") as f:
    json.dump({"access_token": access_token}, f)

update_env("KITE_ACCESS_TOKEN", access_token)

print(f"\nToken saved successfully.")
print("\nRestart the bot to apply:")
print("  sudo systemctl restart kite-trader")
