"""
Full Key Iteration Test with Auto-Calibration, Multi-Camera GIF Recording, and Report.

For each reachable key:
  1. Clear Notepad on DUT
  2. Press the key with the robot arm
  3. Read what DUT registered (Notepad clipboard)
  4. If wrong key detected: compute correction offset and retry
  5. Require 3 consecutive correct presses to PASS
  6. Capture multi-camera frames at each step for GIF
  7. Generate a summary report with failure analysis

Usage:
  python key_iteration_test.py                  # test all right-arm keys
  python key_iteration_test.py k l p            # test specific keys
  python key_iteration_test.py --max-attempts 8 # custom max retries
"""

import httpx
import time
import json
import os
import sys
import base64
import datetime
import traceback
import numpy as np
import cv2
from PIL import Image
import imageio

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
GAMBIT_BASE = "http://192.168.0.4:22133"
ROBOT_RIGHT_IP = "10.105.230.93"
ROBOT_LEFT_IP = "10.105.230.94"
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")

# Create timestamped output directory
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp",
    f"key_test_{TIMESTAMP}"
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Robot motion parameters
HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
SAFE_Z = 200
SPEED_APPROACH = 12
SPEED_PRESS = 8
SPEED_SLIDE = 15

# Right arm systematic Y offset correction (arm lands ~18mm further in -Y than commanded)
# Measured: k(Y=-11.7) types i(Y≈-30), so arm overshoots by ~18mm in -Y
# Correction: add +18 to Y to compensate
# NOTE: disabled — XML-based affine correction handles this per-arm
RIGHT_ARM_Y_OFFSET = 0.0

# Test parameters
REQUIRED_CONSECUTIVE = 3   # need 3 correct in a row
MAX_ATTEMPTS = 10          # max attempts per key before giving up
CORRECTION_GAIN = 0.4      # fraction of computed correction to apply
MAX_CORRECTION = 10.0      # max mm correction per step

# Camera sources
PI_CAM_URL = "http://10.105.230.93:8080/snapshot"
USB_CAM_INDICES = [0, 3]   # camera 0 (webcam), camera 3 (overview)

# Load keyboard physical layout from XML-parsed data
XML_LAYOUT_PATH = os.path.join(DATA_DIR, "keyboard_layout_xml.json")
with open(XML_LAYOUT_PATH) as f:
    XML_LAYOUT = json.load(f)
XML_KEYS = XML_LAYOUT["keys"]  # key_name -> {center_x_mm, center_y_mm, ...}

# Key pitch constants (from XML analysis)
KEY_PITCH_X = 19.0   # mm between key centers horizontally
ROW_PITCH_Y = 18.5   # mm between row centers vertically

# ═══════════════════════════════════════════════════════════════
#  GAMBIT HELPERS
# ═══════════════════════════════════════════════════════════════

def gambit_run(args, timeout=20):
    r = httpx.post(
        f"{GAMBIT_BASE}/Process/run",
        json={"Binary": "cmd.exe", "Args": args},
        timeout=timeout,
    )
    return r.json()


def gambit_start(binary, args=""):
    r = httpx.post(
        f"{GAMBIT_BASE}/Process/start",
        json={"Binary": binary, "Args": args},
        timeout=10,
    )
    return r.json()


def activate_notepad():
    gambit_run(
        '/c powershell -NoProfile -Command "'
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; "
        'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }"'
    )
    time.sleep(0.4)


def clear_notepad():
    activate_notepad()
    gambit_run(
        '/c powershell -NoProfile -Command "'
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.SendKeys]::SendWait('^a'); "
        "Start-Sleep -Milliseconds 100; "
        "[System.Windows.Forms.SendKeys]::SendWait('{DELETE}')\"",
    )
    time.sleep(0.3)


def read_notepad():
    activate_notepad()
    result = gambit_run(
        '/c powershell -NoProfile -Command "'
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.SendKeys]::SendWait('^a'); "
        "Start-Sleep -Milliseconds 200; "
        "[System.Windows.Forms.SendKeys]::SendWait('^c'); "
        "Start-Sleep -Milliseconds 200; "
        'Get-Clipboard"',
        timeout=15,
    )
    return result.get("Output", "").strip()


