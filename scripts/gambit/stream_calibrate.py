"""
Stream-Based Key Calibration & Touchpad Test
=============================================
Uses Gambit HID keyboard stream to detect which key was physically pressed.
No Notepad needed — direct hardware-level detection.

For touchpad: uses cursor stream to detect tap/swipe results.

Keyboard stream: GET /streams/keyboard
  → {"Key":"I","IsPressed":true,"ScanCode":23,...}

Cursor stream:   GET /streams/cursor/current
  → {"X":681,"Y":505,"IsValid":true,...}

XML layout provides:
  - Key positions in mm (for correction computation)
  - Touchpad offset: X=84mm, Y=110mm from keyboard top-left
  - Touchpad size: 111mm x 90mm

Usage:
  python stream_calibrate.py              # calibrate all keys
  python stream_calibrate.py k l i        # calibrate specific keys
  python stream_calibrate.py --touchpad   # test touchpad
"""

import socket
import json
import time
import threading
import sys
import os
import datetime
import numpy as np
from pymycobot import MyCobot280Socket

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
GAMBIT_HOST = "192.168.0.4"
GAMBIT_PORT = 22133
GAMBIT_BASE = f"http://{GAMBIT_HOST}:{GAMBIT_PORT}"

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
XML_LAYOUT_PATH = os.path.join(DATA_DIR, "keyboard_layout_xml.json")
CORRECTIONS_PATH = os.path.join(DATA_DIR, "learned_corrections.json")

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp",
    f"stream_cal_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
)

# Robot motion
HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SAFE_Z = 200
SPEED_SLIDE = 25
SPEED_PRESS = 12

# Calibration
REQUIRED_CONSECUTIVE = 3
MAX_ATTEMPTS = 15

# Touchpad (from XML: offset X=84, Y=110, size W=111, H=90)
TP_KB_OFFSET_X = 84.0   # mm from keyboard left edge
TP_KB_OFFSET_Y = 110.0  # mm from keyboard top edge
TP_WIDTH = 111.0
TP_HEIGHT = 90.0

# ═══════════════════════════════════════════════════════════════
#  VK NAME → KEY NAME MAPPING
#  Maps Gambit stream "Key" values to our internal key names
# ═══════════════════════════════════════════════════════════════
VK_TO_KEY = {
    # Letters
    "A": "a", "B": "b", "C": "c", "D": "d", "E": "e", "F": "f",
    "G": "g", "H": "h", "I": "i", "J": "j", "K": "k", "L": "l",
    "M": "m", "N": "n", "O": "o", "P": "p", "Q": "q", "R": "r",
    "S": "s", "T": "t", "U": "u", "V": "v", "W": "w", "X": "x",
    "Y": "y", "Z": "z",
    # Numbers
    "VK_0": "0", "VK_1": "1", "VK_2": "2", "VK_3": "3", "VK_4": "4",
    "VK_5": "5", "VK_6": "6", "VK_7": "7", "VK_8": "8", "VK_9": "9",
    # OEM keys
    "OEM_1": ";",      # semicolon
    "OEM_2": "/",      # slash
    "OEM_3": "`",      # backtick
    "OEM_4": "[",      # left bracket
    "OEM_5": "\\",     # backslash
    "OEM_6": "]",      # right bracket
    "OEM_7": "'",      # quote/apostrophe
    "OEM_PLUS": "=",   # equals
    "OEM_COMMA": ",",  # comma
    "OEM_MINUS": "_",  # minus/dash (our XML calls it _)
    "OEM_PERIOD": ".", # period
    # Special keys
    "SPACE": "space", "RETURN": "enter", "TAB": "tab",
    "BACK": "backspace", "ESCAPE": "esc", "DELETE": "del",
    "CAPITAL": "caps", "LSHIFT": "shift_l", "RSHIFT": "shift_r",
    "LCONTROL": "ctrl_l", "RCONTROL": "ctrl_r",
    "LMENU": "alt_l", "RMENU": "alt_r",
    "LWIN": "win",
    "LEFT": "left", "RIGHT": "right", "UP": "up", "DOWN": "down",
    "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
    "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
    "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
}

