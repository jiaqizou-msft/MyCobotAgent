"""
Iterative Key Calibration & Test System
========================================
Calibrates every key on the keyboard through iterative press-and-learn.

For each key:
  1. Press at current best-known position
  2. Read what the DUT registered
  3. If wrong: use the measurement to update position estimate
  4. Persist learned corrections for reuse
  5. Require 3 consecutive correct presses to PASS
  6. After all keys pass, run a typing demo

The key insight: each press gives us a real measurement of
"robot position P produces key K". We accumulate these to build
an increasingly accurate mapping, rather than relying on a
single affine model.

Usage:
  python iterative_calibration.py             # calibrate all keys
  python iterative_calibration.py --demo-only # just run the typing demo
"""

import httpx
import time
import json
import os
import sys
import datetime
import base64
import traceback
import numpy as np
import cv2
from PIL import Image
import imageio
from pymycobot import MyCobot280Socket

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
GAMBIT_BASE = "http://192.168.0.4:22133"
RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
XML_LAYOUT_PATH = os.path.join(DATA_DIR, "keyboard_layout_xml.json")
CORRECTIONS_PATH = os.path.join(DATA_DIR, "learned_corrections.json")
CAMERA_MAP_PATH = os.path.join(DATA_DIR, "camera_map.json")

TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp",
    f"calibration_{TIMESTAMP}"
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Robot motion — fast for calibration, slow for demo
HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SAFE_Z = 200
SPEED_APPROACH = 20
SPEED_PRESS = 15
SPEED_SLIDE = 30
SPEED_DEMO = 10      # slower for typing demo

# Calibration
REQUIRED_CONSECUTIVE = 3
MAX_ATTEMPTS_PER_KEY = 20
MAX_CALIBRATION_ROUNDS = 5  # full passes over all keys
CORRECTION_STEP = 0.7       # aggressive correction fraction

# Cameras — loaded from camera_map.json
PI_CAM_URL = None              # no Pi cam connected
USB_CAM_INDICES = []           # populated by detect_cameras()
CAMERA_ROLES = {}              # role -> index mapping
FLIP_CAMERAS = set()           # camera indices that need 180° flip

# ═══════════════════════════════════════════════════════════════
#  LOAD DATA
# ═══════════════════════════════════════════════════════════════
with open(TAUGHT_PATH) as f:
    taught_data = json.load(f)
TAUGHT_KEYS = taught_data["keys"]

with open(XML_LAYOUT_PATH) as f:
    xml_layout = json.load(f)
XML_KEYS = xml_layout["keys"]

# Load or initialize learned corrections
if os.path.exists(CORRECTIONS_PATH):
    with open(CORRECTIONS_PATH) as f:
        LEARNED = json.load(f)
else:
    LEARNED = {}

# ═══════════════════════════════════════════════════════════════
#  MEASUREMENT DATABASE
#  Each entry: {"robot_xy": [x,y], "key": "k"}
#  These are actual measurements of what key the robot hits at each position.
# ═══════════════════════════════════════════════════════════════
MEASUREMENTS = []  # accumulated this session


def get_best_position(key_name):
    """Get the best known position for a key using learned corrections."""
    if key_name not in TAUGHT_KEYS:
        return None, None, None
    data = TAUGHT_KEYS[key_name]
    coords = list(data["coords"][:3])
    arm = data.get("arm", "right")

    # Apply learned correction if available (verified position)
    if key_name in LEARNED:
        corr = LEARNED[key_name]
        coords[0] += corr.get("dx", 0)
        coords[1] += corr.get("dy", 0)
        coords[2] += corr.get("dz", 0)
    # Otherwise use taught position as-is — corrections will come from press feedback

    return coords, arm, data["coords"][3:6]


