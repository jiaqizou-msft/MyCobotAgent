"""Press a single key and report result clearly."""
import sys
import json
import time
import httpx
from pymycobot import MyCobot280Socket

GAMBIT = "http://192.168.0.4:22133"
key = sys.argv[1] if len(sys.argv) > 1 else "i"

# Load position
with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\keyboard_taught.json") as f:
    taught = json.load(f)["keys"]
with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\learned_corrections.json") as f:
    corr = json.load(f)

if key not in taught:
    print(f"Key '{key}' not in taught positions")
    sys.exit(1)

coords = list(taught[key]["coords"][:3])
arm = taught[key].get("arm", "right")
if key in corr:
    coords[0] += corr[key]["dx"]
    coords[1] += corr[key]["dy"]

x, y, z = coords
ip = "10.105.230.93" if arm == "right" else "10.105.230.94"

print(f"╔════════════════════════════════════╗")
print(f"║  PRESSING KEY: '{key}'")
print(f"║  Arm: {arm}  ({ip})")
print(f"║  Position: ({x:.1f}, {y:.1f}, {z:.1f})")
print(f"╚════════════════════════════════════╝")

# Connect
print(f"  Connecting {arm} arm...", end="", flush=True)
mc = MyCobot280Socket(ip, 9000)
time.sleep(1)
mc.power_on()
time.sleep(1)
print(" OK")
mc.set_color(255, 165, 0)

# Clear Notepad
print("  Clearing Notepad...", end="", flush=True)
def gambit_run(args, timeout=20):
    r = httpx.post(f"{GAMBIT}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", "").strip()

gambit_run(
    '/c powershell -NoProfile -Command "'
    'Add-Type -AssemblyName System.Windows.Forms; '
    'Add-Type -AssemblyName Microsoft.VisualBasic; '
    'Set-Clipboard -Value $null; '
    '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
    'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }; '
    'Start-Sleep -Milliseconds 500; '
    '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
    'Start-Sleep -Milliseconds 200; '
    '[System.Windows.Forms.SendKeys]::SendWait(\'{DELETE}\'); '
    'Start-Sleep -Milliseconds 300"'
)
print(" OK")

# Move and press
hover_z = z + 15
press_z = z - 3
print(f"  Moving to hover...", end="", flush=True)
mc.send_coords([x, y, hover_z, 0, 180, 90], 15, 0)
time.sleep(3)
print(" OK")

print(f"  PRESSING key '{key}'...", end="", flush=True)
mc.send_coords([x, y, press_z, 0, 180, 90], 8, 0)
time.sleep(0.8)
mc.send_coords([x, y, hover_z, 0, 180, 90], 8, 0)
time.sleep(1.5)
print(" OK")

# Read result
print("  Reading Notepad...", end="", flush=True)
text = gambit_run(
    '/c powershell -NoProfile -Command "'
    'Add-Type -AssemblyName System.Windows.Forms; '
    'Add-Type -AssemblyName Microsoft.VisualBasic; '
    '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
    'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }; '
    'Start-Sleep -Milliseconds 500; '
    '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
    'Start-Sleep -Milliseconds 500; '
    '[System.Windows.Forms.SendKeys]::SendWait(\'^c\'); '
    'Start-Sleep -Milliseconds 500; '
    'Get-Clipboard"'
)
actual = text[0].lower() if text else "(empty)"
print(f' got: "{text[:20]}"')

passed = actual == key
mc.set_color(0, 255, 0) if passed else mc.set_color(255, 0, 0)

print()
print(f"  ╔══════════════════════════════╗")
print(f"  ║  KEY: '{key}'")
print(f"  ║  Expected: '{key}'")
print(f"  ║  Got:      '{actual}'")
print(f"  ║  Result:   {'✓ PASS' if passed else '✗ FAIL'}")
print(f"  ╚══════════════════════════════╝")
