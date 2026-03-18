"""
Quick keyboard re-teach with better position reading.
Teaches just a few reference keys (corners + center), then computes
the full keyboard grid geometrically.

Release servos, you drag to each key, then we wait and read multiple times
with long delays to get fresh coords.
"""
from pymycobot import MyCobot280Socket
import time
import json
import numpy as np

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)

def read_position_stable():
    """Read position with long waits to ensure fresh data."""
    coords_list = []
    for _ in range(8):
        time.sleep(0.5)
        c = mc.get_coords()
        if c and c != -1:
            coords_list.append(c)
    if not coords_list:
        return None
    # Use the last few readings (most fresh)
    recent = coords_list[-3:] if len(coords_list) >= 3 else coords_list
    avg = [sum(x)/len(x) for x in zip(*recent)]
    return [round(v, 2) for v in avg]

print("=" * 60)
print("  KEYBOARD RE-TEACH (stable readings)")
print("=" * 60)
print()
print("  Servos will be released. Drag the finger to each key.")
print("  Wait until it says 'Ready' before moving to the next key.")
print()

mc.power_on()
time.sleep(1)
mc.release_all_servos()
time.sleep(1)
mc.set_color(0, 100, 255)
print("*** SERVOS RELEASED ***\n")

# We'll teach these reference keys to establish the grid
KEYS_TO_TEACH = [
    "q",    # top-left area
    "p",    # top-right area
    "a",    # middle-left
    "l",    # middle-right
    "z",    # bottom-left
    "/",    # bottom-right (or 'm')
    "g",    # center key
    "5",    # number row center
]

taught = {}

for key in KEYS_TO_TEACH:
    input(f"\n  Drag finger to '{key}' key, then press ENTER here...")
    print(f"  Reading position (hold still for 4 seconds)...")
    time.sleep(1)  # settle
    coords = read_position_stable()
    if coords:
        taught[key] = coords[:3]  # X, Y, Z
        print(f"  ✓ '{key}' = ({coords[0]:.1f}, {coords[1]:.1f}, {coords[2]:.1f})")
    else:
        print(f"  ⚠ Failed to read position for '{key}'!")

print(f"\n\nTaught {len(taught)} reference keys.")

# Lock servos
mc.focus_all_servos()
time.sleep(0.5)
mc.set_color(255, 255, 255)

# Now compute the full keyboard grid
# QWERTY layout with row/col indices
QWERTY = [
    list("`1234567890-="),       # row 0 (number row)
    list("qwertyuiop[]\\"),      # row 1
    list("asdfghjkl;'"),         # row 2
    list("zxcvbnm,./"),          # row 3
]

# Build row/col for each key
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

# Fit a linear model: [row, col, 1] → [X, Y, Z]
# Using the taught reference keys
A = []
B = []
for key, xyz in taught.items():
    if key in key_rc:
        r, c = key_rc[key]
        A.append([r, c, 1])
        B.append(xyz)

A = np.array(A, dtype=float)
B = np.array(B, dtype=float)

if len(A) >= 3:
    # Least squares: A @ M = B  →  M is 3x3
    M, residuals, rank, sv = np.linalg.lstsq(A, B, rcond=None)

    print(f"\nGrid model (row,col → X,Y,Z):")
    print(f"  X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
    print(f"  Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")
    print(f"  Z = {M[0,2]:.2f}*row + {M[1,2]:.2f}*col + {M[2,2]:.2f}")

    # Verify on taught keys
    print(f"\nVerification:")
    for key, xyz in taught.items():
        if key in key_rc:
            r, c = key_rc[key]
            pred = np.array([r, c, 1]) @ M
            err = np.linalg.norm(pred - np.array(xyz))
            print(f"  '{key}' rc=({r},{c}): pred=({pred[0]:.1f},{pred[1]:.1f},{pred[2]:.1f}) "
                  f"actual=({xyz[0]:.1f},{xyz[1]:.1f},{xyz[2]:.1f}) err={err:.1f}mm")

    # Generate ALL key positions
    all_keys = {}
    for key, (r, c) in key_rc.items():
        pred = np.array([r, c, 1]) @ M
        all_keys[key] = {
            "coords": [round(pred[0], 2), round(pred[1], 2), round(pred[2], 2), 0, 180, 90],
            "angles": None,
            "row": r,
            "col": c,
        }

    # Add special keys
    # Space bar: row 4, col ~5
    pred = np.array([4, 5, 1]) @ M
    all_keys["space"] = {"coords": [round(pred[0], 2), round(pred[1], 2), round(pred[2], 2), 0, 180, 90], "angles": None}

    # Enter: row 2, col ~12
    pred = np.array([2, 12, 1]) @ M
    all_keys["enter"] = {"coords": [round(pred[0], 2), round(pred[1], 2), round(pred[2], 2), 0, 180, 90], "angles": None}

    # Backspace: row 0, col ~13
    pred = np.array([0, 13, 1]) @ M
    all_keys["backspace"] = {"coords": [round(pred[0], 2), round(pred[1], 2), round(pred[2], 2), 0, 180, 90], "angles": None}

    # Save
    output = {
        "keys": all_keys,
        "grid_model": M.tolist(),
        "taught_reference": {k: v for k, v in taught.items()},
        "num_keys": len(all_keys),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open("keyboard_taught.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved {len(all_keys)} key positions to keyboard_taught.json")

    # Print some key positions
    print(f"\nSample key positions:")
    for k in ['q', 'a', 'z', 'p', 'l', '/', 'space', 'enter']:
        if k in all_keys:
            c = all_keys[k]['coords'][:3]
            print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")

else:
    print("\nNot enough reference points for grid model!")
    # Just save what we have
    all_keys = {}
    for key, xyz in taught.items():
        all_keys[key] = {"coords": list(xyz) + [0, 180, 90], "angles": None}
    output = {"keys": all_keys, "num_keys": len(all_keys), "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open("keyboard_taught.json", "w") as f:
        json.dump(output, f, indent=2)

print("\nDone!")
