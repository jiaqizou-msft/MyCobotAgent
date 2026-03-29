"""
Anchor-Based Calibration with Gambit Stream Verification
=========================================================
1. User teaches anchor points by dragging arm to specific keys
2. Fits affine transform: XML physical positions → robot coordinates
3. Predicts all key positions from the transform
4. Verifies each key via Gambit HID keyboard stream
5. Corrects iteratively using XML key spacing

Usage:
  python anchor_calibrate.py --arm right    # teach right arm anchors
  python anchor_calibrate.py --arm left     # teach left arm anchors
  python anchor_calibrate.py --verify       # verify all learned keys
  python anchor_calibrate.py --verify k l i # verify specific keys
"""

import socket
import json
import time
import threading
import sys
import os
import re
import numpy as np
from pymycobot import MyCobot280Socket

# ═══════════════════════════════════════════════════════════════
GAMBIT_HOST = "192.168.0.4"
GAMBIT_PORT = 22133

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
XML_LAYOUT_PATH = os.path.join(DATA_DIR, "keyboard_layout_xml.json")
CORRECTIONS_PATH = os.path.join(DATA_DIR, "learned_corrections.json")

HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SPEED_SLIDE = 20
SPEED_PRESS = 10
REQUIRED_CONSECUTIVE = 3
MAX_ATTEMPTS = 12

# VK name → our key name
VK_TO_KEY = {
    "A": "a", "B": "b", "C": "c", "D": "d", "E": "e", "F": "f",
    "G": "g", "H": "h", "I": "i", "J": "j", "K": "k", "L": "l",
    "M": "m", "N": "n", "O": "o", "P": "p", "Q": "q", "R": "r",
    "S": "s", "T": "t", "U": "u", "V": "v", "W": "w", "X": "x",
    "Y": "y", "Z": "z",
    "VK_0": "0", "VK_1": "1", "VK_2": "2", "VK_3": "3", "VK_4": "4",
    "VK_5": "5", "VK_6": "6", "VK_7": "7", "VK_8": "8", "VK_9": "9",
    "OEM_1": ";", "OEM_2": "/", "OEM_3": "`", "OEM_4": "[",
    "OEM_5": "\\", "OEM_6": "]", "OEM_7": "'", "OEM_PLUS": "=",
    "OEM_COMMA": ",", "OEM_MINUS": "_", "OEM_PERIOD": ".",
    "SPACE": "space", "RETURN": "enter", "TAB": "tab",
    "BACK": "backspace", "ESCAPE": "esc", "DELETE": "del",
    "CAPITAL": "caps", "LSHIFT": "shift_l", "RSHIFT": "shift_r",
    "LCONTROL": "ctrl_l", "LMENU": "alt_l", "RMENU": "alt_r",
    "LWIN": "win", "LEFT": "left", "RIGHT": "right",
    "UP": "up", "DOWN": "down",
    "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4", "F5": "f5",
    "F6": "f6", "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10",
    "F11": "f11", "F12": "f12",
}

# Load XML layout
with open(XML_LAYOUT_PATH) as f:
    XML_KEYS = json.load(f)["keys"]

# Load learned corrections
LEARNED = {}
if os.path.exists(CORRECTIONS_PATH):
    with open(CORRECTIONS_PATH) as f:
        LEARNED = json.load(f)


def save_learned():
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(LEARNED, f, indent=2)


# ═══════════════════════════════════════════════════════════════
#  GAMBIT STREAM DETECTION
# ═══════════════════════════════════════════════════════════════
def detect_key_press(mc, x, y, z, timeout=5.0):
    """Open keyboard stream, press key at (x,y,z), return detected key name."""
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
                        if not header_done:
                            if "\r\n\r\n" in text:
                                text = text.split("\r\n\r\n", 1)[1]
                                header_done = True
                            else:
                                continue
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

    t = threading.Thread(target=stream_listen, daemon=True)
    t.start()
    time.sleep(0.3)

    # Press key
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

    t.join(timeout=timeout)
    return detected[0]


