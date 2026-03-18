"""Small global nudge: T/Y hitting bottom-left corner. Shift +2mm X, +2mm Y."""
import json
import numpy as np

with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
M[2, 0] += 2.0  # X: shift right
M[2, 1] += 2.0  # Y: shift up (toward screen)
data["grid_model_xy"] = M.tolist()
kbd_z = data["keyboard_z"]

QWERTY = [list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./")]
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    keys[key] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "camera_measured_v3"}

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "camera_measured_v3"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print("Applied +2mm X, +2mm Y nudge")
for k in "qwerty":
    c = keys[k]["coords"][:2]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f})")
