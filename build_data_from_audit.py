#!/usr/bin/env python3
import json
import os
import datetime
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)
DATA_JSON = os.path.join(REPORTS_DIR, "data.json")

ADULT_KEYWORDS = [
    "adult", "18+", "xxx", "porn", "sex", "nude", "nudes", "escort", "erotic",
    "onlyfans", "camgirl", "camgirls", "hotgirl", "desixxx", "bhabhi", "randi",
    "callgirl", "call girl", "hookup", "fetish", "boobs", "bikini", "sensual",
    "seduction", "kamasutra", "milf", "bdsm", "hentai", "lewd", "nsfw", "sexy",
]

def to_float(v):
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0

def adult_check(username, display, category, subcategory, product_titles=None):
    product_str = " ".join([str(t or "") for t in (product_titles or [])])
    hay = " ".join([str(x or "").lower() for x in (username, display, category, subcategory, product_str)])
    hits = []
    for k in ADULT_KEYWORDS:
        pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        if re.search(pat, hay):
            hits.append(k)
    return (len(hits) > 0, ", ".join(hits))

def parse_txn_date(d_str):
    if not d_str:
        return 0.0
    fmts = [
        "%d %b, %Y; %I:%M %p",
        "%d %b %Y, %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(d_str.strip(), fmt).timestamp()
        except Exception:
            pass
    return 0.0

def main(audit_date=None):
    if not audit_date:
        audit_date = datetime.date.today().strftime("%Y-%m-%d")
    audit_files = [os.path.join(REPORTS_DIR, f) for f in os.listdir(REPORTS_DIR) if f.startswith("audit_") and f.endswith(".json")]
    if not audit_files:
        fallback_data = os.path.join(REPORTS_DIR, "data.json")
        if os.path.exists(fallback_data):
            print(f"No raw audit_*.json found, using existing {fallback_data}")
            import non_sebi_manager
            with open(fallback_data, "r", encoding="utf-8") as f:
                d = json.load(f)
            creators = d.get("creators", [])
            non_sebi_manager.record_daily_settlements(creators, audit_date=datetime.date.today().strftime("%Y-%m-%d"))
            non_sebi_manager.export_cumulative_excel()
            non_sebi_manager.export_cumulative_csv()
            non_sebi_manager.generate_manager_html_report()
            try:
                non_sebi_manager.generate_manager_pdf_report()
            except Exception:
                pass
            return
        print(f"Error: No audit_*.json files found in {REPORTS_DIR}!")
        return

    dated_audit_files = [f for f in audit_files if re.search(r"audit_\d{4}-\d{2}-\d{2}\.json", os.path.basename(f))]
    if dated_audit_files:
        audit_json = sorted(dated_audit_files, key=lambda p: re.search(r"audit_(\d{4}-\d{2}-\d{2})\.json", os.path.basename(p)).group(1), reverse=True)[0]
    else:
        audit_json = sorted(audit_files, key=os.path.getmtime, reverse=True)[0]

    with open(audit_json, "r", encoding="utf-8") as f:
        audit_data = json.load(f)

    all_results = audit_data.get("allResults", [])
    print(f"Loaded {len(all_results)} audited records from {audit_json}")

    out = []
    for r in all_results:
        sid = r.get("settlementId")
        username = r.get("username") or ""
        email = r.get("email") or ""
        phone = r.get("phone") or ""
        payout_amount = to_float(r.get("payoutAmount"))
        cid = r.get("creatorId")
        category = r.get("category")
        self_txns_raw = r.get("selfTransactions") or []
        buyers_checked = r.get("buyersChecked", 0)

        self_txns = []
        for s in self_txns_raw:
            d_str = s.get("date") or ""
            ts = parse_txn_date(d_str)
            self_txns.append({
                "amount": to_float(s.get("amountPaid") or s.get("amount")),
                "buyerEmail": s.get("buyerEmail"),
                "buyerPhone": s.get("buyerPhone"),
                "IP": s.get("IP"),
                "date": d_str,
                "timestamp": ts,
                "productId": s.get("productId")
            })
        self_txns.sort(key=lambda item: -item["timestamp"])

        is_self_txn = len(self_txns) > 0
        self_txn_count = len(self_txns)
        self_txn_max_amount = max((s["amount"] for s in self_txns), default=0.0)
        latest_date = self_txns[0]["date"] if self_txns else ""
        latest_ts = self_txns[0]["timestamp"] if self_txns else 0.0

        is_adult, adult_reason = adult_check(username, "", category, "", [])

        out.append({
            "settlementId": sid,
            "creatorId": cid,
            "username": username,
            "email": email,
            "phone": phone,
            "payoutAmount": payout_amount,
            "onboardedBy": r.get("onboardedBy", ""),
            "status": "pendingSettlement",
            "category": category,
            "subCategory": None,
            "flagLevel": None,
            "displayName": username,
            "selfTransaction": is_self_txn,
            "selfTxnCount": self_txn_count,
            "selfTxnMaxAmount": self_txn_max_amount,
            "selfTxnDetails": self_txns,
            "latestSelfTxnDate": latest_date,
            "latestSelfTxnTimestamp": latest_ts,
            "buyersChecked": buyers_checked,
            "productTitles": [],
            "productsCount": 0,
            "adultFlag": is_adult,
            "adultReason": ("keyword: " + adult_reason) if is_adult else "",
            "noLink": False,
            "noLinkCount": 0,
            "noLinkProducts": [],
            "noLinkReason": "",
            "error": r.get("error", "")
        })

    def get_day_key(c):
        if not c.get("selfTransaction"):
            return 0
        dt_str = str(c.get("latestSelfTxnDate") or "").strip()
        if dt_str:
            m = re.search(r"(\d{1,2})\s+([A-Za-z]{3}),?\s+(\d{4})", dt_str)
            if m:
                day = int(m.group(1))
                months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
                month = months.get(m.group(2))
                year = int(m.group(3))
                if day and month and year:
                    return year * 10000 + month * 100 + day

        ts = to_float(c.get("latestSelfTxnTimestamp"))
        if ts > 0:
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo("Asia/Kolkata")
            except Exception:
                tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            dt = datetime.datetime.fromtimestamp(ts, tz=tz)
            return dt.year * 10000 + dt.month * 100 + dt.day
        return 0

    out.sort(key=lambda r: (
        -get_day_key(r),
        -to_float(r.get("selfTxnMaxAmount") if r.get("selfTransaction") else 0),
        -to_float(r.get("latestSelfTxnTimestamp")),
        -to_float(r.get("payoutAmount"))
    ))

    # Dynamic review date and sale date
    rev_date = audit_date or datetime.date.today().strftime("%Y-%m-%d")
    try:
        rev_dt = datetime.datetime.strptime(rev_date, "%Y-%m-%d")
        sale_date = (rev_dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        sale_date = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # -------------------------------------------------------------
    # Telegram Integration & SEBI Verification Enhancement
    # -------------------------------------------------------------
    try:
        import telegram_sebi_verifier
        out, tele_stats = telegram_sebi_verifier.verify_all_settlements(out)
    except Exception as e:
        print(f"Warning: Telegram SEBI verification failed: {e}")
        tele_stats = {}

    # -------------------------------------------------------------
    # Product Content & Deliverable Verification (Requirement #2)
    # -------------------------------------------------------------
    try:
        import product_review_scanner
        out, prod_stats = product_review_scanner.scan_and_enrich_creators(out, audit_date=rev_date)
        print(f"Product Review Complete: {prod_stats.get('noContentCount', 0)} no-content creators, {prod_stats.get('bothCount', 0)} in both lists (top risk)")
    except Exception as e:
        print(f"Warning: Product review scanning failed: {e}")
        prod_stats = {}

    data = {
        "reviewDate": rev_date,
        "reviewDateFormatted": rev_date,
        "productSaleDate": sale_date,
        "productSaleDateFormatted": sale_date,
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "totalCreators": len(out),
        "counts": {
            "selfTransaction": sum(1 for r in out if r.get("selfTransaction")),
            "selfTransaction2d": sum(1 for r in out if r.get("selfTransaction") and r.get("inSelf2DayWindow")),
            "adult": sum(1 for r in out if r.get("adultFlag")),
            "noLink": sum(1 for r in out if r.get("noLink") is True),
            "topRiskBoth": sum(1 for r in out if r.get("topRiskBoth") is True),
            "unverifiableCap": sum(1 for r in out if r.get("unverifiableCap") is True),
            "telegramCount": tele_stats.get("telegramCount", 0),
            "telegramSebiYes": tele_stats.get("sebiYesCount", 0),
            "telegramSebiNo": tele_stats.get("sebiNoCount", 0),
            "telegramManualReview": tele_stats.get("manualReviewCount", 0),
            "telegramEligible": tele_stats.get("eligibleCount", 0)
        },
        "telegramSebiSummary": tele_stats,
        "productReviewSummary": prod_stats,
        "creators": out,
    }

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Successfully generated data.json!")
    print(f"  Total Creators: {len(out)}")
    print(f"  Self-Transactions: {data['counts']['selfTransaction']} (2-Day Window: {data['counts']['selfTransaction2d']})")
    print(f"  Missing Deliverable (No-Content): {data['counts']['noLink']}")
    print(f"  In Both Lists (Top Risk): {data['counts']['topRiskBoth']}")
    print(f"  Unverifiable (100-Cap): {data['counts']['unverifiableCap']}")
    print(f"  Adult Content (Heuristic): {data['counts']['adult']}")
    print(f"  Telegram Settlements (>= 1k): {data['counts']['telegramCount']}")
    print(f"  SEBI Verified (Yes): {data['counts']['telegramSebiYes']}")
    print(f"  SEBI Not Verified (No / Manual Review): {data['counts']['telegramSebiNo']}")

    # -------------------------------------------------------------
    # 8. Update Non-SEBI Cumulative Ledger & Manager Reports (Until 5 Sep)
    # -------------------------------------------------------------
    try:
        import non_sebi_manager
        non_sebi_manager.record_daily_settlements(out, audit_date=rev_date)
        print("Successfully updated Non-SEBI cumulative ledger and Manager submission reports!")
    except Exception as e:
        print(f"Warning: Failed to update Non-SEBI cumulative ledger: {e}")

    try:
        import generate_report
        generate_report.generate_reports()
    except Exception as e:
        print(f"Warning: Failed to auto-generate HTML report: {e}")

if __name__ == "__main__":
    main()
