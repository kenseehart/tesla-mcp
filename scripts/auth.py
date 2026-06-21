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
        # Non-blocking; avoid UNC cwd hanging cmd.exe from WSL project dirs.
        cmd_line = f'start "" "{url}"'
        for attempt in (
            lambda: subprocess.Popen(
                ["/mnt/c/Windows/System32/cmd.exe", "/c", cmd_line],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd="/mnt/c/Windows",
            ),
            lambda: subprocess.Popen(["wslview", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
            lambda: subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        ):
            try:
                attempt()
                return
            except OSError:
                continue
        print("Could not open browser automatically — copy the URL above into Chrome/Edge.")
    else:
        webbrowser.open(url)


def use_manual_callback() -> bool:
    """WSL opens Windows browser; localhost callback lands on Windows, not WSL."""
    parsed = urllib.parse.urlparse(TESLA_REDIRECT_URI)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        return True
    return is_wsl()


def prompt_for_code() -> str:
    print(f"\nAfter Tesla login, the browser redirects to {TESLA_REDIRECT_URI}?code=...")
    print("The page may fail to load — that's expected on WSL.")
    print("Copy the full redirect URL from the address bar, or just the code= value.")
    print("Do NOT paste the auth.tesla.com authorize URL.\n")
    while True:
        raw = input("Paste redirect URL or authorization code: ").strip()
        if not raw:
            continue
        if raw.startswith("https://auth.tesla.com/"):
            print("That's the login URL, not the callback. Complete login first, then paste the localhost URL.\n")
            continue
        if "redirect_uri=" in raw and "code=" not in raw:
            print("That looks like part of the authorize URL. After login, paste the localhost callback URL.\n")
            continue
        if "code=" in raw:
            parsed = urllib.parse.urlparse(raw if "://" in raw else f"http://x?{raw.lstrip('?')}")
            qs = urllib.parse.parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            if code:
                return code
            print("Found code= but could not parse it — try the full callback URL.\n")
            continue
        if len(raw) < 20:
            print("That code looks too short — paste the full callback URL from the address bar.\n")
            continue
        return raw


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

    if len(sys.argv) > 1 and sys.argv[1] in ("--code", "-c") and len(sys.argv) > 2:
        code = sys.argv[2].strip()
        tokens = exchange_code(code)
        save_tokens(tokens)
        print(f"Saved tokens to {TOKEN_FILE}")
        if ENV_FILE.exists():
            print(f"Updated TESLA_REFRESH_TOKEN in {ENV_FILE}")
        print("Done.")
        return

    url = build_auth_url()
    print("Tesla Fleet OAuth setup")
    print(f"Redirect URI: {TESLA_REDIRECT_URI}")
    manual = use_manual_callback()
    if manual:
        if TESLA_REDIRECT_URI.startswith("https://"):
            print("Open the URL below in your browser. After login, copy the code from the callback page.\n")
        elif is_wsl():
            print("WSL detected — use Windows browser; paste the redirect URL/code back here.\n")
    print(f"{url}\n")

    if manual:
        if not TESLA_REDIRECT_URI.startswith("https://"):
            print("Open the URL above in Chrome/Edge on Windows.\n")
        code = prompt_for_code()
    else:
        open_browser(url)
        code = wait_for_callback()

    tokens = exchange_code(code)
    save_tokens(tokens)
    print(f"Saved tokens to {TOKEN_FILE}")
    if ENV_FILE.exists():
        print(f"Updated TESLA_REFRESH_TOKEN in {ENV_FILE}")
    print("Done.")


if __name__ == "__main__":
    main()