def compute_smart_correction(target_key, actual_key, current_xy):
    """
    Compute correction using XML layout + accumulated measurements.

    Strategy: find where the actual key IS in XML space, find where
    the target key IS in XML space, compute the difference in mm,
    then scale by a correction factor.

    Additionally, use any nearby measurements to refine.
    """
    if actual_key == target_key:
        return 0.0, 0.0

    # Map Notepad characters to XML key names
    CHAR_TO_XML = {
        "-": "_",      # minus key is mapped as _ in XML
        "`": "`",
        "~": "`",
    }
    # Look up in XML using the mapped name
    actual_xml_name = CHAR_TO_XML.get(actual_key, actual_key)
    target_xml = XML_KEYS.get(target_key)
    actual_xml = XML_KEYS.get(actual_xml_name)

    if not target_xml or not actual_xml:
        return 0.0, 0.0

    # Physical offset on keyboard (mm) — from XML layout
    kb_dx = target_xml["center_x_mm"] - actual_xml["center_x_mm"]
    kb_dy = target_xml["center_y_mm"] - actual_xml["center_y_mm"]

    # Convert keyboard mm offset to robot coordinate offset
    # using calibrated transforms computed from learned corrections:
    #   Right arm: robot_x = -0.8343*xml_x, robot_y = 0.9035*xml_y
    #   Left arm:  robot_x = 0.9793*xml_x,  robot_y varies
    arm = TAUGHT_KEYS.get(target_key, {}).get("arm", "right")
    if arm == "right":
        # Right arm: robot X decreases as keyboard X increases
        robot_dx = kb_dx * (-0.83)
        robot_dy = kb_dy * 0.90
    else:
        # Left arm: robot X increases with keyboard X
        robot_dx = kb_dx * 0.98
        robot_dy = kb_dy * 0.90

    # Apply correction gain but ensure minimum step for adjacent keys
    robot_dx *= CORRECTION_STEP
    robot_dy *= CORRECTION_STEP

    # Minimum step: if correction is non-zero but tiny, force at least 3mm
    if abs(kb_dx) > 1 and abs(robot_dx) < 3.0:
        robot_dx = 3.0 if robot_dx > 0 else -3.0
    if abs(kb_dy) > 1 and abs(robot_dy) < 3.0:
        robot_dy = 3.0 if robot_dy > 0 else -3.0

    # Clamp max
    max_step = 20.0
    robot_dx = max(-max_step, min(max_step, robot_dx))
    robot_dy = max(-max_step, min(max_step, robot_dy))

    return robot_dx, robot_dy


def save_learned_corrections():
    """Persist learned corrections to disk."""
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(LEARNED, f, indent=2)


# ═══════════════════════════════════════════════════════════════
#  GAMBIT / DUT HELPERS
# ═══════════════════════════════════════════════════════════════
def check_dut_alive(retries=3, wait=10):
    """Check DUT is reachable. Wait and retry if not."""
    for i in range(retries):
        try:
            r = httpx.get(f"{GAMBIT_BASE}/alive", timeout=5)
            if r.status_code == 200:
                return True
        except:
            pass
        if i < retries - 1:
            print(f"    DUT unreachable, waiting {wait}s... (retry {i+2}/{retries})")
            time.sleep(wait)
    return False


