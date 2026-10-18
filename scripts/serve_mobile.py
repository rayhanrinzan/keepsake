#!/usr/bin/env python3
"""Serve the mobile app's web build and the Keepsake API from one port, for opening on a phone.

    cd mobile && EXPO_PUBLIC_API_URL=same-origin npx expo export --platform web --output-dir ../backend/data/mobile-web
    .venv/bin/python scripts/serve_mobile.py backend/data/mobile-web          # prints the link
    cloudflared tunnel --url http://127.0.0.1:8099                           # HTTPS, for the phone's mic

The app and /api/* share one origin, so no CORS. Because a tunnel makes this reachable from the
internet, every request needs a key: open the printed link (…/?k=KEY) once and a cookie carries it
from then on. Without the key it answers 403. The backend itself stays on 127.0.0.1.
"""
from __future__ import annotations

import argparse
import http.server
import secrets
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BACKEND = "http://127.0.0.1:8000"
HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "server", "date"}


def make_handler(root: Path, key: str):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        _set_cookie = False

        def log_message(self, fmt, *args):  # path only: the query carries the key
            print(f"{self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}"
                  f" cookie={'yes' if self._authorized() else 'no'}"
                  + (f" ua={self.headers.get('User-Agent', '')[:90]}" if not self.path.startswith(("/api/", "/_expo/", "/assets/")) else ""),
                  flush=True)

        def end_headers(self):
            if self._set_cookie:
                self.send_header("Set-Cookie", f"ks={key}; Path=/; Max-Age=86400; SameSite=Lax; Secure")
            super().end_headers()

        def _authorized(self) -> bool:
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            return "ks" in jar and secrets.compare_digest(jar["ks"].value, key)

        def _gate(self) -> bool:
            """True if the request may go on: the key in the link (?k=KEY), which also sets a cookie so
            the app's own requests carry it, or that cookie."""
            url = urlsplit(self.path)
            given = parse_qs(url.query).get("k", [""])[0]
            if given and secrets.compare_digest(given, key):
                self._set_cookie = True
                self.path = url.path or "/"
                return True
            if self._authorized():
                return True
            body = b"Keepsake: open the link with the key."
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False

        def _proxy(self):
            n = int(self.headers.get("Content-Length") or 0)
            headers = {k: v for k, v in self.headers.items() if k.lower() in ("content-type", "accept", "x-keepsake-local")}
            req = urllib.request.Request(BACKEND + self.path, data=self.rfile.read(n) if n else None,
                                         method=self.command, headers=headers)
            try:
                r = urllib.request.urlopen(req, timeout=60)
            except urllib.error.HTTPError as e:
                r = e
            except Exception as e:  # backend down
                return self.send_error(502, f"Keepsake backend unreachable: {e}")
            body = r.read()
            self.send_response(r.status if hasattr(r, "status") else r.code)
            for k, v in r.headers.items():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self):
            if not self._gate():
                return
            if self.path.startswith("/api/"):
                return self._proxy()
            if self.command != "GET":
                return self.send_error(405)
            path = urlsplit(self.path).path
            if path != "/" and not (root / path.lstrip("/")).is_file():
                self.path = "/index.html"  # app routes like /item/keys
            return super().do_GET()

        do_GET = do_POST = do_PUT = do_DELETE = _route

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="the mobile web build (expo export output)")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--key", default=None, help="access key (random if not given)")
    a = ap.parse_args()
    key = a.key or secrets.token_urlsafe(9)
    print(f"Keepsake mobile: http://127.0.0.1:{a.port}/?k={key}", flush=True)
    print(f"Through a tunnel: https://<tunnel host>/?k={key}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.root.resolve(), key)).serve_forever()


if __name__ == "__main__":
    main()
