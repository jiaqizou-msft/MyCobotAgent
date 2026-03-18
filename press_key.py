"""
Press keys on the laptop using taught positions.
Loads keyboard_taught.json and can interpolate for untaught keys.
"""
from pymycobot import MyCobot280Socket
import numpy as np
import time
import json
import sys

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
SLOW_SPEED = 8
SLIDE_SPEED = 12   # speed for lateral moves between keys
PRESS_SPEED = 6    # speed for pressing down
PRESS_DEPTH = 3    # mm below key surface
SAFE_Z = 200       # safe height above keyboard
HOVER_Z = 145      # constant hover height between keys (just above keys)
PRESS_Z_OFFSET = 3 # press this far below the key surface Z

# Load taught positions
with open("keyboard_taught.json", "r") as f:
    taught_data = json.load(f)
TAUGHT_KEYS = taught_data["keys"]
print(f"Loaded {len(TAUGHT_KEYS)} taught key positions")

# QWERTY layout for interpolation
QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]

# Build row/col lookup
KEY_GRID = {}
for r, row in enumerate(QWERTY):
    for c, key in enumerate(row):
        KEY_GRID[key] = (r, c)
# Special keys
KEY_GRID['space'] = (4, 5)
KEY_GRID['enter'] = (2, 12)
KEY_GRID['backspace'] = (0, 13)
KEY_GRID['tab'] = (1, -1)
KEY_GRID['shift'] = (3, -1)
KEY_GRID['esc'] = (-1, 0)


def get_key_position(key_name):
    """
    Get robot XYZ for a key. Uses taught position if available,
    otherwise interpolates from nearby taught keys.
    """
    key = key_name.lower()

    # Direct taught position
    if key in TAUGHT_KEYS and TAUGHT_KEYS[key]["coords"]:
        return TAUGHT_KEYS[key]["coords"][:3]

    # Interpolate from taught keys using QWERTY grid
    if key not in KEY_GRID:
        print(f"  Unknown key: '{key}'")
        return None

    target_row, target_col = KEY_GRID[key]

    # Find taught keys with known grid positions and coords
    ref_points = []
    for taught_key, data in TAUGHT_KEYS.items():
        if taught_key in KEY_GRID and data["coords"]:
            kr, kc = KEY_GRID[taught_key]
            xyz = data["coords"][:3]
            ref_points.append((kr, kc, xyz))

    if len(ref_points) < 2:
        print(f"  Not enough reference points to interpolate!")
        return None

    # Inverse-distance weighted interpolation
    weights = []
    positions = []
    for kr, kc, xyz in ref_points:
        dist = np.sqrt((target_row - kr)**2 + (target_col - kc)**2)
        if dist < 0.01:
            return xyz  # exact match
        w = 1.0 / (dist ** 2)
        weights.append(w)
        positions.append(xyz)

    weights = np.array(weights)
    positions = np.array(positions)
    weights /= weights.sum()

    interpolated = (weights[:, None] * positions).sum(axis=0)
    return interpolated.tolist()


def press_key(mc, key_name):
    """Press a single key (standalone, goes up between presses)."""
    pos = get_key_position(key_name)
    if pos is None:
        print(f"  Cannot determine position for '{key_name}'!")
        return False

    x, y, z = pos
    press_z = z - PRESS_Z_OFFSET

    # Approach from above
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], SLOW_SPEED, 0)
    time.sleep(3)

    # Press down
    mc.send_coords([x, y, press_z, 0, 180, 90], PRESS_SPEED, 0)
    time.sleep(1.5)

    # Release back to hover
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], PRESS_SPEED, 0)
    time.sleep(1.5)

    print(f"  ✓ '{key_name}'")
    return True


def type_text(mc, text):
    """
    Type a string smoothly — finger stays at hover height between keys,
    only dips down to press each key. No going back to safe_z between chars.
    
    Motion: slide laterally at hover → dip to press → lift to hover → slide to next
    """
    print(f"\n{'='*50}")
    print(f"  TYPING: '{text}'")
    print(f"{'='*50}")

    # Collect all key positions first
    keys_to_press = []
    for char in text:
        key = 'space' if char == ' ' else char.lower()
        pos = get_key_position(key)
        if pos is None:
            print(f"  WARNING: skipping unknown key '{key}'")
            continue
        keys_to_press.append((key, pos))

    if not keys_to_press:
        print("  No valid keys to press!")
        return

    # Move to hover height above first key
    first_x, first_y, first_z = keys_to_press[0][1]
    print(f"  Moving to start position...")
    mc.send_coords([first_x, first_y, HOVER_Z, 0, 180, 90], SLOW_SPEED, 0)
    time.sleep(3)

    # Press each key with smooth transitions
    for i, (key, pos) in enumerate(keys_to_press):
        x, y, z = pos
        press_z = z - PRESS_Z_OFFSET

        # Slide to above the key (stay at hover height)
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], SLIDE_SPEED, 0)
        time.sleep(1.2)

        # Quick dip to press
        mc.send_coords([x, y, press_z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(0.8)

        # Lift back to hover
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(0.8)

        print(f"  ✓ '{key}' ({i+1}/{len(keys_to_press)})")

    # Return to safe height after typing
    mc.send_coords([x, y, SAFE_Z, 0, 180, 90], SLOW_SPEED, 0)
    time.sleep(2)
    mc.send_angles([0, 0, 0, 0, 0, 0], 10)
    time.sleep(3)
    print(f"\n  Done typing '{text}'!")


if __name__ == "__main__":
    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)
    mc.set_color(255, 100, 0)  # Orange = pressing mode

    if len(sys.argv) > 1:
        # Press key(s) from command line
        target = " ".join(sys.argv[1:])
        if len(target) == 1:
            press_key(mc, target)
        else:
            type_text(mc, target)
    else:
        # Interactive mode
        print("\nInteractive key press mode.")
        print("Type a key name or text to type, or 'quit' to exit.\n")

        while True:
            cmd = input("Press key / type text: ").strip()
            if not cmd:
                continue
            if cmd.lower() == 'quit':
                break
            if len(cmd) == 1:
                press_key(mc, cmd)
            else:
                type_text(mc, cmd)

    mc.send_angles([0, 0, 0, 0, 0, 0], 10)
    time.sleep(3)
    mc.set_color(255, 255, 255)
    print("\nDone!")
