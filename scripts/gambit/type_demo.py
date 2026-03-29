"""
Type + Touchpad demo on the DUT with dual arms + 3-camera recording.
Supports key presses, space, and touchpad swipe gestures.

Special commands in text:
  {SPACE}       - press spacebar
  {SWIPE_UP}    - swipe up on touchpad
  {SWIPE_DOWN}  - swipe down on touchpad
  {TAP}         - tap center of touchpad

Usage: python type_demo.py "ZAQPLM,QPAL {SPACE} {SWIPE_UP}"
"""
import sys
import json
import time
import os
import re
import socket
import threading
import datetime
import cv2
import numpy as np
from PIL import Image
import imageio
import httpx
from pymycobot import MyCobot280Socket

TEXT = sys.argv[1] if len(sys.argv) > 1 else "ZAQPLM,QPAL"
RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000
GAMBIT_HOST = "192.168.0.4"
GAMBIT_PORT = 22133

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
GIF_NAME = f"type_demo_{TIMESTAMP}.gif"

HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3

# Touchpad: from XML, offset from keyboard top-left = (84mm, 110mm), size = 111x90mm
TP_KB_OFFSET_X = 84.0
TP_KB_OFFSET_Y = 110.0
TP_WIDTH = 111.0
TP_HEIGHT = 90.0

# Load key positions
with open(os.path.join(DATA_DIR, "keyboard_taught.json")) as f:
    TAUGHT = json.load(f)["keys"]
LEARNED = {}
corr_path = os.path.join(DATA_DIR, "learned_corrections.json")
if os.path.exists(corr_path):
    with open(corr_path) as f:
        LEARNED = json.load(f)

# Camera map
with open(os.path.join(DATA_DIR, "camera_map.json")) as f:
    cm = json.load(f)
FLIP_CAMS = set(cm.get("flip_cameras", []))
CAM_INDICES = []
for cid, info in cm.get("cameras", {}).items():
    if info.get("role") != "skip" and info.get("type") == "usb":
        CAM_INDICES.append(int(cid))

# ── Cameras (persistent, 3 views) ──
caps = {}


def init_cameras():
    for idx in CAM_INDICES:
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BRIGHTNESS, 150)
            for _ in range(10):
                cap.grab()
            ret, f = cap.read()
            if ret:
                caps[idx] = cap
                print(f"  Cam {idx}: OK")
            else:
                cap.release()


def capture_3view(label=""):
    tiles = []
    for idx in sorted(caps.keys()):
        cap = caps[idx]
        ret, f = cap.read()
        if ret and f is not None:
            if idx in FLIP_CAMS:
                f = cv2.rotate(f, cv2.ROTATE_180)
            # Gamma brighten
            gamma = 1.3
            table = np.array([((i / 255.0) ** (1.0 / gamma)) * 255
                             for i in np.arange(256)]).astype("uint8")
            f = cv2.LUT(f, table)
            f = cv2.resize(f, (427, 320))
            tiles.append(f)
    if not tiles:
        return None
    while len(tiles) < 3:
        tiles.append(np.zeros((320, 427, 3), dtype=np.uint8))
    canvas = np.hstack(tiles[:3])
    if label:
        cv2.putText(canvas, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 100), 2)
    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))


def release_cameras():
    for cap in caps.values():
        cap.release()
    caps.clear()


# ── Key position ──
def get_pos(key_name):
    k = key_name.lower()
    if k == " ":
        k = "space"
    if k not in TAUGHT:
        return None, None
    data = TAUGHT[k]
    coords = list(data["coords"][:3])
    arm = data.get("arm", "right")
    if k in LEARNED:
        coords[0] += LEARNED[k].get("dx", 0)
        coords[1] += LEARNED[k].get("dy", 0)
    return coords, arm


def compute_touchpad_pos():
    """Compute touchpad center in robot coords using learned key positions."""
    with open(os.path.join(DATA_DIR, "keyboard_layout_xml.json")) as f:
        xml_keys = json.load(f)["keys"]

    pairs = []
    for k, v in LEARNED.items():
        if v.get("final") and k in xml_keys:
            pairs.append((v["final"][0], v["final"][1],
                          xml_keys[k]["center_x_mm"], xml_keys[k]["center_y_mm"]))
    if len(pairs) < 3:
        return None, None, None

    # Fit inverse: xml_mm → robot
    A = np.array([[p[2], p[3], 1] for p in pairs])
    bx = np.array([p[0] for p in pairs])
    by = np.array([p[1] for p in pairs])
    mx, _, _, _ = np.linalg.lstsq(A, bx, rcond=None)
    my, _, _, _ = np.linalg.lstsq(A, by, rcond=None)

    # Touchpad center in keyboard mm
    tp_cx = TP_KB_OFFSET_X + TP_WIDTH / 2
    tp_cy = TP_KB_OFFSET_Y + TP_HEIGHT / 2

    robot_x = mx[0]*tp_cx + mx[1]*tp_cy + mx[2]
    robot_y = my[0]*tp_cx + my[1]*tp_cy + my[2]

    # Z: average of learned keys
    z_vals = [v["final"][2] for v in LEARNED.values() if v.get("final")]
    robot_z = np.mean(z_vals) if z_vals else 60.0

    return round(robot_x, 1), round(robot_y, 1), round(robot_z, 1)


