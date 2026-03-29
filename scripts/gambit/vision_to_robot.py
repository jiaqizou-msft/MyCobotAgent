"""
Convert annotated pixel positions to robot coordinates.
Uses the 3 anchor keys per arm (already taught) to build pixel->robot affine.
Then maps all 78 annotated key pixels to robot coords.
"""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

# Load annotation (pixel positions from annotate_keys.py)
with open(os.path.join(DATA_DIR, "keyboard_vision_detected.json")) as f:
    vision = json.load(f)

# Load current taught data (has anchor robot coords)
with open(os.path.join(DATA_DIR, "keyboard_taught.json")) as f:
    taught = json.load(f)

# XML layout for arm assignment
with open(os.path.join(DATA_DIR, "keyboard_layout_xml.json")) as f:
    xml_data = json.load(f)

LEFT_KEYS = set("` 1 2 3 4 5 6 q w e r t y a s d f g caps tab shift_l ctrl_l fn win alt_l z x c v b".split())

# Get anchor references (robot coords from last calibration)
ref_left = taught.get("taught_reference_left", {})
ref_right = taught.get("taught_reference_right", {})

print(f"Left anchors: {list(ref_left.keys())}")
print(f"Right anchors: {list(ref_right.keys())}")

detected = vision["detected_keys"]


def fit_pixel_to_robot(anchor_keys, detected_keys):
    """Fit affine: pixel -> robot coords using anchor points."""
    A = []
    bx = []
    by = []
    for key, robot_xyz in anchor_keys.items():
        if key not in detected_keys:
            print(f"  Warning: anchor '{key}' not in detected keys")
            continue
        px = detected_keys[key]["pixel"]
        A.append([px[0], px[1], 1])
        bx.append(robot_xyz[0])
        by.append(robot_xyz[1])

    if len(A) < 3:
        print(f"  Only {len(A)} anchors — need 3 for affine, using available")

    A = np.array(A, dtype=float)
    bx = np.array(bx, dtype=float)
    by = np.array(by, dtype=float)

    if len(A) >= 3:
        mx, _, _, _ = np.linalg.lstsq(A, bx, rcond=None)
        my, _, _, _ = np.linalg.lstsq(A, by, rcond=None)
    else:
        # 2-point: pad with identity-ish
        mx, _, _, _ = np.linalg.lstsq(A, bx, rcond=None)
        my, _, _, _ = np.linalg.lstsq(A, by, rcond=None)

    return mx, my


# Fit left arm
print("\nFitting left arm pixel->robot...")
mx_l, my_l = fit_pixel_to_robot(ref_left, detected)

# Fit right arm
print("Fitting right arm pixel->robot...")
mx_r, my_r = fit_pixel_to_robot(ref_right, detected)

# Get Z values from anchors
z_left = np.mean([v[2] for v in ref_left.values()])
z_right = np.mean([v[2] for v in ref_right.values()])

# Compute all key positions
all_keys = {}
for key, kd in detected.items():
    px = kd["pixel"]
    is_left = key in LEFT_KEYS

    if is_left:
        mx, my, z, arm = mx_l, my_l, z_left, "left"
    else:
        mx, my, z, arm = mx_r, my_r, z_right, "right"

    robot_x = mx[0] * px[0] + mx[1] * px[1] + mx[2]
    robot_y = my[0] * px[0] + my[1] * px[1] + my[2]

    all_keys[key] = {
        "coords": [round(float(robot_x), 2), round(float(robot_y), 2), round(float(z), 1), 0, 180, 90],
        "arm": arm,
    }

print(f"\nComputed {len(all_keys)} keys")
print(f"  Left: {sum(1 for v in all_keys.values() if v['arm']=='left')}, Z={z_left:.1f}")
print(f"  Right: {sum(1 for v in all_keys.values() if v['arm']=='right')}, Z={z_right:.1f}")

# Verify anchors
print("\nAnchor verification:")
for key in list(ref_left.keys()) + list(ref_right.keys()):
    if key in all_keys and key in detected:
        ref = ref_left.get(key, ref_right.get(key))
        comp = all_keys[key]["coords"]
        dx = comp[0] - ref[0]
        dy = comp[1] - ref[1]
        print(f"  {key}: ref=({ref[0]:.1f},{ref[1]:.1f}) comp=({comp[0]:.1f},{comp[1]:.1f}) err=({dx:.1f},{dy:.1f})")

# Save
taught["keys"] = all_keys
taught["timestamp"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
taught["affine_model_left"] = {"mx": mx_l.tolist(), "my": my_l.tolist()}
taught["affine_model_right"] = {"mx": mx_r.tolist(), "my": my_r.tolist()}

with open(os.path.join(DATA_DIR, "keyboard_taught.json"), "w") as f:
    json.dump(taught, f, indent=2)
print("\nSaved keyboard_taught.json!")
