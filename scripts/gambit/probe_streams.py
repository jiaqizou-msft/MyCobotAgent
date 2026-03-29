"""Quick probe: test the Gambit streams and injection endpoints."""
import httpx
import json
import time

BASE = "http://192.168.0.4:22133"

# Check swagger for endpoint details
r = httpx.get(f"{BASE}/swagger/v1/swagger.json", timeout=10)
spec = r.json()
paths = spec.get("paths", {})

endpoints = [
    "/streams/keyboard", "/streams/cursor", "/streams/cursor/current",
    "/streams/mouse", "/streams/ptp", "/streams/touch",
    "/injection/keys/available", "/injection/keys/type",
    "/injection/keys/press", "/injection/keys/click",
]

for ep in endpoints:
    if ep in paths:
        for method, details in paths[ep].items():
            params = details.get("parameters", [])
            resp = details.get("responses", {})
            summary = details.get("summary", "")
            print(f"\n{method.upper()} {ep}  {summary}")
            for param in params:
                name = param.get("name", "?")
                loc = param.get("in", "?")
                schema = param.get("schema", {})
                print(f"  param: {name} (in={loc}) type={schema.get('type','?')}")
            if not params:
                print("  (no parameters)")

# Try some endpoints
print("\n" + "="*50)
print("LIVE PROBES:")

# Available keys
print("\n--- /injection/keys/available ---")
try:
    r = httpx.get(f"{BASE}/injection/keys/available", timeout=5)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    if isinstance(data, list):
        print(f"  {len(data)} keys available. First 20: {data[:20]}")
    else:
        print(f"  {str(data)[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# Current cursor position
print("\n--- /streams/cursor/current ---")
try:
    r = httpx.get(f"{BASE}/streams/cursor/current", timeout=5)
    print(f"  {r.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# Keyboard stream (this is likely SSE/streaming, try with short timeout)
print("\n--- /streams/keyboard (2s sample) ---")
try:
    with httpx.stream("GET", f"{BASE}/streams/keyboard", timeout=httpx.Timeout(connect=5, read=3, write=5, pool=5)) as resp:
        data = b""
        for chunk in resp.iter_bytes():
            data += chunk
            if len(data) > 2000 or time.time() > time.time():
                break
        print(f"  Response: {data[:500]}")
except httpx.ReadTimeout:
    print(f"  (timed out — likely streaming, got: {data[:300] if data else 'nothing'})")
except Exception as e:
    print(f"  Error: {e}")