# ═══════════════════════════════════════════════════════════════
#  ROBOT HELPERS
# ═══════════════════════════════════════════════════════════════
def read_position_stable(mc):
    """Read position with retries for stability."""
    coords_list = []
    for _ in range(8):
        time.sleep(0.5)
        c = mc.get_coords()
        if c and c != -1:
            coords_list.append(c)
    if not coords_list:
        return None
    recent = coords_list[-3:] if len(coords_list) >= 3 else coords_list
    avg = [sum(x) / len(x) for x in zip(*recent)]
    return [round(v, 2) for v in avg]


# ═══════════════════════════════════════════════════════════════
#  PHASE 1: TEACH ANCHOR POINTS
# ═══════════════════════════════════════════════════════════════
def teach_anchors(mc, arm_name):
    """Release servos, let user drag to anchor keys, record positions."""
    # Choose anchor keys based on arm
    if arm_name == "right":
        anchors = ["8", "0", "i", "p", "k", "l", ";", "/"]
    else:
        anchors = ["1", "5", "q", "t", "a", "g", "z", "v"]

    print(f"\n  TEACHING {arm_name.upper()} ARM ANCHOR POINTS")
    print(f"  Keys to teach: {anchors}")
    print(f"  Servos will be released — drag the arm to each key center.")
    print()

    mc.power_on()
    time.sleep(1)
    mc.release_all_servos()
    time.sleep(1)
    mc.set_color(0, 100, 255)
    print("  *** SERVOS RELEASED ***\n")

    taught = {}
    for key in anchors:
        xml_data = XML_KEYS.get(key, {})
        xml_x = xml_data.get("center_x_mm", "?")
        xml_y = xml_data.get("center_y_mm", "?")
        input(f"  Drag to '{key}' (XML: {xml_x}mm, {xml_y}mm) → press ENTER...")
        print(f"  Reading position (hold still 4s)...")
        time.sleep(1)
        coords = read_position_stable(mc)
        if coords:
            taught[key] = coords[:3]
            print(f"  ✓ '{key}' = ({coords[0]:.1f}, {coords[1]:.1f}, {coords[2]:.1f})")
        else:
            print(f"  ⚠ Failed to read position!")

    mc.focus_all_servos()
    time.sleep(0.5)
    mc.set_color(255, 200, 0)
    print(f"\n  Taught {len(taught)} anchors")
    return taught


# ═══════════════════════════════════════════════════════════════
#  PHASE 2: FIT TRANSFORM & PREDICT POSITIONS
# ═══════════════════════════════════════════════════════════════
def fit_transform(anchors, arm_name):
    """Fit affine: XML positions → robot positions using anchor points."""
    A = []
    bx, by, bz = [], [], []
    for key, robot_xyz in anchors.items():
        if key not in XML_KEYS:
            continue
        px = XML_KEYS[key]["center_x_mm"]
        py = XML_KEYS[key]["center_y_mm"]
        A.append([px, py, 1])
        bx.append(robot_xyz[0])
        by.append(robot_xyz[1])
        bz.append(robot_xyz[2])

    if len(A) < 3:
        print("  Not enough anchors!")
        return None

    A = np.array(A, dtype=float)
    mx, _, _, _ = np.linalg.lstsq(A, np.array(bx), rcond=None)
    my, _, _, _ = np.linalg.lstsq(A, np.array(by), rcond=None)
    mz, _, _, _ = np.linalg.lstsq(A, np.array(bz), rcond=None)

    # Verify on anchors
    print(f"\n  Transform fit ({len(A)} points):")
    max_err = 0
    for key, robot_xyz in anchors.items():
        if key not in XML_KEYS:
            continue
        px = XML_KEYS[key]["center_x_mm"]
        py = XML_KEYS[key]["center_y_mm"]
        pred_x = mx[0]*px + mx[1]*py + mx[2]
        pred_y = my[0]*px + my[1]*py + my[2]
        pred_z = mz[0]*px + mz[1]*py + mz[2]
        err = np.sqrt((pred_x-robot_xyz[0])**2 + (pred_y-robot_xyz[1])**2)
        max_err = max(max_err, err)
        mark = "✓" if err < 3 else "⚠"
        print(f"    {mark} '{key}': pred=({pred_x:.1f},{pred_y:.1f}) actual=({robot_xyz[0]:.1f},{robot_xyz[1]:.1f}) err={err:.1f}mm")
    print(f"  Max error: {max_err:.1f}mm")

    return {"mx": mx.tolist(), "my": my.tolist(), "mz": mz.tolist()}


