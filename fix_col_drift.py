"""Fix column drift: keys drift left as column increases.
Q=correct, W=top-left, E=top-left, R=hit E, T=hit R, Y=hit T.
The error grows ~3-4mm per column. Column step needs to increase.
Also slight Y drift upward (toward screen).

Current model: X = 13.58*row + 17.28*col + 138.78
                Y = -16.99*row + 0.27*col + 101.97

Need to increase col step in X by ~2mm (17.28 -> 19.3)
and decrease Y offset by ~3mm (top-left drift)
"""
import json
import numpy as np

with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
kbd_z = data["keyboard_z"]

print(f"Before: X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
print(f"        Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")

# Fix 1: Increase column step in X from 17.28 to 19.3mm
# Q (col=0) was correct, but each column after shifts left
# At col=5 (T), we're ~1 full key (19mm) behind -> 19mm/5 = 3.8mm/col short
M[1, 0] = 19.3

# Fix 2: Slight Y offset - keys hitting top-left means Y is too high (too positive)
# Shift Y down by 3mm
M[2, 1] -= 3.0

print(f"After:  X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
print(f"        Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")

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

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    keys[key] = {
        "coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90],
        "source": "grid_model_v3",
    }

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5),
                    ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "grid_model_v3"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print(f"\nQWERTY row positions:")
for k in list("qwerty"):
    c = keys[k]["coords"][:2]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f})")
print(f"\n  q->w step: {keys['w']['coords'][0] - keys['q']['coords'][0]:.1f}mm")
print(f"  w->e step: {keys['e']['coords'][0] - keys['w']['coords'][0]:.1f}mm")
