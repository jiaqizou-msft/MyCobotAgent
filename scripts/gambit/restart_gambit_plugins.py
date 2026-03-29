"""Check plugin DLLs and restart Gambit to load them."""
import httpx
import time

BASE = "http://192.168.0.4:22133"

def run(args, timeout=30):
    r = httpx.post(f"{BASE}/Process/run", json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", ""), r.json().get("ExitCode", -1)

# Check actual plugin folder contents
print("=== Plugin Folder Contents ===")
out, _ = run('/c dir "C:\\gambit\\Plugins" /b 2>nul')
print(out)

# Check each plugin folder for DLLs
folders = [f.strip() for f in out.strip().split("\n") if f.strip()]
for folder in folders:
    print(f"\n--- {folder} ---")
    out, _ = run(f'/c dir "C:\\gambit\\Plugins\\{folder}" /b 2>nul')
    print(out.strip() or "  (empty)")

# Check the Gambit executable & config
print("\n=== Gambit.exe check ===")
out, _ = run('/c dir "C:\\gambit\\Gambit.exe" 2>nul')
print(out)

# Check if there's a config file
print("=== Config files ===")
out, _ = run('/c dir "C:\\gambit" /b 2>nul')
print(out)

# Try restarting Gambit via its own API
print("\n=== Restarting Gambit to load plugins ===")
try:
    r = httpx.get(f"{BASE}/installer/restart", timeout=10)
    print(f"Restart response: {r.status_code} {r.text[:200]}")
except Exception as e:
    print(f"Restart request: {e}")

# Wait for it to come back
print("Waiting for Gambit to restart...")
for i in range(20):
    time.sleep(2)
    try:
        r = httpx.get(f"{BASE}/alive", timeout=3)
        if r.status_code == 200:
            print(f"  Gambit is back! (attempt {i+1})")
            break
    except:
        print(f"  Still restarting... ({i+1})")

# Now check routes again
time.sleep(2)
r = httpx.get(f"{BASE}/Routes", timeout=10)
routes = r.json()
print(f"\n=== Routes after restart ({len(routes)} total) ===")
for route in routes:
    rt = route.get("Route", "")
    method = route.get("Method", "ANY")
    print(f"  {method:7s} {rt}")
