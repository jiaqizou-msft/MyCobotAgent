"""Fix keyboard grid model: use flat Z and refit XY from good reference points."""
import json
import numpy as np

with open("keyboard_taught.json", "r") as f:
    data = json.load(f)

# The keyboard Z is ~70mm (from q=67.6, a=71.4, z=72.5, 5=69.8)
KBD_Z = 70.0

taught = data["taught_reference"]
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

# Only use reference keys with reasonable Z (close to 70mm)
good_refs = {k: v for k, v in taught.items() if abs(v[2] - KBD_Z) < 20}
print(f"Good reference keys: {list(good_refs.keys())}")

# Fit XY model: [row, col, 1] @ M = [X, Y]
A = []
B = []
for key, xyz in good_refs.items():
    if key in key_rc:
        r, c = key_rc[key]
        A.append([r, c, 1])
        B.append([xyz[0], xyz[1]])

A = np.array(A, dtype=float)
B = np.array(B, dtype=float)
M_xy, _, _, _ = np.linalg.lstsq(A, B, rcond=None)

print(f"XY model:")
print(f"  X = {M_xy[0,0]:.2f}*row + {M_xy[1,0]:.2f}*col + {M_xy[2,0]:.2f}")
print(f"  Y = {M_xy[0,1]:.2f}*row + {M_xy[1,1]:.2f}*col + {M_xy[2,1]:.2f}")

# Verify
print("\nVerification:")
for key, xyz in good_refs.items():
    if key in key_rc:
        r, c = key_rc[key]
        pred = np.array([r, c, 1]) @ M_xy
        err = np.sqrt((pred[0]-xyz[0])**2 + (pred[1]-xyz[1])**2)
        print(f"  '{key}': pred=({pred[0]:.1f},{pred[1]:.1f}) actual=({xyz[0]:.1f},{xyz[1]:.1f}) err={err:.1f}mm")

# Regenerate all keys with flat Z
all_keys = {}
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M_xy
    all_keys[key] = {"coords": [round(pred[0],2), round(pred[1],2), KBD_Z, 0, 180, 90], "angles": None}

# Special keys
specials = [("space", 4.2, 5.5), ("enter", 2.5, 12.5), ("backspace", 0.5, 13), ("tab", 1.5, -0.3)]
for name, r, c in specials:
    pred = np.array([r, c, 1]) @ M_xy
    all_keys[name] = {"coords": [round(pred[0],2), round(pred[1],2), KBD_Z, 0, 180, 90], "angles": None}

output = {
    "keys": all_keys,
    "grid_model_xy": M_xy.tolist(),
    "keyboard_z": KBD_Z,
    "taught_reference": taught,
    "num_keys": len(all_keys),
}
with open("keyboard_taught.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nRegenerated {len(all_keys)} keys with flat Z={KBD_Z}mm")
print("\nSample positions:")
for k in ["q", "w", "e", "r", "a", "s", "d", "f", "z", "x", "space", "enter"]:
    if k in all_keys:
        c = all_keys[k]["coords"][:2]
        print(f"  '{k}': X={c[0]:.1f}, Y={c[1]:.1f}, Z={KBD_Z}")
