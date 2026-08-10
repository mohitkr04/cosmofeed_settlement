import json
import datetime

def generate_reports():
    with open('data.json', encoding='utf-8') as f:
        data = json.load(f)

    creators = data.get('creators', [])
    self_creators = [c for c in creators if c.get('selfTransaction')]
    
    # Sort Per Date > Self Txn Amount (High to Low) > Time > Payout Amount
    def get_day_key(c):
        ts = float(c.get('latestSelfTxnTimestamp', 0))
        if not ts: return 0
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.year * 10000 + dt.month * 100 + dt.day

    self_creators.sort(key=lambda c: (
        -get_day_key(c),
        -float(c.get('selfTxnMaxAmount', 0)),
        -float(c.get('latestSelfTxnTimestamp', 0)),
        -float(c.get('payoutAmount', 0))
    ))

    # -------------------------------------------------------------
    # 1. GENERATE SLACK-FRIENDLY MARKDOWN REPORT
    # -------------------------------------------------------------
    slack_lines = [
        "🚨 *COSMOFEED PAYOUT RISK AUDIT REPORT*",
        f"📅 *Generated:* `{data.get('generatedAt', '—')}` | *Total Audited:* `{len(creators):,}` creators",
        "──────────────────────────────────",
        "📊 *SUMMARY METRICS:*",
        f"• *Total Pending Payout:* ₹{sum(c.get('payoutAmount',0) for c in creators):,.2f}",
        f"• *Self-Transaction Flagged:* `{len(self_creators)}` creators",
        f"• *Adult Keyword Flagged:* `{data.get('counts',{}).get('adult',0)}` creators",
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

    slack_report_text = "\n".join(slack_lines)
    with open('slack_report.txt', 'w', encoding='utf-8') as f:
        f.write(slack_report_text)

    # -------------------------------------------------------------
    # 2. GENERATE PRINTABLE PDF-STYLE HTML REPORT
    # -------------------------------------------------------------
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Cosmofeed Payout Risk Audit Executive Report</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 15mm;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a1a2e;
    background: #ffffff;
    margin: 0;
    padding: 24px;
    font-size: 13px;
    line-height: 1.5;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 16px;
    margin-bottom: 24px;
  }}
  .logo {{
    font-size: 22px;
    font-weight: 800;
    color: #e53e3e;
    letter-spacing: -0.5px;
  }}
  .meta {{
    text-align: right;
    font-size: 12px;
    color: #64748b;
  }}
  .cards {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 24px;
  }}
  .card {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 16px;
  }}
  .card .num {{
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
  }}
  .card .num.red {{ color: #e53e3e; }}
  .card .label {{
    font-size: 11px;
    color: #64748b;
    text-transform: uppercase;
    font-weight: 600;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
  }}
  th {{
    background: #f1f5f9;
    color: #475569;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 2px solid #cbd5e1;
  }}
  td {{
    padding: 8px 12px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 12px;
  }}
  tr:nth-child(even) {{ background: #f8fafc; }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 10px;
    font-weight: 700;
  }}
  .badge-self {{ background: #fee2e2; color: #dc2626; }}
  .amt {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .btn-print {{
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #2563eb;
    color: white;
    padding: 10px 20px;
    border-radius: 20px;
    border: none;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(37,99,235,0.3);
  }}
  @media print {{
    .btn-print {{ display: none; }}
  }}
</style>
</head>
<body>

<button class="btn-print" onclick="window.print()">🖨️ Save as PDF / Print</button>

<div class="header">
  <div>
    <div class="logo">💸 Cosmofeed Payout Risk Audit</div>
    <div style="font-size:13px;color:#64748b;margin-top:2px">Executive Settlement Risk & Self-Transaction Summary</div>
  </div>
  <div class="meta">
    <div><b>Generated At:</b> {data.get('generatedAt', '—')}</div>
    <div><b>Scope:</b> Pending Settlement Requests</div>
  </div>
</div>

<div class="cards">
  <div class="card">
    <div class="num">{len(creators):,}</div>
    <div class="label">Total Pending Requests</div>
  </div>
  <div class="card">
    <div class="num red">{len(self_creators)}</div>
    <div class="label">Self-Transactions Flagged</div>
  </div>
  <div class="card">
    <div class="num">{data.get('counts',{}).get('adult',0)}</div>
    <div class="label">Adult Keywords Flagged</div>
  </div>
  <div class="card">
    <div class="num">₹{sum(c.get('payoutAmount',0) for c in creators):,.0f}</div>
    <div class="label">Total Pending Payout</div>
  </div>
</div>

<h3 style="margin-bottom:8px;color:#0f172a">Flagged Self-Transactions (Ordered Per Date ➔ Amount High to Low)</h3>

<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Username</th>
      <th>Creator ID</th>
      <th>Contact Info</th>
      <th>Latest Self-Txn Date</th>
      <th class="amt">Max Self-Txn</th>
      <th class="amt">Payout Amount</th>
    </tr>
  </thead>
  <tbody>
"""
    for idx, c in enumerate(self_creators, 1):
        u = c.get('username', '—')
        cid = c.get('creatorId', '—')
        email = c.get('email', '—')
        phone = c.get('phone', '—')
        dt = c.get('latestSelfTxnDate', '—')
        sa = c.get('selfTxnMaxAmount', 0)
        p = c.get('payoutAmount', 0)
        
        html_content += f"""
    <tr>
      <td>{idx}</td>
      <td><b>{u}</b></td>
      <td><code>{cid}</code></td>
      <td style="color:#64748b">{email}<br>{phone}</td>
      <td style="color:#d97706;font-weight:600">{dt}</td>
      <td class="amt" style="color:#dc2626;font-weight:700">₹{sa:,.2f}</td>
      <td class="amt">₹{p:,.2f}</td>
    </tr>"""

    html_content += """
  </tbody>
</table>

</body>
</html>
"""
    with open('payout_audit_report.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

    print("Generated slack_report.txt and payout_audit_report.html successfully!")

if __name__ == '__main__':
    generate_reports()
