#!/usr/bin/env python3
"""
Generate a SINGLE self-contained dashboard.html with data embedded.
Just double-click dashboard.html to open it — no server, no terminal, no Python needed.

Run this whenever data.json changes:
    python3 make_standalone.py
"""
import os
import re
import json

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
    html = f.read()
data_path = os.path.join(HERE, "reports", "data.json") if os.path.exists(os.path.join(HERE, "reports", "data.json")) else os.path.join(HERE, "data.json")
with open(data_path, encoding="utf-8") as f:
    data = json.load(f)
embedded = "const EMBEDDED_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n"
embedded += """DATA = EMBEDDED_DATA;
const onboarders = [...new Set((DATA.creators || []).map(c => c.onboardedBy).filter(Boolean))].sort();
const sel = document.getElementById('onboardFilter');
if (sel) {
  onboarders.forEach(o => {
    const opt = document.createElement('option');
    opt.value = o;
    opt.textContent = o;
    sel.appendChild(opt);
  });
}
render();"""

new_html, n = re.subn(
    r"// Initial Data Load with static GitHub Pages fallback & cache-busting.*?\n\s*\.catch\(err => \{.*?\n\s*\}\);",
    embedded,
    html,
    flags=re.S,
)
if n != 1:
    # Fallback to general fetch block replacement
    new_html, n = re.subn(
        r"const isStatic = window\.location\.protocol === 'file:'.*?\n\s*\}\);",
        embedded,
        html,
        flags=re.S,
    )
if n != 1:
    raise SystemExit("Could not find bootstrap block to replace (n=%d). "
                     "index.html may have changed." % n)

# The No-Link live button won't work without the server; hide it in standalone mode.
new_html = new_html.replace(
    "document.getElementById('nolinkBtn').onclick = runNoLink;",
    "document.getElementById('nolinkBtn').style.display='none';"
)
# Update footer note for standalone
new_html = new_html.replace(
    "No Link = live page-status check (superprofile pages are bot-protected, so some rows may show “unverifiable”).",
    "No Link = needs the Review Products API (not available yet); use the page link in each row's “view” to check manually."
)

out = os.path.join(HERE, "dashboard.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(new_html)
size_mb = os.path.getsize(out) / 1e6
print(f"Wrote {out}  ({size_mb:.2f} MB, {data['totalCreators']} creators embedded)")
print("Double-click dashboard.html to open it in your browser.")
