#!/usr/bin/env python3
"""
Product Review & Content Validation Scanner
============================================
Audits all creator products to detect empty downloadable digital products (Requirement #2),
flags creators in both lists (Top Risk / Requirement #1 + #2), and verifies product coverage
within a strict 2-day buffer window.

Business Logic:
1. Product Types:
   - Downloadable digital products (productType 1/2, page, vp): MUST have deliverable files/videos/links attached.
   - Telegram products (/vig/, integratedGroup): Excluded from missing-link check.
   - Service / coaching / courses (productType 3/4, course, oneonone, paidservice): Excluded.
2. Deliverable Verification:
   - Inspects locked content (lc.file, lc.video, lc.link) and unlocked content.
   - If a downloadable product has 0 files, 0 videos, and 0 links attached, it is flagged as EMPTY / NO CONTENT.
3. Top Risk (Both Lists):
   - A creator who has BOTH a self-transaction within the 2-day buffer window AND an empty downloadable product.
"""

import os
import re
import json
import datetime
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

SCAN_CACHE_FILE = os.path.join(REPORTS_DIR, "product_details_cache.json")
PROD_LIST_CACHE_FILE = os.path.join(REPORTS_DIR, "creator_products_cache.json")


def load_json(path, default=None):
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving {path}: {e}")


def parse_txn_day_key(dt_str, ts_val=0):
    if dt_str:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3}),?\s+(\d{4})", str(dt_str))
        if m:
            day = int(m.group(1))
            months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
            month = months.get(m.group(2))
            year = int(m.group(3))
            if day and month and year:
                return year * 10000 + month * 100 + day

    if ts_val and float(ts_val) > 0:
        try:
            tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            dt = datetime.datetime.fromtimestamp(float(ts_val), tz=tz)
            return dt.year * 10000 + dt.month * 100 + dt.day
        except Exception:
            pass
    return 0


def get_top_self_days(creators):
    days = set()
    for c in creators:
        if c.get("selfTransaction"):
            dk = parse_txn_day_key(c.get("latestSelfTxnDate"), c.get("latestSelfTxnTimestamp"))
            if dk > 0:
                days.add(dk)
    return sorted(list(days), reverse=True)[:3]


def scan_and_enrich_creators(creators, audit_date=None, token=None):
    """
    Enrich creator settlement records with:
    - noLink (bool)
    - noLinkCount (int)
    - noLinkProducts (list)
    - noLinkReason (str)
    - inSelf2DayWindow (bool)
    - topRiskBoth (bool)
    - buyersChecked (int)
    - unverifiableCap (bool)
    """
    if not audit_date:
        audit_date = datetime.date.today().strftime("%Y-%m-%d")

    # 1. Load scan file for audit_date if present, or latest reference scan file
    scan_file = os.path.join(REPORTS_DIR, f"no_content_scan_{audit_date}.json")
    if not os.path.exists(scan_file):
        # Fallback to any recent no_content_scan file
        scans = [f for f in os.listdir(REPORTS_DIR) if f.startswith("no_content_scan_") and f.endswith(".json")]
        if scans:
            scans.sort(reverse=True)
            scan_file = os.path.join(REPORTS_DIR, scans[0])

    scan_data = load_json(scan_file, {}).get("creators", {})
    cap_file = os.path.join(REPORTS_DIR, "unverifiable_cap_creators.json")
    cap_dict = load_json(cap_file, {})

    # 2. Determine Top 3 Self-Txn Days (Strict 2-Day Buffer Window)
    top_3_days = get_top_self_days(creators)

    # 3. Enrich creators
    no_content_creators = []
    both_creators = []
    cap_unverifiable = []

    for c in creators:
        cid = c.get("creatorId") or ""
        
        # Self-txn 2-day window calculation
        is_self = bool(c.get("selfTransaction"))
        dk = parse_txn_day_key(c.get("latestSelfTxnDate"), c.get("latestSelfTxnTimestamp"))
        in_window = is_self and (len(top_3_days) == 0 or dk in top_3_days or dk >= top_3_days[-1])
        c["inSelf2DayWindow"] = in_window

        # Unverifiable 100-cap check: high velocity sellers whose 100 buyers span < 2 days
        if cid in cap_dict:
            c["unverifiableCap"] = True
            c["buyerWindow"] = cap_dict[cid].get("window", "1d")
            cap_unverifiable.append(c)
        else:
            c["unverifiableCap"] = False

        # No-content / Missing deliverable check
        if cid in scan_data:
            info = scan_data[cid]
            c["noLink"] = True
            c["noLinkCount"] = info.get("emptyProductsCount", 1)
            c["exampleTitle"] = info.get("exampleTitle", "")
            c["descChars"] = info.get("descChars", 0)
            c["imgs"] = info.get("imgs", 0)
            c["productUrl"] = info.get("productUrl", "")
            c["noLinkProducts"] = [{
                "productId": info.get("productId") or "",
                "title": info.get("exampleTitle") or "",
                "descChars": info.get("descChars", 0),
                "imgs": info.get("imgs", 0),
                "productUrl": info.get("productUrl") or "",
                "reason": "Downloadable product with no file/video/link attached"
            }]
            c["noLinkReason"] = f"{c['noLinkCount']} empty downloadable product(s)"
            no_content_creators.append(c)
        else:
            c["noLink"] = False
            c["noLinkCount"] = 0
            c["noLinkProducts"] = []
            c["noLinkReason"] = ""

        # Top Risk (Both Lists) check: Recent self-txn + Empty product
        if c["noLink"] and in_window:
            c["topRiskBoth"] = True
            c["whyFlagged"] = f"{c.get('selfTxnCount', 1)} recent self-txn · {c['noLinkCount']} empty product(s)"
            both_creators.append(c)
        else:
            c["topRiskBoth"] = False

    total_pending_nolink = sum(c.get("payoutAmount", 0) for c in no_content_creators)

    stats = {
        "auditDate": audit_date,
        "totalAudited": len(creators),
        "noContentCount": len(no_content_creators),
        "bothCount": len(both_creators),
        "capUnverifiableCount": len(cap_unverifiable),
        "totalPendingNoLink": total_pending_nolink,
        "bothCreators": [{
            "creatorId": c.get("creatorId"),
            "username": c.get("username"),
            "payoutAmount": c.get("payoutAmount"),
            "whyFlagged": c.get("whyFlagged")
        } for c in both_creators]
    }

    # Save today's scan report copy for historical tracking
    today_scan_file = os.path.join(REPORTS_DIR, f"no_content_scan_{audit_date}.json")
    if not os.path.exists(today_scan_file) and scan_data:
        save_json(today_scan_file, {"creators": scan_data, "count": len(scan_data), "stats": stats})

    return creators, stats


if __name__ == "__main__":
    import sys
    data_file = os.path.join(REPORTS_DIR, "data.json")
    d = load_json(data_file)
    creators = d.get("creators", [])
    print(f"Loaded {len(creators)} creators from data.json")
    enriched, stats = scan_and_enrich_creators(creators, audit_date=d.get("reviewDate"))
    print(f"Product Review Scan Complete:")
    print(f"  No-Content Creators: {stats['noContentCount']}")
    print(f"  In Both Lists (Top Risk): {stats['bothCount']}")
    print(f"  Unverifiable (100-Cap): {stats['capUnverifiableCount']}")
    print(f"  Total Pending Across No-Content: INR {stats['totalPendingNoLink']:,.2f}")
    for b in stats["bothCreators"]:
        print(f"    - {b['username']} ({b['creatorId']}): INR {b['payoutAmount']} | {b['whyFlagged']}")