def swipe_touchpad(mc, direction, tp_x, tp_y, tp_z, frames_list, capture_fn):
    """Perform a touchpad swipe gesture."""
    hover_z = tp_z + HOVER_Z_OFFSET
    touch_z = tp_z - PRESS_Z_OFFSET
    swipe_dist = 20.0  # mm

    # Compute swipe start/end
    if direction == "up":
        sx, sy = tp_x, tp_y + swipe_dist/2
        ex, ey = tp_x, tp_y - swipe_dist/2
    elif direction == "down":
        sx, sy = tp_x, tp_y - swipe_dist/2
        ex, ey = tp_x, tp_y + swipe_dist/2
    elif direction == "left":
        sx, sy = tp_x + swipe_dist/2, tp_y
        ex, ey = tp_x - swipe_dist/2, tp_y
    elif direction == "right":
        sx, sy = tp_x - swipe_dist/2, tp_y
        ex, ey = tp_x + swipe_dist/2, tp_y
    else:
        return

    # Move to start
    mc.send_coords([sx, sy, hover_z, 0, 180, 90], 15, 0)
    time.sleep(1.0)
    frame = capture_fn(f"Touchpad: swipe {direction}")
    if frame:
        frames_list.append(frame)

    # Touch down
    mc.send_coords([sx, sy, touch_z, 0, 180, 90], 8, 0)
    time.sleep(0.4)
    frame = capture_fn(f"Swiping {direction}...")
    if frame:
        frames_list.append(frame)

    # Swipe
    mc.send_coords([ex, ey, touch_z, 0, 180, 90], 5, 0)
    time.sleep(0.8)
    frame = capture_fn(f"Swiping {direction}...")
    if frame:
        frames_list.append(frame)

    # Lift
    mc.send_coords([ex, ey, hover_z, 0, 180, 90], 10, 0)
    time.sleep(0.5)
    frame = capture_fn(f"Swipe {direction} done")
    if frame:
        frames_list.append(frame)


def get_cursor():
    try:
        r = httpx.get(f"http://{GAMBIT_HOST}:{GAMBIT_PORT}/streams/cursor/current", timeout=5)
        return r.json()
    except:
        return None


# ── VK name mapping for stream validation ──
VK_TO_KEY = {}
for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    VK_TO_KEY[c] = c.lower()
for d in range(10):
    VK_TO_KEY[f"D{d}"] = str(d)
    VK_TO_KEY[f"VK_{d}"] = str(d)
VK_TO_KEY.update({
    "OEM_1": ";", "Oem1": ";", "OemSemicolon": ";",
    "OEM_2": "/", "Oem2": "/", "OemQuestion": "/",
    "OEM_3": "`", "Oem3": "`", "Oemtilde": "`",
    "OEM_4": "[", "Oem4": "[",
    "OEM_5": "\\", "Oem5": "\\",
    "OEM_6": "]", "Oem6": "]",
    "OEM_7": "'", "Oem7": "'",
    "OEM_PLUS": "=", "Oemplus": "=",
    "OEM_COMMA": ",", "Oemcomma": ",",
    "OEM_MINUS": "_", "OemMinus": "_",
    "OEM_PERIOD": ".", "OemPeriod": ".",
    "SPACE": "space", "Space": "space",
    "RETURN": "enter", "Return": "enter",
})
# Add uppercase versions
for k, v in list(VK_TO_KEY.items()):
    VK_TO_KEY[k.upper()] = v


