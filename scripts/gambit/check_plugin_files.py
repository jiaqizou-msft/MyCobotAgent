"""Check actual contents of plugin folders and find real DLLs."""
import httpx

BASE = "http://192.168.0.4:22133"

def run(args, timeout=30):
    r = httpx.post(f"{BASE}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", "")

# Check what's actually IN each plugin folder
plugins = [
    "Gambit.Plugin.Audio",
    "Gambit.Plugin.Digitizer",
    "Gambit.Plugin.Digitizer.Firmware",
    "Gambit.Plugin.Display",
    "Gambit.Plugin.Injection",
    "Gambit.Plugin.PowerStateTransition",
    "Gambit.Plugin.ScreenCapture",
    "Gambit.Plugin.Sensors",
    "Gambit.Plugin.Streams.Raw",
]

for p in plugins:
    print(f"\n=== {p} ===")
    out = run(f'/c dir "C:\\gambit\\Plugins\\{p}" /b 2>nul')
    if out.strip():
        lines = out.strip().split("\n")
        print(f"  {len(lines)} items: {lines[:5]}")
        # Check for DLLs specifically
        dll_out = run(f'/c dir "C:\\gambit\\Plugins\\{p}" /s /b *.dll 2>nul')
        if dll_out.strip():
            dlls = dll_out.strip().split("\n")
            print(f"  DLLs: {len(dlls)}")
            for d in dlls[:3]:
                print(f"    {d.strip()}")
        else:
            print("  NO DLLs found!")
    else:
        print("  (folder empty or missing)")

# Check Gambit logs for plugin loading errors
print("\n\n=== Gambit startup log ===")
try:
    r = httpx.get(f"{BASE}/logs/current", timeout=10)
    for line in r.text.strip().split("\n")[:20]:
        print(line)
except:
    print("Could not get logs")

# Check if this Gambit binary is from C:\gambit
print("\n=== Running Gambit path ===")
out = run('/c powershell -NoProfile -Command "Get-Process Gambit | Select-Object Path | Format-List"')
print(out)
