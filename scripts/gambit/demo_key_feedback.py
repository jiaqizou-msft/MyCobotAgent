"""
Demo: Robot presses a physical key → Gambit detects it via keyboard stream → captures screenshot.

Flow:
  1. Start listening to the DUT keyboard stream (background thread)
  2. Open Notepad on DUT for visual feedback
  3. Press a key with the robot arm
  4. Show keyboard events detected by Gambit
  5. Capture a screenshot of the DUT screen
"""
import httpx
import threading
import time
import json
import os
import sys
import base64

# ── Config ──────────────────────────────────────────────────────
GAMBIT_BASE = "http://192.168.0.4:22133"
ROBOT_IP = "10.105.230.93"
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp")

# Robot motion
HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SAFE_Z = 200
SPEED_APPROACH = 10
SPEED_PRESS = 6

# Default test key
TEST_KEY = "k"

# ── Keyboard stream listener ───────────────────────────────────
keyboard_events = []
stream_stop = threading.Event()


def listen_keyboard_stream():
    """Listen to Gambit keyboard stream and collect events."""
    try:
        with httpx.stream("GET", f"{GAMBIT_BASE}/streams/keyboard",
                          timeout=httpx.Timeout(connect=5, read=60, write=5, pool=5)) as resp:
            buffer = ""
            for chunk in resp.iter_text():
                if stream_stop.is_set():
                    break
                buffer += chunk
                # Try to parse JSON objects from the stream
                while buffer:
                    buffer = buffer.strip()
                    if not buffer:
                        break
                    # Try parsing as JSON
                    try:
                        obj = json.loads(buffer)
                        # If it's the initial key list, skip it
                        if isinstance(obj, list):
                            buffer = ""
                            continue
                        keyboard_events.append(obj)
                        print(f"  [KB] {obj}")
                        buffer = ""
                    except json.JSONDecodeError:
                        # Maybe partial data, try to find complete JSON objects
                        # Look for }{ boundary
                        idx = buffer.find("}{")
                        if idx >= 0:
                            part = buffer[:idx+1]
                            buffer = buffer[idx+1:]
                            try:
                                obj = json.loads(part)
                                if not isinstance(obj, list):
                                    keyboard_events.append(obj)
                                    print(f"  [KB] {obj}")
                            except:
                                pass
                        else:
                            break
    except Exception as e:
        if not stream_stop.is_set():
            print(f"  [KB stream error] {e}")


# ── Gambit helpers ──────────────────────────────────────────────
def gambit_run(args, timeout=15):
    r = httpx.post(f"{GAMBIT_BASE}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json()


def gambit_start(binary, args="", timeout=10):
    r = httpx.post(f"{GAMBIT_BASE}/Process/start",
                   json={"Binary": binary, "Args": args}, timeout=timeout)
    return r.json()


def capture_screenshot(filename="dut_screenshot.png"):
    """Try to capture a screenshot via Gambit screen capture or PowerShell."""
    # Method 1: Try Gambit screen capture plugin
    try:
        r = httpx.get(f"{GAMBIT_BASE}/screen/capture", timeout=10)
        if r.status_code == 200:
            path = os.path.join(OUTPUT_DIR, filename)
            with open(path, "wb") as f:
                f.write(r.content)
            print(f"  Screenshot saved: {path}")
            return path
    except:
        pass

    # Method 2: Use PowerShell on DUT to take screenshot and download
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$bmp = [System.Drawing.Bitmap]::new([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, "
        "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size); "
        "$path = 'C:\\temp_screenshot.png'; "
        "$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); "
        "$g.Dispose(); $bmp.Dispose(); "
        "$bytes = [System.IO.File]::ReadAllBytes($path); "
        "[Convert]::ToBase64String($bytes)"
    )
    result = gambit_run(f'/c powershell -NoProfile -Command "{ps_script}"', timeout=30)
    output = result.get("Output", "").strip()
    if output and len(output) > 100:
        try:
            img_data = base64.b64decode(output)
            path = os.path.join(OUTPUT_DIR, filename)
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(path, "wb") as f:
                f.write(img_data)
            print(f"  Screenshot saved: {path} ({len(img_data)//1024} KB)")
            return path
        except Exception as e:
            print(f"  Screenshot decode failed: {e}")
    else:
        print(f"  Screenshot capture failed (output len={len(output)})")
    return None


# ── Robot helpers ───────────────────────────────────────────────
def connect_robot():
    from pymycobot import MyCobot280Socket
    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)
    for _ in range(10):
        a = mc.get_angles()
        if a and a != -1:
            print(f"  Robot connected — angles: {[round(x,1) for x in a]}")
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

    print(f"  Moving above key (x={x:.1f}, y={y:.1f}, hover_z={hover_z:.1f}) ...")
    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=5)

    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)

    print(f"  Pressing down to z={press_z:.1f} ...")
    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)
    time.sleep(0.15)

    print(f"  Releasing ...")
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)

    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)


