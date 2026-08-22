#!/usr/bin/env python3
"""
Cosmofeed Daily Payout Audit Agent
===================================
Step-by-step agent that audits pending settlements (payouts) and flags risky creators.

Pipeline (per creator):
  1. Fetch all pending settlements   -> IDgetSettlements   (paged)
  2. Resolve real creatorId + flags  -> IDgetSettlementDetails?settlementId={_id}
  3. Check last-100 buyers            -> getCreatorKundli?type=userId&value={creatorId}
     -> any buyer with selfPayment==true  => SELF-TRANSACTION
  4. Collect flagLevel                -> flagged creator/product

Outputs a JSON + human-readable report to the output dir.

NOTE on content categories:
  - "self transaction" : detected via selfPayment flag in buyer list (reliable).
  - "flagged product/creator" : detected via flagLevel field from settlement details.
  - "copyright" / "adult content" : the admin "Review Products" endpoint is required
    for these and was not captured yet. Placeholder hooks are left in check_content_flags().
"""

import json
import os
import sys
import time
import socket
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

socket.setdefaulttimeout(8.0)

import datetime
try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

API_BASE = "https://prod.api.cosmofeed.com/api/internal_dashboard"
HERE = os.path.dirname(os.path.abspath(__file__))


def get_business_dates(timezone_str="Asia/Kolkata", now_dt=None):
    """
    Dynamically calculate today's date and yesterday's date in IST business timezone.
    Returns dict:
      - today_date: 'YYYY-MM-DD'
      - yesterday_date: 'YYYY-MM-DD'
      - today_formatted: 'DD-MM-YYYY'
      - yesterday_formatted: 'DD-MM-YYYY'
    """
    try:
        tz = zoneinfo.ZoneInfo(timezone_str)
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

    if now_dt is None:
        now_dt = datetime.datetime.now(tz)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=tz)

    yesterday_dt = now_dt - datetime.timedelta(days=1)

    return {
        "today_date": now_dt.strftime("%Y-%m-%d"),
        "yesterday_date": yesterday_dt.strftime("%Y-%m-%d"),
        "today_formatted": now_dt.strftime("%d-%m-%Y"),
        "yesterday_formatted": yesterday_dt.strftime("%d-%m-%Y"),
        "now_dt": now_dt,
        "yesterday_dt": yesterday_dt,
    }

def _load_env():
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v

_load_env()

# Bearer token is read from the COSMOFEED_TOKEN env var (or passed via --token).
# Never hardcode credentials here.
DEFAULT_TOKEN = os.environ.get("COSMOFEED_TOKEN", "")

HEADERS_BASE = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://admin.cosmofeed.com",
    "referer": "https://admin.cosmofeed.com/",
    "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"),
}


import http.client
import threading

class RatePacer:
    """Thread-safe rate pacer to cap request rate and eliminate HTTP 429 stalls."""
    def __init__(self, max_per_second=30):
        self.interval = 1.0 / max_per_second
        self.lock = threading.Lock()
        self.last_time = 0.0

    def wait(self):
        to_sleep = 0.0
        with self.lock:
            now = time.time()
            if self.last_time < now:
                self.last_time = now
            scheduled = self.last_time + self.interval
            to_sleep = scheduled - now
            if to_sleep > 1.0:
                scheduled = now + self.interval
                to_sleep = self.interval
            self.last_time = scheduled
        if to_sleep > 0:
            time.sleep(to_sleep)

RATE_PACER = RatePacer(max_per_second=2)


def api_get(path, token, retries=3, timeout=6):
    """GET a dashboard API path (starting with /), return parsed JSON or None."""
    url = API_BASE + path
    headers = dict(HEADERS_BASE)
    tok_str = str(token or DEFAULT_TOKEN or "").strip()
    headers["authorization"] = "Bearer " + tok_str
    last_err = None
    for attempt in range(retries):
        RATE_PACER.wait()
        try:
            req = urlreq.Request(url, headers=headers, method="GET")
            with urlreq.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code == 429:
                time.sleep(10.0 * (attempt + 1))
                continue
            return {"__error__": last_err}
        except Exception as e:
            last_err = str(e)
            time.sleep(1.0)
    return {"__error__": last_err or "failed"}


