import urllib.request
import json

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OGVmNTM3ZmZkYWNlNzlkNzQ4ZGI1MTciLCJpYXQiOjE3ODQ2NTIyOTIsImV4cCI6MjEwMDAxMjI5Mn0.cz_rw88NxMz6zwHbO7WAls8oo3oB4O4wWfOSF_CBrmY"

with open("data.json", encoding="utf-8") as f:
    data = json.load(f)

creators = data.get("creators", [])
product_ids = []
for c in creators:
    for p in c.get("noLinkProducts", []):
        if p.get("productId"):
            product_ids.append((p.get("productId"), "page"))
            if len(product_ids) >= 5:
                break
    if len(product_ids) >= 5:
        break

print("Testing product IDs with productType=page:", product_ids)

for pid, ptype in product_ids:
    url = f"https://prod.api.cosmofeed.com/api/internal_dashboard/IDviewProductDetails?id={pid}&productType={ptype}"
    headers = {
        "authorization": f"Bearer {TOKEN}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "accept": "application/json, text/plain, */*",
        "origin": "https://admin.cosmofeed.com",
        "referer": "https://admin.cosmofeed.com/"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            print(f"\n--- API Result for {pid} ({ptype}) ---")
            print(json.dumps(res_data, indent=2)[:1500])
    except Exception as e:
        print(f"Error for {pid}: {e}")
