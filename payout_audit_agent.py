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
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

API_BASE = "https://prod.api.cosmofeed.com/api/internal_dashboard"

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

def api_get(path, token, retries=3, timeout=30):
    """GET a dashboard API path (starting with /), return parsed JSON or None."""
    url = API_BASE + path
    headers = dict(HEADERS_BASE)
    headers["authorization"] = "Bearer " + token
    last_err = None
    for attempt in range(retries):
        try:
            req = urlreq.Request(url, headers=headers, method="GET")
            with urlreq.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (429, 502, 503, 504):
                time.sleep(3.0 * (attempt + 1))
                continue
            break
        except (URLError, TimeoutError, OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            last_err = str(e)
            time.sleep(1.5 * (attempt + 1))
    return {"__error__": last_err}


# ---------- Step 1: fetch all pending settlements ----------

def fetch_all_settlements(token, request_type="pending", verbose=True):
    rows = []
    # first page to learn total pages
    first = api_get(
        f"/IDgetSettlements?requestType={request_type}&page=1&sortField=&onlyFlagged=0"
        f"&AmountGreaterThan=0&AmountLessThan=0&filter=&paymentVerified=", token)
    data = (first or {}).get("data", {})
    total_pages = data.get("totalPages", 1)
    total = data.get("totalSettlements", 0)
    rows.extend(data.get("settelements") or data.get("settlements") or [])
    if verbose:
        print(f"[step1] total settlements={total} pages={total_pages}", flush=True)
    for page in range(2, total_pages + 1):
        d = api_get(
            f"/IDgetSettlements?requestType={request_type}&page={page}&sortField=&onlyFlagged=0"
            f"&AmountGreaterThan=0&AmountLessThan=0&filter=&paymentVerified=", token)
        pdata = (d or {}).get("data", {})
        rows.extend(pdata.get("settelements") or pdata.get("settlements") or [])
        if verbose and page % 10 == 0:
            print(f"[step1] fetched page {page}/{total_pages} ({len(rows)} rows)", flush=True)
        time.sleep(0.05)
    return rows


# ---------- Step 2: resolve creatorId + flags ----------

def resolve_settlement_details(settlement_id, token):
    d = api_get(f"/IDgetSettlementDetails?settlementId={settlement_id}", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown")}
    data = d.get("data", {})
    user = data.get("currentUserDetails", {}) or {}
    sett = data.get("currentSettlementDetails", {}) or {}
    return {
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
    d = api_get(f"/getCreatorKundli?type=userId&value={creator_id}"
                f"&requestedAction=groupedByBuyerId", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown"), "self": [], "buyers": 0}
    buyers = extract_kundli_payload(d, "groupedByBuyerId")
    self_txns = [b for b in buyers if isinstance(b, dict) and b.get("selfPayment") is True]
    return {"self": self_txns, "buyers": len(buyers)}


PRODUCT_CACHE = {}

def inspect_product_url(url, pid, raw_type="", title=""):
    """Fetch product page props and determine if content/delivery link is attached."""
    if not url:
        return {
            "productId": pid,
            "productType": raw_type or "unknown",
            "productUrl": url or "",
            "title": title or "",
            "isAttached": False,
            "status": "Flagged",
            "reason": "Payment page exists, but no product/content link is attached"
        }

    if url in PRODUCT_CACHE:
        return PRODUCT_CACHE[url]

    norm_type = "vp"
    if "/vig/" in url or raw_type == "integratedGroup":
        norm_type = "vig"
    elif "/course/" in url or raw_type == "course":
        norm_type = "course"
    elif "/ps/" in url or raw_type == "ps":
        norm_type = "ps"
    elif "/e/" in url or raw_type == "webinar":
        norm_type = "webinar"
    elif "/bookings/" in url or raw_type == "oneOnOne":
        norm_type = "oneOnOne"
    elif "/vp/" in url or raw_type == "page":
        norm_type = "vp"

    headers = {
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    is_attached = False

    try:
        req = urlreq.Request(url, headers=headers)
        with urlreq.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", "ignore")
            matches = re.findall(r'(\{"props":\{"pageProps":.*?\})\s*</script>', html, re.DOTALL)
            if not matches:
                matches = re.findall(r'(\{"props":\{"pageProps":.*)', html, re.DOTALL)
            if matches:
                parsed = json.loads(matches[0])
                page_props = parsed.get("props", {}).get("pageProps", {})
                data_obj = (page_props.get("prefetchedData") or
                            page_props.get("courseData", {}).get("collection") or
                            page_props.get("channelData") or
                            page_props.get("eventData") or
                            page_props)

                redir = data_obj.get("redirectionLink")
                resources = data_obj.get("resourcesDetails") or {}
                total_res_size = data_obj.get("totalResourcesSize") or 0
                prods_arr = data_obj.get("products") or []
                p0 = prods_arr[0] if prods_arr else {}
                modules = data_obj.get("modules") or data_obj.get("chapters") or []
                thank_you = data_obj.get("thankYouNote") or {}

                has_redir = False
                if isinstance(redir, dict):
                    if redir.get("isEnabled") is not False and redir.get("text"):
                        has_redir = True
                elif isinstance(redir, str) and redir.strip():
                    has_redir = True

                has_file = (resources.get("file", 0) > 0 and total_res_size > 0)
                has_video = (resources.get("video", 0) > 0)
                has_link = (resources.get("link", 0) > 0)
                has_prod_link = bool(p0.get("link") or p0.get("custom") or p0.get("courseIds"))
                has_modules = bool(len(modules) > 0)
                has_thankyou = bool(isinstance(thank_you, dict) and (thank_you.get("note") or thank_you.get("isEnabled")))

                if norm_type in ("vp", "ps"):
                    is_attached = has_file or has_video or has_link or has_redir or has_prod_link or has_modules or has_thankyou
                elif norm_type == "vig":
                    is_attached = has_redir or bool(data_obj.get("telegramLink"))
                elif norm_type == "course":
                    is_attached = has_modules or has_redir or has_prod_link
                elif norm_type in ("oneOnOne", "webinar"):
                    is_attached = True
    except Exception:
        is_attached = False

    res = {
        "productId": pid,
        "productType": norm_type,
        "productUrl": url,
        "title": title,
        "isAttached": is_attached,
        "status": "Valid" if is_attached else "Flagged",
        "reason": "Product Link Attached" if is_attached else "Payment page exists, but no product/content link is attached"
    }

    PRODUCT_CACHE[url] = res
    return res


def check_creator_product_links(creator_id, token):
    """Fetch creator's last hundred sold products and inspect each product URL for attached content."""
    res = check_creator_products(creator_id, token)
    if "__error__" in res:
        return {"__error__": res["__error__"], "allProducts": [], "noLinkProducts": []}

    prods = res.get("products", [])
    inspected = []
    no_link = []

    for p in prods:
        pid = p.get("_id") or p.get("productId") or ""
        purl = p.get("productLink") or ""
        ptype = p.get("productType") or ""
        title = p.get("productTtile") or p.get("productTitle") or ""

        info = inspect_product_url(purl, pid, ptype, title)
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
    d = api_get(f"/getCreatorKundli?type=userId&value={creator_id}"
                f"&requestedAction=lastHundredSoldProducts", token)
    if not d or "__error__" in d:
        return {"__error__": (d or {}).get("__error__", "unknown"), "products": []}
    prods = extract_kundli_payload(d, "lastHundredSoldProducts")
    return {"products": prods}


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
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--limit", type=int, default=0, help="limit creators (0=all)")
    ap.add_argument("--workers", type=int, default=6)
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
