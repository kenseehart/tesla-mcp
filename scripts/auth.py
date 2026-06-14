#!/usr/bin/env python3
"""Tesla Fleet OAuth setup. Saves ~/.tesla_tokens.json and updates .env."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv, set_key

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TESLA_CLIENT_ID = os.getenv("TESLA_CLIENT_ID", "")
TESLA_CLIENT_SECRET = os.getenv("TESLA_CLIENT_SECRET", "")
TESLA_REGION = os.getenv("TESLA_REGION", "na")
TESLA_REDIRECT_URI = os.getenv("TESLA_REDIRECT_URI", "http://localhost:3456/callback")
TOKEN_FILE = Path(os.getenv("TESLA_TOKEN_FILE", str(Path.home() / ".tesla_tokens.json")))
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

REGION_URLS = {
    "na": "https://fleet-api.prd.na.vn.cloud.tesla.com",
    "eu": "https://fleet-api.prd.eu.vn.cloud.tesla.com",
    "cn": "https://fleet-api.prd.cn.vn.cloud.tesla.cn",
}
AUTH_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
AUTH_AUTHORIZE_URL = "https://auth.tesla.com/oauth2/v3/authorize"
BASE_URL = REGION_URLS.get(TESLA_REGION, REGION_URLS["na"])
SCOPES = (
    "openid offline_access user_data vehicle_device_data "
    "vehicle_location vehicle_cmds vehicle_charging_cmds"
)


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def build_auth_url() -> str:
    params = {
        "client_id": TESLA_CLIENT_ID,
        "locale": "en-US",
        "prompt": "login",
        "redirect_uri": TESLA_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": "tesla_auth_setup",
    }
    return f"{AUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            AUTH_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": TESLA_CLIENT_ID,
                "client_secret": TESLA_CLIENT_SECRET,
                "code": code,
                "audience": BASE_URL,
                "redirect_uri": TESLA_REDIRECT_URI,
            },
        )
    if resp.status_code != 200:
        print(f"Token exchange failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": time.time() + data.get("expires_in", 3600),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_tokens(tokens: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    TOKEN_FILE.chmod(0o600)
    refresh = tokens.get("refresh_token", "")
    if refresh and ENV_FILE.exists():
        set_key(str(ENV_FILE), "TESLA_REFRESH_TOKEN", refresh)


def open_browser(url: str) -> None:
    if is_wsl():
        for cmd in (
            ["/mnt/c/Windows/System32/cmd.exe", "/c", "start", "", url],
            ["wslview", url],
            ["xdg-open", url],
        ):
            try:
                subprocess.run(cmd, check=False)
                return
            except OSError:
                continue
        print("Could not open browser automatically — copy the URL above into Chrome/Edge.")
    else:
        webbrowser.open(url)


def wait_for_callback() -> str:
    parsed = urllib.parse.urlparse(TESLA_REDIRECT_URI)
    port = parsed.port or 3456
    path = parsed.path or "/callback"
    code_holder: list[str | None] = [None]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            req = urllib.parse.urlparse(self.path)
            if req.path != path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(req.query)
            code_holder[0] = qs.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorized. You can close this tab.</h1>")

        def log_message(self, *_args) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    deadline = time.time() + 300
    print(f"Waiting for callback on {TESLA_REDIRECT_URI} (5 min timeout)...")
    while code_holder[0] is None and time.time() < deadline:
        server.handle_request()
    server.server_close()
    if not code_holder[0]:
        print("Timed out waiting for authorization.", file=sys.stderr)
        sys.exit(1)
    return code_holder[0]


def main() -> None:
    if not TESLA_CLIENT_ID or not TESLA_CLIENT_SECRET:
        print("Error: set TESLA_CLIENT_ID and TESLA_CLIENT_SECRET in .env", file=sys.stderr)
        sys.exit(1)

    url = build_auth_url()
    print("Tesla Fleet OAuth setup")
    print(f"Redirect URI: {TESLA_REDIRECT_URI}")
    if is_wsl():
        print("WSL detected — opening your Windows browser.")
    print(f"\n{url}\n")

    if TESLA_REDIRECT_URI.startswith("http://localhost") or TESLA_REDIRECT_URI.startswith(
        "http://127.0.0.1"
    ):
        open_browser(url)
        code = wait_for_callback()
    else:
        open_browser(url)
        print(f"After login, copy the code from the redirect to {TESLA_REDIRECT_URI}")
        code = input("Paste authorization code: ").strip()

    tokens = exchange_code(code)
    save_tokens(tokens)
    print(f"Saved tokens to {TOKEN_FILE}")
    if ENV_FILE.exists():
        print(f"Updated TESLA_REFRESH_TOKEN in {ENV_FILE}")
    print("Done.")


if __name__ == "__main__":
    main()