# ── Main ────────────────────────────────────────────────────────
def main():
    test_key = sys.argv[1] if len(sys.argv) > 1 else TEST_KEY

    # Load taught positions
    with open(TAUGHT_PATH) as f:
        taught = json.load(f)["keys"]
    if test_key not in taught:
        print(f"Key '{test_key}' not in taught positions.")
        return
    key_data = taught[test_key]
    coords = key_data["coords"]
    print(f"Test key: '{test_key}'  coords: {coords[:3]}  arm: {key_data.get('arm')}")

    # Step 1: Check DUT
    print("\n[1/6] Checking DUT connectivity ...")
    r = httpx.get(f"{GAMBIT_BASE}/alive", timeout=5)
    print(f"  DUT alive: {r.text.strip()}")

    # Step 2: Open Notepad
    print("\n[2/6] Opening Notepad on DUT ...")
    gambit_start("notepad.exe")
    time.sleep(2)
    # Clear Notepad
    gambit_run('/c powershell -NoProfile -Command "'
              'Add-Type -AssemblyName Microsoft.VisualBasic; '
              'Add-Type -AssemblyName System.Windows.Forms; '
              '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
              'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id); '
              'Start-Sleep -Milliseconds 500; '
              '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
              'Start-Sleep -Milliseconds 100; '
              '[System.Windows.Forms.SendKeys]::SendWait(\'{DELETE}\') }"')
    time.sleep(1)
    print("  Notepad ready")

    # Step 3: Start keyboard stream listener
    print("\n[3/6] Starting keyboard stream listener ...")
    kb_thread = threading.Thread(target=listen_keyboard_stream, daemon=True)
    kb_thread.start()
    time.sleep(1)
    print(f"  Listener running (events so far: {len(keyboard_events)})")

    # Step 4: Screenshot BEFORE
    print("\n[4/6] Capturing screenshot BEFORE key press ...")
    capture_screenshot("before_keypress.png")

    # Step 5: Press the key with robot
    print(f"\n[5/6] Pressing key '{test_key}' with robot arm ...")
    mc = connect_robot()
    mc.set_color(255, 165, 0)
    press_key_robot(mc, coords)
    mc.set_color(0, 255, 0)

    # Wait a moment for keyboard event to arrive
    time.sleep(2)

    # Step 6: Screenshot AFTER + results
    print(f"\n[6/6] Capturing screenshot AFTER key press ...")
    capture_screenshot("after_keypress.png")

    # Stop stream and report
    stream_stop.set()
    time.sleep(1)

    print(f"\n{'='*55}")
    print(f"  RESULTS")
    print(f"{'='*55}")
    print(f"  Key pressed by robot: '{test_key}'")
    print(f"  Keyboard events detected: {len(keyboard_events)}")
    for i, evt in enumerate(keyboard_events):
        print(f"    Event {i+1}: {evt}")

    if keyboard_events:
        print(f"\n  *** PASS — DUT keyboard stream detected physical key press! ***")
    else:
        print(f"\n  *** No keyboard events in stream (key may still have registered) ***")
        # Check Notepad content as fallback
        result = gambit_run(
            '/c powershell -NoProfile -Command "'
            'Add-Type -AssemblyName Microsoft.VisualBasic; '
            'Add-Type -AssemblyName System.Windows.Forms; '
            '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
            'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }; '
            'Start-Sleep -Milliseconds 500; '
            '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
            'Start-Sleep -Milliseconds 200; '
            '[System.Windows.Forms.SendKeys]::SendWait(\'^c\'); '
            'Start-Sleep -Milliseconds 200; '
            'Get-Clipboard"',
            timeout=20,
        )
        notepad_text = result.get("Output", "").strip()
        print(f"  Notepad content: '{notepad_text}'")
        if test_key in notepad_text.lower():
            print(f"  *** PASS — Notepad shows '{test_key}' was typed! ***")

    # Return robot home
    print("\nReturning robot to home ...")
    mc.send_angles([0, 0, 0, 0, 0, 0], 15)
    time.sleep(4)
    mc.set_color(255, 255, 255)
    print("Done.")


if __name__ == "__main__":
    main()
