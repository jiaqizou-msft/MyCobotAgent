"""Fix: taught positions are 1 row off. Shift the model by -1 row."""
import json
import numpy as np

with open("keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
kbd_z = data["keyboard_z"]

# Model: X = 13.58*row + 17.28*col + 152.36
#         Y = -16.99*row + 0.27*col + 84.98
# Pressing s(row2,col1) hits x(row3,col1) → we're 1 row too far
# Fix: subtract 1 row's worth from the offset
# X_offset -= 13.58 (one row step in X)
# Y_offset += 16.99 (one row step in Y, since Y decreases per row)

M[2, 0] -= M[0, 0]  # X offset -= row_coeff
M[2, 1] -= M[0, 1]  # Y offset -= row_coeff (which adds since coeff is negative)

data["grid_model_xy"] = M.tolist()

print(f"Corrected grid model:")
print(f"  X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
print(f"  Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")

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

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    keys[key] = {
        "coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90],
        "source": "grid_model_corrected",
    }

# Special keys
for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5),
                    ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "grid_model_corrected"}

# Don't override with taught coords since they're the ones that were off

with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print(f"\nSample positions (corrected):")
for k in ["a", "s", "d", "f", "q", "w", "z", "x"]:
    c = keys[k]["coords"][:2]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f})")
print(f"\n  a->s step: {keys['s']['coords'][0] - keys['a']['coords'][0]:.1f}mm")
print(f"  a->q step: Y diff = {keys['q']['coords'][1] - keys['a']['coords'][1]:.1f}mm")