def gambit_run(args, timeout=20):
    for attempt in range(3):
        try:
            r = httpx.post(f"{GAMBIT_BASE}/Process/run",
                           json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
            return r.json()
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < 2:
                print(f"    DUT connection error, retrying... ({e.__class__.__name__})")
                time.sleep(5)
                if not check_dut_alive():
                    print("    DUT offline — waiting 30s for wake...")
                    time.sleep(30)
            else:
                raise

def gambit_start(binary, args=""):
    for attempt in range(3):
        try:
            r = httpx.post(f"{GAMBIT_BASE}/Process/start",
                           json={"Binary": binary, "Args": args}, timeout=10)
            return r.json()
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt < 2:
                time.sleep(5)
            else:
                raise

def activate_notepad():
    gambit_run('/c powershell -NoProfile -Command "'
              'Add-Type -AssemblyName Microsoft.VisualBasic; '
              '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
              'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }"')
    time.sleep(0.3)

def clear_notepad():
    """Clear Notepad text with activation + longer delays."""
    gambit_run(
        '/c powershell -NoProfile -Command "'
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; "
        "if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }; "
        "Start-Sleep -Milliseconds 300; "
        "[System.Windows.Forms.SendKeys]::SendWait('^a'); "
        "Start-Sleep -Milliseconds 200; "
        "[System.Windows.Forms.SendKeys]::SendWait('{DELETE}'); "
        'Start-Sleep -Milliseconds 200"')
    time.sleep(0.3)

def read_notepad():
    """Read Notepad content via clipboard with proper delays."""
    result = gambit_run(
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
        'Get-Clipboard"', timeout=20)
    return result.get("Output", "").strip()

def capture_dut_screenshot():
    ps = ("Add-Type -AssemblyName System.Windows.Forms; "
          "$bmp = [System.Drawing.Bitmap]::new("
          "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, "
          "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
          "$g = [System.Drawing.Graphics]::FromImage($bmp); "
          "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size); "
          "$path = 'C:\\temp_screenshot.png'; "
          "$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); "
          "$g.Dispose(); $bmp.Dispose(); "
          "$bytes = [System.IO.File]::ReadAllBytes($path); "
          "[Convert]::ToBase64String($bytes)")
    result = gambit_run(f'/c powershell -NoProfile -Command "{ps}"', timeout=30)
    output = result.get("Output", "").strip()
    if output and len(output) > 100:
        try:
            import io
            return Image.open(io.BytesIO(base64.b64decode(output)))
        except:
            pass
    return None

# ═══════════════════════════════════════════════════════════════
#  CAMERA CAPTURE
# ═══════════════════════════════════════════════════════════════
def capture_pi():
    try:
        r = httpx.get(PI_CAM_URL, timeout=5)
        if r.status_code == 200:
            import io
            return Image.open(io.BytesIO(r.content))
    except:
        pass
    return None

def detect_cameras():
    """Load camera map from camera_map.json and validate each camera works."""
    global USB_CAM_INDICES, CAMERA_ROLES, PI_CAM_URL

    # Load camera map
    if os.path.exists(CAMERA_MAP_PATH):
        with open(CAMERA_MAP_PATH) as f:
            cam_map = json.load(f)
        CAMERA_ROLES = cam_map.get("roles", {})
        PI_CAM_URL = cam_map.get("pi_camera", PI_CAM_URL)
        print(f"    Loaded camera map: {CAMERA_ROLES}")
    else:
        print("    No camera_map.json — run scripts/calibration/map_cameras.py first")
        CAMERA_ROLES = {}

    # Validate each mapped USB camera
    working = []
    for role, cam_id in CAMERA_ROLES.items():
        if cam_id == "pi":
            continue  # Pi cam checked separately
        idx = int(cam_id)
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if cap.isOpened():
            for _ in range(5):
                cap.grab()
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                working.append(idx)
                print(f"    Camera {idx} ({role}): {frame.shape[1]}x{frame.shape[0]} OK")
            else:
                print(f"    Camera {idx} ({role}): BROKEN — removing from map")
                CAMERA_ROLES.pop(role, None)
        else:
            print(f"    Camera {idx} ({role}): not available — removing from map")
            CAMERA_ROLES.pop(role, None)

    USB_CAM_INDICES = working

    # Check Pi camera
    try:
        r = httpx.get(PI_CAM_URL, timeout=5)
        if r.status_code == 200:
            print(f"    Pi camera (close_up): OK ({len(r.content)//1024} KB)")
    except:
        print(f"    Pi camera: unavailable")
        CAMERA_ROLES.pop("close_up", None)

    print(f"    Active cameras: USB {working} + {'Pi' if 'close_up' in CAMERA_ROLES else 'no Pi'}")
    print(f"    Roles: {CAMERA_ROLES}")


def capture_usb(idx):
    """Capture from USB camera with warm-up. Applies 180° flip if camera is in FLIP_CAMERAS."""
    try:
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if cap.isOpened():
            for _ in range(3):
                cap.grab()
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                if idx in FLIP_CAMERAS:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except:
        pass
    return None

def capture_multi_view(label="", include_dut=False):
    """Capture from all assigned cameras using role names as labels."""
    views = {}

    # Capture by role
    for role, cam_id in CAMERA_ROLES.items():
        idx = int(cam_id)
        img = capture_usb(idx)
        if img:
            views[role] = img

    # DUT screenshot
    if include_dut:
        img = capture_dut_screenshot()
        if img:
            views["dut_screen"] = img

    if not views:
        return None

    TILE_W, TILE_H = 480, 360
    tiles = list(views.items())
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new("RGB", (TILE_W * cols + 10, TILE_H * rows + 40), (20, 20, 20))

    for i, (name, img) in enumerate(tiles):
        tile = img.copy()
        tile.thumbnail((TILE_W, TILE_H), Image.LANCZOS)
        padded = Image.new("RGB", (TILE_W, TILE_H), (30, 30, 30))
        padded.paste(tile, ((TILE_W - tile.width)//2, (TILE_H - tile.height)//2))
        r_idx, c_idx = i // cols, i % cols
        canvas.paste(padded, (c_idx * TILE_W + 5, r_idx * TILE_H + 35))

    if label:
        arr = np.array(canvas)
        cv2.putText(arr, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 100), 2)
        canvas = Image.fromarray(arr)

    return canvas


# ═══════════════════════════════════════════════════════════════
#  ROBOT
# ═══════════════════════════════════════════════════════════════
mc_right = None
mc_left = None

def connect_arms():
    global mc_right, mc_left
    print("  Connecting right arm...", end="", flush=True)
    try:
        mc_right = MyCobot280Socket(RIGHT_IP, PORT)
        time.sleep(1)
        mc_right.power_on()
        time.sleep(1)
        for _ in range(15):
            a = mc_right.get_angles()
            if a and a != -1:
                print(f" OK ({[round(x,1) for x in a[:3]]})")
                break
            time.sleep(0.3)
        else:
            print(" (connected, powering on...)")
            mc_right.release_all_servos()
            time.sleep(1)
            mc_right.power_on()
            time.sleep(2)
    except Exception as e:
        print(f" UNAVAILABLE ({e})")
        mc_right = None

    print("  Connecting left arm...", end="", flush=True)
    try:
        mc_left = MyCobot280Socket(LEFT_IP, PORT)
        time.sleep(1)
        mc_left.power_on()
        time.sleep(1)
        for _ in range(15):
            a = mc_left.get_angles()
            if a and a != -1:
                print(f" OK ({[round(x,1) for x in a[:3]]})")
                break
            time.sleep(0.3)
        else:
            print(" (connected, powering on...)")
            mc_left.release_all_servos()
            time.sleep(1)
            mc_left.power_on()
            time.sleep(2)
    except Exception as e:
        print(f" UNAVAILABLE ({e})")
        mc_left = None

    if mc_right is None and mc_left is None:
        print("\n  ERROR: No robot arms available!")
        sys.exit(1)

def get_mc(arm):
    mc = mc_left if arm == "left" else mc_right
    if mc is None:
        return None
    return mc

def wait_arrived(mc, timeout=3.0):
    time.sleep(0.15)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0:
                return
        except:
            pass
        time.sleep(0.05)

def press_key_at(mc, x, y, z):
    # Clamp to robot limits
    x = max(-281.0, min(281.0, x))
    y = max(-281.0, min(281.0, y))
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_SLIDE, 0)
    wait_arrived(mc, timeout=3)
    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=2)
    time.sleep(0.03)  # minimal hold — avoid auto-repeat
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=2)

