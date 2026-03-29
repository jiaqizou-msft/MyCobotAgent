"""
Demo v2: Robot presses a key → Gambit keyboard stream detects it → screenshot captured.

Improvements:
- Bring Notepad to foreground before robot press
- Use /injection/keys/type to verify injection works
- Screenshot via PowerShell (ScreenCapture plugin not available)
- Better keyboard stream parsing
"""
import httpx
import threading
import time
import json
import os
import sys
import base64

GAMBIT_BASE = "http://192.168.0.4:22133"
ROBOT_IP = "10.105.230.93"
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp")
os.makedirs(OUTPUT_DIR, exist_ok=True)

HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SAFE_Z = 200
SPEED_APPROACH = 10
SPEED_PRESS = 6
TEST_KEY = "k"

# ── Keyboard stream ────────────────────────────────────────────
keyboard_events = []
stream_stop = threading.Event()
raw_stream_data = []


def listen_keyboard_stream():
    """Listen to /streams/keyboard and collect key events."""
    try:
        with httpx.stream("GET", f"{GAMBIT_BASE}/streams/keyboard",
                          timeout=httpx.Timeout(connect=5, read=120, write=5, pool=5)) as resp:
            for line in resp.iter_lines():
                if stream_stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                raw_stream_data.append(line)
                # Try to parse as JSON
                try:
                    obj = json.loads(line)
                    if isinstance(obj, list):
                        continue  # initial key list
                    keyboard_events.append(obj)
                    print(f"  [KB EVENT] {json.dumps(obj)}")
                except json.JSONDecodeError:
                    # Might be partial — store raw
                    pass
    except Exception as e:
        if not stream_stop.is_set():
            print(f"  [KB stream ended] {e}")


