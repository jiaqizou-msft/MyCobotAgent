"""Fix: 1) Increase col step slightly, 2) Add QWERTY row stagger offsets.

Real QWERTY keyboards have staggered rows:
  Number row: no offset
  Q-row: offset ~0.25 key right from number row
  A-row: offset ~0.5 key right from number row  
  Z-row: offset ~0.75 key right from number row (or ~0.25 right from A-row)

Our grid model treats all rows as aligned. We need per-row X offsets.
Row 3 hitting Shift means Z-row is ~1 key too far left -> need +19.8mm X for row 3.
"""
import json
import numpy as np

with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
kbd_z = data["keyboard_z"]

# Increase column step slightly (H still drifting left)
M[1, 0] = 20.2  # was 19.8
print(f"Column step: {M[1, 0]:.1f}mm")

data["grid_model_xy"] = M.tolist()

# QWERTY row stagger: each row is offset to the right
# Standard stagger (fraction of key width ~19mm):
#   Row 0 (numbers): 0
#   Row 1 (QWERTY):  +0.25 keys = +5mm
#   Row 2 (ASDFG):   +0.5 keys = +10mm  
#   Row 3 (ZXCVB):   +0.75 keys = +15mm
# But our model already places Q-row by fitting to taught data.
# The issue is only visible on row 3 (Z hit Shift = 1 key left).
# So the stagger correction needed for row 3 relative to what model predicts:
ROW_STAGGER_X = {
    0: 0,      # number row - baseline
    1: 0,      # Q-row - model was fitted to this
    2: 0,      # A-row - worked fine 
    3: 10.0,   # Z-row - hitting 1 key left, needs ~half-key right shift
}

QWERTY = [list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./")]
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    stagger = ROW_STAGGER_X.get(r, 0)
    keys[key] = {
        "coords": [round(pred[0] + stagger, 2), round(pred[1], 2), kbd_z, 0, 180, 90],
        "source": "v5_stagger",
    }

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13), 
                    ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    stagger = ROW_STAGGER_X.get(int(round(r)), 0)
    keys[name] = {"coords": [round(pred[0] + stagger, 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "v5_stagger"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print(f"\nRow positions (first keys):")
for row_name, row_keys in [("Numbers", "`1234"), ("QWERTY", "qwert"), ("ASDFG", "asdfg"), ("ZXCVB", "zxcvb")]:
    coords = [(k, keys[k]["coords"][0]) for k in row_keys]
    print(f"  {row_name}: {', '.join(f'{k}:{x:.0f}' for k,x in coords)}")

# Verify the stagger makes sense
print(f"\n  Q vs A vs Z at col 0: Q={keys['q']['coords'][0]:.0f}, A={keys['a']['coords'][0]:.0f}, Z={keys['z']['coords'][0]:.0f}")
print(f"  Stagger Z-A: {keys['z']['coords'][0] - keys['a']['coords'][0]:.0f}mm")
