"""Check Gambit routes after restart."""
import httpx
import json

BASE = "http://192.168.0.4:22133"

r = httpx.get(f"{BASE}/alive", timeout=5)
print("Alive:", r.text)

r2 = httpx.get(f"{BASE}/Routes", timeout=10)
routes = r2.json()
print(f"Routes: {len(routes)}")

# Group by prefix
from collections import defaultdict
groups = defaultdict(list)
for rt in routes:
    path = rt.get("Route", "")
    method = rt.get("Method", "ANY")
    prefix = "/" + path.strip("/").split("/")[0] if path.strip("/") else "/"
    groups[prefix].append(f"{method:7s} {path}")

for prefix in sorted(groups):
    print(f"\n=== {prefix} ({len(groups[prefix])}) ===")
    for ep in groups[prefix]:
        print(f"  {ep}")