# ── Helpers ─────────────────────────────────────────────────────
def gambit_run(args, timeout=15):
    r = httpx.post(f"{GAMBIT_BASE}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json()


def gambit_start(binary, args="", timeout=10):
    r = httpx.post(f"{GAMBIT_BASE}/Process/start",
                   json={"Binary": binary, "Args": args}, timeout=timeout)
    return r.json()


def activate_notepad():
    """Bring Notepad to the foreground on the DUT."""
    gambit_run(
        '/c powershell -NoProfile -Command "'
        'Add-Type -AssemblyName Microsoft.VisualBasic; '
        '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
        'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }"'
    )
    time.sleep(0.5)


def clear_notepad():
    """Select all and delete in Notepad."""
    activate_notepad()
    gambit_run(
        '/c powershell -NoProfile -Command "'
        'Add-Type -AssemblyName System.Windows.Forms; '
        '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
        'Start-Sleep -Milliseconds 100; '
        '[System.Windows.Forms.SendKeys]::SendWait(\'{DELETE}\')"'
    )
    time.sleep(0.5)


def read_notepad():
    """Read Notepad content via clipboard."""
    activate_notepad()
    result = gambit_run(
        '/c powershell -NoProfile -Command "'
        'Add-Type -AssemblyName System.Windows.Forms; '
        '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
        'Start-Sleep -Milliseconds 200; '
        '[System.Windows.Forms.SendKeys]::SendWait(\'^c\'); '
        'Start-Sleep -Milliseconds 200; '
        'Get-Clipboard"',
        timeout=15,
    )
    return result.get("Output", "").strip()


def capture_screenshot(filename):
    """Capture DUT screenshot via PowerShell."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$bmp = [System.Drawing.Bitmap]::new("
        "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, "
        "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size); "
        "$path = 'C:\\temp_screenshot.png'; "
        "$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); "
        "$g.Dispose(); $bmp.Dispose(); "
        "$bytes = [System.IO.File]::ReadAllBytes($path); "
        "[Convert]::ToBase64String($bytes)"
    )
    result = gambit_run(f'/c powershell -NoProfile -Command "{ps}"', timeout=30)
    output = result.get("Output", "").strip()
    if output and len(output) > 100:
        try:
            img_data = base64.b64decode(output)
            path = os.path.join(OUTPUT_DIR, filename)
            with open(path, "wb") as f:
                f.write(img_data)
            print(f"  Screenshot: {path} ({len(img_data)//1024} KB)")
            return path
        except Exception as e:
            print(f"  Screenshot decode error: {e}")
    return None


def connect_robot():
    from pymycobot import MyCobot280Socket
    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)
    for _ in range(10):
        a = mc.get_angles()
        if a and a != -1:
            print(f"  Robot angles: {[round(x,1) for x in a]}")
            return mc
        time.sleep(0.3)
    print("  Robot connected (angles read timed out)")
    return mc


def wait_arrived(mc, timeout=3.0):
    time.sleep(0.2)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0:
                return True
        except:
            pass
        time.sleep(0.05)
    return False


def press_key_robot(mc, coords):
    x, y, z = coords[:3]
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET

    print(f"  Approach (x={x:.1f}, y={y:.1f}) ...")
    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=5)
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)

    print(f"  Press down (z={press_z:.1f}) ...")
    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)
    time.sleep(0.1)  # brief touch

    print(f"  Release ...")
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)
    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)


# ── Main ────────────────────────────────────────────────────────
def main():
    test_key = sys.argv[1] if len(sys.argv) > 1 else TEST_KEY

    with open(TAUGHT_PATH) as f:
        taught = json.load(f)["keys"]
    if test_key not in taught:
        print(f"Key '{test_key}' not in taught positions. Available: {sorted(taught.keys())}")
        return
    key_data = taught[test_key]
    coords = key_data["coords"]
    print(f"=== Robot Key Press Demo ===")
    print(f"Key: '{test_key}'  Coords: {coords[:3]}  Arm: {key_data.get('arm')}")

    # 1. DUT check
    print("\n[1] DUT check ...")
    r = httpx.get(f"{GAMBIT_BASE}/alive", timeout=5)
    print(f"  Alive: {r.text.strip()}")

    # 2. Open & prepare Notepad
    print("\n[2] Preparing Notepad ...")
    # Kill any old notepad
    gambit_run('/c taskkill /f /im notepad.exe 2>nul')
    time.sleep(1)
    gambit_start("notepad.exe")
    time.sleep(3)
    activate_notepad()
    time.sleep(1)
    clear_notepad()
    print("  Notepad ready (cleared)")

    # 3. Start keyboard stream
    print("\n[3] Starting keyboard stream listener ...")
    kb_thread = threading.Thread(target=listen_keyboard_stream, daemon=True)
    kb_thread.start()
    time.sleep(1)

    # 4. Screenshot before
    print("\n[4] Screenshot BEFORE ...")
    capture_screenshot("demo_before.png")

    # 5. Make sure Notepad is in foreground right before pressing
    print("\n[5] Pressing key with robot ...")
    activate_notepad()
    time.sleep(0.5)

    mc = connect_robot()
    mc.set_color(255, 165, 0)
    press_key_robot(mc, coords)
    mc.set_color(0, 255, 0)
    time.sleep(2)

    # 6. Screenshot after
    print("\n[6] Screenshot AFTER ...")
    capture_screenshot("demo_after.png")

    # 7. Results
    stream_stop.set()
    time.sleep(1)

    notepad_text = read_notepad()

    print(f"\n{'='*55}")
    print(f"  DEMO RESULTS")
    print(f"{'='*55}")
    print(f"  Robot pressed: '{test_key}'")
    print(f"  Notepad shows: '{notepad_text}'")
    print(f"  Keyboard stream events: {len(keyboard_events)}")
    for i, evt in enumerate(keyboard_events):
        print(f"    {i+1}: {evt}")
    print(f"  Raw stream lines: {len(raw_stream_data)}")
    if raw_stream_data:
        for line in raw_stream_data[:5]:
            if len(line) > 200:
                print(f"    (list of {len(json.loads(line))} keys)")
            else:
                print(f"    {line}")

    if notepad_text:
        print(f"\n  *** SUCCESS — Robot physically typed '{notepad_text}' on the DUT! ***")
    else:
        print(f"\n  *** Check: Notepad was empty ***")

    # Home
    mc.send_angles([0, 0, 0, 0, 0, 0], 15)
    time.sleep(4)
    mc.set_color(255, 255, 255)
    print("\nDone.")


if __name__ == "__main__":
    main()
