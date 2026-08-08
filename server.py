#!/usr/bin/env python3
"""
Payout Check — local dashboard server (standard library only, no pip install).

Run:
    cd ~/Desktop/payout_check
    python3 server.py
Then open  http://localhost:8000  in your browser.

Serves:
  GET /                     -> the dashboard (index.html)
  GET /api/data             -> data.json (enriched payout list)
  GET /api/nolink?username= -> live-checks one creator's public page and
                               reports whether the page/link works.

To refresh the underlying data (re-run the self-transaction sweep):
    python3 build_data.py            # full
    python3 build_data.py --limit 100
"""
import os
import json
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))


def live_nolink_check(username):
    """Best-effort live check of a creator's public page.
    Returns dict: {reachable, status, noLink, reason}.
    Note: superprofile pages are bot-protected; a challenge => 'unverifiable'."""
    if not username:
        return {"reachable": False, "status": 0, "noLink": None, "reason": "no username"}
    url = f"https://superprofile.bio/{username}"
    headers = {"user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/150.0.0.0 Safari/537.36"),
               "accept": "text/html,application/xhtml+xml"}
    try:
        req = urlreq.Request(url, headers=headers)
        with urlreq.urlopen(req, timeout=15) as resp:
            final_url = resp.geturl().rstrip('/')
            body = resp.read(60000).decode("utf-8", "ignore").lower()
            status = resp.getcode()
            if final_url in ("https://superprofile.bio", "http://superprofile.bio") or username.lower() not in final_url.lower():
                return {"reachable": True, "status": status, "noLink": True,
                        "reason": "page redirected to root (user page not found)"}
    except HTTPError as e:
        if e.code == 404:
            return {"reachable": True, "status": 404, "noLink": True,
                    "reason": "page not found (404)"}
        if e.code == 429:
            return {"reachable": True, "status": 429, "noLink": None,
                    "reason": "bot-challenge / rate-limited (unverifiable from script)"}
        return {"reachable": True, "status": e.code, "noLink": None,
                "reason": f"HTTP {e.code}"}
    except (URLError, TimeoutError) as e:
        return {"reachable": False, "status": 0, "noLink": True,
                "reason": f"unreachable: {e}"}
    # loaded something — is it a real store or a challenge / empty?
    if "vercel security checkpoint" in body or "just a moment" in body:
        return {"reachable": True, "status": status, "noLink": None,
                "reason": "bot-challenge (open in a browser to verify)"}
    # crude: a working store page references products / buy / superprofile store markup
    markers = ["addtocart", "add to cart", "buy now", "/e/", "product", "checkout"]
    has_products = any(m in body for m in markers)
    if not has_products:
        return {"reachable": True, "status": status, "noLink": True,
                "reason": "page loads but no product/link markers found"}
    return {"reachable": True, "status": status, "noLink": False,
            "reason": "page has product links"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def _json(self, obj, code=200):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path == "/api/data":
            fp = os.path.join(HERE, "data.json")
            if not os.path.exists(fp):
                return self._json({"error": "data.json not found — run build_data.py"}, 404)
            with open(fp, encoding="utf-8") as f:
                return self._json(json.load(f))
        if parsed.path == "/api/nolink":
            q = parse_qs(parsed.query)
            username = (q.get("username") or [""])[0]
            return self._json(live_nolink_check(username))
        return super().do_GET()

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    os.chdir(HERE)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"\n  Payout Check dashboard running:  http://localhost:{PORT}\n")
        print("  Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")
