"""Fix: G hits F (col step too small), B not pressed (out of reach?), add speed modes."""
import json
import numpy as np

with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
kbd_z = data["keyboard_z"]

print(f"Before: col_step_X = {M[1,0]:.2f}")

# G is at col=4 in ASDF row. It hit F (col=3). Error = ~19mm at col 4.
# Per-column error = ~19/4 = ~4.75mm. But it hit right side of F, so maybe ~10mm off.
# col_step needs increase: 18.98 + (10/4) = ~21.5? That seems too much.
# Actually G hit "right side of F", so it's maybe 5-8mm short at col 4.
# That's 5-8mm / 4 cols = 1.3-2mm per col short.
# New col step: 18.98 + 1.5 = ~20.5mm
# But also T/Y were slightly left-of-center, confirming the drift.
# Let's try 19.8mm — conservative increase.
M[1, 0] = 19.8

print(f"After:  col_step_X = {M[1,0]:.2f}")

data["grid_model_xy"] = M.tolist()

# Regenerate
QWERTY = [list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./")]
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    keys[key] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "v4"}

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "v4"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

# Check B reachability
b_coords = keys['b']['coords'][:3]
print(f"\n'b' position: ({b_coords[0]:.1f}, {b_coords[1]:.1f}, {b_coords[2]:.1f})")
print(f"  X in range [-281, 281]? {'YES' if -281 <= b_coords[0] <= 281 else 'NO - OUT OF REACH'}")

print(f"\nAll rows:")
for row_keys in ["qwerty", "asdfgh", "zxcvb"]:
    positions = [(k, keys[k]['coords'][0]) for k in row_keys]
    print(f"  {''.join(row_keys).upper()}: {', '.join(f'{k}:{x:.0f}' for k,x in positions)}")
