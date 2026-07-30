# Payout Check — Local Dashboard

A local dashboard that shows Cosmofeed **pending settlements (payouts)** like the admin panel,
with clickable filters:

- **All** — every pending settlement
- **🔴 Self-Transaction** — creators who paid themselves (buyer email/phone = creator's own)
- **🟠 Adult** — keyword-heuristic candidates (username / category)
- **🟡 No Link** — live check of the creator's public page

---

## How to run (VS Code)

1. Open this folder (`payout_check`) in VS Code.
2. Open a terminal (**Terminal → New Terminal**).
3. Run:

   ```bash
   python3 server.py
   ```

4. Open your browser at **http://localhost:8000**

No installation needed — it uses only Python's standard library. Press `Ctrl+C` in the
terminal to stop the server.

---

## Files

| File | What it is |
|------|-----------|
| `server.py` | The local web server (start this). |
| `index.html` | The dashboard UI. |
| `data.json` | The data the dashboard shows (pre-built for 2026-07-21). |
| `build_data.py` | Re-generates `data.json` from the live Cosmofeed API. |
| `payout_audit_agent.py` | The underlying API + detection logic (used by `build_data.py`). |

---

## Refreshing the data

`data.json` is a snapshot. To pull fresh pending settlements and re-run the self-transaction
check:

```bash
python3 build_data.py            # full sweep (all ~1800 creators, takes a few minutes)
python3 build_data.py --limit 100   # quick test on the first 100
```

Then refresh the browser.

The API token is embedded in `payout_audit_agent.py` (`DEFAULT_TOKEN`). To use a different
token without editing the file:

```bash
COSMOFEED_TOKEN=your_token_here python3 build_data.py
```

---

## What each filter can and cannot do (please read)

| Filter | Accuracy | How it works |
|--------|----------|--------------|
| **Self-Transaction** | ✅ Accurate | Uses the platform's own `selfPayment` flag from the creator's last-100 buyers. Every hit was verified: buyer email/phone matches the creator's own. |
| **Adult** | ⚠️ Heuristic | Keyword match on username + business category (`sex`, `xxx`, `escort`, `bhabhi`, etc., word-boundary matched to avoid false positives like "Option**sex**perts"). Flags **candidates for human review** — not definitive. This dataset had 0 keyword hits. |
| **No Link** | ⚠️ Limited | Clicks "Run No-Link live check" and fetches each creator's `superprofile.bio/<username>` page. **superprofile pages are protected by a Vercel bot-challenge, so automated checks usually return "unverifiable — open in browser".** The 404 / unreachable cases are detected reliably. |

### To make Adult + No-Link fully accurate

Both need the product/page data that lives behind the admin **"Review Products"** page.
That page currently does not load (it hangs on a blocking script), and no standalone product
API was found. Once that page works, capture its network request (the API call it fires) and
share it — the detection can then read real product titles/images and live link status per
creator, replacing the heuristics above.

---

## Notes

- The dashboard sorts by any column (click a header) and has a search box (username / email / phone).
- Click **"view ▾"** on a row to see the self-transaction details (buyer, IP, date) or the No-Link reason.
- Everything runs locally on your machine; data is read from `data.json` only.
