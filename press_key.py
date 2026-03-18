"""
Press keys on the laptop using taught positions.
Supports slow/medium/fast speed modes.

Usage:
  python press_key.py sad                # type 'sad' at slow speed
  python press_key.py --fast qwerty      # type at fast speed
  python press_key.py --medium hello     # type at medium speed
"""
from pymycobot import MyCobot280Socket
import numpy as np
import time
import json
import sys
import os

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000

# Speed profiles
PROFILES = {
    "slow": {"slide": 12, "press": 6, "approach": 8,
             "slide_wait": 1.5, "press_wait": 1.2, "release_wait": 1.0, "start_wait": 3},
    "medium": {"slide": 20, "press": 12, "approach": 15,
               "slide_wait": 0.8, "press_wait": 0.6, "release_wait": 0.5, "start_wait": 2},
    "fast": {"slide": 30, "press": 20, "approach": 20,
             "slide_wait": 0.5, "press_wait": 0.4, "release_wait": 0.3, "start_wait": 1.5},
}

SAFE_Z = 200
HOVER_Z = 145
PRESS_Z_OFFSET = 3

# Load taught positions
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
with open(os.path.join(DATA_DIR, "keyboard_taught.json"), "r") as f:
    taught_data = json.load(f)
TAUGHT_KEYS = taught_data["keys"]
print(f"Loaded {len(TAUGHT_KEYS)} key positions")

# QWERTY grid for interpolation
QWERTY = [list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./")]
KEY_GRID = {}
for r, row in enumerate(QWERTY):
    for c, key in enumerate(row):
        KEY_GRID[key] = (r, c)
KEY_GRID['space'] = (4, 5)
KEY_GRID['enter'] = (2, 12)
KEY_GRID['backspace'] = (0, 13)
KEY_GRID['tab'] = (1, -1)
KEY_GRID['esc'] = (-1, 0)


def get_key_position(key_name):
    key = key_name.lower()
    if key in TAUGHT_KEYS and TAUGHT_KEYS[key].get("coords"):
        return TAUGHT_KEYS[key]["coords"][:3]
    if key not in KEY_GRID:
        return None
    target_row, target_col = KEY_GRID[key]
    ref_points = []
    for tk, data in TAUGHT_KEYS.items():
        if tk in KEY_GRID and data.get("coords"):
            kr, kc = KEY_GRID[tk]
            ref_points.append((kr, kc, data["coords"][:3]))
    if len(ref_points) < 2:
        return None
    weights, positions = [], []
    for kr, kc, xyz in ref_points:
        dist = np.sqrt((target_row - kr)**2 + (target_col - kc)**2)
        if dist < 0.01:
            return xyz
        weights.append(1.0 / (dist ** 2))
        positions.append(xyz)
    weights = np.array(weights)
    positions = np.array(positions)
    weights /= weights.sum()
    return (weights[:, None] * positions).sum(axis=0).tolist()


def press_key(mc, key_name, sp):
    pos = get_key_position(key_name)
    if pos is None:
        print(f"  Skipping '{key_name}' (unknown)")
        return False
    x, y, z = pos
    if not (-281 <= x <= 281):
        print(f"  Skipping '{key_name}' (out of reach X={x:.0f})")
        return False
    press_z = z - PRESS_Z_OFFSET
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], sp["approach"], 0)
    time.sleep(sp["start_wait"])
    mc.send_coords([x, y, press_z, 0, 180, 90], sp["press"], 0)
    time.sleep(sp["press_wait"])
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], sp["press"], 0)
    time.sleep(sp["release_wait"])
    print(f"  ✓ '{key_name}'")
    return True


def type_text(mc, text, sp):
    print(f"\n{'='*50}")
    print(f"  TYPING: '{text}' [{sp_name}]")
    print(f"{'='*50}")

    keys = []
    for ch in text:
        k = 'space' if ch == ' ' else ch.lower()
        pos = get_key_position(k)
        if pos is None:
            print(f"  Skipping '{k}' (unknown)")
            continue
        x, y, z = pos
        if not (-281 <= x <= 281):
            print(f"  Skipping '{k}' (out of reach)")
            continue
        keys.append((k, pos))

    if not keys:
        print("  No valid keys!")
        return

    # Move to first key
    x, y, z = keys[0][1]
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], sp["approach"], 0)
    time.sleep(sp["start_wait"])

    for i, (key, (x, y, z)) in enumerate(keys):
        press_z = z - PRESS_Z_OFFSET
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], sp["slide"], 0)
        time.sleep(sp["slide_wait"])
        mc.send_coords([x, y, press_z, 0, 180, 90], sp["press"], 0)
        time.sleep(sp["press_wait"])
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], sp["press"], 0)
        time.sleep(sp["release_wait"])
        print(f"  ✓ '{key}' ({i+1}/{len(keys)})")

    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], sp["approach"], 0)
    time.sleep(2)
    mc.send_angles([0, 0, 0, 0, 0, 0], 10)
    time.sleep(3)
    print(f"\n  Done typing '{text}'!")


if __name__ == "__main__":
    # Parse speed flag
    sp_name = "slow"
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for a in sys.argv[1:]:
        if a in ("--fast", "--medium", "--slow"):
            sp_name = a[2:]
    sp = PROFILES[sp_name]

    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)
    mc.set_color(255, 100, 0)

    if args:
        target = " ".join(args)
        if len(target) == 1:
            press_key(mc, target, sp)
        else:
            type_text(mc, target, sp)
    else:
        print(f"\nInteractive mode [{sp_name}]. Type text or 'quit'.\n")
        while True:
            cmd = input("Type: ").strip()
            if not cmd or cmd == "quit":
                break
            if len(cmd) == 1:
                press_key(mc, cmd, sp)
            else:
                type_text(mc, cmd, sp)

    mc.send_angles([0, 0, 0, 0, 0, 0], 10)
    time.sleep(3)
    mc.set_color(255, 255, 255)
    print("Done!")
