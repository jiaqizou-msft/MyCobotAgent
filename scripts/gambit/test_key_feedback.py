"""
Test: press a key with the robot arm and verify the DUT registers it.

Flow:
  1. Open Notepad on the DUT via Gambit Process API
  2. Wait for Notepad to be ready
  3. Press a key ('j') on the physical keyboard using the robot arm
  4. Read back Notepad content via PowerShell to verify
"""
import httpx
import time
import json
import os
import sys

# ── Config ──────────────────────────────────────────────────────
GAMBIT_BASE = "http://192.168.0.4:22133"

ROBOT_IP = "10.105.230.93"   # right arm
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")

# Key to test — must be reachable by the right arm
TEST_KEY = "j"

# Robot motion parameters (slow/safe for testing)
HOVER_Z_OFFSET = 15   # mm above key surface
PRESS_Z_OFFSET = 3    # mm below surface to register
SAFE_Z = 200
SPEED_APPROACH = 10
SPEED_PRESS = 6

# ── Gambit helpers ──────────────────────────────────────────────
def gambit_run(args, timeout=15):
    """Run a command on the DUT via Gambit and return output."""
    r = httpx.post(
        f"{GAMBIT_BASE}/Process/run",
        json={"Binary": "cmd.exe", "Args": args},
        timeout=timeout,
    )
    return r.json()

def gambit_start(binary, args="", timeout=10):
    """Start a process on the DUT without waiting for it to finish."""
    r = httpx.post(
        f"{GAMBIT_BASE}/Process/start",
        json={"Binary": binary, "Args": args},
        timeout=timeout,
    )
    return r.json()

def gambit_ps_run(script, timeout=15):
    """Run a PowerShell one-liner on the DUT."""
    return gambit_run(f'/c powershell -NoProfile -Command "{script}"', timeout=timeout)

# ── Robot helpers ───────────────────────────────────────────────
def connect_robot():
    from pymycobot import MyCobot280Socket
    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)
    # Verify connection
    for _ in range(10):
        a = mc.get_angles()
        if a and a != -1:
            print(f"  Robot connected — angles: {[round(x,1) for x in a]}")
            return mc
        time.sleep(0.3)
    print("  Robot connected (angles read timed out, proceeding anyway)")
    return mc

def wait_arrived(mc, timeout=3.0):
    time.sleep(0.2)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0:
                return True
        except Exception:
            pass
        time.sleep(0.05)
    return False

def press_key_robot(mc, coords):
    """Press a single key: approach → press → release → retract."""
    x, y, z = coords[:3]
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET

    print(f"  Moving above key (x={x:.1f}, y={y:.1f}, hover_z={hover_z:.1f}) ...")
    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=5)

    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)

    print(f"  Pressing down to z={press_z:.1f} ...")
    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)
    time.sleep(0.15)   # brief hold

    print(f"  Releasing ...")
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)

    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)

# ── Main test ───────────────────────────────────────────────────
def main():
    test_key = sys.argv[1] if len(sys.argv) > 1 else TEST_KEY

    # Load taught positions
    with open(TAUGHT_PATH) as f:
        taught = json.load(f)["keys"]
    if test_key not in taught:
        print(f"Key '{test_key}' not found in taught positions.")
        print(f"Available right-arm keys: {[k for k,v in taught.items() if v.get('arm')=='right']}")
        return
    key_data = taught[test_key]
    coords = key_data["coords"]
    print(f"Test key: '{test_key}'  coords: {coords[:3]}  arm: {key_data.get('arm')}")

    # Step 1: Check DUT connectivity
    print("\n[1/5] Checking DUT (Gambit) connectivity ...")
    try:
        r = httpx.get(f"{GAMBIT_BASE}/alive", timeout=5)
        print(f"  DUT alive: {r.status_code} — {r.text.strip()}")
    except Exception as e:
        print(f"  FAILED to reach DUT: {e}")
        return

    # Step 2: Open Notepad on DUT
    print("\n[2/5] Opening Notepad on DUT ...")
    gambit_start("notepad.exe")
    time.sleep(3)
    # Bring Notepad to foreground and clear any existing content
    gambit_ps_run(
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "$p = Get-Process notepad -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id); Start-Sleep -Milliseconds 500 }"
    )
    # Select all + delete to ensure Notepad is empty
    gambit_ps_run(
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.SendKeys]::SendWait('^a'); "
        "Start-Sleep -Milliseconds 100; "
        "[System.Windows.Forms.SendKeys]::SendWait('{DELETE}')"
    )
    time.sleep(1)
    print("  Notepad opened and cleared")

    # Step 3: Connect robot
    print("\n[3/5] Connecting to robot arm ...")
    mc = connect_robot()
    mc.set_color(255, 165, 0)  # orange = working

    # Step 4: Press the key
    print(f"\n[4/5] Pressing key '{test_key}' with robot arm ...")
    press_key_robot(mc, coords)
    mc.set_color(0, 255, 0)  # green = done
    time.sleep(1)

    # Step 5: Read back from DUT
    print(f"\n[5/5] Reading Notepad content from DUT ...")
    # Bring Notepad to foreground, select all, copy to clipboard, read clipboard
    result = gambit_ps_run(
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$p = Get-Process notepad -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }; "
        "Start-Sleep -Milliseconds 500; "
        "[System.Windows.Forms.SendKeys]::SendWait('^a'); "
        "Start-Sleep -Milliseconds 200; "
        "[System.Windows.Forms.SendKeys]::SendWait('^c'); "
        "Start-Sleep -Milliseconds 200; "
        "Get-Clipboard",
        timeout=20,
    )

    output = result.get("Output", "").strip()
    print(f"  Notepad content: '{output}'")

    if test_key in output.lower():
        print(f"\n  *** PASS — DUT registered key '{test_key}' ***")
    elif output:
        print(f"\n  *** UNEXPECTED — DUT shows '{output}' (expected '{test_key}') ***")
    else:
        print(f"\n  *** FAIL — Notepad is empty, key press not registered ***")

    # Return robot home
    print("\nReturning robot to home ...")
    mc.send_angles([0, 0, 0, 0, 0, 0], 15)
    time.sleep(4)
    mc.set_color(255, 255, 255)
    print("Done.")


if __name__ == "__main__":
    main()