def capture_dut_screenshot():
    """Capture DUT screen via PowerShell, return PIL Image or None."""
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
            import io
            return Image.open(io.BytesIO(img_data))
        except:
            pass
    return None


# ═══════════════════════════════════════════════════════════════
#  CAMERA CAPTURE
# ═══════════════════════════════════════════════════════════════

def capture_pi_cam():
    """Capture from Pi network camera, return PIL Image or None."""
    try:
        r = httpx.get(PI_CAM_URL, timeout=5)
        if r.status_code == 200:
            import io
            return Image.open(io.BytesIO(r.content))
    except:
        pass
    return None


def capture_usb_cam(index):
    """Capture from USB camera, return PIL Image or None."""
    try:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return Image.fromarray(frame_rgb)
    except:
        pass
    return None


def capture_all_cameras():
    """Capture from all available cameras, return dict of PIL Images."""
    views = {}
    img = capture_pi_cam()
    if img:
        views["pi_cam"] = img
    for idx in USB_CAM_INDICES:
        img = capture_usb_cam(idx)
        if img:
            views[f"cam_{idx}"] = img
    img = capture_dut_screenshot()
    if img:
        views["dut_screen"] = img
    return views


def compose_multi_view(views, label=""):
    """Tile multiple camera views into one image with label."""
    if not views:
        return None

    TILE_W, TILE_H = 480, 360
    tiles = []
    for name, img in views.items():
        tile = img.copy()
        tile.thumbnail((TILE_W, TILE_H), Image.LANCZOS)
        # Pad to exact size
        padded = Image.new("RGB", (TILE_W, TILE_H), (30, 30, 30))
        x_off = (TILE_W - tile.width) // 2
        y_off = (TILE_H - tile.height) // 2
        padded.paste(tile, (x_off, y_off))
        tiles.append((name, padded))

    # Arrange: 2 columns
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    canvas_w = TILE_W * cols + 10
    canvas_h = TILE_H * rows + 40  # extra for label
    canvas = Image.new("RGB", (canvas_w, canvas_h), (20, 20, 20))

    for i, (name, tile) in enumerate(tiles):
        r_idx = i // cols
        c_idx = i % cols
        x = c_idx * TILE_W + 5
        y = r_idx * TILE_H + 35
        canvas.paste(tile, (x, y))

    # Add label text (simple approach — draw text as numpy)
    if label:
        arr = np.array(canvas)
        cv2.putText(arr, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 100), 2)
        for i, (name, _) in enumerate(tiles):
            r_idx = i // cols
            c_idx = i % cols
            tx = c_idx * TILE_W + 10
            ty = r_idx * TILE_H + 55
            cv2.putText(arr, name, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        canvas = Image.fromarray(arr)

    return canvas


# ═══════════════════════════════════════════════════════════════
#  ROBOT
# ═══════════════════════════════════════════════════════════════

mc_right = None
mc_left = None

def connect_robots():
    global mc_right, mc_left
    from pymycobot import MyCobot280Socket
    print("  Connecting right arm...")
    mc_right = MyCobot280Socket(ROBOT_RIGHT_IP, ROBOT_PORT)
    time.sleep(1)
    for _ in range(10):
        a = mc_right.get_angles()
        if a and a != -1:
            print(f"  Right arm OK: {[round(x,1) for x in a]}")
            break
        time.sleep(0.3)
    print("  Connecting left arm...")
    mc_left = MyCobot280Socket(ROBOT_LEFT_IP, ROBOT_PORT)
    time.sleep(1)
    for _ in range(10):
        a = mc_left.get_angles()
        if a and a != -1:
            print(f"  Left arm OK: {[round(x,1) for x in a]}")
            break
        time.sleep(0.3)
    return mc_right, mc_left

def get_arm_for_key(key_data):
    """Return the correct mc object based on key's arm assignment."""
    arm = key_data.get("arm", "right")
    return mc_left if arm == "left" else mc_right


def wait_arrived(mc, timeout=3.0):
    time.sleep(0.15)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0:
                return True
        except:
            pass
        time.sleep(0.05)
    return False


def press_key_at(mc, x, y, z):
    """Press a key at exact coordinates. Returns quickly for iteration speed."""
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET

    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_SLIDE, 0)
    wait_arrived(mc, timeout=3)

    mc.send_coords([x, y, press_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=2)
    time.sleep(0.05)  # very brief hold — avoid auto-repeat

    mc.send_coords([x, y, hover_z, 0, 180, 90], SPEED_PRESS, 0)
    wait_arrived(mc, timeout=2)


def go_safe(mc):
    mc.send_coords([200, 0, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc, timeout=4)


# ═══════════════════════════════════════════════════════════════
#  CALIBRATION / CORRECTION
# ═══════════════════════════════════════════════════════════════

def compute_correction(target_key, actual_char, taught_keys):
    """
    Given that pressing target_key's position produced actual_char,
    compute an XY correction vector using the physical keyboard layout from XML.

    The XML gives exact key center positions in mm. We compute the physical
    offset between target and actual key, then map that to robot coordinates
    using an affine model fitted from taught key positions.
    """
    if actual_char == target_key:
        return 0.0, 0.0

    # Look up both keys in the XML layout
    target_xml = XML_KEYS.get(target_key)
    actual_xml = XML_KEYS.get(actual_char)

    if target_xml is None or actual_xml is None:
        return 0.0, 0.0

    # Physical offset on keyboard surface (mm)
    # target is where we WANT to be, actual is where we ARE
    # So correction = target_pos - actual_pos (in keyboard mm coordinates)
    kb_dx = target_xml["center_x_mm"] - actual_xml["center_x_mm"]
    kb_dy = target_xml["center_y_mm"] - actual_xml["center_y_mm"]

    # If the physical distance is huge (>80mm = ~4 keys), skip correction
    dist_mm = np.sqrt(kb_dx**2 + kb_dy**2)
    if dist_mm > 80:
        return 0.0, 0.0

    # Map keyboard mm offset to robot coordinate offset using taught key pairs
    # Collect taught keys that are also in the XML
    ref_points = []
    for k, data in taught_keys.items():
        if k in XML_KEYS and data.get("coords"):
            xml_pos = XML_KEYS[k]
            robot_xyz = data["coords"][:3]
            ref_points.append((
                xml_pos["center_x_mm"], xml_pos["center_y_mm"],
                robot_xyz[0], robot_xyz[1]
            ))

    if len(ref_points) < 3:
        # Fallback: assume 1:1 mm mapping with sign conventions
        # Robot X increases with keyboard X, Robot Y decreases with keyboard Y
        return kb_dx * CORRECTION_GAIN, -kb_dy * CORRECTION_GAIN

    # Fit affine: robot_x = a0 + a1*kb_x + a2*kb_y
    #             robot_y = b0 + b1*kb_x + b2*kb_y
    A = np.array([[1, rp[0], rp[1]] for rp in ref_points])
    robot_x = np.array([rp[2] for rp in ref_points])
    robot_y = np.array([rp[3] for rp in ref_points])

    ax, _, _, _ = np.linalg.lstsq(A, robot_x, rcond=None)
    ay, _, _, _ = np.linalg.lstsq(A, robot_y, rcond=None)

    # Correction in robot coordinates = affine_slope * keyboard_mm_offset
    dx = ax[1] * kb_dx + ax[2] * kb_dy
    dy = ay[1] * kb_dx + ay[2] * kb_dy

    return dx * CORRECTION_GAIN, dy * CORRECTION_GAIN


def char_for_key(key_name):
    """What character should appear in Notepad when this key is pressed?"""
    if len(key_name) == 1:
        return key_name
    return None  # special keys don't produce simple chars


# ═══════════════════════════════════════════════════════════════
#  MAIN TEST LOOP
# ═══════════════════════════════════════════════════════════════

def run_key_test(test_keys, taught_keys, max_attempts=MAX_ATTEMPTS):
    """
    Test each key using the correct arm. Returns results dict.
    """
    results = {}
    gif_frames = []
    total_keys = len(test_keys)

    for key_idx, key_name in enumerate(test_keys):
        expected_char = char_for_key(key_name)
        if expected_char is None:
            print(f"\n[{key_idx+1}/{total_keys}] Skipping '{key_name}' (non-character key)")
            continue

        key_data = taught_keys[key_name]
        mc = get_arm_for_key(key_data)
        arm_name = key_data.get("arm", "right")
        base_coords = list(key_data["coords"][:3])
        # Apply systematic arm offset corrections
        if arm_name == "right":
            base_coords[1] += RIGHT_ARM_Y_OFFSET
        current_coords = list(base_coords)
        corrections_applied = []

        print(f"\n{'='*60}")
        print(f"[{key_idx+1}/{total_keys}] Testing key '{key_name}'  "
              f"expect='{expected_char}'  arm={arm_name}  coords={[round(c,1) for c in current_coords]}")
        print(f"{'='*60}")

        consecutive_correct = 0
        attempts = []
        status = "FAIL"

        for attempt in range(max_attempts):
            x, y, z = current_coords

            # Verify in robot reach
            if not (-281.45 <= x <= 281.45):
                print(f"  Attempt {attempt+1}: OUT OF REACH (x={x:.1f})")
                attempts.append({
                    "attempt": attempt + 1,
                    "coords": list(current_coords),
                    "result": "OUT_OF_REACH",
                    "actual": None,
                })
                break

            # 1. Clear Notepad
            clear_notepad()
            time.sleep(0.3)

            # 2. Activate Notepad (ensure focus)
            activate_notepad()
            time.sleep(0.2)

            # 3. Capture before frame
            label = f"Key '{key_name}' attempt {attempt+1}/{max_attempts}"

            # 4. Press the key
            print(f"  Attempt {attempt+1}: pressing at ({x:.1f}, {y:.1f}, {z:.1f}) ...", end="")
            press_key_at(mc, x, y, z)
            time.sleep(0.5)

            # 5. Read what was typed
            actual_text = read_notepad()
            # Take first char (might have repeats)
            actual_char = actual_text[0].lower() if actual_text else ""

            # 6. Capture after frame
            views = capture_all_cameras()
            frame = compose_multi_view(
                views,
                label=f"Key '{key_name}' A{attempt+1}: expect='{expected_char}' got='{actual_char}'"
            )
            if frame:
                gif_frames.append(frame)

            # 7. Evaluate
            correct = (actual_char == expected_char)
            if correct:
                consecutive_correct += 1
                print(f"  CORRECT ('{actual_char}') [{consecutive_correct}/{REQUIRED_CONSECUTIVE}]")
            else:
                consecutive_correct = 0
                print(f"  WRONG (got '{actual_char}' from '{actual_text[:20]}')")

            attempts.append({
                "attempt": attempt + 1,
                "coords": [round(c, 2) for c in current_coords],
                "actual_text": actual_text[:30],
                "actual_char": actual_char,
                "expected": expected_char,
                "correct": correct,
                "consecutive": consecutive_correct,
            })

            # 8. Check if passed
            if consecutive_correct >= REQUIRED_CONSECUTIVE:
                status = "PASS"
                print(f"  >>> PASS — {REQUIRED_CONSECUTIVE} consecutive correct presses!")
                break

            # 9. Apply correction if wrong
            if not correct and actual_char and actual_char in XML_KEYS:
                dx, dy = compute_correction(key_name, actual_char, taught_keys)
                # Clamp correction magnitude
                dx = max(-MAX_CORRECTION, min(MAX_CORRECTION, dx))
                dy = max(-MAX_CORRECTION, min(MAX_CORRECTION, dy))
                if abs(dx) > 0.1 or abs(dy) > 0.1:
                    current_coords[0] += dx
                    current_coords[1] += dy
                    corrections_applied.append({
                        "from_char": actual_char,
                        "dx": round(dx, 2),
                        "dy": round(dy, 2),
                        "new_coords": [round(c, 2) for c in current_coords],
                    })
                    print(f"  Correction: dx={dx:.2f} dy={dy:.2f} -> "
                          f"({current_coords[0]:.1f}, {current_coords[1]:.1f})")

        results[key_name] = {
            "status": status,
            "expected": expected_char,
            "arm": arm_name,
            "base_coords": [round(c, 2) for c in base_coords],
            "final_coords": [round(c, 2) for c in current_coords],
            "total_attempts": len(attempts),
            "corrections": corrections_applied,
            "attempts": attempts,
        }

        # Save per-key GIF
        key_frames = [f for f in gif_frames if f is not None]
        # Collect only frames added during this key's test
        new_frame_count = len(attempts)
        key_specific_frames = key_frames[-new_frame_count:] if new_frame_count > 0 else []
        if key_specific_frames:
            key_dir = os.path.join(OUTPUT_DIR, f"key_{key_name}")
            os.makedirs(key_dir, exist_ok=True)
            key_gif_path = os.path.join(key_dir, "demo.gif")
            save_gif(key_specific_frames, key_gif_path, duration=1.0)
            # Also save last frame as PNG
            key_specific_frames[-1].save(os.path.join(key_dir, "final.png"))
            print(f"  Saved key GIF: {key_gif_path} ({len(key_specific_frames)} frames)")

        # Briefly go safe between keys
        go_safe(mc)
        time.sleep(0.5)

    return results, gif_frames


# ═══════════════════════════════════════════════════════════════
#  REPORT GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_report(results, output_dir):
    """Generate a markdown report with pass/fail summary and failure analysis."""
    report_path = os.path.join(output_dir, "report.md")

    passed = {k: v for k, v in results.items() if v["status"] == "PASS"}
    failed = {k: v for k, v in results.items() if v["status"] == "FAIL"}

    lines = []
    lines.append(f"# Key Iteration Test Report")
    lines.append(f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Robot Right:** {ROBOT_RIGHT_IP}  Left: {ROBOT_LEFT_IP}  Port: {ROBOT_PORT}")
    lines.append(f"**DUT:** {GAMBIT_BASE}")
    lines.append(f"**Required consecutive:** {REQUIRED_CONSECUTIVE}")
    lines.append(f"**Max attempts per key:** {MAX_ATTEMPTS}")
    lines.append("")

    # Summary
    total = len(results)
    lines.append(f"## Summary")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total keys tested | {total} |")
    lines.append(f"| Passed | {len(passed)} ({100*len(passed)//max(total,1)}%) |")
    lines.append(f"| Failed | {len(failed)} ({100*len(failed)//max(total,1)}%) |")
    lines.append("")

    # Pass/Fail table
    lines.append(f"## Results by Key")
    lines.append(f"| Key | Status | Attempts | Expected | Final Char | Correction Applied |")
    lines.append(f"|-----|--------|----------|----------|------------|-------------------|")
    for k in sorted(results.keys()):
        r = results[k]
        last_attempt = r["attempts"][-1] if r["attempts"] else {}
        final_char = last_attempt.get("actual_char", "?")
        corr = "Yes" if r["corrections"] else "No"
        lines.append(f"| `{k}` | **{r['status']}** | {r['total_attempts']} | "
                      f"`{r['expected']}` | `{final_char}` | {corr} |")
    lines.append("")

    # Calibration corrections
    corrected = {k: v for k, v in results.items() if v["corrections"]}
    if corrected:
        lines.append(f"## Calibration Corrections Applied")
        lines.append(f"| Key | Original XY | Final XY | Total dX | Total dY |")
        lines.append(f"|-----|-------------|----------|----------|----------|")
        for k in sorted(corrected.keys()):
            r = corrected[k]
            ox, oy = r["base_coords"][0], r["base_coords"][1]
            fx, fy = r["final_coords"][0], r["final_coords"][1]
            lines.append(f"| `{k}` | ({ox:.1f}, {oy:.1f}) | ({fx:.1f}, {fy:.1f}) | "
                          f"{fx-ox:+.2f} | {fy-oy:+.2f} |")
        lines.append("")

    # Failure analysis
    if failed:
        lines.append(f"## Failure Analysis")
        lines.append("")
        for k in sorted(failed.keys()):
            r = failed[k]
            lines.append(f"### Key `{k}` — FAILED")
            lines.append(f"- **Expected:** `{r['expected']}`")
            lines.append(f"- **Base coords:** ({r['base_coords'][0]:.1f}, "
                          f"{r['base_coords'][1]:.1f}, {r['base_coords'][2]:.1f})")
            lines.append(f"- **Final coords:** ({r['final_coords'][0]:.1f}, "
                          f"{r['final_coords'][1]:.1f}, {r['final_coords'][2]:.1f})")
            lines.append(f"- **Total attempts:** {r['total_attempts']}")
            lines.append("")

            # Attempt history
            lines.append(f"  | Attempt | Coords | Got | Correct? |")
            lines.append(f"  |---------|--------|-----|----------|")
            for a in r["attempts"]:
                coords_str = f"({a['coords'][0]:.1f}, {a['coords'][1]:.1f})"
                got = a.get("actual_char", "?")
                correct_mark = "Y" if a.get("correct") else "N"
                lines.append(f"  | {a['attempt']} | {coords_str} | `{got}` | {correct_mark} |")
            lines.append("")

            # Root cause hypothesis using XML layout
            actual_chars = [a.get("actual_char", "") for a in r["attempts"] if a.get("actual_char")]
            if actual_chars:
                from collections import Counter
                char_counts = Counter(actual_chars)
                most_common = char_counts.most_common(1)[0]
                lines.append(f"  **Most common wrong key:** `{most_common[0]}` "
                              f"({most_common[1]}/{len(actual_chars)} attempts)")
                # Physical distance from XML layout
                if k in XML_KEYS and most_common[0] in XML_KEYS:
                    t_pos = XML_KEYS[k]
                    a_pos = XML_KEYS[most_common[0]]
                    dx_mm = a_pos["center_x_mm"] - t_pos["center_x_mm"]
                    dy_mm = a_pos["center_y_mm"] - t_pos["center_y_mm"]
                    dist = np.sqrt(dx_mm**2 + dy_mm**2)
                    lines.append(f"  **Physical offset:** dx={dx_mm:+.1f}mm, dy={dy_mm:+.1f}mm ({dist:.1f}mm)")
                    if abs(dy_mm) > abs(dx_mm):
                        direction = "above (toward Fn row)" if dy_mm < 0 else "below (toward spacebar)"
                        lines.append(f"  **Likely cause:** Robot pressing {abs(dy_mm):.0f}mm too far {direction}")
                    else:
                        direction = "left (toward Esc)" if dx_mm < 0 else "right (toward Backspace)"
                        lines.append(f"  **Likely cause:** Robot pressing {abs(dx_mm):.0f}mm too far {direction}")
                lines.append("")

    # Updated calibration data
    lines.append(f"## Updated Calibration Data")
    lines.append("Keys that were corrected during testing — use these updated coordinates:")
    lines.append("```json")
    updated = {}
    for k, r in results.items():
        if r["status"] == "PASS" and r["corrections"]:
            updated[k] = r["final_coords"]
    lines.append(json.dumps(updated, indent=2))
    lines.append("```")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    return report_path


def save_gif(frames, output_path, duration=1.5):
    """Save list of PIL Images as an animated GIF."""
    if not frames:
        return None
    # Convert to consistent size
    target_size = frames[0].size
    images = []
    for frame in frames:
        if frame.size != target_size:
            frame = frame.resize(target_size, Image.LANCZOS)
        images.append(np.array(frame))

    imageio.mimsave(output_path, images, duration=duration, loop=0)
    return output_path


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    # Parse args
    max_attempts = MAX_ATTEMPTS
    specific_keys = []
    for arg in sys.argv[1:]:
        if arg.startswith("--max-attempts"):
            if "=" in arg:
                max_attempts = int(arg.split("=")[1])
        elif not arg.startswith("--"):
            specific_keys.append(arg.lower())

    # Load taught positions
    with open(TAUGHT_PATH) as f:
        taught = json.load(f)["keys"]

    # Determine which keys to test (right arm, in reach, single-char)
    if specific_keys:
        test_keys = [k for k in specific_keys if k in taught]
    else:
        test_keys = []
        for k, v in taught.items():
            coords = v["coords"][:3]
            x = coords[0]
            if -281.45 <= x <= 281.45 and len(k) == 1:
                test_keys.append(k)
        test_keys.sort()

    if not test_keys:
        print("No testable keys found!")
        return

    print(f"╔══════════════════════════════════════════════════╗")
    print(f"║       KEY ITERATION TEST WITH CALIBRATION        ║")
    print(f"╠══════════════════════════════════════════════════╣")
    print(f"║  Keys to test: {len(test_keys):3d}                              ║")
    print(f"║  Required consecutive: {REQUIRED_CONSECUTIVE}                       ║")
    print(f"║  Max attempts per key: {max_attempts:3d}                       ║")
    print(f"║  Output: {OUTPUT_DIR[-40:]:<40s} ║")
    print(f"╚══════════════════════════════════════════════════╝")
    print(f"\nTest keys: {test_keys}")

    # Check DUT
    print("\nChecking DUT connectivity...")
    r = httpx.get(f"{GAMBIT_BASE}/alive", timeout=5)
    print(f"  DUT alive: {r.text.strip()}")

    # Prepare Notepad
    print("Preparing Notepad on DUT...")
    gambit_run('/c taskkill /f /im notepad.exe 2>nul')
    time.sleep(1)
    gambit_start("notepad.exe")
    time.sleep(3)
    activate_notepad()
    time.sleep(1)

    # Connect both robots
    print("Connecting robot arms...")
    mc_r, mc_l = connect_robots()
    mc_r.set_color(255, 165, 0)
    mc_l.set_color(255, 165, 0)

    # Move both arms to safe position
    for mc in [mc_r, mc_l]:
        mc.send_coords([200, 0, SAFE_Z, 0, 180, 90], SPEED_APPROACH, 0)
    wait_arrived(mc_r, timeout=5)
    wait_arrived(mc_l, timeout=5)

    # Run tests
    results, gif_frames = run_key_test(test_keys, taught, max_attempts)

    # Return both arms home
    print("\nReturning robots to home...")
    for mc in [mc_r, mc_l]:
        mc.send_angles([0, 0, 0, 0, 0, 0], 15)
    time.sleep(5)
    for mc in [mc_r, mc_l]:
        mc.set_color(255, 255, 255)

    # Save results JSON
    results_path = os.path.join(OUTPUT_DIR, "results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {results_path}")

    # Generate report
    report_path = generate_report(results, OUTPUT_DIR)
    print(f"Report saved: {report_path}")

    # Save GIF
    if gif_frames:
        gif_path = os.path.join(OUTPUT_DIR, "demo.gif")
        save_gif(gif_frames, gif_path, duration=1.5)
        print(f"Demo GIF saved: {gif_path} ({len(gif_frames)} frames)")

    # Print summary
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    failed = sum(1 for r in results.values() if r["status"] == "FAIL")
    print(f"\n{'='*55}")
    print(f"  FINAL SUMMARY: {passed} PASS / {failed} FAIL / {len(results)} total")
    print(f"{'='*55}")

    for k in sorted(results.keys()):
        r = results[k]
        mark = "PASS" if r["status"] == "PASS" else "FAIL"
        last = r["attempts"][-1] if r["attempts"] else {}
        got = last.get("actual_char", "?")
        print(f"  [{mark}] '{k}' -> got '{got}' in {r['total_attempts']} attempts")


if __name__ == "__main__":
    main()
