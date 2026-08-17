import sys
import os
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)

import payout_audit_agent as agent
import build_data

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OGVmNTM3ZmZkYWNlNzlkNzQ4ZGI1MTciLCJpYXQiOjE3ODY1OTQ4NDMsImV4cCI6MjEwMTk1NDg0M30.r47i32k6PktqovRWGptLLFQ8GW1OuDxgCI-XIm3m5DI"

settlements = agent.fetch_all_settlements(token, verbose=False)
print("Fetched settlements:", len(settlements))

t0 = time.time()
r0 = build_data.enrich_one(settlements[0], token)
t1 = time.time()
print(f"Enriched 1 creator in {t1-t0:.2f}s:")
print(json.dumps(r0, indent=2))
