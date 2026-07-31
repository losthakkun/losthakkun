#!/usr/bin/env python3
"""One-time helper: obtain a Google Calendar refresh token for CI.

Run locally, never in CI. Prints the refresh token to stdout and nothing else,
so it can be piped straight into `gh secret set` without the value ever landing
in shell history.

Prerequisites — in the Google Cloud project for your Workspace:
  1. Enable the Google Calendar API.
  2. OAuth consent screen: User type = Internal. Internal apps do not expire
     refresh tokens; an app left in "Testing" invalidates them after 7 days.
  3. Credentials: create an OAuth client, type "Desktop app".

Usage:
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python authorize_calendar.py
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python authorize_calendar.py \
    | gh secret set GOOGLE_REFRESH_TOKEN --repo <owner>/<repo>
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{PORT}/"


class CodeHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self) -> None:  # noqa: N802  (http.server naming)
        query = urllib.parse.urlparse(self.path).query
        CodeHandler.code = urllib.parse.parse_qs(query).get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "Authorized. Close this tab and return to the terminal.".encode()
            if CodeHandler.code
            else "No authorization code received.".encode()
        )

    def log_message(self, *_args) -> None:
        """Silence request logging so stdout stays clean for the token."""


def main() -> int:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET", file=sys.stderr)
        return 1

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # force a refresh token even on re-authorization
        }
    )
    url = f"{AUTH_ENDPOINT}?{params}"

    print(f"Open this URL if a browser does not appear:\n{url}\n", file=sys.stderr)
    webbrowser.open(url)

    with http.server.HTTPServer(("127.0.0.1", PORT), CodeHandler) as server:
        server.handle_request()

    if not CodeHandler.code:
        print("authorization failed: no code received", file=sys.stderr)
        return 1

    payload = urllib.parse.urlencode(
        {
            "code": CodeHandler.code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_ENDPOINT, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        tokens = json.load(response)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print(f"no refresh token in response: {sorted(tokens)}", file=sys.stderr)
        return 1

    print(refresh_token)  # stdout carries only the token, ready to pipe
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
