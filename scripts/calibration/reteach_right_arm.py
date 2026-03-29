"""
Re-teach right arm key positions after end-effector change.
Uses the Ortler XML layout for precise key spacing.

Teaches 8 reference keys by dragging the arm, then computes
all right-side key positions via affine model + XML geometry.

Preserves existing left-arm data in keyboard_taught.json.
"""
from pymycobot import MyCobot280Socket
import time
import json
import os
import numpy as np

ROBOT_IP = "10.105.230.93"
ROBOT_PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
XML_LAYOUT_PATH = os.path.join(DATA_DIR, "keyboard_layout_xml.json")

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)

# Load XML layout for key positions in mm
with open(XML_LAYOUT_PATH) as f:
    xml_layout = json.load(f)
XML_KEYS = xml_layout["keys"]

# Load existing taught data (to preserve left arm keys)
if os.path.exists(TAUGHT_PATH):
    with open(TAUGHT_PATH) as f:
        existing_data = json.load(f)
    existing_keys = existing_data.get("keys", {})
else:
    existing_keys = {}


def read_position_stable():
    """Read position with long waits to ensure fresh data."""
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


print("=" * 60)
print("  RIGHT ARM RE-TEACH (new end effector)")
print("=" * 60)
print()
print("  Reference keys to teach (right side of keyboard):")
print("    8, 9, 0  (number row)")
print("    i, o, p  (QWERTY row)")
print("    k, l     (home row)")
print()
print("  Servos will be released. Drag finger to each key.")
print("  Hold still for 4 seconds while position is read.")
print()

mc.power_on()
time.sleep(1)
mc.release_all_servos()
time.sleep(1)
mc.set_color(0, 100, 255)
print("*** RIGHT ARM SERVOS RELEASED ***\n")

# Reference keys to teach — spread across the right side
KEYS_TO_TEACH = ["8", "0", "i", "p", "k", "l", ";", "/"]

taught = {}
for key in KEYS_TO_TEACH:
    xml_pos = XML_KEYS.get(key, {})
    xml_x = xml_pos.get("center_x_mm", "?")
    xml_y = xml_pos.get("center_y_mm", "?")
    input(f"\n  Drag finger to '{key}' (XML: {xml_x}mm, {xml_y}mm), press ENTER...")
    print(f"  Reading position (hold still 4s)...")
    time.sleep(1)
    coords = read_position_stable()
    if coords:
        taught[key] = coords[:3]
        print(f"  ✓ '{key}' = ({coords[0]:.1f}, {coords[1]:.1f}, {coords[2]:.1f})")
    else:
        print(f"  ⚠ Failed to read position for '{key}'!")

print(f"\n\nTaught {len(taught)} reference keys.")

# Lock servos
mc.focus_all_servos()
time.sleep(0.5)
mc.set_color(255, 200, 0)

# ── Fit affine model: XML(mm) → robot(mm) ───────────────────
# Using XML key center positions as input, robot coords as output
# Model: robot_xyz = M @ [xml_x, xml_y, 1]
A = []
B = []
for key, robot_xyz in taught.items():
    if key in XML_KEYS:
        xml_x = XML_KEYS[key]["center_x_mm"]
        xml_y = XML_KEYS[key]["center_y_mm"]
        A.append([xml_x, xml_y, 1])
        B.append(robot_xyz)

A = np.array(A, dtype=float)
B = np.array(B, dtype=float)

if len(A) < 3:
    print("Not enough reference points! Need at least 3.")
    exit(1)

M, residuals, rank, sv = np.linalg.lstsq(A, B, rcond=None)

print(f"\nAffine model (XML mm → robot mm):")
print(f"  robot_X = {M[0,0]:.4f}*kb_x + {M[1,0]:.4f}*kb_y + {M[2,0]:.2f}")
print(f"  robot_Y = {M[0,1]:.4f}*kb_x + {M[1,1]:.4f}*kb_y + {M[2,1]:.2f}")
print(f"  robot_Z = {M[0,2]:.4f}*kb_x + {M[1,2]:.4f}*kb_y + {M[2,2]:.2f}")

# Verify on taught keys
print(f"\nVerification (taught keys):")
max_err = 0
for key, robot_xyz in taught.items():
    if key in XML_KEYS:
        xml_x = XML_KEYS[key]["center_x_mm"]
        xml_y = XML_KEYS[key]["center_y_mm"]
        pred = np.array([xml_x, xml_y, 1]) @ M
        err = np.linalg.norm(pred - np.array(robot_xyz))
        max_err = max(max_err, err)
        mark = "✓" if err < 2 else "⚠"
        print(f"  {mark} '{key}': pred=({pred[0]:.1f},{pred[1]:.1f},{pred[2]:.1f}) "
              f"actual=({robot_xyz[0]:.1f},{robot_xyz[1]:.1f},{robot_xyz[2]:.1f}) err={err:.1f}mm")
print(f"  Max error: {max_err:.1f}mm")

# ── Generate all right-side key positions ────────────────────
# Right-side keys: those with XML center_x > ~130mm (roughly right half)
# Plus any key that was previously assigned to the right arm
RIGHT_KEYS = set()
for key_name, xml_data in XML_KEYS.items():
    if xml_data["center_x_mm"] > 130:
        RIGHT_KEYS.add(key_name)

# Also include keys from original taught data that were right arm
for key_name, data in existing_keys.items():
    if data.get("arm") == "right":
        RIGHT_KEYS.add(key_name)

print(f"\nGenerating {len(RIGHT_KEYS)} right-arm key positions...")

new_right_keys = {}
for key_name in sorted(RIGHT_KEYS):
    if key_name not in XML_KEYS:
        continue
    xml_x = XML_KEYS[key_name]["center_x_mm"]
    xml_y = XML_KEYS[key_name]["center_y_mm"]
    pred = np.array([xml_x, xml_y, 1]) @ M
    coords = [round(pred[0], 2), round(pred[1], 2), round(pred[2], 2), 0, 180, 90]

    # Check if within robot reach
    if -281.45 <= coords[0] <= 281.45:
        new_right_keys[key_name] = {
            "coords": coords,
            "arm": "right",
        }
    else:
        print(f"  ⚠ '{key_name}' out of reach (x={coords[0]:.1f})")

# ── Merge with existing left-arm data ────────────────────────
merged_keys = {}
for key_name, data in existing_keys.items():
    if data.get("arm") == "left":
        merged_keys[key_name] = data  # keep left arm as-is

# Add/replace right arm keys
for key_name, data in new_right_keys.items():
    merged_keys[key_name] = data

# Save
output = {
    "keys": merged_keys,
    "affine_model_right": M.tolist(),
    "taught_reference_right": taught,
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}
with open(TAUGHT_PATH, "w") as f:
    json.dump(output, f, indent=2)

left_count = sum(1 for v in merged_keys.values() if v.get("arm") == "left")
right_count = sum(1 for v in merged_keys.values() if v.get("arm") == "right")
print(f"\nSaved {len(merged_keys)} keys ({left_count} left, {right_count} right)")
print(f"File: {TAUGHT_PATH}")

# Print right-side key positions
print(f"\nRight arm key positions:")
for k in sorted(new_right_keys.keys()):
    c = new_right_keys[k]["coords"][:3]
    in_taught = "★" if k in taught else " "
    print(f"  {in_taught} '{k:5s}': ({c[0]:7.1f}, {c[1]:7.1f}, {c[2]:7.1f})")

mc.set_color(255, 255, 255)
print("\nDone! Right arm positions updated.")
