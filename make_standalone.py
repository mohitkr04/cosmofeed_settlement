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
with open(os.path.join(HERE, "data.json"), encoding="utf-8") as f:
    data = json.load(f)
embedded = "const EMBEDDED_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n"
embedded += "DATA = EMBEDDED_DATA; init();\n"

new_html, n = re.subn(
    r"function fatal\(html\)\{.*?\n\}\nif\(location\.protocol.*?\n\}\n</script>",
    embedded + "</script>",
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
