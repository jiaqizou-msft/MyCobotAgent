"""
Multi-camera drag-teach: teach a few reference keys, capture from all cameras
at each position, then compute the full keyboard grid.

At each taught key:
  - Record robot TCP coords (accurate ground truth)
  - Capture overhead RealSense (pixel position + depth)
  - Capture side view from Pi cam
  - Capture overview cam

Then fit a model: pixel position -> robot XY, with known Z from teaching.
"""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import json
import threading
import os

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
PI_SNAPSHOT = 'http://10.105.230.93:8080/snapshot'
os.makedirs("temp", exist_ok=True)

print("=" * 60)
print("  MULTI-CAMERA DRAG-TEACH CALIBRATION")
print("=" * 60)
print()
print("  1. Servos will be RELEASED")
print("  2. Drag finger to each key, then type key name + ENTER")
print("  3. Hold still for 3 seconds while all cameras capture")
print("  4. Teach ~6-8 keys spread across the keyboard")
print("     Recommended: q, t, a, f, z, c, 1, 4")
print("  5. Type 'done' when finished")
print()

# Connect
mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)

# Start RealSense
print("Starting RealSense...")
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
cs = profile.get_stream(rs.stream.color)
intrinsics = cs.as_video_stream_profile().get_intrinsics()
align = rs.align(rs.stream.color)
for _ in range(30):
    pipeline.wait_for_frames()
print(f"  RealSense ready. fx={intrinsics.fx:.1f}")

# Release servos
mc.power_on()
time.sleep(1)
mc.release_all_servos()
time.sleep(1)
mc.set_color(255, 50, 0)  # orange = teaching mode
print("\n*** SERVOS RELEASED ***\n")


def read_robot_stable():
    """Read robot coords with multiple retries for stable reading."""
    coords_list = []
    for _ in range(10):
        time.sleep(0.4)
        c = mc.get_coords()
        if c and c != -1 and len(c) >= 6:
            coords_list.append(c)
    if not coords_list:
        return None
    recent = coords_list[-4:] if len(coords_list) >= 4 else coords_list
    avg = [sum(x)/len(x) for x in zip(*recent)]
    return [round(v, 2) for v in avg]


