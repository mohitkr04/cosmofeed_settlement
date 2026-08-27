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
import datetime
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))


def live_nolink_check(username):
    """Live check of a creator's public page & product links.
    Uses official internal API if COSMOFEED_TOKEN is present to avoid bot challenges."""
    if not username:
        return {"reachable": False, "status": 0, "noLink": None, "reason": "no username"}

    token = os.environ.get("COSMOFEED_TOKEN")
    if token:
        try:
            import payout_audit_agent as agent
            res = agent.check_creator_product_links(username, token)
            if "__error__" not in res:
                has_nolink = res.get("hasNoLink", False)
                reason = "Page and product links verified via internal API" if not has_nolink else f"Payment page exists, but no product/content link attached ({res.get('noLinkCount', 1)} products)"
                return {"reachable": True, "status": 200, "noLink": has_nolink, "reason": reason}
        except Exception:
            pass

    url = f"https://superprofile.bio/{username}"
    headers = {"user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/150.0.0.0 Safari/537.36"),
               "accept": "text/html,application/xhtml+xml"}
    try:
        req = urlreq.Request(url, headers=headers)
        with urlreq.urlopen(req, timeout=15) as resp:
            body = resp.read(60000).decode("utf-8", "ignore").lower()
            status = resp.getcode()
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

    if "vercel security checkpoint" in body or "just a moment" in body:
        return {"reachable": True, "status": status, "noLink": None,
                "reason": "bot-challenge (open in a browser to verify)"}

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
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path == "/download-report" or parsed.path == "/reports/download":
            try:
                import generate_report
                generate_report.generate_reports()
            except Exception as e:
                pass
            fp = os.path.join(HERE, "reports", "payout_audit_report.html")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="Cosmofeed_Payout_Audit_Report_{today_str}.html"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                return self._json({"error": "payout_audit_report.html not found"}, 404)

        if parsed.path == "/api/download-pdf" or parsed.path == "/download-pdf":
            try:
                import generate_pdf
                pdf_path = os.path.join(HERE, "reports", "Cosmofeed_Payout_Audit_Report.pdf")
                generate_pdf.generate_pdf_report(output_pdf_path=pdf_path)
                if os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        content = f.read()
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'attachment; filename="Cosmofeed_Payout_Audit_Report_{today_str}.pdf"')
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                else:
                    return self._json({"error": "Failed to locate generated PDF"}, 404)
            except Exception as e:
                return self._json({"error": f"PDF generation error: {str(e)}"}, 500)

        if parsed.path == "/api/telegram-sebi/download-excel":
            fp = os.path.join(HERE, "reports", "telegram_sebi_10day_report.xlsx")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="Telegram_SEBI_10Day_Audit_Report.xlsx"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self._json({"error": "telegram_sebi_10day_report.xlsx not found"}, 404)

        if parsed.path == "/api/telegram-sebi/download-csv":
            fp = os.path.join(HERE, "reports", "telegram_sebi_10day_report.csv")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="Telegram_SEBI_10Day_Audit_Report.csv"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self._json({"error": "telegram_sebi_10day_report.csv not found"}, 404)

        if parsed.path == "/api/telegram-sebi/records":
            fp = os.path.join(HERE, "reports", "telegram_sebi_10day_records.json")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8") as f:
                    return self._json(json.load(f))
            return self._json({})

        if parsed.path == "/api/non-sebi/download-excel":
            fp = os.path.join(HERE, "data", "non_sebi_creators_cumulative.xlsx")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="Cosmofeed_Non_SEBI_Cumulative_Ledger_Until_05Sep.xlsx"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self._json({"error": "non_sebi_creators_cumulative.xlsx not found"}, 404)

        if parsed.path == "/api/non-sebi/download-csv":
            fp = os.path.join(HERE, "data", "non_sebi_creators_cumulative.csv")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="Cosmofeed_Non_SEBI_Cumulative_Ledger_Until_05Sep.csv"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self._json({"error": "non_sebi_creators_cumulative.csv not found"}, 404)

        if parsed.path == "/api/non-sebi/download-pdf":
            fp = os.path.join(HERE, "reports", "Manager_Submission_Non_SEBI_Report.pdf")
            if not os.path.exists(fp):
                try:
                    import non_sebi_manager
                    non_sebi_manager.generate_manager_pdf_report()
                except Exception:
                    pass
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", 'attachment; filename="Cosmofeed_Manager_Submission_Non_SEBI_Report_05Sep.pdf"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self._json({"error": "Manager_Submission_Non_SEBI_Report.pdf not found"}, 404)

        if parsed.path == "/api/non-sebi/manager-report":
            fp = os.path.join(HERE, "reports", "Manager_Submission_Non_SEBI_Report.html")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self._json({"error": "Manager_Submission_Non_SEBI_Report.html not found"}, 404)

        if parsed.path == "/api/non-sebi/ledger":
            fp = os.path.join(HERE, "data", "non_sebi_creators_ledger.json")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8") as f:
                    return self._json(json.load(f))
            return self._json({"creators": {}})

        if parsed.path == "/api/data":
            fp = os.path.join(HERE, "reports", "data.json")
            if not os.path.exists(fp):
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

    # Automatically open http://localhost:8000 in browser
    import threading
    import time
    import webbrowser

    def open_browser():
        time.sleep(0.8)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"\n  Cosmofeed Payout Audit Dashboard running at: http://localhost:{PORT}\n")
        print("  Automatically opening dashboard in your web browser...\n")
        print("  Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")
