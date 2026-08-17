import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)

import payout_audit_agent as agent

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OGVmNTM3ZmZkYWNlNzlkNzQ4ZGI1MTciLCJpYXQiOjE3ODY1OTQ4NDMsImV4cCI6MjEwMTk1NDg0M30.r47i32k6PktqovRWGptLLFQ8GW1OuDxgCI-XIm3m5DI"

res = agent.api_get("/IDgetSettlements?requestType=pending&page=1&sortField=&onlyFlagged=0&AmountGreaterThan=0&AmountLessThan=0&filter=&paymentVerified=", token)
data = res.get("data", {})
rows = data.get("settelements") or data.get("settlements") or []
print(f"Total rows in page 1: {len(rows)}")
if rows:
    print("Sample row keys:", list(rows[0].keys()))
    print("Sample row 0:")
    print(json.dumps(rows[0], indent=2))
    print("\nSample row 1:")
    print(json.dumps(rows[1], indent=2))
