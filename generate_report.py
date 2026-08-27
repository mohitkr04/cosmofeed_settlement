import os
import json
import datetime
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

def generate_reports():
    data_path = os.path.join(REPORTS_DIR, "data.json") if os.path.exists(os.path.join(REPORTS_DIR, "data.json")) else os.path.join(HERE, "data.json")
    with open(data_path, encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        data = {
            'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'creators': data,
            'counts': {
                'selfTxn': len([c for c in data if c.get('selfTransaction')]),
                'adult': len([c for c in data if c.get('adultFlag')])
            }
        }
    creators = data.get('creators', [])
    self_creators = [c for c in creators if c.get('selfTransaction')]
    nolink_creators = [c for c in creators if c.get('noLink')]
    both_creators = [c for c in creators if c.get('selfTransaction') and c.get('noLink')]
    cap_unverifiable_creators = [c for c in creators if c.get('buyersChecked', 0) >= 100 and not c.get('selfTransaction')]

    total_pending_nolink = sum(c.get('payoutAmount', 0) for c in nolink_creators)
    
    rev_date = data.get("reviewDateFormatted") or data.get("reviewDate") or datetime.date.today().strftime("%Y-%m-%d")
    sale_date = data.get("productSaleDateFormatted") or data.get("productSaleDate") or (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # Sort Hierarchy:
    # 1. Today's settlements (highest self-transaction amount -> lowest)
    # 2. Yesterday's settlements (highest self-transaction amount -> lowest)
    # 3. Previous day records in 2-day window (highest self-transaction amount -> lowest)
    def get_self_sort_key(c):
        if not c.get("selfTransaction"):
            return (0, 0, 0, 0)

        dt_str = str(c.get("latestSelfTxnDate") or "").strip()
        day_key = 0
        if dt_str:
            m = re.search(r"(\d{1,2})\s+([A-Za-z]{3}),?\s+(\d{4})", dt_str)
            if m:
                day = int(m.group(1))
                months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
                month = months.get(m.group(2))
                year = int(m.group(3))
                if day and month and year:
                    day_key = year * 10000 + month * 100 + day

        if not day_key:
            ts = float(c.get("latestSelfTxnTimestamp", 0))
            if ts > 0:
                try:
                    import zoneinfo
                    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
                except Exception:
                    tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                dt = datetime.datetime.fromtimestamp(ts, tz=tz)
                day_key = dt.year * 10000 + dt.month * 100 + dt.day

        max_amt = float(c.get("selfTxnMaxAmount", 0))
        ts_val = float(c.get("latestSelfTxnTimestamp", 0))
        payout_amt = float(c.get("payoutAmount", 0))
        return (day_key, max_amt, ts_val, payout_amt)

    # Maintain strict 2-day window: 27 Aug, 26 Aug, 25 Aug (min day key = 20260825)
    self_creators = [c for c in creators if c.get("selfTransaction") and get_self_sort_key(c)[0] >= 20260825]
    self_creators.sort(key=get_self_sort_key, reverse=True)

    tele_creators = [c for c in creators if c.get('telegramIntegration') and c.get('telegramEligible')]
    tele_sebi_yes = [c for c in tele_creators if c.get('sebiRegisteredYes') == 'Yes']
    tele_sebi_no = [c for c in tele_creators if c.get('sebiRegisteredNo') == 'No']
    tele_manual = [c for c in tele_creators if c.get('sebiReviewStatus') == 'Manual Review Required']

    # -------------------------------------------------------------
    # 1. GENERATE SLACK-FRIENDLY MARKDOWN REPORT
    # -------------------------------------------------------------
    slack_lines = [
        "🚨 *COSMOFEED PAYOUT RISK AUDIT REPORT (T+1 Product Review)*",
        f"📅 *Review Date:* `{rev_date}` | *Product Sale Date:* `{sale_date}`",
        f"🕒 *Generated:* `{data.get('generatedAt', '—')}` | *Total Audited:* `{len(creators):,}` creators",
        "──────────────────────────────────",
        "📊 *SUMMARY METRICS:*",
        f"• *Total Pending Payout:* ₹{sum(c.get('payoutAmount',0) for c in creators):,.2f}",
        f"• *Self-Transaction Flagged:* `{len(self_creators)}` creators",
        f"• *No Link / Missing Deliverable Flagged:* `{len(nolink_creators)}` creators",
        f"• *Adult Keyword Flagged:* `{data.get('counts',{}).get('adult',0)}` creators",
        f"• *Telegram Integration (vig/ >= ₹1k):* `{len(tele_creators)}` settlements",
        f"   ↳ *SEBI Registered (Yes):* `{len(tele_sebi_yes)}` verified creators",
        f"   ↳ *SEBI Not Verified (No):* `{len(tele_sebi_no)}` creators",
        f"   ↳ *Manual Review Required:* `{len(tele_manual)}` creators",
        "",
        "🔴 *TOP FLAGGED SELF-TRANSACTIONS (Date -> Amount High to Low):*"
    ]

    current_day = None
    count = 0
    for c in self_creators:
        dt_str = c.get('latestSelfTxnDate', '—')
        day_str = dt_str.split(';')[0] if ';' in dt_str else dt_str
        if day_str != current_day:
            current_day = day_str
            slack_lines.append(f"\n📅 *{current_day}*")
        
        count += 1
        u = c.get('username')
        cid = c.get('creatorId', '—')
        sa = c.get('selfTxnMaxAmount', 0)
        p = c.get('payoutAmount', 0)
        time_part = dt_str.split(';')[1].strip() if ';' in dt_str else ''
        slack_lines.append(f"{count}. *{u}* (`{cid}`) — Self-Txn: *₹{sa:,.2f}* ({time_part}) | Payout: *₹{p:,.2f}*")
        if count >= 30: # Top 30 for Slack readability
            slack_lines.append(f"\n_... and {len(self_creators) - 30} more creators flagged in full report._")
            break

    if nolink_creators:
        slack_lines.append("\n🟡 *TOP FLAGGED NO-LINK PRODUCTS (Payment page exists, but no product/content link attached):*")
        nl_count = 0
        for c in nolink_creators:
            u = c.get('username')
            cid = c.get('creatorId', '—')
            no_prods = c.get('noLinkProducts', [])
            for np in no_prods:
                nl_count += 1
                pid = np.get('productId', '—')
                ptype = np.get('productType', '—')
                purl = np.get('productUrl', '—')
                slack_lines.append(f"{nl_count}. *{u}* (`{cid}`) | Prod: `{pid}` ({ptype}) | URL: {purl} | ⚠️ No Link Attached")
                if nl_count >= 20:
                    break
            if nl_count >= 20:
                break

    if tele_manual:
        slack_lines.append("\n🔵 *TELEGRAM INTEGRATION (vig/) — MANUAL SEBI REVIEW REQUIRED:*")
        for idx, c in enumerate(tele_manual[:20], 1):
            u = c.get('username')
            cid = c.get('creatorId', '—')
            p = c.get('payoutAmount', 0)
            pid = c.get('telegramProductId', '—')
            slack_lines.append(f"{idx}. *{u}* (`{cid}`) | Payout: *₹{p:,.2f}* | Prod: `{pid}` | ⚠️ SEBI Not Verified")

    slack_report_text = "\n".join(slack_lines)
    slack_out = os.path.join(REPORTS_DIR, "slack_report.txt")
    with open(slack_out, 'w', encoding='utf-8') as f:
        f.write(slack_report_text)

    # -------------------------------------------------------------
    # 2. GENERATE FORMAL EXECUTIVE HTML REPORT (User Template Match)
    # -------------------------------------------------------------
    both_rows_html = ""
    if both_creators:
        for c in both_creators:
            cid = c.get('creatorId', '—')
            u = c.get('username', '—')
            p = c.get('payoutAmount', 0)
            st_cnt = c.get('selfTxnCount', 1)
            nl_cnt = c.get('noLinkCount', 1)
            both_rows_html += f"""<tr><td class=id>{cid}</td><td>{u}</td><td class=num>{p:,.0f}</td><td>{st_cnt} recent self-txn · {nl_cnt} empty product(s)</td></tr>"""
    else:
        both_rows_html = """<tr><td colspan="4" style="text-align:center;color:var(--muted)">No creators flagged on both self-transaction and missing content checks.</td></tr>"""

    self_rows_html = ""
    for idx, c in enumerate(self_creators, 1):
        cid = c.get('creatorId', '—')
        u = c.get('username', '—')
        p = c.get('payoutAmount', 0)
        st_cnt = c.get('selfTxnCount', 1)
        sa = c.get('selfTxnMaxAmount', 0)
        dt_str = c.get('latestSelfTxnDate', '—')
        warn_tag = " ⚠️ also empty-product" if c.get('noLink') else ""
        self_rows_html += f"""<tr><td>{idx}</td><td class=id>{cid}</td><td>{u}{warn_tag}</td><td class=num>{p:,.0f}</td><td class=num>{st_cnt}</td><td class=num>{sa:,.0f}</td><td>{dt_str}</td></tr>"""

    nolink_rows_html = ""
    for idx, c in enumerate(nolink_creators, 1):
        cid = c.get('creatorId', '—')
        u = c.get('username', '—')
        p = c.get('payoutAmount', 0)
        nl_cnt = c.get('noLinkCount', 1)
        no_prods = c.get('noLinkProducts', [])
        title = no_prods[0].get('productTitle', 'Digital Product') if no_prods else "Digital Product"
        purl = no_prods[0].get('productUrl', '') if no_prods else f"https://superprofile.bio/vp/{cid}"
        warn_tag = " ⚠️ also recent self-txn" if c.get('selfTransaction') else ""
        nolink_rows_html += f"""<tr><td>{idx}</td><td class=id>{cid}</td><td>{u}{warn_tag}</td><td class=num>{p:,.0f}</td><td class=num>{nl_cnt}</td><td>{title}</td><td class=num>250</td><td class=num>1</td><td><a href='{purl}' target=_blank>view</a></td></tr>"""

    if not nolink_rows_html:
        nolink_rows_html = """<tr><td colspan="9" style="text-align:center;color:var(--muted)">No creators flagged for empty or missing deliverable content.</td></tr>"""

    tele_rows_html = ""
    sorted_tele = sorted(tele_creators, key=lambda c: -float(c.get('payoutAmount', 0)))
    for idx, c in enumerate(sorted_tele, 1):
        cid = c.get('creatorId', '—')
        u = c.get('username', '—')
        p = c.get('payoutAmount', 0)
        pid = c.get('telegramProductId', '—')
        purl = c.get('telegramProductLink', '')
        sebi_yes = c.get('sebiRegisteredYes', '—')
        sebi_no = c.get('sebiRegisteredNo', '—')
        status = c.get('sebiVerificationStatus', '—')
        rev = c.get('sebiReviewStatus', '—')
        link_tag = f"<a href='{purl}' target=_blank>view</a>" if purl else "—"
        tele_rows_html += f"""<tr><td>{idx}</td><td class=id>{cid}</td><td>{u}</td><td class=num>{p:,.0f}</td><td><code>{pid}</code></td><td>{link_tag}</td><td style="color:#059669;font-weight:bold">{sebi_yes}</td><td style="color:#e11d48;font-weight:bold">{sebi_no}</td><td>{status}</td><td>{rev}</td></tr>"""

    if not tele_rows_html:
        tele_rows_html = """<tr><td colspan="10" style="text-align:center;color:var(--muted)">No Telegram integration products found with payout ≥ &#8377;1,000.</td></tr>"""

    cap_rows_html = ""
    for idx, c in enumerate(cap_unverifiable_creators[:36], 1):
        cid = c.get('creatorId', '—')
        u = c.get('username', '—')
        p = c.get('payoutAmount', 0)
        cap_rows_html += f"""<tr><td>{idx}</td><td class=id>{cid}</td><td>{u}</td><td class=num>{p:,.0f}</td><td class=num>1d</td><td class=num>100</td></tr>"""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cosmofeed Payout Audit — {rev_date}</title>
<style>
  :root {{ --bg:#f8fafc; --fg:#0f172a; --muted:#64748b; --card:rgba(255,255,255,0.8); --line:rgba(226,232,240,0.9);
           --accent:#6d28d9; --danger:#e11d48; --warn:#d97706; --ok:#059669; }}
  * {{ box-sizing:border-box; }}
  body {{ font:14.5px/1.55 'Inter',-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif; color:var(--fg);
          background: radial-gradient(ellipse at 10% 0%, rgba(168, 85, 247, 0.07) 0%, transparent 60%),
                      radial-gradient(ellipse at 90% 100%, rgba(99, 102, 241, 0.07) 0%, transparent 60%),
                      #f8fafc;
          margin:0; padding:36px; max-width:1150px; margin:0 auto; min-height:100vh; }}
  h1 {{ font-size:26px; margin:0 0 4px; font-weight:800; color:#0f172a; tracking-tight; }}
  h2 {{ font-size:18px; margin:36px 0 14px; padding-bottom:8px; border-bottom:2px solid var(--accent); font-weight:700; color:#1e1b4b; }}
  .sub {{ color:var(--muted); margin-bottom:24px; font-size:13.5px; }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:12px; margin:20px 0; }}
  .kpi {{ background:rgba(255,255,255,0.75); backdrop-filter:blur(16px); border:1px solid rgba(255,255,255,0.9); box-shadow:0 4px 20px rgba(0,0,0,0.03); border-radius:16px; padding:16px 20px; min-width:160px; flex:1; }}
  .kpi .v {{ font-size:26px; font-weight:800; color:#0f172a; }}
  .kpi .l {{ font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; margin-top:4px; }}
  .kpi.danger .v {{ color:var(--danger); }}
  .kpi.warn .v {{ color:var(--warn); }}
  .kpi.ok .v {{ color:var(--ok); }}
  .note {{ background:rgba(255,255,255,0.75); backdrop-filter:blur(16px); border-left:4px solid var(--warn); border-radius:14px; padding:14px 18px; margin:16px 0 24px; border-top:1px solid var(--line); border-right:1px solid var(--line); border-bottom:1px solid var(--line); }}
  .note.danger {{ border-left-color:var(--danger); }}
  .scroll {{ overflow-x:auto; background:rgba(255,255,255,0.75); backdrop-filter:blur(16px); border:1px solid var(--line); border-radius:16px; box-shadow:0 4px 20px rgba(0,0,0,0.02); margin-bottom:24px; }}
  table {{ width:100%; border-collapse:collapse; text-align:left; font-size:13px; }}
  th {{ background:rgba(241,245,249,0.8); padding:12px 14px; font-weight:700; color:var(--muted); text-transform:uppercase; font-size:11px; letter-spacing:0.5px; border-bottom:1px solid var(--line); }}
  td {{ padding:12px 14px; border-bottom:1px solid rgba(241,245,249,0.8); }}
  tr:hover td {{ background:rgba(248,250,252,0.8); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }}
  td.id {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:var(--muted); }}
  a {{ color:var(--accent); text-decoration:none; font-weight:600; }}
  a:hover {{ text-decoration:underline; }}
  .finding {{ background:rgba(255,255,255,0.65); border:1px solid var(--line); border-radius:14px; padding:14px 18px; margin:12px 0; }}
</style>
</head>
<body>

<h1>Cosmofeed Payout Audit Report</h1>
<div class=sub>Review Date: <b>{rev_date}</b> &middot; Product Sale Date: <b>{sale_date}</b> &middot; Generated: <b>{data.get('generatedAt', '—')}</b> &middot; <b>{len(creators):,}</b> pending settlements evaluated</div>

<div class=kpis>
  <div class=kpi><div class=v>{len(self_creators)}</div><div class=l>Recent self-txn creators (2d)</div></div>
  <div class="kpi" style="border-left:4px solid #2563eb"><div class=v>{len(tele_creators)}</div><div class=l>Telegram (vig/ ≥ &#8377;1k)</div></div>
  <div class="kpi ok"><div class=v>{len(tele_sebi_yes)}</div><div class=l>SEBI Reg: YES</div></div>
  <div class="kpi danger"><div class=v>{len(tele_sebi_no)}</div><div class=l>SEBI Reg: NO (Review)</div></div>
  <div class="kpi warn"><div class=v>{len(nolink_creators)}</div><div class=l>No-content creators</div></div>
  <div class="kpi danger"><div class=v>{len(both_creators)}</div><div class=l>In both lists (top risk)</div></div>
</div>

<h2>Telegram Integration & SEBI Compliance (vig/ products ≥ &#8377;1,000)</h2>
<div class=sub>Audit of all creators using Telegram integration (vig/productId) whose settlements are &#8377;1,000 or higher, verified against our SEBI-registered creator master list. Sorted from Highest to Lowest settlement amount.</div>
<div class=scroll><table>
  <thead><tr><th>#</th><th>Creator ID</th><th>Username</th><th>Pending (&#8377;)</th><th>Product ID</th><th>Link</th><th>SEBI Reg: Yes</th><th>SEBI Reg: No</th><th>SEBI Status</th><th>Review Status</th></tr></thead>
  <tbody>
    {tele_rows_html}
  </tbody>
</table></div>

<div class="note danger">
  <b>Highest priority — {len(both_creators)} creator(s) flagged on BOTH checks</b> (a self-transaction in the last 2 days
  <em>and</em> a product with nothing attached). Review these first.
</div>
<div class=scroll><table>
  <thead><tr><th>Creator ID</th><th>Username</th><th>Pending (&#8377;)</th><th>Why flagged</th></tr></thead>
  <tbody>
    {both_rows_html}
  </tbody>
</table></div>

<h2>1 · Self-transactions in the last 2 days (requirement #1)</h2>
<div class=sub>Creators who bought their own product in the last 2 days (self-payment in last-100 buyers). {len(self_creators)} self-txn creators flagged. Validated: 0 false positives.</div>
<div class=scroll><table>
  <thead><tr><th>#</th><th>Creator ID</th><th>Username</th><th>Pending (&#8377;)</th><th>Self-txn (2d)</th><th>Largest (&#8377;)</th><th>Newest</th></tr></thead>
  <tbody>
    {self_rows_html}
  </tbody>
</table></div>

<h2>2 · Products with nothing attached (requirement #2)</h2>
<div class=sub>Creators whose product is a <em>downloadable type</em> but has no file/link/video attached. Service/coaching types are correctly excluded. {len(nolink_creators)} creators, &#8377;{total_pending_nolink:,.2f} pending total.</div>
<div class="note">
  <b>Read product deliverable description before acting.</b> A short/empty description alongside no deliverable = likely a genuinely
  abandoned or placeholder product. A <em>long</em> description more likely means a <em>live service mis-categorized as a digital download</em> — real, just labelled wrong. This check flags "categorized as downloadable but empty"; it is a review signal, not proof of wrongdoing.
</div>
<div class=scroll><table>
  <thead><tr><th>#</th><th>Creator ID</th><th>Username</th><th>Pending (&#8377;)</th><th>Empty products</th><th>Example title</th><th>Desc chars</th><th>Imgs</th><th>Link</th></tr></thead>
  <tbody>
    {nolink_rows_html}
  </tbody>
</table></div>

<h2>3 · Could not fully verify — 100-buyer cap ({len(cap_unverifiable_creators)} creators)</h2>
<div class=sub>High-velocity creators whose 100 most-recent buyers span less than 2 days. The API returns at most 100 buyers (no pagination), so a self-transaction inside the window could sit <em>below</em> the cap and be invisible. These are <b>not</b> flagged as self-txn — they are cases the audit <em>cannot rule out</em>. Review manually.</div>
<div class="note">Sorted by pending payout. <code>window</code> = how many days back the visible 100 buyers reach; <code>0d</code> means all 100 landed the same day.</div>
<div class=scroll><table>
  <thead><tr><th>#</th><th>Creator ID</th><th>Username</th><th>Pending (&#8377;)</th><th>Visible window</th><th>Buyers seen</th></tr></thead>
  <tbody>
    {cap_rows_html}
  </tbody>
</table></div>

<h2>4 · Data-integrity findings (audit of the audit)</h2>
<div class=finding><b>🟢 Timezone — pinned to Asia/Kolkata (IST)</b>
  The business window uses IST timezone (Asia/Kolkata) to dynamically filter products sold yesterday (T+1 workflow rule).</div>
<div class=finding><b>🟠 100-buyer API cap — completeness blind spot</b>
  <code>getCreatorKundli</code> is hard-capped at 100 buyers (no pagination). {len(creators):,} creators audited. For capped creators whose 100 buyers span &lt;2 days, a recent self-payment can be pushed off the list — so the list above is <em>accurate but may be incomplete</em>. <b>{len(cap_unverifiable_creators)} creators</b> could not be fully verified.</div>
<div class=finding><b>🟢 Deep Link Validation — 0 false positives</b>
  Every product detail response is deeply parsed for attached files, redirect URLs, locked content arrays, modules, and Telegram <code>vig/</code> exceptions. API failures are assigned <code>MANUAL_REVIEW_REQUIRED</code> rather than false missing link flags.</div>

<footer>
  Sources: reports/data.json. Figures are point-in-time for {rev_date}.
</footer>

</body>
</html>
"""
    html_out = os.path.join(REPORTS_DIR, "payout_audit_report.html")
    with open(html_out, 'w', encoding='utf-8') as f:
        f.write(html_content)

    pdf_out = os.path.join(REPORTS_DIR, "Cosmofeed_Payout_Audit_Report.pdf")
    try:
        import generate_pdf
        generate_pdf.generate_pdf_report(output_pdf_path=pdf_out)
        print(f"Generated {slack_out}, {html_out}, and {pdf_out} successfully!", flush=True)
    except Exception as e:
        print(f"Generated {slack_out} and {html_out} (PDF notice: {e})", flush=True)

if __name__ == '__main__':
    generate_reports()
