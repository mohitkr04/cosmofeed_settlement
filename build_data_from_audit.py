#!/usr/bin/env python3
import json
import os
import datetime
import re

REPORTS_DIR = os.path.join(HERE, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)
AUDIT_JSON = os.path.join(REPORTS_DIR, "audit_2026-08-18.json")
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

def main():
    if not os.path.exists(AUDIT_JSON):
        print(f"Error: {AUDIT_JSON} not found!")
        return

    with open(AUDIT_JSON, "r", encoding="utf-8") as f:
        audit_data = json.load(f)

    all_results = audit_data.get("allResults", [])
    print(f"Loaded {len(all_results)} audited records from {AUDIT_JSON}")

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
        ts = to_float(c.get("latestSelfTxnTimestamp"))
        if not ts: return 0
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.year * 10000 + dt.month * 100 + dt.day

    out.sort(key=lambda r: (
        -get_day_key(r),
        -to_float(r.get("selfTxnMaxAmount") if r.get("selfTransaction") else 0),
        -to_float(r.get("latestSelfTxnTimestamp")),
        -to_float(r.get("payoutAmount"))
    ))

    data = {
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "totalCreators": len(out),
        "counts": {
            "selfTransaction": sum(1 for r in out if r["selfTransaction"]),
            "adult": sum(1 for r in out if r["adultFlag"]),
            "noLink": sum(1 for r in out if r["noLink"] is True),
        },
        "creators": out,
    }

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Successfully generated data.json!")
    print(f"  Total Creators: {len(out)}")
    print(f"  Self-Transactions: {data['counts']['selfTransaction']}")
    print(f"  Adult Content (Heuristic): {data['counts']['adult']}")

if __name__ == "__main__":
    main()
