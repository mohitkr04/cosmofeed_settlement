#!/usr/bin/env python3
"""
Product Review & Content Validation Scanner
============================================
Audits all creator products to detect empty downloadable digital products (Requirement #2),
flags creators in both lists (Top Risk / Requirement #1 + #2), and verifies product coverage
within a strict 2-day buffer window.

Business Logic:
1. Product Types:
   - Downloadable digital products (productType 1/2, page, vp): MUST have deliverable files/videos/links/redirects attached.
   - Telegram products (/vig/, integratedGroup): Excluded from missing-link check (TELEGRAM_VIG_EXCLUDED).
   - Service / coaching / courses (productType 3/4, course, oneonone, paidservice): Excluded.
2. Deliverable Verification:
   - Checks unlocked files, unlocked links, unlocked videos, unlocked images, locked content (file, video, link, image),
     redirectSuccessURL, courseIds, modules, chapters, resourcesDetails, and thank-you notes.
   - If a downloadable product has 0 deliverables attached, it is flagged as LINK_MISSING.
   - API failure != missing link (classified as API_VALIDATION_FAILED without false positives).
3. Top Risk (Both Lists):
   - A creator who has BOTH a self-transaction within the 2-day buffer window AND an empty downloadable product.
"""

import os
import re
import json
import datetime
from concurrent.futures import ThreadPoolExecutor
import product_validator
import payout_audit_agent as agent

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
            months = {
                "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
            }
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


def is_downloadable_product(p):
    """Check if product is a downloadable digital product (not Telegram or service/course)."""
    ptype = str(p.get("productType") or "").strip().lower()
    plink = str(p.get("productLink") or p.get("url") or "").strip().lower()

    if "/vig/" in plink or ptype in ("integratedgroup", "vig"):
        return False
    if "/course/" in plink or ptype in ("course", "oneonone", "paidservice", "service", "3", "4"):
        return False
    return True


def validate_product_batch(pids, token, details_cache, max_workers=10):
    """Validate a batch of product IDs concurrently using product_validator and cache results."""
    missing_pids = [pid for pid in pids if pid and pid not in details_cache]
    if not missing_pids or not token:
        return

    def _val(pid):
        return pid, product_validator.validate_product_link(pid, token=token)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for pid, val_res in ex.map(lambda p: _val(p), missing_pids):
            details_cache[pid] = val_res


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

    tok = token or os.environ.get("COSMOFEED_TOKEN") or agent.DEFAULT_TOKEN

    details_cache = load_json(SCAN_CACHE_FILE, {})
    prod_cache = load_json(PROD_LIST_CACHE_FILE, {})
    cap_dict = load_json(os.path.join(REPORTS_DIR, "unverifiable_cap_creators.json"), {})

    # Load existing scan data as baseline
    scan_file = os.path.join(REPORTS_DIR, f"no_content_scan_{audit_date}.json")
    if not os.path.exists(scan_file):
        scans = [f for f in os.listdir(REPORTS_DIR) if f.startswith("no_content_scan_") and f.endswith(".json")]
        if scans:
            scans.sort(reverse=True)
            scan_file = os.path.join(REPORTS_DIR, scans[0])

    scan_data = load_json(scan_file, {}).get("creators", {})

    # Collect product IDs to validate:
    # 1. Products of creators who have self-transactions (vital for Top Risk / Both Lists)
    # 2. Products of creators previously flagged in scan_data (to verify against false-positives)
    # 3. High-payout downloadable creators
    pids_to_validate = set()
    creator_downloadables = {}

    for c in creators:
        cid = c.get("creatorId")
        if not cid:
            continue
        c_prods = prod_cache.get(cid, [])
        dl_prods = [p for p in c_prods if is_downloadable_product(p)]
        creator_downloadables[cid] = dl_prods

        should_check = c.get("selfTransaction") or (cid in scan_data) or (c.get("payoutAmount", 0) >= 10000)
        if should_check and dl_prods:
            for p in dl_prods:
                pid = product_validator.extract_product_id(p.get("_id") or p.get("productId") or p.get("productLink"))
                if pid:
                    pids_to_validate.add(pid)

    # Validate all collected products against IDviewProductDetails
    if pids_to_validate and tok:
        validate_product_batch(list(pids_to_validate), tok, details_cache, max_workers=10)
        save_json(SCAN_CACHE_FILE, details_cache)

    # Re-evaluate empty products for creators with validated products
    for cid, dl_prods in creator_downloadables.items():
        if not dl_prods:
            continue
        empty_for_creator = []
        has_any_validated = False
        all_attached = True

        for p in dl_prods:
            pid = product_validator.extract_product_id(p.get("_id") or p.get("productId") or p.get("productLink"))
            if not pid or pid not in details_cache:
                all_attached = False
                continue
            has_any_validated = True
            v = details_cache[pid]
            if v.get("validationStatus") == "LINK_MISSING" or v.get("isAttached") is False:
                all_attached = False
                empty_for_creator.append({
                    "productId": pid,
                    "title": p.get("productTtile") or p.get("title") or "",
                    "productUrl": v.get("productUrl") or f"https://superprofile.bio/vp/{pid}",
                    "reason": v.get("reason", "Downloadable product with no deliverable attached")
                })
            elif v.get("validationStatus") != "LINK_ATTACHED" and not v.get("isVigExcluded"):
                all_attached = False

        if empty_for_creator:
            # Genuinely empty product detected
            c_meta = next((c for c in creators if c.get("creatorId") == cid), {})
            scan_data[cid] = {
                "creatorId": cid,
                "username": c_meta.get("username") or scan_data.get(cid, {}).get("username", ""),
                "pending": c_meta.get("payoutAmount", 0),
                "emptyProductsCount": len(empty_for_creator),
                "exampleTitle": empty_for_creator[0]["title"],
                "productUrl": empty_for_creator[0]["productUrl"],
                "productId": empty_for_creator[0]["productId"],
                "products": empty_for_creator
            }
        elif has_any_validated and all_attached and cid in scan_data:
            # False positive resolved: all checked products have valid attached deliverables!
            del scan_data[cid]

    # Save today's updated scan file
    today_scan_file = os.path.join(REPORTS_DIR, f"no_content_scan_{audit_date}.json")
    save_json(today_scan_file, {"creators": scan_data, "count": len(scan_data)})

    # Determine Top 3 Self-Txn Days (Strict 2-Day Buffer Window)
    top_3_days = get_top_self_days(creators)

    # Enrich creators
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
            c["noLinkProducts"] = info.get("products") or [{
                "productId": info.get("productId") or "",
                "title": info.get("exampleTitle") or "",
                "productUrl": info.get("productUrl") or "",
                "reason": "Downloadable product with no deliverable attached"
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

    return creators, stats


if __name__ == "__main__":
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
