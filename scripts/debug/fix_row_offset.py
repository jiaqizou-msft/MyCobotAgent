"""Fix: model is consistently 1 row off (hitting one row below target).
Shift all key positions by -1 row in the grid model."""
import json
import numpy as np

with open("keyboard_taught.json", "r") as f:
    data = json.load(f)

# Our model: X = 7.55*row + 15.36*col + 189.10
#             Y = -15.95*row + 0.57*col + 92.77
# Pressing 'q' (row 1) hits 'a' (row 2) → we're 1 row too far
# Fix: subtract 1 row from each position → X -= 7.55, Y += 15.95

ROW_OFFSET_X = -7.55
ROW_OFFSET_Y = 15.95

keys = data["keys"]
for key_name, key_data in keys.items():
    coords = key_data["coords"]
    coords[0] = round(coords[0] + ROW_OFFSET_X, 2)
    coords[1] = round(coords[1] + ROW_OFFSET_Y, 2)

# Update grid model offset too
M = np.array(data["grid_model_xy"])
M[2, 0] += ROW_OFFSET_X  # X offset
M[2, 1] += ROW_OFFSET_Y  # Y offset
data["grid_model_xy"] = M.tolist()
data["row_correction_applied"] = True

with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2)

print("Applied -1 row correction to all keys.")
print(f"  X offset: {ROW_OFFSET_X:+.2f}mm")
print(f"  Y offset: {ROW_OFFSET_Y:+.2f}mm")
print()

# Verify key positions
for k in ["q", "w", "e", "r", "a", "s", "d", "f", "z", "x", "c", "v", "1", "2", "3"]:
    if k in keys:
        c = keys[k]["coords"][:3]
        reach = keys[k].get("reachable", True)
        status = "✓" if reach else "✗"
        print(f"  {status} '{k}': ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")