def api_get_product_details(product_id, token, product_type="page"):
    """Query production IDviewProductDetails endpoint for a given product ID and type."""
    if not product_id:
        return {"__error__": "missing product_id"}
    path = f"/IDviewProductDetails?id={product_id}&productType={product_type}"
    return api_get(path, token, retries=3, timeout=15)


# ---------- Step 1: fetch all pending settlements ----------

def fetch_all_settlements(token, request_type="pending", verbose=True):
    first = None
    time.sleep(15.0)  # Ensure rate limit window is completely reset
    for attempt in range(5):
        first = api_get(
            f"/IDgetSettlements?requestType={request_type}&page=1&sortField=&onlyFlagged=0"
            f"&AmountGreaterThan=0&AmountLessThan=0&filter=&paymentVerified=", token, retries=3)
        if first and "__error__" not in first:
            break
        if verbose:
            err_msg = (first or {}).get("__error__", "no response")
            print(f"[step1] page 1 attempt {attempt+1}/5 retry due to {err_msg}...", flush=True)
        time.sleep(15.0 * (attempt + 1))

    if not first or "__error__" in first:
        err = (first or {}).get("__error__", "API call failed")
        raise RuntimeError(f"Failed to fetch settlements from API: {err}")

    data = first.get("data", {})
    total_pages = data.get("totalPages", 1)
    total = data.get("totalSettlements", 0)
    page1_rows = data.get("settelements") or data.get("settlements") or []
    if verbose:
        print(f"[step1] total settlements={total} pages={total_pages}", flush=True)

    if total_pages <= 1:
        return page1_rows

    pages_dict = {1: page1_rows}

    def fetch_page(p):
        time.sleep(0.3)
        d = api_get(
            f"/IDgetSettlements?requestType={request_type}&page={p}&sortField=&onlyFlagged=0"
            f"&AmountGreaterThan=0&AmountLessThan=0&filter=&paymentVerified=", token, retries=5)
        pdata = (d or {}).get("data", {})
        return p, pdata.get("settelements") or pdata.get("settlements") or []

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(fetch_page, p) for p in range(2, total_pages + 1)]
        for fut in as_completed(futs):
            p, r = fut.result()
            pages_dict[p] = r

    rows = []
    for p in range(1, total_pages + 1):
        rows.extend(pages_dict.get(p, []))
    if verbose:
        print(f"[step1] completed fetching {len(rows)} settlements across {total_pages} pages", flush=True)
    return rows


# ---------- Step 2: resolve creatorId + flags ----------

DETAILS_CACHE = {}
SELF_TXN_CACHE = {}
PROD_LIST_CACHE = {}


