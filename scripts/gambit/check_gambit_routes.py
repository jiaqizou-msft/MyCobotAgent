"""Quick check: Gambit install path, plugins, and available keyboard/touchpad routes."""
import httpx
import json

BASE = "http://192.168.0.4:22133"

def run(args, timeout=15):
    r = httpx.post(f"{BASE}/Process/run", json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", "")

# Where is Gambit running from?
print("--- Gambit.exe location ---")
out = run('/c wmic process where "name=\'Gambit.exe\'" get ExecutablePath /value 2>nul')
print(out.strip() or "(not found via wmic)")

# Check for running Gambit
print("\n--- Gambit process ---")
print(run('/c tasklist /fi "imagename eq Gambit.exe" 2>nul'))

# Find Gambit.exe on disk
print("--- Searching for Gambit.exe ---")
for p in [r"C:\gambit", r"C:\Gambit", r"C:\Program Files\Gambit",
          r"C:\Users\jiaqizou\OneDrive - Microsoft\Desktop\NewGambit\App"]:
    out = run(f'/c if exist "{p}\\Gambit.exe" echo FOUND: {p}')
    if "FOUND" in out:
        print(f"  {p}")
        # List plugins
        pout = run(f'/c dir "{p}\\Plugins" /b /s *.dll 2>nul')
        if pout.strip():
            print(f"  Plugins DLLs:\n{pout}")
        else:
            pout2 = run(f'/c dir "{p}\\Plugins" /b 2>nul')
            print(f"  Plugins dir: {pout2.strip() or '(empty)'}")

# Check all Gambit routes including plugin routes
print("\n--- All Gambit Routes ---")
r = httpx.get(f"{BASE}/Routes", timeout=10)
routes = r.json()
for route in routes:
    rt = route.get("Route", "")
    method = route.get("Method", "ANY")
    # Highlight keyboard/touchpad/digitizer/input related
    lower = rt.lower()
    marker = " <<<" if any(w in lower for w in ["key", "touch", "digit", "input", "inject", "hid"]) else ""
    print(f"  {method:7s} {rt}{marker}")

# Try some common plugin routes even if not in swagger
print("\n--- Probing common plugin endpoints ---")
for ep in ["/keyboard", "/keyboard/key", "/touchpad", "/digitizer",
           "/injection", "/injection/keyboard", "/injection/key",
           "/hid", "/hid/keyboard", "/input", "/input/keyboard"]:
    try:
        r = httpx.get(f"{BASE}{ep}", timeout=3)
        print(f"  GET {ep} -> {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  GET {ep} -> FAIL: {e}")