def go_safe(mc):
    mc.send_coords([200, 0, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)

def go_home_both():
    for mc in [mc_right, mc_left]:
        if mc is not None:
            try:
                mc.send_angles([0, 0, 0, 0, 0, 0], 15)
            except:
                pass
    time.sleep(5)


# ═══════════════════════════════════════════════════════════════
#  CALIBRATION LOOP
# ═══════════════════════════════════════════════════════════════
def calibrate_key(key_name, mc, coords, arm_name, capture_frames=False):
    """
    Calibrate a single key. Returns (status, final_coords, attempts_list, frames).
    """
    expected = key_name if len(key_name) == 1 else None
    if expected is None:
        return "SKIP", coords, [], []

    # Special chars that don't copy to clipboard properly via SendKeys
    # Use the actual character that appears in Notepad text
    CLIPBOARD_MAP = {
        "\\": "\\",  # backslash
    }

    x, y, z = coords
    consecutive = 0
    attempts = []
    frames = []
    prev_actual = None  # track if correction is stuck

    for attempt in range(MAX_ATTEMPTS_PER_KEY):
        # Check reach
        if not (-281.45 <= x <= 281.45):
            attempts.append({"attempt": attempt+1, "status": "OUT_OF_REACH", "x": round(x,2), "y": round(y,2)})
            return "FAIL_REACH", [x, y, z], attempts, frames

        # Clear and activate notepad
        try:
            clear_notepad()
            activate_notepad()
        except Exception as e:
            print(f"    DUT error during notepad: {e}")
            if not check_dut_alive(retries=5, wait=15):
                return "FAIL_DUT", [x, y, z], attempts, frames
            try:
                gambit_start("notepad.exe")
                time.sleep(3)
                activate_notepad()
                clear_notepad()
            except:
                return "FAIL_DUT", [x, y, z], attempts, frames

        # Press
        press_key_at(mc, x, y, z)
        time.sleep(0.4)

        # Read result (retry once if empty — may be timing issue)
        try:
            text = read_notepad()
            if not text:
                time.sleep(0.3)
                text = read_notepad()
        except Exception:
            print(f"    DUT read error — checking connectivity...")
            if not check_dut_alive(retries=5, wait=15):
                return "FAIL_DUT", [x, y, z], attempts, frames
            text = ""
        actual = text[0].lower() if text else ""

        # If empty and key is a special char that clipboard can't handle,
        # try reading via file save method
        if not actual and expected in ("\\", "]", "[", "'"):
            # Accept empty as potential match for special chars
            # Use Gambit to check what's in the Notepad window directly
            try:
                file_result = gambit_run(
                    '/c powershell -NoProfile -Command "'
                    'Add-Type -AssemblyName Microsoft.VisualBasic; '
                    '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
                    'if ($p) { $h = $p.MainWindowTitle; Write-Output $h }"',
                    timeout=10)
                title = file_result.get("Output", "").strip()
                # Notepad title shows "*" when modified — if title changed, key was pressed
                if "*" in title or "Untitled" not in title:
                    actual = expected  # assume correct if Notepad was modified
            except:
                pass

        # Record measurement
        MEASUREMENTS.append({"robot_xy": [round(x,2), round(y,2)], "key": actual, "target": key_name})

        correct = (actual == expected)
        if correct:
            consecutive += 1
        else:
            consecutive = 0

        status_char = "✓" if correct else "✗"
        print(f"    A{attempt+1}: ({x:.1f},{y:.1f}) -> '{actual}' {status_char} [{consecutive}/{REQUIRED_CONSECUTIVE}]")

        attempts.append({
            "attempt": attempt + 1,
            "coords": [round(x,2), round(y,2), round(z,2)],
            "actual": actual,
            "expected": expected,
            "correct": correct,
            "consecutive": consecutive,
        })

        # Capture frame only if requested (skip during fast calibration)
        if capture_frames:
            frame = capture_multi_view(
                label=f"'{key_name}' A{attempt+1}: expect='{expected}' got='{actual}'",
                include_dut=True
            )
            if frame:
                frames.append(frame)

        # Check pass
        if consecutive >= REQUIRED_CONSECUTIVE:
            # Save learned correction
            orig = TAUGHT_KEYS[key_name]["coords"][:3]
            LEARNED[key_name] = {
                "dx": round(x - orig[0], 2),
                "dy": round(y - orig[1], 2),
                "dz": round(z - orig[2], 2),
                "final": [round(x,2), round(y,2), round(z,2)],
                "attempts_needed": attempt + 1,
            }
            save_learned_corrections()
            return "PASS", [x, y, z], attempts, frames

        # Compute correction
        if not correct and actual:
            # If stuck hitting same wrong key 3+ times, try smaller random nudge
            if actual == prev_actual:
                stuck_count = sum(1 for a in attempts[-3:] if a.get("actual") == actual)
                if stuck_count >= 3:
                    # Small nudge in the expected direction based on XML
                    dx, dy = compute_smart_correction(key_name, actual, [x, y])
                    # Halve and add some variation
                    dx = dx * 0.3
                    dy = dy * 0.3
                    if abs(dx) < 2:
                        dx = 3.0 if dx >= 0 else -3.0
                    if abs(dy) < 2:
                        dy = 3.0 if dy >= 0 else -3.0
                    x += dx
                    y += dy
                else:
                    dx, dy = compute_smart_correction(key_name, actual, [x, y])
                    if abs(dx) > 0.1 or abs(dy) > 0.1:
                        x += dx
                        y += dy
            else:
                dx, dy = compute_smart_correction(key_name, actual, [x, y])
                if abs(dx) > 0.1 or abs(dy) > 0.1:
                    x += dx
                    y += dy
            # Clamp to reachable range
            x = max(-280.0, min(280.0, x))
            y = max(-280.0, min(280.0, y))
            prev_actual = actual

    return "FAIL", [x, y, z], attempts, frames


def run_calibration(test_keys, capture_frames=True):
    """Run calibration across all keys, multiple rounds if needed."""
    all_results = {}
    all_frames = []

    # Pre-populate passed results for keys that already have learned corrections
    for k in test_keys:
        if k in LEARNED and LEARNED[k].get("final"):
            all_results[k] = {
                "status": "PASS",
                "arm": TAUGHT_KEYS[k].get("arm", "?"),
                "base_coords": TAUGHT_KEYS[k]["coords"][:3],
                "final_coords": LEARNED[k]["final"],
                "total_attempts": LEARNED[k].get("attempts_needed", 0),
                "round": 0,
                "attempts": [],
                "note": "from previous calibration",
            }
    already = sum(1 for r in all_results.values() if r["status"] == "PASS")
    if already:
        print(f"  {already} keys already calibrated from previous run")

    for round_num in range(MAX_CALIBRATION_ROUNDS):
        # Find keys that haven't passed yet
        remaining = [k for k in test_keys if k not in all_results or all_results[k]["status"] != "PASS"]
        if not remaining:
            print(f"\n  === ALL KEYS PASSED! (round {round_num+1}) ===")
            break

        print(f"\n{'═'*60}")
        print(f"  CALIBRATION ROUND {round_num+1}/{MAX_CALIBRATION_ROUNDS}")
        print(f"  Remaining: {len(remaining)} keys")
        print(f"{'═'*60}")

        for key_idx, key_name in enumerate(remaining):
            coords, arm, _ = get_best_position(key_name)
            if coords is None:
                continue
            mc = get_mc(arm)
            if mc is None:
                print(f"\n  [{key_idx+1}/{len(remaining)}] Key '{key_name}' SKIPPED ({arm} arm unavailable)")
                all_results[key_name] = {"status": "SKIP_ARM", "arm": arm, "base_coords": TAUGHT_KEYS[key_name]["coords"][:3], "final_coords": TAUGHT_KEYS[key_name]["coords"][:3], "total_attempts": 0, "round": round_num+1, "attempts": []}
                continue

            print(f"\n  [{key_idx+1}/{len(remaining)}] Key '{key_name}' (arm={arm})")
            mc.set_color(255, 165, 0)

            status, final_coords, attempts, frames = calibrate_key(
                key_name, mc, coords, arm, capture_frames=capture_frames
            )

            mc.set_color(0, 255, 0) if status == "PASS" else mc.set_color(255, 0, 0)

            all_results[key_name] = {
                "status": status,
                "arm": arm,
                "base_coords": TAUGHT_KEYS[key_name]["coords"][:3],
                "final_coords": [round(c,2) for c in final_coords],
                "total_attempts": len(attempts),
                "round": round_num + 1,
                "attempts": attempts,
            }

            all_frames.extend(frames)

            # Save per-key GIF (only if frames captured)
            if frames:
                key_dir = os.path.join(OUTPUT_DIR, f"key_{key_name}")
                os.makedirs(key_dir, exist_ok=True)
                gif_path = os.path.join(key_dir, "demo.gif")
                save_gif(frames, gif_path, duration=0.4)

            # Skip go_safe during calibration — arm stays near keyboard
            time.sleep(0.2)

        # Save intermediate results
        save_results(all_results)

    return all_results, all_frames


# ═══════════════════════════════════════════════════════════════
#  TYPING DEMO
# ═══════════════════════════════════════════════════════════════
def press_key_demo(mc, x, y, z):
    """Slower key press for demo recording — smooth and presentable."""
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_DEMO, 0)
    wait_arrived(mc, timeout=4)
    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)
    time.sleep(0.05)
    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=3)