def resolve_settlement_details(settlement_id, token):
    if settlement_id in DETAILS_CACHE:
        return DETAILS_CACHE[settlement_id]
    d = api_get(f"/IDgetSettlementDetails?settlementId={settlement_id}", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown")}
    data = d.get("data", {})
    user = data.get("currentUserDetails", {}) or {}
    sett = data.get("currentSettlementDetails", {}) or {}
    res = {
        "creatorId": user.get("creatorId"),
        "username": user.get("username"),
        "email": user.get("Email") or user.get("email"),
        "phone": user.get("PhoneNumber") or user.get("phone") or user.get("phoneNumber"),
        "flagLevel": user.get("flagLevel"),
        "categoryOfBusiness": user.get("categoryOfBusiness"),
        "subCategoryOfBusiness": user.get("subCategoryOfBusiness"),
        "totalMemoAmount": sett.get("totalMemoAmount"),
        "currentStatus": sett.get("currentStatus"),
    }
    DETAILS_CACHE[settlement_id] = res
    return res


def extract_kundli_payload(d, key):
    if not isinstance(d, dict):
        return []
    data_val = d.get("data")
    if isinstance(data_val, list):
        return data_val
    if isinstance(data_val, dict):
        inner_val = data_val.get("data")
        if isinstance(inner_val, list):
            return inner_val
        if isinstance(inner_val, dict):
            res = inner_val.get(key)
            if isinstance(res, list):
                return res
        res = data_val.get(key)
        if isinstance(res, list):
            return res
    return []


# ---------- Step 3: self-transaction check via buyer list ----------

def check_self_transactions(creator_id, token):
    if creator_id in SELF_TXN_CACHE:
        return SELF_TXN_CACHE[creator_id]
    d = api_get(f"/getCreatorKundli?type=userId&value={creator_id}"
                f"&requestedAction=groupedByBuyerId", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown"), "self": [], "buyers": 0}
    buyers = extract_kundli_payload(d, "groupedByBuyerId")
    self_txns = [b for b in buyers if isinstance(b, dict) and b.get("selfPayment") is True]
    res = {"self": self_txns, "buyers": len(buyers)}
    SELF_TXN_CACHE[creator_id] = res
    return res


PRODUCT_CACHE = {}

def inspect_product_url(url, pid, raw_type="", title="", token=None):
    """
    Inspect product link using official Cosmofeed internal API (product_validator)
    when token is available, or fallback gracefully.
    Eliminates unauthenticated scraping of superprofile.bio to prevent bot-challenges/IP blocks.
    """
    tok = token or DEFAULT_TOKEN
    cache_key = f"{pid}:{url}:{raw_type}"
    if cache_key in PRODUCT_CACHE:
        return PRODUCT_CACHE[cache_key]
    if url and url in PRODUCT_CACHE:
        return PRODUCT_CACHE[url]

    # Fast path for Telegram / integratedGroup products (0 API calls needed)
    if raw_type == "integratedGroup" or "/vig/" in str(url):
        res = {
            "productId": pid,
            "productType": "vig",
            "productUrl": url or (f"https://superprofile.bio/vig/{pid}" if pid else ""),
            "title": title or "",
            "isAttached": True,
            "status": "Valid",
            "reason": "Excluded from missing-link validation (vig/Telegram product)"
        }
        PRODUCT_CACHE[cache_key] = res
        if url:
            PRODUCT_CACHE[url] = res
        return res

    import product_validator

    if tok and pid:
        val_res = product_validator.validate_product_link(
            product_id=pid,
            product_url=url,
            product_type=raw_type,
            token=tok
        )
        is_attached = val_res.get("isAttached")
        is_ok = (is_attached is True) or (val_res.get("validationStatus") == "TELEGRAM_VIG_EXCLUDED")
        res = {
            "productId": val_res.get("productId") or pid,
            "productType": val_res.get("productType") or raw_type or "page",
            "productUrl": val_res.get("productUrl") or url,
            "title": title or "",
            "isAttached": is_ok,
            "status": "Valid" if is_ok else "Flagged",
            "reason": val_res.get("reason") or ("Product Link Attached" if is_ok else "Payment page exists, but no product/content link is attached")
        }
        PRODUCT_CACHE[cache_key] = res
        if url:
            PRODUCT_CACHE[url] = res
        return res

    # Fallback when no token or missing PID
    norm_type = "vig" if ("/vig/" in str(url) or raw_type == "integratedGroup") else ("course" if "/course/" in str(url) or raw_type == "course" else "vp")
    is_attached = True if norm_type == "vig" else False
    res = {
        "productId": pid,
        "productType": norm_type,
        "productUrl": url or "",
        "title": title or "",
        "isAttached": is_attached,
        "status": "Valid" if is_attached else "Flagged",
        "reason": "Telegram vig product (excluded)" if norm_type == "vig" else "Payment page exists, but no product/content link is attached"
    }
    PRODUCT_CACHE[cache_key] = res
    return res


def check_creator_product_links(creator_id, token, max_products=5, fast=True):
    """Fetch creator's sold products and inspect top products using official internal API."""
    res = check_creator_products(creator_id, token)
    if "__error__" in res:
        return {"__error__": res["__error__"], "allProducts": [], "noLinkProducts": []}

    prods = res.get("products", [])
    if max_products and len(prods) > max_products:
        prods = prods[:max_products]
    inspected = []
    no_link = []

    for p in prods:
        pid = p.get("_id") or p.get("productId") or ""
        purl = p.get("productLink") or p.get("url") or ""
        ptype = p.get("productType") or ""
        title = p.get("productTtile") or p.get("productTitle") or p.get("title") or ""

        if fast:
            norm_type = "vig" if ("/vig/" in str(purl) or ptype == "integratedGroup") else ("course" if "/course/" in str(purl) or ptype == "course" else "vp")
            is_attached = True if (norm_type == "vig" or purl) else False
            info = {
                "productId": pid,
                "productType": norm_type,
                "productUrl": purl,
                "title": title,
                "isAttached": is_attached,
                "status": "Valid" if is_attached else "Flagged",
                "reason": "Telegram vig product (excluded)" if norm_type == "vig" else ("Valid product link" if is_attached else "Payment page exists, but no product/content link is attached")
            }
        else:
            info = inspect_product_url(purl, pid, ptype, title, token=token)

        inspected.append(info)
        if not info["isAttached"]:
            no_link.append(info)

    return {
        "allProducts": inspected,
        "noLinkProducts": no_link,
        "noLinkCount": len(no_link),
        "hasNoLink": len(no_link) > 0
    }


def check_creator_products(creator_id, token):
    """Fetch creator's last hundred sold products via getCreatorKundli."""
    if creator_id in PROD_LIST_CACHE:
        return PROD_LIST_CACHE[creator_id]
    d = api_get(f"/getCreatorKundli?type=userId&value={creator_id}"
                f"&requestedAction=lastHundredSoldProducts", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown"), "products": []}
    prods = extract_kundli_payload(d, "lastHundredSoldProducts")
    res = {"products": prods}
    PROD_LIST_CACHE[creator_id] = res
    return res


def check_previous_payouts(creator_id, token):
    """Fetch creator's previous payout details via getCreatorKundli."""
    d = api_get(f"/getCreatorKundli?type=userId&value={creator_id}"
                f"&requestedAction=previousPayoutDetails", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown"), "payouts": []}
    payouts = extract_kundli_payload(d, "previousPayoutDetails")
    return {"payouts": payouts}



# ---------- Step 4: content flags (flagLevel + product inspection) ----------

def check_content_flags(details, products=None):
    flags = []
    fl = (details.get("flagLevel") or "").strip()
    if fl and fl not in ("---", "", "None", "null"):
        flags.append(f"flagLevel={fl}")
    return flags


# ---------- Orchestration ----------

def audit_one(row, token):
    sid = row.get("_id")
    detail = resolve_settlement_details(sid, token)
    if "__error__" in detail:
        return {"settlementId": sid, "username": row.get("username"),
                "error": "details:" + detail["__error__"]}
    creator_id = detail.get("creatorId")
    result = {
        "settlementId": sid,
        "creatorId": creator_id,
        "username": detail.get("username") or row.get("username"),
        "email": detail.get("email") or row.get("Email"),
        "phone": detail.get("phone") or row.get("PhoneNumber"),
        "payoutAmount": row.get("payoutAmount"),
        "totalMemoAmount": detail.get("totalMemoAmount"),
        "category": detail.get("categoryOfBusiness"),
        "contentFlags": check_content_flags(detail),
        "selfTransactions": [],
        "buyersChecked": 0,
    }
    if creator_id:
        st = check_self_transactions(creator_id, token)
        if "__error__" not in st:
            result["buyersChecked"] = st["buyers"]
            for b in st["self"]:
                result["selfTransactions"].append({
                    "amountPaid": b.get("amountPaid"),
                    "buyerEmail": b.get("buyerEmail"),
                    "buyerPhone": b.get("buyerPhoneNumber"),
                    "IP": b.get("IP"),
                    "date": b.get("createdAt"),
                    "productId": b.get("purchasedProductId"),
                })
        else:
            result["error"] = "kundli:" + st["__error__"]
    else:
        result["error"] = "no_creator_id"
    return result


def to_float(v):
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("COSMOFEED_TOKEN", DEFAULT_TOKEN))
    reports_dir = os.path.join(HERE, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    ap.add_argument("--out", default=reports_dir)
    ap.add_argument("--limit", type=int, default=0, help="limit creators (0=all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--date", default="", help="report date label (YYYY-MM-DD)")
    args = ap.parse_args()

    token = args.token
    date_label = args.date or "run"

    print("=== Cosmofeed Payout Audit Agent ===", flush=True)
    settlements = fetch_all_settlements(token)
    if args.limit:
        settlements = settlements[:args.limit]
    print(f"[step2-3] auditing {len(settlements)} creators with {args.workers} workers...", flush=True)

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(audit_one, r, token): r for r in settlements}
        for fut in as_completed(futs):
            results.append(fut.result())
            done += 1
            if done % 50 == 0:
                print(f"  audited {done}/{len(settlements)}", flush=True)

    # Aggregate findings
    self_txn = [r for r in results if r.get("selfTransactions")]
    flagged = [r for r in results if r.get("contentFlags")]
    errors = [r for r in results if r.get("error")]

    report = {
        "date": date_label,
        "totalAudited": len(results),
        "selfTransactionCount": len(self_txn),
        "flaggedCount": len(flagged),
        "errorCount": len(errors),
        "selfTransactions": sorted(self_txn, key=lambda r: -to_float(r.get("payoutAmount"))),
        "flagged": sorted(flagged, key=lambda r: -to_float(r.get("payoutAmount"))),
        "errors": errors[:50],
    }

    out_json = os.path.join(args.out, f"audit_{date_label}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"report": report, "allResults": results}, f, indent=2)

    # Human-readable summary
    lines = []
    lines.append(f"# Payout Audit Report — {date_label}")
    lines.append(f"Audited: {len(results)} pending settlements")
    lines.append(f"Self-transactions found: {len(self_txn)}")
    lines.append(f"Flagged (flagLevel): {len(flagged)}")
    lines.append(f"Errors: {len(errors)}")
    lines.append("")
    if self_txn:
        lines.append("## SELF-TRANSACTIONS (creator bought own product)")
        for r in report["selfTransactions"]:
            lines.append(f"- {r['username']} ({r['email']}) | payout ₹{r['payoutAmount']} "
                         f"| creatorId={r['creatorId']} | {len(r['selfTransactions'])} self-txn(s)")
            for s in r["selfTransactions"]:
                lines.append(f"    ↳ ₹{s['amountPaid']} by {s['buyerEmail']} "
                             f"(IP {s['IP']}) on {s['date']}")
    else:
        lines.append("## SELF-TRANSACTIONS: none found")
    lines.append("")
    if flagged:
        lines.append("## FLAGGED CREATORS")
        for r in report["flagged"]:
            lines.append(f"- {r['username']} ({r['email']}) | payout ₹{r['payoutAmount']} "
                         f"| {', '.join(r['contentFlags'])}")
    else:
        lines.append("## FLAGGED CREATORS: none found")

    out_md = os.path.join(args.out, f"audit_{date_label}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n".join(lines[:8]), flush=True)
    print(f"\n[done] JSON: {out_json}\n[done] Report: {out_md}", flush=True)


if __name__ == "__main__":
    main()