def capture_all_cameras():
    """Capture from RealSense + Pi side + overview."""
    # RealSense overhead
    frames = pipeline.wait_for_frames()
    aligned_frames = align.process(frames)
    rs_color = np.asanyarray(aligned_frames.get_color_frame().get_data())
    rs_depth = np.asanyarray(aligned_frames.get_depth_frame().get_data())

    # Pi side view
    pi_img = None
    try:
        resp = httpx.get(PI_SNAPSHOT, timeout=3)
        pi_img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
    except:
        pass

    # Overview on laptop idx 3
    overview = None
    try:
        cap = cv2.VideoCapture(3, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                overview = frame
            cap.release()
    except:
        pass

    return rs_color, rs_depth, pi_img, overview


def robust_depth_at(depth_map, u, v, radius=5):
    h, w = depth_map.shape
    u = max(radius, min(w - radius - 1, int(u)))
    v = max(radius, min(h - radius - 1, int(v)))
    patch = depth_map[v-radius:v+radius+1, u-radius:u+radius+1]
    valid = patch[patch > 0].astype(float)
    if len(valid) == 0:
        return 0.0
    return float(np.median(valid)) * depth_scale


# ── Teaching Loop ──

taught_keys = {}  # key_name -> {robot_coords, rs_pixel, rs_depth, ...}

while True:
    try:
        user_input = input("Key (or 'done'): ").strip()
    except (EOFError, KeyboardInterrupt):
        break

    if not user_input:
        continue
    if user_input.lower() == 'done':
        break
    if user_input.lower() == 'show':
        for k, v in sorted(taught_keys.items()):
            rc = v['robot_coords'][:3]
            px = v.get('rs_pixel', ('?', '?'))
            print(f"  '{k}': robot=({rc[0]:.1f},{rc[1]:.1f},{rc[2]:.1f}), pixel={px}")
        continue

    key_name = user_input.lower()
    print(f"  Recording '{key_name}' — hold still...")
    time.sleep(1)

    # Read robot position (multiple reads for stability)
    robot_coords = read_robot_stable()
    if robot_coords is None:
        print(f"  WARNING: failed to read robot position!")
        continue

    # Capture all cameras
    rs_color, rs_depth, pi_img, overview = capture_all_cameras()

    # Save images
    cv2.imwrite(f"temp/teach_{key_name}_rs.jpg", rs_color)
    if pi_img is not None:
        cv2.imwrite(f"temp/teach_{key_name}_side.jpg", pi_img)
    if overview is not None:
        cv2.imwrite(f"temp/teach_{key_name}_overview.jpg", overview)

    # Try to detect the end-effector in the overhead RealSense image
    # Turn LED on briefly for detection
    mc.set_color(0, 255, 0)
    time.sleep(0.5)
    frames2 = pipeline.wait_for_frames()
    aligned2 = align.process(frames2)
    rs_color_led = np.asanyarray(aligned2.get_color_frame().get_data())

    mc.set_color(0, 0, 0)
    time.sleep(0.5)
    frames3 = pipeline.wait_for_frames()
    aligned3 = align.process(frames3)
    rs_color_off = np.asanyarray(aligned3.get_color_frame().get_data())

    mc.set_color(255, 50, 0)  # back to orange

    # LED differencing
    diff = cv2.absdiff(rs_color_led, rs_color_off)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, diff_mask = cv2.threshold(diff_gray, 15, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    diff_mask = cv2.morphologyEx(diff_mask, cv2.MORPH_OPEN, kernel)
    diff_mask = cv2.morphologyEx(diff_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(diff_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rs_pixel = None
    if contours:
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) >= 3:
            M = cv2.moments(largest)
            if M["m00"] > 0:
                rs_pixel = (int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"]))

    # Depth at the LED position
    rs_depth_val = 0
    if rs_pixel:
        rs_depth_val = robust_depth_at(rs_depth, rs_pixel[0], rs_pixel[1])

    taught_keys[key_name] = {
        "robot_coords": robot_coords,
        "rs_pixel": rs_pixel,
        "rs_depth_m": rs_depth_val,
    }

    rc = robot_coords[:3]
    print(f"  Recorded '{key_name}':")
    print(f"    Robot: ({rc[0]:.1f}, {rc[1]:.1f}, {rc[2]:.1f})")
    if rs_pixel:
        print(f"    RS pixel: {rs_pixel}, depth: {rs_depth_val*1000:.0f}mm")
    else:
        print(f"    RS pixel: not detected")


# ── Lock servos ──
print("\nLocking servos...")
mc.focus_all_servos()
time.sleep(0.5)
mc.set_color(255, 255, 255)

print(f"\n{'='*60}")
print(f"  TAUGHT {len(taught_keys)} KEYS")
print(f"{'='*60}")

# ── Compute keyboard grid model ──

# QWERTY layout
QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

# Fit robot XY as function of grid (row, col)
# [row, col, 1] @ M = [robot_x, robot_y]
A = []
B_xy = []
z_values = []
pixel_pairs = []  # (pixel, robot_xy) for the affine transform

for key, data in taught_keys.items():
    if key not in key_rc:
        continue
    r, c = key_rc[key]
    rc = data["robot_coords"]
    A.append([r, c, 1])
    B_xy.append([rc[0], rc[1]])
    z_values.append(rc[2])

    if data["rs_pixel"]:
        pixel_pairs.append((data["rs_pixel"], (rc[0], rc[1])))

A = np.array(A, dtype=float)
B_xy = np.array(B_xy, dtype=float)

if len(A) >= 3:
    M_grid, _, _, _ = np.linalg.lstsq(A, B_xy, rcond=None)
    print(f"\nGrid model:")
    print(f"  X = {M_grid[0,0]:.2f}*row + {M_grid[1,0]:.2f}*col + {M_grid[2,0]:.2f}")
    print(f"  Y = {M_grid[0,1]:.2f}*row + {M_grid[1,1]:.2f}*col + {M_grid[2,1]:.2f}")

    # Use median Z as uniform keyboard surface height
    kbd_z = float(np.median(z_values))
    print(f"  Keyboard Z: {kbd_z:.1f}mm (median of taught)")

    # Verify on taught keys
    print(f"\nVerification:")
    pred_xy = A @ M_grid
    errors = np.sqrt(np.sum((pred_xy - B_xy)**2, axis=1))
    for i, (key, data) in enumerate([(k,d) for k,d in taught_keys.items() if k in key_rc]):
        rc = data["robot_coords"]
        print(f"  '{key}': pred=({pred_xy[i][0]:.1f},{pred_xy[i][1]:.1f}) "
              f"actual=({rc[0]:.1f},{rc[1]:.1f}) err={errors[i]:.1f}mm")
    print(f"  Mean error: {np.mean(errors):.1f}mm")

    # Also fit pixel->robot affine if we have enough pixel pairs
    if len(pixel_pairs) >= 3:
        pA = np.array([[p[0], p[1], 1] for p, _ in pixel_pairs])
        pB = np.array([r for _, r in pixel_pairs])
        M_pixel, _, _, _ = np.linalg.lstsq(pA, pB, rcond=None)
        print(f"\nPixel->Robot affine also computed from {len(pixel_pairs)} pairs.")
    else:
        M_pixel = None

    # Generate ALL key positions
    all_keys = {}
    for key, (r, c) in key_rc.items():
        pred = np.array([r, c, 1]) @ M_grid
        all_keys[key] = {
            "coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90],
            "pixel": None,
            "source": "grid_model",
        }

    # Override with taught positions (ground truth)
    for key, data in taught_keys.items():
        rc = data["robot_coords"]
        all_keys[key] = {
            "coords": [rc[0], rc[1], kbd_z, 0, 180, 90],
            "pixel": data["rs_pixel"],
            "source": "taught",
        }

    # Special keys
    for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5),
                        ("backspace", 0.5, 13), ("tab", 1.5, -0.3)]:
        pred = np.array([r, c, 1]) @ M_grid
        all_keys[name] = {
            "coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90],
            "pixel": None,
            "source": "grid_model",
        }

    # Save
    output = {
        "keys": all_keys,
        "grid_model_xy": M_grid.tolist(),
        "pixel_affine": M_pixel.tolist() if M_pixel is not None else None,
        "keyboard_z": kbd_z,
        "taught_reference": {k: v for k, v in taught_keys.items()},
        "num_keys": len(all_keys),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open("keyboard_taught.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved {len(all_keys)} keys to keyboard_taught.json")

    # Print reachable keys
    reachable = [k for k, v in all_keys.items()
                 if 80 <= v["coords"][0] <= 270 and abs(v["coords"][1]) <= 200]
    print(f"Reachable: {len(reachable)} keys")
    print(f"  {', '.join(sorted(reachable))}")
else:
    print(f"\nNeed at least 3 reference keys! Only got {len(A)}.")

# Cleanup
pipeline.stop()
print("\nDone!")