# Reverse: our key name → expected VK name
KEY_TO_VK = {v: k for k, v in VK_TO_KEY.items()}

# ═══════════════════════════════════════════════════════════════
#  LOAD DATA
# ═══════════════════════════════════════════════════════════════
with open(TAUGHT_PATH) as f:
    TAUGHT = json.load(f)["keys"]
with open(XML_LAYOUT_PATH) as f:
    XML_KEYS = json.load(f)["keys"]

LEARNED = {}
if os.path.exists(CORRECTIONS_PATH):
    with open(CORRECTIONS_PATH) as f:
        LEARNED = json.load(f)


def save_learned():
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(LEARNED, f, indent=2)


def get_position(key_name):
    if key_name not in TAUGHT:
        return None, None
    data = TAUGHT[key_name]
    coords = list(data["coords"][:3])
    arm = data.get("arm", "right")
    if key_name in LEARNED:
        coords[0] += LEARNED[key_name].get("dx", 0)
        coords[1] += LEARNED[key_name].get("dy", 0)
    return coords, arm


# ═══════════════════════════════════════════════════════════════
#  GAMBIT KEYBOARD STREAM
# ═══════════════════════════════════════════════════════════════
def detect_key_press(duration=3.0):
    """Open a fresh keyboard stream, wait for a key press, return the key name."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(duration + 5)
    sock.connect((GAMBIT_HOST, GAMBIT_PORT))
    req = f"GET /streams/keyboard HTTP/1.1\r\nHost: {GAMBIT_HOST}:{GAMBIT_PORT}\r\nAccept: */*\r\n\r\n"
    sock.sendall(req.encode())

    import re
    raw = b""
    start = time.time()
    sock.settimeout(1)
    while time.time() - start < duration:
        try:
            data = sock.recv(8192)
            if data:
                raw += data
                text = data.decode("utf-8", errors="replace")
                # Look for Key field
                for m in re.finditer(r'"Key"\s*:\s*"([^"]+)"', text):
                    vk_name = m.group(1)
                    key_name = VK_TO_KEY.get(vk_name, vk_name.lower())
                    sock.close()
                    return key_name
        except socket.timeout:
            pass
    sock.close()
    return None


# ═══════════════════════════════════════════════════════════════
#  CURSOR STREAM (for touchpad)
# ═══════════════════════════════════════════════════════════════
def get_cursor():
    """Get current cursor position from Gambit."""
    import httpx
    try:
        r = httpx.get(f"{GAMBIT_BASE}/streams/cursor/current", timeout=5)
        return r.json()
    except:
        return None


# ═══════════════════════════════════════════════════════════════
#  ROBOT
# ═══════════════════════════════════════════════════════════════
mc_right = None
mc_left = None


def connect_arms():
    global mc_right, mc_left
    for ip, name, attr in [(RIGHT_IP, "right", "mc_right"), (LEFT_IP, "left", "mc_left")]:
        print(f"  {name} arm...", end="", flush=True)
        try:
            mc = MyCobot280Socket(ip, ROBOT_PORT)
            time.sleep(1)
            mc.power_on()
            time.sleep(1)
            for _ in range(15):
                a = mc.get_angles()
                if a and a != -1:
                    print(f" OK")
                    break
                time.sleep(0.3)
            else:
                print(f" connected (servos warming up)")
            if name == "right":
                mc_right = mc
            else:
                mc_left = mc
        except Exception as e:
            print(f" UNAVAILABLE")
            if name == "right":
                mc_right = None
            else:
                mc_left = None


def get_mc(arm):
    return mc_left if arm == "left" else mc_right


def press_at(mc, x, y, z):
    x = max(-280, min(280, x))
    y = max(-280, min(280, y))
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_SLIDE, 0)
    time.sleep(1.5)
    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    time.sleep(0.6)
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    time.sleep(1.0)


# ═══════════════════════════════════════════════════════════════
#  CORRECTION (using XML key positions)
# ═══════════════════════════════════════════════════════════════
def compute_correction(target_key, actual_key, arm):
    """Compute robot XY correction from XML key positions."""
    if actual_key == target_key:
        return 0, 0

    # Map to XML key names
    char_map = {"-": "_"}
    target_xml_name = char_map.get(target_key, target_key)
    actual_xml_name = char_map.get(actual_key, actual_key)

    t = XML_KEYS.get(target_xml_name)
    a = XML_KEYS.get(actual_xml_name)
    if not t or not a:
        return 0, 0

    kb_dx = t["center_x_mm"] - a["center_x_mm"]
    kb_dy = t["center_y_mm"] - a["center_y_mm"]

    # Scale: keyboard mm → robot mm (calibrated from learned data)
    if arm == "right":
        robot_dx = kb_dx * (-0.83) * 0.7
        robot_dy = kb_dy * 0.90 * 0.7
    else:
        robot_dx = kb_dx * 0.98 * 0.7
        robot_dy = kb_dy * 0.90 * 0.7

    # Minimum step for adjacent keys
    if abs(kb_dx) > 1 and abs(robot_dx) < 3:
        robot_dx = 3.0 if robot_dx > 0 else -3.0
    if abs(kb_dy) > 1 and abs(robot_dy) < 3:
        robot_dy = 3.0 if robot_dy > 0 else -3.0

    return max(-20, min(20, robot_dx)), max(-20, min(20, robot_dy))


# ═══════════════════════════════════════════════════════════════
#  CALIBRATE ONE KEY
# ═══════════════════════════════════════════════════════════════
def press_and_detect(mc, x, y, z, timeout=4.0):
    """Start stream listener, press key, return detected key name."""
    import re
    detected = [None]

    def stream_listen():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout + 5)
            s.connect((GAMBIT_HOST, GAMBIT_PORT))
            req = f"GET /streams/keyboard HTTP/1.1\r\nHost: {GAMBIT_HOST}:{GAMBIT_PORT}\r\nAccept: */*\r\n\r\n"
            s.sendall(req.encode())
            s.settimeout(1)
            start = time.time()
            header_done = False
            while time.time() - start < timeout:
                try:
                    data = s.recv(8192)
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        # Skip HTTP headers
                        if not header_done:
                            if "\r\n\r\n" in text:
                                text = text.split("\r\n\r\n", 1)[1]
                                header_done = True
                            else:
                                continue
                        # Find Key values — must be valid VK names
                        for m in re.finditer(r'"Key"\s*:\s*"([A-Z][A-Z0-9_]+)"', text):
                            vk = m.group(1)
                            if vk in VK_TO_KEY:
                                detected[0] = VK_TO_KEY[vk]
                                s.close()
                                return
                except socket.timeout:
                    pass
            s.close()
        except:
            pass

    # Start listener in background
    t = threading.Thread(target=stream_listen, daemon=True)
    t.start()
    time.sleep(0.3)  # let stream connect

    # Press the key
    press_at(mc, x, y, z)

    # Wait for detection
    t.join(timeout=timeout)
    return detected[0]


def calibrate_key(key_name):
    """Calibrate a single key using stream detection."""
    coords, arm = get_position(key_name)
    if coords is None:
        return "SKIP", 0
    mc = get_mc(arm)
    if mc is None:
        return "SKIP_ARM", 0

    x, y, z = coords
    consecutive = 0
    mc.set_color(255, 165, 0)

    for attempt in range(MAX_ATTEMPTS):
        if not (-280 <= x <= 280 and -280 <= y <= 280):
            print(f"    A{attempt+1}: OUT OF REACH ({x:.0f},{y:.0f})")
            return "FAIL_REACH", attempt + 1

        # Press and detect via stream
        detected = press_and_detect(mc, x, y, z)

        correct = (detected == key_name)
        if correct:
            consecutive += 1
        else:
            consecutive = 0

        mark = "✓" if correct else "✗"
        det_str = detected if detected else "(none)"
        print(f"    A{attempt+1}: ({x:.0f},{y:.0f}) → {det_str} {mark} [{consecutive}/{REQUIRED_CONSECUTIVE}]")

        if consecutive >= REQUIRED_CONSECUTIVE:
            orig = TAUGHT[key_name]["coords"][:3]
            LEARNED[key_name] = {
                "dx": round(x - orig[0], 2),
                "dy": round(y - orig[1], 2),
                "dz": 0,
                "final": [round(x, 2), round(y, 2), round(z, 2)],
                "attempts_needed": attempt + 1,
            }
            save_learned()
            mc.set_color(0, 255, 0)
            return "PASS", attempt + 1

        # Correction
        if detected and detected != key_name:
            dx, dy = compute_correction(key_name, detected, arm)
            x += dx
            y += dy
            x = max(-280, min(280, x))
            y = max(-280, min(280, y))
        elif not detected:
            # No key detected — arm probably not reaching keyboard
            pass

    mc.set_color(255, 0, 0)
    return "FAIL", MAX_ATTEMPTS


# ═══════════════════════════════════════════════════════════════
#  TOUCHPAD TEST
# ═══════════════════════════════════════════════════════════════
def test_touchpad():
    """Test touchpad by tapping center and reading cursor movement."""
    print("\n╔═══════════════════════════════════════════╗")
    print("║  TOUCHPAD TEST                             ║")
    print("╚═══════════════════════════════════════════╝")

    # From XML: touchpad center relative to keyboard top-left
    # TP offset: X=84mm, Y=110mm; TP size: 111x90mm
    # TP center in keyboard coords: (84 + 55.5, 110 + 45) = (139.5, 155)
    tp_center_kb_x = TP_KB_OFFSET_X + TP_WIDTH / 2
    tp_center_kb_y = TP_KB_OFFSET_Y + TP_HEIGHT / 2
    print(f"  Touchpad center (keyboard mm): ({tp_center_kb_x:.1f}, {tp_center_kb_y:.1f})")

    # Use learned keyboard positions to compute the robot coords for touchpad
    # We need the keyboard→robot transform
    arm_learned = {k: v for k, v in LEARNED.items()
                   if k in TAUGHT and TAUGHT[k].get("arm") == "left" and k in XML_KEYS}
    if len(arm_learned) < 3:
        # Try right arm
        arm_learned = {k: v for k, v in LEARNED.items()
                       if k in TAUGHT and TAUGHT[k].get("arm") == "right" and k in XML_KEYS}
        tp_arm = "right"
    else:
        tp_arm = "left"

    if len(arm_learned) < 3:
        print("  Not enough calibrated keys to compute touchpad position")
        return

    # Build xml→robot transform from learned keys
    A = []
    bx, by = [], []
    for k, v in arm_learned.items():
        px = XML_KEYS[k]["center_x_mm"]
        py = XML_KEYS[k]["center_y_mm"]
        A.append([px, py, 1])
        bx.append(v["final"][0])
        by.append(v["final"][1])

    A = np.array(A)
    mx, _, _, _ = np.linalg.lstsq(A, np.array(bx), rcond=None)
    my, _, _, _ = np.linalg.lstsq(A, np.array(by), rcond=None)

    # Predict touchpad center in robot coords
    tp_robot_x = mx[0] * tp_center_kb_x + mx[1] * tp_center_kb_y + mx[2]
    tp_robot_y = my[0] * tp_center_kb_x + my[1] * tp_center_kb_y + my[2]

    # Use keyboard Z (touchpad is at same height)
    sample_key = list(arm_learned.keys())[0]
    tp_z = arm_learned[sample_key]["final"][2]

    print(f"  Predicted robot coords: ({tp_robot_x:.1f}, {tp_robot_y:.1f}, {tp_z:.1f})")
    print(f"  Using {tp_arm} arm ({len(arm_learned)} reference keys)")

    mc = get_mc(tp_arm)
    if mc is None:
        print(f"  {tp_arm} arm not available")
        return

    # Get cursor before
    cur_before = get_cursor()
    if cur_before:
        print(f"  Cursor before: ({cur_before.get('X')}, {cur_before.get('Y')})")

    # Tap touchpad center
    print(f"  Tapping touchpad center...")
    mc.set_color(0, 255, 255)
    press_at(mc, tp_robot_x, tp_robot_y, tp_z)
    time.sleep(1)

    # Get cursor after
    cur_after = get_cursor()
    if cur_after:
        print(f"  Cursor after: ({cur_after.get('X')}, {cur_after.get('Y')})")
        if cur_before:
            dx = cur_after["X"] - cur_before["X"]
            dy = cur_after["Y"] - cur_before["Y"]
            moved = abs(dx) > 5 or abs(dy) > 5
            print(f"  Cursor moved: dx={dx}, dy={dy}  {'✓ DETECTED' if moved else '✗ no movement'}")

    mc.set_color(255, 255, 255)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    do_touchpad = "--touchpad" in sys.argv
    specific_keys = [a for a in sys.argv[1:] if not a.startswith("--")]

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("╔═══════════════════════════════════════════════════╗")
    print("║  STREAM-BASED KEY CALIBRATION                     ║")
    print("║  Detection: Gambit HID keyboard stream             ║")
    print("╚═══════════════════════════════════════════════════╝")

    # Connect arms
    print("\nConnecting arms:")
    connect_arms()

    if not mc_right and not mc_left:
        print("ERROR: No arms available!")
        return

    # Determine keys to test
    if specific_keys:
        test_keys = specific_keys
    else:
        test_keys = sorted([k for k, v in TAUGHT.items()
                           if len(k) == 1 and -280 <= v["coords"][0] <= 280
                           and get_mc(v.get("arm", "right")) is not None])

    # Skip already learned
    remaining = [k for k in test_keys if k not in LEARNED]
    already = len(test_keys) - len(remaining)

    print(f"\n  Total keys: {len(test_keys)}")
    print(f"  Already calibrated: {already}")
    print(f"  To calibrate: {len(remaining)}")
    if remaining:
        print(f"  Keys: {remaining}")

    # Calibrate remaining keys
    results = {}
    for i, key in enumerate(remaining):
        print(f"\n  [{i+1}/{len(remaining)}] ══ Key '{key}' ══ (arm={TAUGHT[key].get('arm','?')})")
        status, attempts = calibrate_key(key)
        results[key] = {"status": status, "attempts": attempts}

        if status == "PASS":
            print(f"    ✓ PASSED in {attempts} attempts")
        else:
            print(f"    ✗ {status} after {attempts} attempts")

    # Summary
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    failed = sum(1 for r in results.values() if r["status"] != "PASS" and r["status"] != "SKIP" and r["status"] != "SKIP_ARM")
    total_learned = len(LEARNED)

    print(f"\n{'═'*50}")
    print(f"  RESULTS: {passed} passed, {failed} failed this run")
    print(f"  Total learned: {total_learned}/{len(test_keys)}")
    print(f"{'═'*50}")

    for k in sorted(results):
        r = results[k]
        mark = "✓" if r["status"] == "PASS" else "✗"
        print(f"  {mark} '{k}' → {r['status']} ({r['attempts']} attempts)")

    # Save results
    results_path = os.path.join(OUTPUT_DIR, "results.json")
    with open(results_path, "w") as f:
        json.dump({"results": results, "total_learned": total_learned, "timestamp": str(datetime.datetime.now())}, f, indent=2)

    # Touchpad test
    if do_touchpad:
        test_touchpad()

    # Home
    for mc in [mc_right, mc_left]:
        if mc:
            try:
                mc.send_angles([0, 0, 0, 0, 0, 0], 15)
                mc.set_color(255, 255, 255)
            except:
                pass
    time.sleep(3)
    print("\nDone!")


if __name__ == "__main__":
    main()
