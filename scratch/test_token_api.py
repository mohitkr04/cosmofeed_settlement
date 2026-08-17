import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)

import payout_audit_agent as agent
import product_validator

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OGVmNTM3ZmZkYWNlNzlkNzQ4ZGI1MTciLCJpYXQiOjE3ODY1OTQ4NDMsImV4cCI6MjEwMTk1NDg0M30.r47i32k6PktqovRWGptLLFQ8GW1OuDxgCI-XIm3m5DI"

print("Testing API fetch settlements...")
settlements = agent.fetch_all_settlements(token, verbose=True)
print(f"Fetched {len(settlements)} settlements.")

if settlements:
    s0 = settlements[0]
    sid = s0.get("_id")
    print(f"Resolving details for settlement {sid}...")
    details = agent.resolve_settlement_details(sid, token)
    print("Details:", json.dumps(details, indent=2))
    
    cid = details.get("creatorId")
    if cid:
        print(f"Testing check_self_transactions for creator {cid}...")
        st = agent.check_self_transactions(cid, token)
        print("Self-txns:", json.dumps(st, indent=2)[:500])
        
        print(f"Testing check_creator_products for creator {cid}...")
        prods = agent.check_creator_products(cid, token)
        print("Products:", json.dumps(prods, indent=2)[:500])
