"""Fix column spacing: expand from 15.4mm/key to 19mm/key."""
import json
import numpy as np

with open("keyboard_taught.json", "r") as f:
    data = json.load(f)

# Current model puts a→s→d at 15.4mm apart, should be ~19mm
# We know 'a' (col=0 in its row) hits correctly at X=181.3
# So expand the column step. 
# The affine X = row_coeff*row + col_coeff*col + offset
# Current col_coeff = 15.36, need ~19.0

OLD_COL_STEP = 15.36
NEW_COL_STEP = 19.0

M = np.array(data["grid_model_xy"])
print(f"Old model: X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")

# Scale the column coefficient
scale = NEW_COL_STEP / OLD_COL_STEP
M[1, 0] = NEW_COL_STEP  # X per column
# Keep Y column coefficient proportionally scaled
M[1, 1] = M[1, 1] * scale

print(f"New model: X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")

data["grid_model_xy"] = M.tolist()

# Regenerate all key positions
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

KBD_Z = data.get("keyboard_z", 70.0)

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    keys[key]["coords"] = [round(pred[0], 2), round(pred[1], 2), KBD_Z, 0, 180, 90]

# Special keys
for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13), ("tab", 1.5, -0.3)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), KBD_Z, 0, 180, 90], "angles": None}

with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"\nUpdated key positions:")
for k in ["a", "s", "d", "f", "q", "w", "e", "z", "x", "1", "2"]:
    c = keys[k]["coords"][:2]
    print(f"  '{k}': X={c[0]:.1f} Y={c[1]:.1f}")
print(f"\n  a→s step: {keys['s']['coords'][0] - keys['a']['coords'][0]:.1f}mm")
print(f"  s→d step: {keys['d']['coords'][0] - keys['s']['coords'][0]:.1f}mm")
