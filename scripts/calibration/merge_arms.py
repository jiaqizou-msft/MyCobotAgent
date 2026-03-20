"""Merge left arm data from earlier session with the new right arm data."""
import json
import numpy as np

# The right arm was just re-taught and saved
with open("data/keyboard_dual_arm.json") as f:
    current = json.load(f)

# Left arm taught data from the earlier session:
# q: (198.0, 47.0, 46.7), x: (231.5, 20.2, 46.9), g: (277.3, 40.6, 47.6)
# 5: (272.5, 58.0, 47.5), s: (222.3, 27.8, 47.1), caps: (181.5, 27.7, 46.7)
left_taught = {
    "q": [198.0, 47.0, 46.7],
    "x": [231.5, 20.2, 46.9],
    "g": [277.3, 40.6, 47.6],
    "5": [272.5, 58.0, 47.5],
    "s": [222.3, 27.8, 47.1],
    "caps": [181.5, 27.7, 46.7],
}

# Load annotation for pixel positions
with open("data/keyboard_vision_detected.json") as f:
    anno = json.load(f)
keys_px = anno["detected_keys"]

# Build left arm affine
A, B = [], []
for key, robot_xyz in left_taught.items():
    if key in keys_px:
        px, py = keys_px[key]["pixel"]
        A.append([px, py, 1])
        B.append([robot_xyz[0], robot_xyz[1]])

A = np.array(A, dtype=float)
B = np.array(B, dtype=float)
M_left, _, _, _ = np.linalg.lstsq(A, B, rcond=None)

pred = A @ M_left
errors = np.sqrt(np.sum((pred - B)**2, axis=1))
print(f"Left arm affine: {len(A)} points, mean error={np.mean(errors):.1f}mm")

z_left = float(np.median([v[2] for v in left_taught.values()]))

# Compute left arm keys
left_keys = {}
for key, kd in keys_px.items():
    px, py = kd["pixel"]
    robot_xy = np.array([px, py, 1]) @ M_left
    rx, ry = float(robot_xy[0]), float(robot_xy[1])
    reachable = -281 <= rx <= 281 and -200 <= ry <= 200
    left_keys[key] = {
        "pixel": kd["pixel"],
        "mm": kd.get("mm", [0, 0]),
        "robot": [round(rx, 2), round(ry, 2), z_left],
        "arm": "left",
        "reachable": reachable,
    }

# Add left arm to current data
current["arms"]["left"] = {
    "affine": M_left.tolist(),
    "kbd_z": z_left,
    "taught": {k: list(v) for k, v in left_taught.items()},
    "keys": left_keys,
}

# Re-merge: left arm handles cols 0-5 (left side), right arm handles right side
right_keys = current["arms"]["right"]["keys"]
merged = {}

# QWERTY column mapping  
QWERTY = [list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./")]
KEY_COL = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        KEY_COL[k] = c

for key in set(list(left_keys.keys()) + list(right_keys.keys())):
    col = KEY_COL.get(key, 7)  # default to middle
    
    left_ok = key in left_keys and left_keys[key]["reachable"]
    right_ok = key in right_keys and right_keys[key]["reachable"]
    
    if col <= 5 and left_ok:
        merged[key] = left_keys[key]
    elif col > 5 and right_ok:
        merged[key] = right_keys[key]
    elif left_ok:
        merged[key] = left_keys[key]
    elif right_ok:
        merged[key] = right_keys[key]

# Special keys
for key in ["space", "enter", "backspace", "tab", "caps", "shift_l", "shift_r",
            "ctrl_l", "fn", "win", "alt_l", "alt_r", "copilot", "left", "right", "up", "down",
            "esc", "del"]:
    left_ok = key in left_keys and left_keys[key]["reachable"]
    right_ok = key in right_keys and right_keys[key]["reachable"]
    if key in ("enter", "backspace", "del", "shift_r", "right", "down", "up"):
        if right_ok: merged[key] = right_keys[key]
        elif left_ok: merged[key] = left_keys[key]
    else:
        if left_ok: merged[key] = left_keys[key]
        elif right_ok: merged[key] = right_keys[key]

current["merged_keys"] = merged
current["num_merged"] = len(merged)

with open("data/keyboard_dual_arm.json", "w") as f:
    json.dump(current, f, indent=2, default=str)

# Also update keyboard_taught.json
taught_compat = {"keys": {}, "keyboard_z": z_left}
for key, kd in merged.items():
    taught_compat["keys"][key] = {
        "coords": kd["robot"] + [0, 180, 90],
        "arm": kd["arm"],
    }
with open("data/keyboard_taught.json", "w") as f:
    json.dump(taught_compat, f, indent=2)

left_count = sum(1 for v in merged.values() if v["arm"] == "left")
right_count = sum(1 for v in merged.values() if v["arm"] == "right")
print(f"\nMerged: {len(merged)} keys (left={left_count}, right={right_count})")

# Show the problem keys
for k in ["a", "enter", "z", "k"]:
    if k in merged:
        d = merged[k]
        print(f"  {k}: arm={d['arm']}, robot=({d['robot'][0]:.1f},{d['robot'][1]:.1f},{d['robot'][2]:.1f})")