# ── Persistent keyboard stream listener ──
class KeyboardListener:
    def __init__(self):
        self.sock = None
        self.thread = None
        self.events = []
        self.running = False
        self.header_done = False
        self.lock = threading.Lock()

    def start(self):
        self.running = True
        self.header_done = False
        self.events.clear()
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()
        time.sleep(1)

    def stop(self):
        self.running = False
        if self.sock:
            try: self.sock.shutdown(socket.SHUT_RDWR)
            except: pass
            try: self.sock.close()
            except: pass
        self.sock = None

    def clear(self):
        with self.lock:
            self.events.clear()

    def get_first_key(self):
        with self.lock:
            for vk in self.events:
                if vk in VK_TO_KEY:
                    return VK_TO_KEY[vk]
            return None

    def _listen(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((GAMBIT_HOST, GAMBIT_PORT))
            req = f"GET /streams/keyboard HTTP/1.1\r\nHost: {GAMBIT_HOST}:{GAMBIT_PORT}\r\nAccept: */*\r\n\r\n"
            self.sock.sendall(req.encode())
            self.sock.settimeout(1)
            while self.running:
                try:
                    data = self.sock.recv(8192)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    if not self.header_done:
                        if "\r\n\r\n" in text:
                            text = text.split("\r\n\r\n", 1)[1]
                            self.header_done = True
                        else:
                            continue
                    if "Unable to add consumer" in text:
                        self.running = False
                        break
                    for m in re.finditer(r'"Key"\s*:\s*"([A-Za-z][A-Za-z0-9_]*)"', text):
                        vk = m.group(1)
                        if vk in VK_TO_KEY:
                            with self.lock:
                                self.events.append(vk)
                except socket.timeout:
                    pass
        except:
            pass
        self.running = False


kb_listener = KeyboardListener()


# ── Main ──
print("╔═══════════════════════════════════════════╗")
print(f"║  TYPING + TOUCHPAD DEMO")
print(f"║  Input: \"{TEXT}\"")
print("╚═══════════════════════════════════════════╝")

# Parse input into actions: regular chars + special commands
actions = []
i = 0
while i < len(TEXT):
    if TEXT[i] == '{':
        end = TEXT.find('}', i)
        if end > i:
            cmd = TEXT[i+1:end].upper()
            actions.append(("cmd", cmd))
            i = end + 1
            continue
    elif TEXT[i] == ' ':
        actions.append(("key", "space"))
    else:
        actions.append(("key", TEXT[i]))
    i += 1

print(f"  Actions: {len(actions)}")
for a in actions:
    print(f"    {a[0]}: {a[1]}")

# Connect arms
print("\nConnecting arms...")
mc_r = MyCobot280Socket(RIGHT_IP, PORT)
time.sleep(1)
mc_r.power_on()
time.sleep(1)
try:
    mc_l = MyCobot280Socket(LEFT_IP, PORT)
    time.sleep(1)
    mc_l.power_on()
    time.sleep(1)
    print("  Both arms connected")
except:
    mc_l = None
    print("  Right arm only")

# Init cameras
print("\nInitializing cameras...")
init_cameras()
print(f"  {len(caps)} cameras ready")

# Record
# Start keyboard stream for validation
print("\\n  Starting Gambit keyboard stream...", end="", flush=True)
kb_listener.start()
time.sleep(2)  # give stream time to fully establish
if kb_listener.running:
    print(" OK")
else:
    print(" FAILED (validation disabled)")

# Compute touchpad position
tp_x, tp_y, tp_z = compute_touchpad_pos()
if tp_x:
    print(f"  Touchpad predicted at: ({tp_x}, {tp_y}, {tp_z})")
else:
    print(f"  Touchpad position: could not compute")

# Record
frames = []
typed = ""

print(f"\nExecuting {len(actions)} actions...")
for i, (action_type, action_val) in enumerate(actions):
    if action_type == "key":
        ch = action_val
        coords, arm = get_pos(ch)
        if coords is None:
            print(f"  [{i+1}] '{ch}' — unknown key, skipping")
            typed += ch if ch != "space" else " "
            continue

        mc = mc_l if arm == "left" and mc_l else mc_r
        x, y, z = coords
        x = max(-280, min(280, x))
        y = max(-280, min(280, y))
        hover_z = z + HOVER_Z_OFFSET
        press_z = z - PRESS_Z_OFFSET
        display_ch = ch if ch != "space" else "SPACE"

        frame = capture_3view(f"Typing: {typed}|{display_ch}")
        if frame:
            frames.append(frame)

        mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
        time.sleep(1.0)

        # Clear stream RIGHT before pressing — ensures no stale events from previous key
        kb_listener.clear()

        frame = capture_3view(f"Press: '{display_ch}' [{arm}]")
        if frame:
            frames.append(frame)

        mc.send_coords([x, y, press_z, 0, 180, 90], 10, 0)
        time.sleep(0.5)

        frame = capture_3view(f">>> '{display_ch}' <<<")
        if frame:
            frames.append(frame)

        mc.send_coords([x, y, hover_z, 0, 180, 90], 10, 0)
        time.sleep(0.8)

        # Validate via Gambit stream — wait for events to arrive
        for _ in range(10):
            detected = kb_listener.get_first_key()
            if detected:
                break
            time.sleep(0.1)

        expected = ch.lower() if ch != "space" else "space"
        if detected:
            if detected == expected:
                verify = "✓ VERIFIED"
            else:
                verify = f"⚠ got '{detected}'"
        else:
            verify = "? no stream"

        typed += ch if ch != "space" else " "
        print(f"  [{i+1}/{len(actions)}] KEY '{display_ch}' ({arm})  {verify}")

        frame = capture_3view(f"Typed: {typed[-30:]}  {verify}")
        if frame:
            frames.append(frame)

    elif action_type == "cmd":
        cmd = action_val
        if cmd.startswith("SWIPE_"):
            direction = cmd.split("_")[1].lower()
            if tp_x is None:
                print(f"  [{i+1}] SWIPE {direction} — no touchpad position!")
                continue

            mc = mc_r  # use right arm for touchpad (closer)
            mc.set_color(0, 255, 255)

            # Get cursor before
            cur_before = get_cursor()
            if cur_before:
                print(f"    Cursor before: ({cur_before.get('X')}, {cur_before.get('Y')})")

            print(f"  [{i+1}/{len(actions)}] TOUCHPAD SWIPE {direction}")
            swipe_touchpad(mc, direction, tp_x, tp_y, tp_z, frames, capture_3view)

            # Get cursor after
            time.sleep(0.5)
            cur_after = get_cursor()
            if cur_after:
                print(f"    Cursor after: ({cur_after.get('X')}, {cur_after.get('Y')})")
                if cur_before:
                    dx = cur_after["X"] - cur_before["X"]
                    dy = cur_after["Y"] - cur_before["Y"]
                    print(f"    Movement: dx={dx}, dy={dy}")

            mc.set_color(255, 255, 255)

        elif cmd == "TAP":
            if tp_x is None:
                print(f"  [{i+1}] TAP — no touchpad position!")
                continue
            mc = mc_r
            mc.set_color(0, 255, 255)
            hover_z = tp_z + HOVER_Z_OFFSET
            press_z = tp_z - PRESS_Z_OFFSET
            mc.send_coords([tp_x, tp_y, hover_z, 0, 180, 90], 15, 0)
            time.sleep(1.0)
            frame = capture_3view("Touchpad: TAP")
            if frame: frames.append(frame)
            mc.send_coords([tp_x, tp_y, press_z, 0, 180, 90], 8, 0)
            time.sleep(0.3)
            mc.send_coords([tp_x, tp_y, hover_z, 0, 180, 90], 8, 0)
            time.sleep(0.5)
            frame = capture_3view("Touchpad: TAP done")
            if frame: frames.append(frame)
            print(f"  [{i+1}/{len(actions)}] TOUCHPAD TAP ✓")
            mc.set_color(255, 255, 255)

        elif cmd == "SPACE":
            # Treat as space key
            coords, arm = get_pos("space")
            if coords:
                mc = mc_l if arm == "left" and mc_l else mc_r
                x, y, z = coords
                hover_z = z + HOVER_Z_OFFSET
                press_z = z - PRESS_Z_OFFSET
                mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
                time.sleep(1.0)
                mc.send_coords([x, y, press_z, 0, 180, 90], 10, 0)
                time.sleep(0.5)
                mc.send_coords([x, y, hover_z, 0, 180, 90], 10, 0)
                time.sleep(0.5)
                typed += " "
                print(f"  [{i+1}/{len(actions)}] SPACE ✓")
                frame = capture_3view(f"Typed: {typed[-30:]}")
                if frame: frames.append(frame)
            else:
                print(f"  [{i+1}] SPACE — no position!")

        else:
            print(f"  [{i+1}] Unknown command: {cmd}")

# Final frames
time.sleep(1)
for _ in range(5):
    frame = capture_3view(f"DONE: \"{typed}\"")
    if frame:
        frames.append(frame)
    time.sleep(0.1)

# Stop stream
kb_listener.stop()
time.sleep(0.5)

# Home
for mc in [mc_r, mc_l]:
    if mc:
        mc.send_angles([0, 0, 0, 0, 0, 0], 15)
        mc.set_color(255, 255, 255)
time.sleep(2)

# Save GIF with unique timestamped name
release_cameras()
if frames:
    gif_path = os.path.join(OUTPUT_DIR, GIF_NAME)
    images = [np.array(f) for f in frames]
    imageio.mimsave(gif_path, images, duration=0.12, loop=0)
    print(f"\n  GIF saved: {gif_path} ({len(frames)} frames)")

print(f"\n  Typed: \"{typed}\"")
print("Done!")
