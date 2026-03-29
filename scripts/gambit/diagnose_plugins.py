"""Diagnose why Gambit plugins aren't loading."""
import httpx

BASE = "http://192.168.0.4:22133"

def run(args, timeout=20):
    r = httpx.post(f"{BASE}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", "")

# Where is Gambit running from?
print("=== Gambit Process Location ===")
out = run('/c wmic process where "name=\'Gambit.exe\'" get ExecutablePath 2>nul')
print(out.strip())

# Check for actual DLL files in Plugins
print("\n=== Plugin DLLs ===")
out = run('/c dir "C:\\gambit\\Plugins" /s /b *.dll 2>nul', timeout=30)
print(out.strip() if out.strip() else "(no DLLs found!)")

# List all files in the plugins dir
print("\n=== All files under Plugins/ ===")
out = run('/c dir "C:\\gambit\\Plugins" /s /b 2>nul', timeout=30)
print(out[:3000] if out else "(empty)")

# Check the Gambit logs for plugin loading info
print("\n=== Gambit Logs (last 50 lines) ===")
try:
    r = httpx.get(f"{BASE}/logs/current", timeout=10)
    lines = r.text.strip().split("\n")
    for line in lines[-50:]:
        print(line)
except Exception as e:
    print(f"Failed to get logs: {e}")

# Check Gambit.exe version in C:\gambit vs the running one
print("\n=== Gambit version ===")
r = httpx.get(f"{BASE}/version", timeout=5)
print(r.text)