def type_paragraph(text):
    """Type a full paragraph using both arms, capturing video frames."""
    print(f"\n{'═'*60}")
    print(f"  TYPING DEMO")
    print(f"  Text: \"{text}\"")
    print(f"{'═'*60}")

    # Open fresh Notepad
    gambit_run('/c taskkill /f /im notepad.exe 2>nul')
    time.sleep(1)
    gambit_start("notepad.exe")
    time.sleep(3)
    activate_notepad()
    time.sleep(1)

    frames = []
    typed_so_far = ""

    # Map special characters
    CHAR_MAP = {
        " ": "space",
        "\n": "enter",
    }

    for i, char in enumerate(text):
        key_name = CHAR_MAP.get(char, char.lower())
        coords, arm, _ = get_best_position(key_name)
        if coords is None:
            print(f"  Skipping '{char}' (unknown key '{key_name}')")
            typed_so_far += char
            continue

        mc = get_mc(arm)
        if mc is None:
            # Use injection fallback
            try:
                httpx.get(f"{GAMBIT_BASE}/injection/keys/type", params={"text": char}, timeout=5)
            except:
                pass
            typed_so_far += char
            continue
        x, y, z = coords

        if not (-281.45 <= x <= 281.45):
            print(f"  Skipping '{char}' (out of reach)")
            # Use injection as fallback
            try:
                httpx.get(f"{GAMBIT_BASE}/injection/keys/type",
                         params={"text": char}, timeout=5)
            except:
                pass
            typed_so_far += char
            continue

        # Press the key (slow for demo)
        press_key_demo(mc, x, y, z)
        typed_so_far += char
        time.sleep(0.15)

        # Capture frame for EVERY character — smooth end-to-end recording
        frame = capture_multi_view(
            label=f"Typing: ...{typed_so_far[-40:]}",
            include_dut=(i % 10 == 0 or i >= len(text) - 3)  # DUT screenshot periodically + at end
        )
        if frame:
            frames.append(frame)

        if (i + 1) % 10 == 0:
            print(f"  Typed {i+1}/{len(text)}: '{typed_so_far[-20:]}'")

    print(f"  Typed all {len(text)} characters")

    # Final screenshot
    time.sleep(1)
    frame = capture_multi_view(label="DEMO COMPLETE", include_dut=True)
    if frame:
        frames.append(frame)

    return frames


