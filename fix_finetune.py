"""Fine-tune: ASDFG skews left (+2mm X), ZXCVB skews bottom-left (+3mm X, +2mm Y)."""
import json
import numpy as np

with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
kbd_z = data["keyboard_z"]

# Per-row corrections on top of existing stagger
# Row 0 (numbers): fine
# Row 1 (QWERTY): fine  
# Row 2 (ASDFG): +2mm X
# Row 3 (ZXCVB): +3mm X, +2mm Y
ROW_CORRECTIONS = {
    0: (0, 0),
    1: (0, 0),
    2: (2, 0),
    3: (3, 2),  # (dX, dY)
}

# Previous stagger values
ROW_STAGGER_X = {0: 0, 1: 0, 2: 0, 3: 10.0}

QWERTY = [list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./")]
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    stagger = ROW_STAGGER_X.get(r, 0)
    corr_x, corr_y = ROW_CORRECTIONS.get(r, (0, 0))
    keys[key] = {
        "coords": [round(pred[0] + stagger + corr_x, 2), round(pred[1] + corr_y, 2), kbd_z, 0, 180, 90],
        "source": "v6_finetuned",
    }

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13),
                    ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    ri = int(round(r))
    pred = np.array([r, c, 1]) @ M
    stagger = ROW_STAGGER_X.get(ri, 0)
    corr_x, corr_y = ROW_CORRECTIONS.get(ri, (0, 0))
    keys[name] = {"coords": [round(pred[0] + stagger + corr_x, 2), round(pred[1] + corr_y, 2), kbd_z, 0, 180, 90], "source": "v6_finetuned"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print("Applied per-row corrections:")
for rn, rk in [("QWERTY", "qwerty"), ("ASDFGH", "asdfgh"), ("ZXCVB", "zxcvb")]:
    parts = []
    for k in rk:
        cx = keys[k]["coords"][0]
        cy = keys[k]["coords"][1]
        parts.append(f"{k}:({cx:.0f},{cy:.0f})")
    print(f"  {rn}: {', '.join(parts)}")
