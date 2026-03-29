"""
Quick anchor calibration: teach 3 keys per arm, fit affine to XML layout.
Uses CachedRobot at new IPs.
"""
import json, time, sys, os, threading
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

RIGHT_IP = "192.168.0.5"  # red arm
LEFT_IP = "192.168.0.6"  # blue arm
PORT = 9000
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

# Load XML layout
with open(os.path.join(DATA_DIR, "keyboard_layout_xml.json")) as f:
    XML_KEYS = json.load(f)["keys"]

# Define which keys belong to which arm
# Left arm: left side of keyboard
# Left arm: left side + center column (6, Y, H, B included to avoid collision)
LEFT_KEYS = set("` 1 2 3 4 5 6 q w e r t y a s d f g h caps tab shift_l ctrl_l fn win alt_l z x c v b".split())
# Right arm: right side (7 onward)
RIGHT_KEYS = set(k for k in XML_KEYS if k not in LEFT_KEYS)

# Suggested anchors
LEFT_ANCHORS = ["q", "z", "6"]   # include 6 since it's now left's far edge
RIGHT_ANCHORS = ["p", "/", "9", "n"]

mc_r = CachedRobot(RIGHT_IP, PORT)
mc_l = CachedRobot(LEFT_IP, PORT)
mc_r.power_on()
mc_l.power_on()
time.sleep(1)


def read_coords_stable(mc, retries=15):
    for _ in range(retries):
        c = mc.get_coords()
        if c and c != -1 and isinstance(c, list) and len(c) >= 6:
            return [round(v, 2) for v in c]
        time.sleep(0.5)
    return None


def teach_anchors(mc, arm_name, anchor_keys):
    """Release arm, teach anchor key positions."""
    print(f"\n  {arm_name.upper()} ARM RELEASED")
    print(f"  Move finger to each key, press ENTER to record.")
    mc.release_all_servos()
    mc.set_color(255, 100, 0)
    time.sleep(0.5)

    taught = {}
    for key in anchor_keys:
        if key not in XML_KEYS:
            print(f"  '{key}' not in XML layout, skipping")
            continue
        input(f"  >>> Move to '{key}' and press ENTER...")
        mc.focus_all_servos()
        time.sleep(1)
        coords = read_coords_stable(mc)
        mc.release_all_servos()
        time.sleep(0.3)
        if coords is None:
            print(f"  FAILED to read '{key}'")
            continue
        taught[key] = coords[:3]
        print(f"  '{key}': ({coords[0]}, {coords[1]}, {coords[2]})")

    mc.focus_all_servos()
    mc.set_color(0, 255, 0)
    return taught


def fit_affine(taught, xml_keys):
    """Fit affine transform: XML mm -> robot coords."""
    A = []
    bx = []
    by = []
    for key, robot_xyz in taught.items():
        xml = xml_keys[key]
        A.append([xml["center_x_mm"], xml["center_y_mm"], 1])
        bx.append(robot_xyz[0])
        by.append(robot_xyz[1])

    A = np.array(A)
    bx = np.array(bx)
    by = np.array(by)
    mx, _, _, _ = np.linalg.lstsq(A, bx, rcond=None)
    my, _, _, _ = np.linalg.lstsq(A, by, rcond=None)
    return mx, my


def compute_all_keys(mx, my, z, arm_name, key_set):
    """Compute all key positions using affine model."""
    result = {}
    for key, xml in XML_KEYS.items():
        if key not in key_set:
            continue
        x = mx[0] * xml["center_x_mm"] + mx[1] * xml["center_y_mm"] + mx[2]
        y = my[0] * xml["center_x_mm"] + my[1] * xml["center_y_mm"] + my[2]
        result[key] = {
            "coords": [round(x, 2), round(y, 2), z, 0, 180, 90],
            "arm": arm_name
        }
    return result


print("=" * 55)
print("  QUICK ANCHOR CALIBRATION")
print("  Teach 3 keys per arm, compute all via affine")
print("=" * 55)

# STEP 1: Left arm
print("\n" + "=" * 55)
print(f"  STEP 1: LEFT arm — teach {LEFT_ANCHORS}")
print("=" * 55)
taught_left = teach_anchors(mc_l, "left", LEFT_ANCHORS)
if len(taught_left) < 3:
    print("  Need at least 3 anchors!")
    sys.exit(1)
z_left = np.mean([v[2] for v in taught_left.values()])

# Park left, do right
mc_l.send_angles([0, 0, 0, 0, 0, 0], 25)
time.sleep(3)

# STEP 2: Right arm
print("\n" + "=" * 55)
print(f"  STEP 2: RIGHT arm — teach {RIGHT_ANCHORS}")
print("=" * 55)
taught_right = teach_anchors(mc_r, "right", RIGHT_ANCHORS)
if len(taught_right) < 3:
    print("  Need at least 3 anchors!")
    sys.exit(1)
z_right = np.mean([v[2] for v in taught_right.values()])

# Fit affine models
mx_l, my_l = fit_affine(taught_left, XML_KEYS)
mx_r, my_r = fit_affine(taught_right, XML_KEYS)

# Compute all keys
all_keys = {}
all_keys.update(compute_all_keys(mx_l, my_l, round(z_left, 1), "left", LEFT_KEYS))
all_keys.update(compute_all_keys(mx_r, my_r, round(z_right, 1), "right", RIGHT_KEYS))

print(f"\nComputed {len(all_keys)} key positions")
print(f"  Left arm: {sum(1 for v in all_keys.values() if v['arm']=='left')} keys, Z={round(z_left,1)}")
print(f"  Right arm: {sum(1 for v in all_keys.values() if v['arm']=='right')} keys, Z={round(z_right,1)}")

# Save
kbd_path = os.path.join(DATA_DIR, "keyboard_taught.json")
with open(kbd_path) as f:
    kbd_data = json.load(f)
kbd_data["keys"] = all_keys
kbd_data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
kbd_data["taught_reference_left"] = taught_left
kbd_data["taught_reference_right"] = taught_right
kbd_data["affine_model_left"] = {"mx": mx_l.tolist(), "my": my_l.tolist()}
kbd_data["affine_model_right"] = {"mx": mx_r.tolist(), "my": my_r.tolist()}
with open(kbd_path, "w") as f:
    json.dump(kbd_data, f, indent=2)
print(f"Saved to {kbd_path}")

# Quick test
r = input("\nTest type ASDF? (y/n): ").strip().lower()
if r == "y":
    for ch in "ASDF":
        k = ch.lower()
        if k in all_keys:
            v = all_keys[k]
            mc = mc_l if v["arm"] == "left" else mc_r
            x, y, z = v["coords"][:3]
            print(f"  {ch} ({v['arm']})")
            mc.send_coords([x, y, z + 15, 0, 180, 90], 20, 0)
            time.sleep(1.0)
            mc.send_coords([x, y, z - 3, 0, 180, 90], 10, 0)
            time.sleep(0.5)
            mc.send_coords([x, y, z + 15, 0, 180, 90], 10, 0)
            time.sleep(0.5)
    print("  Done!")

mc_r.send_angles([0, 0, 0, 0, 0, 0], 25)
mc_l.send_angles([0, 0, 0, 0, 0, 0], 25)
mc_r.set_color(255, 255, 255)
mc_l.set_color(255, 255, 255)
print("\nCalibration complete!")
