"""Rebuild the dual-arm layout from both teach sessions.
Right arm was taught: k, u, enter, power, m
Left arm was taught: d, z, g, 1
"""
import json
import numpy as np

# Right arm taught data (from the earlier session output)
right_taught = {
    "k": [263.1, -9.0, 128.4],
    "u": [277.0, -24.3, 128.4],
    "enter": [179.9, -6.8, 132.3],
    "m": [230.5, -21.9, 130.1],
}

# Left arm taught data
left_taught = {
    "d": [242.6, -2.8, 47.4],
    "z": [211.9, -18.8, 46.9],
    "g": [278.4, -3.6, 46.1],
    "1": [173.8, 23.5, 16.6],
}

QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]
KEY_RC = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        KEY_RC[k] = (r, c)


def build_model(taught, name):
    A, B = [], []
    z_vals = []
    for key, xyz in taught.items():
        if key not in KEY_RC:
            continue
        r, c = KEY_RC[key]
        A.append([r, c, 1])
        B.append([xyz[0], xyz[1]])
        z_vals.append(xyz[2])
    A = np.array(A, dtype=float)
    B = np.array(B, dtype=float)
    if len(A) < 3:
        print(f"  {name}: only {len(A)} keys, need 3+")
        return None, None
    M, _, _, _ = np.linalg.lstsq(A, B, rcond=None)
    kbd_z = float(np.median(z_vals))
    pred = A @ M
    errors = np.sqrt(np.sum((pred - B)**2, axis=1))
    print(f"  {name}: mean error={np.mean(errors):.1f}mm, Z={kbd_z:.1f}")
    print(f"    X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
    print(f"    Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")
    return M, kbd_z


# Build models
print("Building grid models...")
M_right, z_right = build_model(right_taught, "right")
M_left, z_left = build_model(left_taught, "left")

# Row stagger for QWERTY
ROW_STAGGER = {0: 0, 1: 0, 2: 0, 3: 10}

# Generate keys for each arm
def gen_keys(M, kbd_z, taught, arm_name):
    keys = {}
    for key, (r, c) in KEY_RC.items():
        pred = np.array([r, c, 1]) @ M
        stagger = ROW_STAGGER.get(r, 0)
        x = round(pred[0] + stagger, 2)
        keys[key] = {
            "coords": [x, round(pred[1], 2), kbd_z, 0, 180, 90],
            "arm": arm_name,
            "reachable": -281 <= x <= 281,
        }
    # Special keys
    for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5),
                        ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
        pred = np.array([r, c, 1]) @ M
        stagger = ROW_STAGGER.get(int(round(r)), 0)
        x = round(pred[0] + stagger, 2)
        keys[name] = {"coords": [x, round(pred[1], 2), kbd_z, 0, 180, 90], "arm": arm_name, "reachable": -281 <= x <= 281}
    # Override with taught
    for key, xyz in taught.items():
        if key in keys:
            keys[key]["coords"] = [xyz[0], xyz[1], kbd_z, 0, 180, 90]
            keys[key]["source"] = "taught"
    return keys

right_keys = gen_keys(M_right, z_right, right_taught, "right") if M_right is not None else {}
left_keys = gen_keys(M_left, z_left, left_taught, "left") if M_left is not None else {}

# Merge: left arm gets left-side keys, right arm gets right-side keys
# Split at roughly column 6 (between T/Y on QWERTY row)
merged = {}
for key in set(list(right_keys.keys()) + list(left_keys.keys())):
    rc = KEY_RC.get(key)
    if rc:
        r, c = rc
        # Left arm handles cols 0-5, right arm handles cols 6+
        if c <= 5 and key in left_keys and left_keys[key]["reachable"]:
            merged[key] = left_keys[key]
        elif c > 5 and key in right_keys and right_keys[key]["reachable"]:
            merged[key] = right_keys[key]
        elif key in left_keys and left_keys[key]["reachable"]:
            merged[key] = left_keys[key]
        elif key in right_keys and right_keys[key]["reachable"]:
            merged[key] = right_keys[key]
    else:
        # Special keys
        if key in left_keys and left_keys[key]["reachable"]:
            merged[key] = left_keys[key]
        elif key in right_keys and right_keys[key]["reachable"]:
            merged[key] = right_keys[key]

# Save
output = {
    "arms": {
        "right": {"grid_model_xy": M_right.tolist() if M_right is not None else None,
                   "keyboard_z": z_right, "taught_reference": right_taught, "keys": right_keys},
        "left": {"grid_model_xy": M_left.tolist() if M_left is not None else None,
                  "keyboard_z": z_left, "taught_reference": left_taught, "keys": left_keys},
    },
    "merged_keys": merged,
}
with open("data/keyboard_dual_arm.json", "w") as f:
    json.dump(output, f, indent=2, default=str)

# Summary
left_merged = [k for k, v in merged.items() if v["arm"] == "left"]
right_merged = [k for k, v in merged.items() if v["arm"] == "right"]
print(f"\nMerged: {len(merged)} keys total")
print(f"  Left arm ({len(left_merged)}): {sorted(left_merged)}")
print(f"  Right arm ({len(right_merged)}): {sorted(right_merged)}")
