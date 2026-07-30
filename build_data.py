#!/usr/bin/env python3
"""
Build data.json for the Payout Check dashboard.

Pipeline per creator:
  IDgetSettlements -> IDgetSettlementDetails (creatorId, category, flagLevel)
                   -> getCreatorKundli (last-100 buyers -> selfPayment)
Then runs local heuristics for the Adult flag.

Usage:
  python3 build_data.py                 # full sweep (all pending settlements, slow)
  python3 build_data.py --limit 100     # quick test on first 100
  COSMOFEED_TOKEN=... python3 build_data.py

Output: data.json  (read by server.py / the dashboard)

Filter accuracy notes:
  - selfTransaction : ACCURATE (platform's own selfPayment flag).
  - adultFlag       : HEURISTIC keyword match on username/displayName/category.
                      Flags CANDIDATES for human review; not definitive.
  - noLink          : left null here (unknown). server.py can live-check page
                      status on demand. Precise detection needs the internal
                      "Review Products" API.
"""
import os
import re
import sys
import json
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import payout_audit_agent as agent  # noqa: E402

# ---- Adult-content heuristic keyword list (lowercase, substring match) ----
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
    # word-boundary match to avoid substring false positives
    # (e.g. "sex" must NOT match "OptionsExperts")
    product_str = " ".join([str(t or "") for t in (product_titles or [])])
    hay = " ".join([str(x or "").lower() for x in (username, display, category, subcategory, product_str)])
    hits = []
    for k in ADULT_KEYWORDS:
        pat = r"(?<![a-z])" + re.escape(k) + r"(?![a-z])"
        if re.search(pat, hay):
            hits.append(k)
    return (len(hits) > 0, ", ".join(hits))


def enrich_one(row, token):
    time.sleep(0.01)
    sid = row.get("_id")
    detail = agent.resolve_settlement_details(sid, token)
    base = {
        "settlementId": sid,
        "username": row.get("username"),
        "email": row.get("Email"),
        "phone": row.get("PhoneNumber"),
        "payoutAmount": to_float(row.get("payoutAmount")),
        "onboardedBy": row.get("onboardedBy"),
        "status": row.get("status"),
        "creatorId": None, "category": None, "subCategory": None, "flagLevel": None,
        "displayName": None,
        "selfTransaction": False, "selfTxnCount": 0, "selfTxnMaxAmount": 0.0,
        "selfTxnDetails": [], "buyersChecked": 0,
        "productTitles": [], "productsCount": 0,
        "adultFlag": False, "adultReason": "",
        "noLink": None, "noLinkReason": "",
        "error": "",
    }
    if "__error__" in detail:
        base["error"] = "details:" + detail["__error__"]
        return base
    cid = detail.get("creatorId")
    base.update({
        "creatorId": cid,
        "category": detail.get("categoryOfBusiness"),
        "subCategory": detail.get("subCategoryOfBusiness"),
        "flagLevel": detail.get("flagLevel"),
    })
    # self-transaction check via Kundli
    if cid:
        st = agent.check_self_transactions(cid, token)
        if "__error__" not in st:
            base["buyersChecked"] = st["buyers"]
            selfs = st["self"]
            base["selfTransaction"] = len(selfs) > 0
            base["selfTxnCount"] = len(selfs)
            base["selfTxnMaxAmount"] = max((to_float(s.get("amountPaid") or s.get("amount")) for s in selfs), default=0.0)
            base["selfTxnDetails"] = [{
                "amount": to_float(s.get("amountPaid") or s.get("amount")), "buyerEmail": s.get("buyerEmail"),
                "buyerPhone": s.get("buyerPhoneNumber"), "IP": s.get("IP"),
                "date": s.get("createdAt"), "productId": s.get("purchasedProductId"),
            } for s in selfs]
        else:
            base["error"] = "kundli:" + st["__error__"]
    else:
        base["error"] = "no_creator_id"

    # adult heuristic (username, display, category, subcategory, AND product titles)
    is_adult, reason = adult_check(base["username"], base["displayName"],
                                   base["category"], base["subCategory"],
                                   base["productTitles"])
    base["adultFlag"] = is_adult
    base["adultReason"] = ("keyword: " + reason) if is_adult else ""
    # flagLevel-based flag also feeds adult/flagged
    fl = (base["flagLevel"] or "").strip()
    if fl and fl not in ("---", "", "None", "null"):
        base["adultReason"] = (base["adultReason"] + f" | flagLevel={fl}").strip(" |")
        base["adultFlag"] = True
    return base


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--token", default=os.environ.get("COSMOFEED_TOKEN", agent.DEFAULT_TOKEN))
    args = ap.parse_args()
    token = args.token

    print("Fetching pending settlements...", flush=True)
    rows = agent.fetch_all_settlements(token)
    if args.limit:
        rows = rows[:args.limit]
    print(f"Enriching {len(rows)} creators (self-txn + category + adult heuristic)...", flush=True)

    out = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(enrich_one, r, token) for r in rows]
        for fut in as_completed(futs):
            out.append(fut.result())
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(rows)}", flush=True)

    out.sort(key=lambda r: -to_float(r.get("payoutAmount")))
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
    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote data.json | creators={len(out)} "
          f"self-txn={data['counts']['selfTransaction']} "
          f"adult(heuristic)={data['counts']['adult']}", flush=True)


if __name__ == "__main__":
    main()
