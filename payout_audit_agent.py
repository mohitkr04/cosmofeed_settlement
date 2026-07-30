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
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = str(e)
            time.sleep(1.0 * (attempt + 1))
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
    rows.extend(data.get("settelements", []))
    if verbose:
        print(f"[step1] total settlements={total} pages={total_pages}", flush=True)
    for page in range(2, total_pages + 1):
        d = api_get(
            f"/IDgetSettlements?requestType={request_type}&page={page}&sortField=&onlyFlagged=0"
            f"&AmountGreaterThan=0&AmountLessThan=0&filter=&paymentVerified=", token)
        pdata = (d or {}).get("data", {})
        rows.extend(pdata.get("settelements", []))
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
        "email": user.get("Email"),
        "phone": user.get("PhoneNumber"),
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


def main():
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

def to_float(v):
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


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
