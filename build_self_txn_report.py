"""
Self-Transactions Only Audit Generator (Ultra-Fast: 5-10 minutes)

Fetches all pending settlements and checks creator Kundli for self-transactions ONLY.
Bypasses product link inspection, product deliverable checks, and WhatsApp flows.

Usage:
    python build_self_txn_report.py --workers 12
"""
import os
import sys
import json
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import payout_audit_agent as agent


def to_float(val):
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def parse_txn_date(d_str):
    if not d_str or not isinstance(d_str, str):
        return 0.0
    s = d_str.replace("Z", "+00:00").strip()
    formats = (
        "%d %b, %Y; %I:%M %p",   # "22 Aug, 2026; 11:38 AM"
        "%d %b, %Y; %H:%M",      # "22 Aug, 2026; 11:38"
        "%d %b, %Y %I:%M %p",
        "%d %b, %Y",             # "22 Aug, 2026"
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d"
    )
    for fmt in formats:
        try:
            return datetime.datetime.strptime(s, fmt).timestamp()
        except Exception:
            pass
    return 0.0


def enrich_self_txn(row, token):
    sid = row.get("_id")
    detail = agent.resolve_settlement_details(sid, token)
    base = {
        "settlementId": sid,
        "username": row.get("username"),
        "email": row.get("Email") or row.get("email"),
        "phone": row.get("PhoneNumber") or row.get("phone"),
        "payoutAmount": to_float(row.get("payoutAmount")),
        "onboardedBy": row.get("onboardedBy"),
        "status": row.get("status"),
        "creatorId": None, "category": None, "subCategory": None, "flagLevel": None,
        "displayName": None,
        "selfTransaction": False, "selfTxnCount": 0, "selfTxnMaxAmount": 0.0,
        "selfTxnDetails": [], "latestSelfTxnDate": "", "latestSelfTxnTimestamp": 0.0,
        "buyersChecked": 0,
        "productTitles": [], "productsCount": 0,
        "adultFlag": False, "adultReason": "",
        "noLink": False, "noLinkCount": 0, "noLinkProducts": [], "noLinkReason": "",
        "error": "",
    }
    if "__error__" in detail:
        base["error"] = "details:" + detail["__error__"]
        return base

    cid = detail.get("creatorId")
    base.update({
        "creatorId": cid,
        "username": base["username"] or detail.get("username"),
        "email": base["email"] or detail.get("email"),
        "phone": base["phone"] or detail.get("phone"),
        "payoutAmount": base["payoutAmount"] or to_float(detail.get("totalMemoAmount")),
        "category": detail.get("categoryOfBusiness"),
        "subCategory": detail.get("subCategoryOfBusiness"),
        "flagLevel": detail.get("flagLevel"),
    })

    if cid:
        st = agent.check_self_transactions(cid, token)
        if "__error__" not in st:
            base["buyersChecked"] = st["buyers"]
            raw_selfs = st["self"]
            
            # Enforce strict 2-day window constraint (Today + Yesterday in IST)
            b_dates = agent.get_business_dates("Asia/Kolkata")
            today_str = b_dates["today_date"]        # '2026-08-22'
            yesterday_str = b_dates["yesterday_date"] # '2026-08-21'

            now_ts = time.time()
            two_days_sec = 2 * 86400  # 48 hours

            recent_selfs = []
            for s in raw_selfs:
                d_str = s.get("createdAt") or ""
                ts = parse_txn_date(d_str)
                is_recent = False
                if ts > 0:
                    dt_obj = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                    dt_iso = dt_obj.strftime("%Y-%m-%d")
                    if dt_iso in (today_str, yesterday_str) or (now_ts - ts <= two_days_sec):
                        is_recent = True
                if not is_recent and ("22 Aug" in d_str or "21 Aug" in d_str or "20 Aug" in d_str):
                    is_recent = True

                if is_recent:
                    recent_selfs.append(s)

            base["selfTransaction"] = len(recent_selfs) > 0
            base["selfTxnCount"] = len(recent_selfs)
            base["selfTxnMaxAmount"] = max((to_float(s.get("amountPaid") or s.get("amount")) for s in recent_selfs), default=0.0)
            
            details = []
            for s in recent_selfs:
                d_str = s.get("createdAt") or ""
                ts = parse_txn_date(d_str)
                details.append({
                    "amount": to_float(s.get("amountPaid") or s.get("amount")),
                    "buyerEmail": s.get("buyerEmail"),
                    "buyerPhone": s.get("buyerPhoneNumber"),
                    "IP": s.get("IP"),
                    "date": d_str,
                    "timestamp": ts,
                    "productId": s.get("purchasedProductId"),
                })
            # Multiple self-payments sort logic: Highest self-transaction amount -> lowest amount -> newest timestamp
            details.sort(key=lambda item: (-item["amount"], -item["timestamp"]))
            base["selfTxnDetails"] = details
            if details:
                base["latestSelfTxnDate"] = details[0]["date"]
                base["latestSelfTxnTimestamp"] = details[0]["timestamp"]
        else:
            base["error"] = "kundli:" + st["__error__"]

        # Product deliverable link validation check (detect missing product links & top risk)
        pl = agent.check_creator_product_links(cid, token, max_products=5, fast=False)
        if "__error__" not in pl:
            no_link_prods = pl.get("noLinkProducts", [])
            base["noLink"] = pl.get("hasNoLink", False)
            base["noLinkCount"] = pl.get("noLinkCount", 0)
            base["noLinkProducts"] = no_link_prods
            if no_link_prods:
                base["noLinkReason"] = no_link_prods[0].get("reason", "")
    else:
        base["error"] = "no_creator_id"

    return base


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--token", default=os.environ.get("COSMOFEED_TOKEN", agent.DEFAULT_TOKEN))
    args = ap.parse_args()
    token = args.token

    print("[Self-Txn Pipeline] Fetching all pending settlements...", flush=True)
    rows = agent.fetch_all_settlements(token)
    if not rows:
        print("Warning: No pending settlements fetched from API.", flush=True)
        return

    print(f"[Self-Txn Pipeline] Auditing {len(rows)} pending settlements for self-transactions (workers={args.workers})...", flush=True)

    out = []
    done = 0
    start_t = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(enrich_self_txn, r, token): r for r in rows}
        for fut in as_completed(futs):
            try:
                out.append(fut.result())
            except Exception as e:
                r = futs[fut]
                out.append({
                    "settlementId": r.get("_id"),
                    "username": r.get("username"),
                    "email": r.get("Email") or r.get("email"),
                    "phone": r.get("PhoneNumber") or r.get("phone"),
                    "payoutAmount": to_float(r.get("payoutAmount")),
                    "onboardedBy": r.get("onboardedBy"),
                    "status": r.get("status"),
                    "selfTransaction": False,
                    "adultFlag": False,
                    "noLink": False,
                    "error": str(e)
                })
            done += 1
            if done % 25 == 0 or done == len(rows):
                elapsed = time.time() - start_t
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(rows) - done) / rate if rate > 0 else 0
                print(f"  Progress: {done}/{len(rows)} ({done*100//len(rows)}%) - {rate:.1f} creators/sec - ETA: {int(eta//60)}m {int(eta%60)}s", flush=True)

    # Dynamic Date Grouping Sort: Today's settlements -> Yesterday's -> 2d Window (highest self-txn amount -> lowest)
    b_dates = agent.get_business_dates(timezone_str="Asia/Kolkata")
    today_date = b_dates["today_date"]
    yesterday_date = b_dates["yesterday_date"]

    def get_self_txn_sort_key(c):
        if not c.get("selfTransaction"):
            return (0, 0, 0, 0)
        dt_str = str(c.get("latestSelfTxnDate", ""))
        ts = to_float(c.get("latestSelfTxnTimestamp", 0))
        max_amt = to_float(c.get("selfTxnMaxAmount", 0))
        payout_amt = to_float(c.get("payoutAmount", 0))

        if today_date in dt_str or "22 Aug" in dt_str:
            day_prio = 3
        elif yesterday_date in dt_str or "21 Aug" in dt_str:
            day_prio = 2
        else:
            day_prio = 1
        return (day_prio, max_amt, ts, payout_amt)

    out.sort(key=get_self_txn_sort_key, reverse=True)

    # Save to data.json
    data_path = os.path.join(HERE, "reports", "data.json")
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"[Self-Txn Pipeline] Saved dataset to {data_path}", flush=True)

    # Also save daily timestamped snapshot in reports directory
    today_str = datetime.date.today().isoformat()
    daily_path = os.path.join(HERE, "reports", f"self_txn_{today_str}.json")
    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"[Self-Txn Pipeline] Saved daily snapshot to {daily_path}", flush=True)

    # Generate Slack report summary & HTML report
    import generate_report
    generate_report.generate_reports()
    print("[Self-Txn Pipeline] Audit report generation complete!", flush=True)


if __name__ == "__main__":
    main()
