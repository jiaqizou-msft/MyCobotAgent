"""
Quick Calibration: Annotate Anchors → 3-Point Robot Teaching → Stream Verify All
=================================================================================
Uses the camera annotation (78 keys with mm positions) + 3 robot anchor points
per arm to compute the full mm→robot transform, then verifies every key via
Gambit HID keyboard stream.

Flow:
  1. Load annotated key positions from keyboard_vision_detected.json
  2. For each arm: release servos, teach 3 anchor keys by dragging
  3. Fit affine: mm → robot coordinates (from 3 anchors)
  4. Predict all key positions for that arm
  5. Press each key, verify via /streams/keyboard, correct if wrong
  6. Save all learned corrections

Usage:
  python quick_calibrate.py                   # full flow (teach + verify)
  python quick_calibrate.py --verify-only     # skip teaching, use existing data
  python quick_calibrate.py --right-only      # only right arm
  python quick_calibrate.py --left-only       # only left arm
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
VISION_PATH = os.path.join(DATA_DIR, "keyboard_vision_detected.json")
XML_LAYOUT_PATH = os.path.join(DATA_DIR, "keyboard_layout_xml.json")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
CORRECTIONS_PATH = os.path.join(DATA_DIR, "learned_corrections.json")

HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SPEED_SLIDE = 20
SPEED_PRESS = 10
REQUIRED_CONSECUTIVE = 3
MAX_ATTEMPTS = 12

# VK → key name (Gambit uses mixed case: "Space", "OEM_1", "A", etc.)
def _build_vk_map():
    base = {
        "A":"a","B":"b","C":"c","D":"d","E":"e","F":"f","G":"g","H":"h",
        "I":"i","J":"j","K":"k","L":"l","M":"m","N":"n","O":"o","P":"p",
        "Q":"q","R":"r","S":"s","T":"t","U":"u","V":"v","W":"w","X":"x",
        "Y":"y","Z":"z",
        "VK_0":"0","VK_1":"1","VK_2":"2","VK_3":"3","VK_4":"4",
        "VK_5":"5","VK_6":"6","VK_7":"7","VK_8":"8","VK_9":"9",
        "OEM_1":";","OEM_2":"/","OEM_3":"`","OEM_4":"[","OEM_5":"\\",
        "OEM_6":"]","OEM_7":"'","OEM_PLUS":"=","OEM_COMMA":",",
        "OEM_MINUS":"_","OEM_PERIOD":".",
        "SPACE":"space","Space":"space",
        "RETURN":"enter","Return":"enter",
        "TAB":"tab","Tab":"tab",
        "BACK":"backspace","Back":"backspace",
        "ESCAPE":"esc","Escape":"esc",
        "DELETE":"del","Delete":"del",
        "CAPITAL":"caps","Capital":"caps",
        "LSHIFT":"shift_l","LShiftKey":"shift_l",
        "RSHIFT":"shift_r","RShiftKey":"shift_r",
        "LCONTROL":"ctrl_l","LControlKey":"ctrl_l",
        "LMENU":"alt_l","LMenu":"alt_l",
        "RMENU":"alt_r","RMenu":"alt_r",
        "LWIN":"win","LWin":"win",
        "LEFT":"left","Left":"left",
        "RIGHT":"right","Right":"right",
        "UP":"up","Up":"up",
        "DOWN":"down","Down":"down",
        "F1":"f1","F2":"f2","F3":"f3","F4":"f4","F5":"f5","F6":"f6",
        "F7":"f7","F8":"f8","F9":"f9","F10":"f10","F11":"f11","F12":"f12",
        "Oem1":";","Oem2":"/","Oem3":"`","Oem4":"[",
        "Oem5":"\\","Oem6":"]","Oem7":"'",
        "Oemplus":"=","OemMinus":"_","Oemcomma":",","OemPeriod":".",
        "Oem102":"\\",
        "Oemtilde":"`",
        "OemSemicolon":";","OemQuotes":"'",
        "OemOpenBrackets":"[","OemCloseBrackets":"]",
        "OemPipe":"\\","OemQuestion":"/",
        "D0":"0","D1":"1","D2":"2","D3":"3","D4":"4",
        "D5":"5","D6":"6","D7":"7","D8":"8","D9":"9",
    }
    # Also add uppercase versions
    extra = {}
    for k, v in base.items():
        extra[k.upper()] = v
    base.update(extra)
    return base

VK_TO_KEY = _build_vk_map()

# Load data
with open(VISION_PATH) as f:
    VISION = json.load(f)
DETECTED_KEYS = VISION["detected_keys"]

with open(XML_LAYOUT_PATH) as f:
    XML_KEYS = json.load(f)["keys"]

with open(TAUGHT_PATH) as f:
    TAUGHT = json.load(f)["keys"]

LEARNED = {}
if os.path.exists(CORRECTIONS_PATH):
    with open(CORRECTIONS_PATH) as f:
        LEARNED = json.load(f)


def save_learned():
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(LEARNED, f, indent=2)


# ═══════════════════════════════════════════════════════════════
#  GAMBIT KEYBOARD STREAM — single persistent connection
# ═══════════════════════════════════════════════════════════════
class KeyboardListener:
    """Persistent keyboard stream listener. One consumer, reused for all keys."""

    def __init__(self):
        self.sock = None
        self.thread = None
        self.events = []
        self.running = False
        self.header_done = False
        self.lock = threading.Lock()

    def start(self):
        """Open the keyboard stream. Call once at startup."""
        self.running = True
        self.header_done = False
        self.events.clear()
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()
        # Wait for connection
        time.sleep(1)
        if not self.running:
            print("    ⚠ Stream failed to connect")

    def stop(self):
        """Close the stream. Call once at shutdown."""
        self.running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                self.sock.close()
            except:
                pass
        self.sock = None

    def clear(self):
        """Clear captured events before a new key press."""
        with self.lock:
            self.events.clear()

    def get_first_key(self):
        """Return the first detected key name, or None."""
        with self.lock:
            for evt in self.events:
                if evt in VK_TO_KEY:
                    return VK_TO_KEY[evt]
            return None

    def _listen(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((GAMBIT_HOST, GAMBIT_PORT))
            req = (f"GET /streams/keyboard HTTP/1.1\r\n"
                   f"Host: {GAMBIT_HOST}:{GAMBIT_PORT}\r\n"
                   f"Accept: */*\r\n\r\n")
            self.sock.sendall(req.encode())
            print("    Stream connected")
            self.sock.settimeout(1)

            while self.running:
                try:
                    data = self.sock.recv(8192)
                    if not data:
                        print("    [stream] connection closed")
                        break
                    text = data.decode("utf-8", errors="replace")

                    # Skip HTTP headers on first chunk
                    if not self.header_done:
                        if "\r\n\r\n" in text:
                            text = text.split("\r\n\r\n", 1)[1]
                            self.header_done = True
                        else:
                            continue

                    # Check for error
                    if "Unable to add consumer" in text:
                        print("    ⚠ Stream busy — another consumer connected")
                        self.running = False
                        break

                    # Extract VK key names
                    for m in re.finditer(r'"Key"\s*:\s*"([A-Za-z][A-Za-z0-9_]*)"', text):
                        vk = m.group(1)
                        if vk in VK_TO_KEY:
                            with self.lock:
                                self.events.append(vk)
                except socket.timeout:
                    pass
        except Exception as e:
            print(f"    Stream error: {e}")
        self.running = False


# Global listener instance
kb_listener = KeyboardListener()


def press_and_detect(mc, x, y, z):
    """Press key and return what the stream detected."""
    # Clear previous events
    kb_listener.clear()

    # Press
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

    # Wait for stream to process events
    time.sleep(1.0)

    # Read detected key — try a few times
    for _ in range(5):
        result = kb_listener.get_first_key()
        if result:
            return result
        time.sleep(0.3)

    return None


# ═══════════════════════════════════════════════════════════════
#  ROBOT HELPERS
# ═══════════════════════════════════════════════════════════════
def read_stable(mc):
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
#  PHASE 1: TEACH 3 ANCHORS PER ARM
# ═══════════════════════════════════════════════════════════════
def teach_arm_anchors(mc, arm_name):
    """Release servos, user drags to 3 keys. Returns {key: [x,y,z]}."""
    if arm_name == "right":
        anchors = ["k", "0", "/"]  # home row, number row, bottom row
    else:
        anchors = ["a", "5", "z"]  # home row, number row, bottom row

    print(f"\n  ═══ TEACHING {arm_name.upper()} ARM (3 anchors) ═══")
    print(f"  Keys: {anchors}")
    print(f"  Servos releasing — drag arm to key CENTER, press Enter.\n")

    mc.power_on()
    time.sleep(1)
    mc.release_all_servos()
    time.sleep(1)
    mc.set_color(0, 100, 255)

    taught = {}
    for key in anchors:
        mm = DETECTED_KEYS.get(key, {}).get("mm", [0, 0])
        input(f"  → Drag to '{key}' (mm: {mm[0]:.1f}, {mm[1]:.1f}) then ENTER...")
        print(f"    Reading (hold still 4s)...", end="", flush=True)
        time.sleep(1)
        coords = read_stable(mc)
        if coords:
            taught[key] = coords[:3]
            print(f" ({coords[0]:.1f}, {coords[1]:.1f}, {coords[2]:.1f}) ✓")
        else:
            print(f" FAILED ✗")

    mc.focus_all_servos()
    time.sleep(0.5)
    mc.set_color(255, 200, 0)
    return taught


# ═══════════════════════════════════════════════════════════════
#  PHASE 2: FIT TRANSFORM (mm → robot)
# ═══════════════════════════════════════════════════════════════
def fit_mm_to_robot(anchors):
    """Fit affine: XML mm position → robot XYZ from 3+ anchor points."""
    A, bx, by, bz = [], [], [], []
    for key, robot_xyz in anchors.items():
        mm = DETECTED_KEYS.get(key, {}).get("mm")
        if mm is None:
            continue
        A.append([mm[0], mm[1], 1])
        bx.append(robot_xyz[0])
        by.append(robot_xyz[1])
        bz.append(robot_xyz[2])

    if len(A) < 3:
        return None

    A = np.array(A, dtype=float)
    mx, _, _, _ = np.linalg.lstsq(A, np.array(bx), rcond=None)
    my, _, _, _ = np.linalg.lstsq(A, np.array(by), rcond=None)
    mz, _, _, _ = np.linalg.lstsq(A, np.array(bz), rcond=None)

    # Verify
    print(f"\n  Transform fit ({len(A)} points):")
    for key, robot_xyz in anchors.items():
        mm = DETECTED_KEYS[key]["mm"]
        px = mx[0]*mm[0] + mx[1]*mm[1] + mx[2]
        py = my[0]*mm[0] + my[1]*mm[1] + my[2]
        err = np.sqrt((px-robot_xyz[0])**2 + (py-robot_xyz[1])**2)
        print(f"    '{key}': err={err:.1f}mm")

    return {"mx": mx.tolist(), "my": my.tolist(), "mz": mz.tolist()}


def predict_key(key_name, transform):
    """Predict robot position for a key from its mm position."""
    mm = DETECTED_KEYS.get(key_name, {}).get("mm")
    if mm is None:
        return None
    mx, my, mz = transform["mx"], transform["my"], transform["mz"]
    x = mx[0]*mm[0] + mx[1]*mm[1] + mx[2]
    y = my[0]*mm[0] + my[1]*mm[1] + my[2]
    z = mz[0]*mm[0] + mz[1]*mm[1] + mz[2]
    return [round(x, 2), round(y, 2), round(z, 2)]


# ═══════════════════════════════════════════════════════════════
#  PHASE 3: VERIFY ALL KEYS VIA STREAM
# ═══════════════════════════════════════════════════════════════
def verify_key(key_name, mc, coords, arm_name):
    """Press key, verify via stream, correct iteratively."""
    x, y, z = coords
    consecutive = 0

    for attempt in range(MAX_ATTEMPTS):
        if not (-280 <= x <= 280 and -280 <= y <= 280):
            print(f"      A{attempt+1}: OUT OF REACH ({x:.0f},{y:.0f})")
            return "FAIL_REACH", [x, y, z], attempt + 1

        detected = press_and_detect(mc, x, y, z)
        correct = (detected == key_name)
        if correct:
            consecutive += 1
        else:
            consecutive = 0

        mark = "✓" if correct else "✗"
        det = detected if detected else "(none)"
        print(f"      A{attempt+1}: ({x:.0f},{y:.0f}) → {det} {mark} [{consecutive}/{REQUIRED_CONSECUTIVE}]")

        if consecutive >= REQUIRED_CONSECUTIVE:
            return "PASS", [x, y, z], attempt + 1

        # Correct using XML spacing
        if detected and detected != key_name:
            char_map = {"-": "_"}
            t = XML_KEYS.get(key_name)
            a = XML_KEYS.get(char_map.get(detected, detected))
            if t and a:
                kb_dx = t["center_x_mm"] - a["center_x_mm"]
                kb_dy = t["center_y_mm"] - a["center_y_mm"]
                if arm_name == "right":
                    x += kb_dx * (-0.83) * 0.7
                    y += kb_dy * 0.90 * 0.7
                else:
                    x += kb_dx * 0.98 * 0.7
                    y += kb_dy * 0.90 * 0.7
                if abs(kb_dx) > 1 and abs(kb_dx * 0.83 * 0.7) < 3:
                    x += 3.0 if (kb_dx * (-0.83 if arm_name == "right" else 0.98)) > 0 else -3.0
                x = max(-280, min(280, x))
                y = max(-280, min(280, y))

    return "FAIL", [x, y, z], MAX_ATTEMPTS


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    verify_only = "--verify-only" in sys.argv
    right_only = "--right-only" in sys.argv
    left_only = "--left-only" in sys.argv

    print("╔═══════════════════════════════════════════════════════╗")
    print("║  QUICK CALIBRATION: Annotate → 3-Point → Stream      ║")
    print("║  78 keys detected from camera annotation              ║")
    print("╚═══════════════════════════════════════════════════════╝")
    print(f"  Annotated keys: {len(DETECTED_KEYS)}")
    print(f"  Already learned: {len(LEARNED)}")

    arms = []
    if not left_only:
        arms.append(("right", RIGHT_IP))
    if not right_only:
        arms.append(("left", LEFT_IP))

    for arm_name, ip in arms:
        print(f"\n{'═'*55}")
        print(f"  {arm_name.upper()} ARM ({ip})")
        print(f"{'═'*55}")

        # Connect
        print(f"  Connecting...", end="", flush=True)
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
                print(f" (warming up)")
        except Exception as e:
            print(f" FAILED ({e})")
            continue

        # Determine which keys belong to this arm
        arm_keys = sorted([k for k, v in TAUGHT.items()
                          if v.get("arm") == arm_name and len(k) == 1
                          and k in DETECTED_KEYS and k in XML_KEYS])
        print(f"  Keys for this arm: {len(arm_keys)}")

        transform = None
        if not verify_only:
            # PHASE 1: Teach 3 anchors
            anchors = teach_arm_anchors(mc, arm_name)
            if len(anchors) < 3:
                print("  Not enough anchors! Skipping arm.")
                continue

            # PHASE 2: Fit transform
            transform = fit_mm_to_robot(anchors)
            if not transform:
                print("  Transform fit failed!")
                continue

        # PHASE 3: Verify all keys
        # Start keyboard stream (one connection for entire arm)
        print(f"\n  Starting keyboard stream...", end="", flush=True)
        kb_listener.start()
        if not kb_listener.running:
            print(" FAILED — skipping verification")
            continue

        print(f"\n  ═══ VERIFYING {len(arm_keys)} KEYS ═══")
        mc.set_color(255, 165, 0)

        passed = 0
        failed = 0
        for i, key in enumerate(arm_keys):
            # Get position: learned > predicted > taught
            if key in LEARNED and LEARNED[key].get("final"):
                coords = LEARNED[key]["final"]
                src = "learned"
            elif transform:
                coords = predict_key(key, transform)
                src = "predicted"
            else:
                c = list(TAUGHT[key]["coords"][:3])
                if key in LEARNED:
                    c[0] += LEARNED[key].get("dx", 0)
                    c[1] += LEARNED[key].get("dy", 0)
                coords = c
                src = "taught"

            if coords is None or not (-280 <= coords[0] <= 280):
                print(f"\n    [{i+1}/{len(arm_keys)}] '{key}' — SKIP (out of reach)")
                failed += 1
                continue

            print(f"\n    [{i+1}/{len(arm_keys)}] '{key}' ({src})")
            status, final, attempts = verify_key(key, mc, coords, arm_name)

            if status == "PASS":
                passed += 1
                orig = TAUGHT[key]["coords"][:3]
                LEARNED[key] = {
                    "dx": round(final[0] - orig[0], 2),
                    "dy": round(final[1] - orig[1], 2),
                    "dz": 0,
                    "final": [round(c, 2) for c in final],
                    "attempts_needed": attempts,
                }
                save_learned()
                print(f"      ✓ PASSED ({attempts} attempts)")
                mc.set_color(0, 255, 0)
            else:
                failed += 1
                print(f"      ✗ {status} ({attempts} attempts)")
                mc.set_color(255, 0, 0)

        print(f"\n  {arm_name.upper()}: {passed} PASS / {failed} FAIL / {len(arm_keys)} total")

        # Stop keyboard stream before switching arms or finishing
        kb_listener.stop()
        time.sleep(1)

        # Home
        mc.send_angles([0, 0, 0, 0, 0, 0], 15)
        time.sleep(3)
        mc.set_color(255, 255, 255)

    # Final summary
    print(f"\n{'═'*55}")
    print(f"  TOTAL LEARNED: {len(LEARNED)} keys")
    print(f"{'═'*55}")
    print("Done!")


if __name__ == "__main__":
    main()