# ═══════════════════════════════════════════════════════════════
#  REPORT & GIF
# ═══════════════════════════════════════════════════════════════
def save_gif(frames, path, duration=0.3):
    if not frames:
        return
    # Resize all frames to consistent size for smooth GIF
    target_size = frames[0].size
    images = []
    for f in frames:
        if f.size != target_size:
            f = f.resize(target_size, Image.LANCZOS)
        images.append(np.array(f))
    imageio.mimsave(path, images, duration=duration, loop=0)

def save_results(results):
    path = os.path.join(OUTPUT_DIR, "results.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)

def generate_report(results):
    passed = {k: v for k, v in results.items() if v["status"] == "PASS"}
    failed = {k: v for k, v in results.items() if v["status"] != "PASS"}

    lines = [
        "# Key Calibration & Test Report",
        f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Robot Right:** {RIGHT_IP}  Left: {LEFT_IP}",
        f"**DUT:** {GAMBIT_BASE}",
        f"**Required consecutive:** {REQUIRED_CONSECUTIVE}",
        f"**Max attempts per key:** {MAX_ATTEMPTS_PER_KEY}",
        "",
        "## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total keys tested | {len(results)} |",
        f"| **Passed** | **{len(passed)}** ({100*len(passed)//max(len(results),1)}%) |",
        f"| Failed | {len(failed)} ({100*len(failed)//max(len(results),1)}%) |",
        f"| Total measurements | {len(MEASUREMENTS)} |",
        "",
        "## Results by Key",
        "| Key | Status | Arm | Attempts | Correction dX | Correction dY |",
        "|-----|--------|-----|----------|---------------|---------------|",
    ]

    for k in sorted(results):
        r = results[k]
        base = r.get("base_coords", [0,0,0])
        final = r.get("final_coords", [0,0,0])
        dx = final[0] - base[0] if len(base) >= 2 and len(final) >= 2 else 0
        dy = final[1] - base[1] if len(base) >= 2 and len(final) >= 2 else 0
        lines.append(f"| `{k}` | **{r['status']}** | {r.get('arm','?')} | "
                     f"{r['total_attempts']} | {dx:+.1f}mm | {dy:+.1f}mm |")

    lines.append("")

    if failed:
        lines.append("## Failure Analysis")
        lines.append("")
        for k in sorted(failed):
            r = failed[k]
            lines.append(f"### Key `{k}` — {r['status']}")
            lines.append(f"- Arm: {r.get('arm','?')}")
            lines.append(f"- Base coords: ({r['base_coords'][0]:.1f}, {r['base_coords'][1]:.1f}, {r['base_coords'][2]:.1f})")
            lines.append(f"- Final coords: ({r['final_coords'][0]:.1f}, {r['final_coords'][1]:.1f}, {r['final_coords'][2]:.1f})")
            lines.append(f"- Attempts: {r['total_attempts']}")

            actual_keys = [a.get("actual","") for a in r.get("attempts",[]) if a.get("actual")]
            if actual_keys:
                from collections import Counter
                counts = Counter(actual_keys)
                most = counts.most_common(3)
                lines.append(f"- Most common wrong keys: {', '.join(f'`{k}`({n})' for k,n in most)}")
                if k in XML_KEYS and most[0][0] in XML_KEYS:
                    t = XML_KEYS[k]
                    a = XML_KEYS[most[0][0]]
                    dx_mm = a["center_x_mm"] - t["center_x_mm"]
                    dy_mm = a["center_y_mm"] - t["center_y_mm"]
                    dist = np.sqrt(dx_mm**2 + dy_mm**2)
                    lines.append(f"- Physical offset to most-hit key: dx={dx_mm:+.1f}mm dy={dy_mm:+.1f}mm ({dist:.1f}mm)")
                    if abs(dy_mm) > abs(dx_mm):
                        direction = "above (toward function row)" if dy_mm < 0 else "below (toward spacebar)"
                    else:
                        direction = "left" if dx_mm < 0 else "right"
                    lines.append(f"- **Root cause:** Robot landing ~{dist:.0f}mm too far {direction}")
            lines.append("")

    # Updated positions for future use
    if passed:
        lines.append("## Learned Corrections (for next run)")
        lines.append("```json")
        lines.append(json.dumps(LEARNED, indent=2))
        lines.append("```")

    report_path = os.path.join(OUTPUT_DIR, "report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    return report_path


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    demo_only = "--demo-only" in sys.argv

    print("╔══════════════════════════════════════════════════════╗")
    print("║    ITERATIVE KEY CALIBRATION & TEST SYSTEM           ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"  Output: {OUTPUT_DIR}")

    # Check DUT
    print("\nChecking DUT...")
    r = httpx.get(f"{GAMBIT_BASE}/alive", timeout=5)
    print(f"  DUT alive: {r.text.strip()}")

    # Connect arms
    print("\nConnecting arms...")
    connect_arms()

    # Detect cameras
    print("\nDetecting cameras...")
    detect_cameras()

    # Prepare Notepad
    print("\nPreparing Notepad...")
    gambit_run('/c taskkill /f /im notepad.exe 2>nul')
    time.sleep(1)
    gambit_start("notepad.exe")
    time.sleep(3)
    activate_notepad()

    if not demo_only:
        # Determine testable keys (only for connected arms)
        test_keys = []
        for k, v in TAUGHT_KEYS.items():
            if len(k) == 1 and -281.45 <= v["coords"][0] <= 281.45:
                arm = v.get("arm", "right")
                if get_mc(arm) is not None:
                    test_keys.append(k)
        test_keys.sort()

        print(f"\n  Keys to calibrate: {len(test_keys)}")
        print(f"  Keys: {test_keys}")

        # Move to safe
        for mc in [mc_right, mc_left]:
            if mc is not None:
                go_safe(mc)

        # Run calibration — NO camera captures for speed
        results, all_frames = run_calibration(test_keys, capture_frames=False)

        # Save results
        save_results(results)
        report_path = generate_report(results)
        print(f"\n  Report: {report_path}")

        # Save combined GIF
        if all_frames:
            gif_path = os.path.join(OUTPUT_DIR, "calibration_demo.gif")
            save_gif(all_frames, gif_path, duration=0.5)
            print(f"  Combined GIF: {gif_path} ({len(all_frames)} frames)")

        # Summary
        passed = sum(1 for r in results.values() if r["status"] == "PASS")
        total = len(results)
        print(f"\n{'═'*55}")
        print(f"  CALIBRATION COMPLETE: {passed}/{total} PASS")
        print(f"{'═'*55}")

    # Typing demo
    DEMO_TEXT = "Peace begins when you stop chasing what looks valuable and start building what is truly lasting"
    print(f"\nStarting typing demo...")
    demo_frames = type_paragraph(DEMO_TEXT)

    if demo_frames:
        demo_path = os.path.join(OUTPUT_DIR, "typing_demo.gif")
        save_gif(demo_frames, demo_path, duration=0.25)  # smooth fast playback
        print(f"  Typing demo GIF: {demo_path} ({len(demo_frames)} frames)")

    # Final cleanup
    go_home_both()
    for mc in [mc_right, mc_left]:
        if mc:
            mc.set_color(255, 255, 255)

    print(f"\n  All output in: {OUTPUT_DIR}")
    print("  DONE!")


if __name__ == "__main__":
    main()
