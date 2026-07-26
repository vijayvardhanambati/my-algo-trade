import os
import json
import ssl
import sys
import webbrowser
import truststore
truststore.inject_into_ssl()  # use Windows cert store (corporate proxy CA)

from flask import Flask, request
from kiteconnect import KiteConnect
from config import API_KEY, API_SECRET

TOKEN_FILE = "token.json"
_flask_app = Flask(__name__)
kite = KiteConnect(api_key=API_KEY)

# True when running on a headless server (no display / Oracle Cloud VM)
HEADLESS = not os.environ.get("DISPLAY") and sys.platform != "win32" and sys.platform != "darwin"


def save_token(access_token: str):
    with open(TOKEN_FILE, "w") as f:
        json.dump({"access_token": access_token}, f)
    _update_env("KITE_ACCESS_TOKEN", access_token)


def load_token() -> str | None:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f).get("access_token")
    return os.environ.get("KITE_ACCESS_TOKEN") or None


def _update_env(key: str, value: str):
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


@_flask_app.route("/")
def _callback():
    request_token = request.args.get("request_token")
    if not request_token:
        return "Missing request_token", 400
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    save_token(data["access_token"])
    func = request.environ.get("werkzeug.server.shutdown")
    if func:
        func()
    return "<h2>Login successful! You can close this tab.</h2>"


def _login_headless():
    """Server/headless login: print URL, user pastes request_token from browser redirect."""
    login_url = kite.login_url()
    print("\n" + "=" * 60)
    print("HEADLESS LOGIN — follow these steps:")
    print("=" * 60)
    print(f"\n1. Open this URL in your local browser:\n\n   {login_url}\n")
    print("2. Log in with your Zerodha credentials.")
    print("3. After login, your browser will try to redirect to")
    print("   http://127.0.0.1:5000/?request_token=XXXXXXXX&...")
    print("   The page will fail to load — that is expected.")
    print("4. Copy the FULL URL from your browser's address bar.")
    print("5. Paste it here and press Enter:\n")

    redirected_url = input("Paste redirect URL: ").strip()

    # extract request_token from URL query string
    from urllib.parse import urlparse, parse_qs
    params = parse_qs(urlparse(redirected_url).query)
    request_token = params.get("request_token", [None])[0]

    if not request_token:
        raise ValueError("Could not find request_token in the URL. Please try again.")

    data = kite.generate_session(request_token, api_secret=API_SECRET)
    save_token(data["access_token"])
    print("[auth] Login successful. Token saved.\n")


def _login_browser():
    """Local login: open browser and capture token via Flask redirect server."""
    login_url = kite.login_url()
    print(f"\n[auth] Opening browser for Zerodha login...\n{login_url}\n")
    webbrowser.open(login_url)
    _flask_app.run(host="127.0.0.1", port=5000, debug=False)


def login() -> KiteConnect:
    existing = load_token()
    if existing:
        kite.set_access_token(existing)
        try:
            kite.profile()
            print("[auth] Using cached access token.")
            return kite
        except Exception:
            print("[auth] Cached token expired, re-authenticating...")

    if HEADLESS:
        _login_headless()
    else:
        _login_browser()

    token = load_token()
    kite.set_access_token(token)
    return kite
