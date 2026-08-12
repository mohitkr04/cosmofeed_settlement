import urllib.request
import json

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OGVmNTM3ZmZkYWNlNzlkNzQ4ZGI1MTciLCJpYXQiOjE3ODQ2NTIyOTIsImV4cCI6MjEwMDAxMjI5Mn0.cz_rw88NxMz6zwHbO7WAls8oo3oB4O4wWfOSF_CBrmY"

pid = "67b3f39cae18900013e0aa95"
url = f"https://prod.api.cosmofeed.com/api/internal_dashboard/IDviewProductDetails?id={pid}&productType=page"

headers = {
    "authorization": f"Bearer {TOKEN}",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=15) as resp:
    res_data = json.loads(resp.read().decode("utf-8"))
    page_data = res_data.get("data", {}).get("pageData", {})
    print("KEYS in pageData:", list(page_data.keys()))
    print("Full JSON:")
    print(json.dumps(page_data, indent=2))
