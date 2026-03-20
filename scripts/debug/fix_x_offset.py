"""Fix: Q hit Tab (1 col left). Shift X offset by +19mm (one key right)."""
import json
import numpy as np

with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
print(f"Before: X offset = {M[2,0]:.2f}")

# Shift right by one column step
M[2, 0] += 19.0

print(f"After:  X offset = {M[2,0]:.2f}")

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
    keys[key] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "camera_measured_v2"}

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "camera_measured_v2"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print(f"\nQWERTY: {', '.join(k+':'+str(round(keys[k]['coords'][0],1)) for k in 'qwerty')}")
print(f"ASDFG:  {', '.join(k+':'+str(round(keys[k]['coords'][0],1)) for k in 'asdfg')}")