def predict_position(key_name, transform):
    """Predict robot position for a key using the affine transform."""
    if key_name not in XML_KEYS:
        return None
    px = XML_KEYS[key_name]["center_x_mm"]
    py = XML_KEYS[key_name]["center_y_mm"]
    mx, my, mz = transform["mx"], transform["my"], transform["mz"]
    x = mx[0]*px + mx[1]*py + mx[2]
    y = my[0]*px + my[1]*py + my[2]
    z = mz[0]*px + mz[1]*py + mz[2]
    return [round(x, 2), round(y, 2), round(z, 2)]


# ═══════════════════════════════════════════════════════════════
#  PHASE 3: VERIFY & CORRECT VIA STREAM
# ═══════════════════════════════════════════════════════════════
def verify_key(key_name, mc, coords, arm_name):
    """Verify a key by pressing and detecting via stream. Correct if wrong."""
    x, y, z = coords
    consecutive = 0

    for attempt in range(MAX_ATTEMPTS):
        if not (-280 <= x <= 280 and -280 <= y <= 280):
            print(f"    A{attempt+1}: OUT OF REACH ({x:.0f},{y:.0f})")
            return "FAIL_REACH", [x, y, z], attempt + 1

        detected = detect_key_press(mc, x, y, z)
        correct = (detected == key_name)
        if correct:
            consecutive += 1
        else:
            consecutive = 0

        mark = "✓" if correct else "✗"
        det = detected if detected else "(none)"
        print(f"    A{attempt+1}: ({x:.0f},{y:.0f}) → {det} {mark} [{consecutive}/{REQUIRED_CONSECUTIVE}]")

        if consecutive >= REQUIRED_CONSECUTIVE:
            return "PASS", [x, y, z], attempt + 1

        # Correct using XML spacing
        if detected and detected != key_name:
            t = XML_KEYS.get(key_name)
            a_name = {"_": "_", "-": "_"}.get(detected, detected)
            a = XML_KEYS.get(a_name)
            if t and a:
                kb_dx = t["center_x_mm"] - a["center_x_mm"]
                kb_dy = t["center_y_mm"] - a["center_y_mm"]
                if arm_name == "right":
                    x += kb_dx * (-0.83) * 0.7
                    y += kb_dy * 0.90 * 0.7
                else:
                    x += kb_dx * 0.98 * 0.7
                    y += kb_dy * 0.90 * 0.7

                if abs(kb_dx) > 1 and abs(x - coords[0]) < 2:
                    x += 3.0 if kb_dx > 0 else -3.0
                x = max(-280, min(280, x))
                y = max(-280, min(280, y))

    return "FAIL", [x, y, z], MAX_ATTEMPTS


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    arm_name = "right"
    do_verify = "--verify" in sys.argv
    specific_keys = [a for a in sys.argv[1:] if not a.startswith("--")]

    for a in sys.argv[1:]:
        if a == "--arm" and sys.argv.index(a) + 1 < len(sys.argv):
            arm_name = sys.argv[sys.argv.index(a) + 1]

    ip = RIGHT_IP if arm_name == "right" else LEFT_IP

    print("╔═══════════════════════════════════════════════════╗")
    print("║  ANCHOR-BASED CALIBRATION + STREAM VERIFICATION   ║")
    print("╚═══════════════════════════════════════════════════╝")

    # Connect
    print(f"\n  Connecting {arm_name} arm ({ip})...", end="", flush=True)
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
        print(" (servos warming up)")

    if do_verify:
        # Just verify specific keys or all learned keys
        keys_to_verify = specific_keys if specific_keys else sorted(
            k for k in LEARNED if k in XML_KEYS
            and LEARNED[k].get("final")
        )
        print(f"\n  Verifying {len(keys_to_verify)} keys via stream...")
        mc.set_color(255, 165, 0)

        passed = 0
        for i, key in enumerate(keys_to_verify):
            coords = LEARNED[key]["final"]
            print(f"\n  [{i+1}/{len(keys_to_verify)}] Key '{key}'")
            status, final, attempts = verify_key(key, mc, coords, arm_name)
            if status == "PASS":
                passed += 1
                print(f"    ✓ PASSED ({attempts} attempts)")
                mc.set_color(0, 255, 0)
            else:
                print(f"    ✗ {status} ({attempts} attempts)")
                mc.set_color(255, 0, 0)
            time.sleep(0.3)

        print(f"\n  Verified: {passed}/{len(keys_to_verify)} PASS")
    else:
        # PHASE 1: Teach anchors
        anchors = teach_anchors(mc, arm_name)

        if len(anchors) < 3:
            print("Not enough anchors taught!")
            return

        # PHASE 2: Fit transform
        transform = fit_transform(anchors, arm_name)
        if not transform:
            return

        # PHASE 3: Predict & verify all keys
        # Determine which keys this arm handles
        with open(TAUGHT_PATH) as f:
            taught = json.load(f)["keys"]

        arm_keys = sorted([k for k, v in taught.items()
                          if v.get("arm") == arm_name and len(k) == 1 and k in XML_KEYS])

        print(f"\n  Predicting and verifying {len(arm_keys)} keys...")
        mc.set_color(255, 165, 0)

        passed = 0
        failed = 0
        for i, key in enumerate(arm_keys):
            # Use learned position if available, otherwise predict
            if key in LEARNED and LEARNED[key].get("final"):
                coords = LEARNED[key]["final"]
                source = "learned"
            elif key in anchors:
                coords = anchors[key]
                source = "anchor"
            else:
                coords = predict_position(key, transform)
                source = "predicted"

            if coords is None:
                continue
            if not (-280 <= coords[0] <= 280):
                print(f"\n  [{i+1}/{len(arm_keys)}] Key '{key}' — OUT OF REACH (x={coords[0]:.0f})")
                failed += 1
                continue

            print(f"\n  [{i+1}/{len(arm_keys)}] Key '{key}' ({source}: {coords[0]:.0f},{coords[1]:.0f},{coords[2]:.0f})")
            status, final, attempts = verify_key(key, mc, coords, arm_name)

            if status == "PASS":
                passed += 1
                orig = taught[key]["coords"][:3]
                LEARNED[key] = {
                    "dx": round(final[0] - orig[0], 2),
                    "dy": round(final[1] - orig[1], 2),
                    "dz": 0,
                    "final": [round(c, 2) for c in final],
                    "attempts_needed": attempts,
                }
                save_learned()
                print(f"    ✓ PASSED ({attempts} attempts)")
                mc.set_color(0, 255, 0)
            else:
                failed += 1
                print(f"    ✗ {status} ({attempts} attempts)")
                mc.set_color(255, 0, 0)
            time.sleep(0.3)

        print(f"\n{'═'*50}")
        print(f"  {arm_name.upper()} ARM: {passed} PASS / {failed} FAIL / {len(arm_keys)} total")
        print(f"  Total learned: {len(LEARNED)} keys")
        print(f"{'═'*50}")

    # Home
    mc.send_angles([0, 0, 0, 0, 0, 0], 15)
    time.sleep(3)
    mc.set_color(255, 255, 255)
    print("Done!")


if __name__ == "__main__":
    main()
