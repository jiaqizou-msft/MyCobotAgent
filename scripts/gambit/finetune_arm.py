"""
Interactive Robot Arm Fine-Tune Controller
==========================================
Nudge the robot arm position with precise increments.
Supports both left and right arms.

Controls:
  Movement (XY plane):
    W / S  — move Y+/Y- (forward/backward)
    A / D  — move X-/X+ (left/right)
  Height (Z axis):
    Q / E  — move Z+/Z- (up/down)
  Step size:
    1      — 0.5mm steps (fine)
    2      — 1.0mm steps (normal)
    3      — 2.0mm steps (coarse)
    4      — 5.0mm steps (big)
  Actions:
    P      — press key (descend, tap, release)
    G      — go to a taught key position
    T      — save current position as key correction
    H      — go home (safe position)
    L / R  — switch to left / right arm
    C      — show current coords
    X      — exit

Usage:
  python finetune_arm.py            # start with right arm
  python finetune_arm.py --left     # start with left arm
  python finetune_arm.py --key k    # go to key 'k' position first
"""

from pymycobot import MyCobot280Socket
import time
import json
import sys
import os
import msvcrt  # Windows getch

# ── Config ──────────────────────────────────────────────────────
RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
TAUGHT_PATH = os.path.join(DATA_DIR, "keyboard_taught.json")
CORRECTIONS_PATH = os.path.join(DATA_DIR, "key_corrections.json")

SAFE_Z = 200
HOVER_Z_OFFSET = 15
PRESS_Z_OFFSET = 3
PRESS_SPEED = 6
MOVE_SPEED = 15

STEP_SIZES = {
    b"1": 0.5,
    b"2": 1.0,
    b"3": 2.0,
    b"4": 5.0,
}

# ── Globals ─────────────────────────────────────────────────────
mc_right = None
mc_left = None
active_mc = None
active_arm = "right"
current_pos = [200.0, 0.0, 200.0, 0.0, 180.0, 90.0]
step_size = 1.0
taught_keys = {}
corrections = {}


def connect_arms():
    global mc_right, mc_left
    print("Connecting right arm...", end="")
    mc_right = MyCobot280Socket(RIGHT_IP, PORT)
    time.sleep(1)
    print(" OK")
    print("Connecting left arm...", end="")
    mc_left = MyCobot280Socket(LEFT_IP, PORT)
    time.sleep(1)
    print(" OK")


def read_position(mc, retries=15):
    """Read current coords with retries."""
    for _ in range(retries):
        c = mc.get_coords()
        if c and c != -1 and len(c) == 6:
            return list(c)
        time.sleep(0.3)
    return None


def move_to(mc, coords, speed=MOVE_SPEED):
    """Send coordinate command and wait."""
    mc.send_coords(coords, speed, 0)
    time.sleep(0.1)
    t0 = time.time()
    while time.time() - t0 < 3:
        try:
            if mc.is_moving() == 0:
                return
        except:
            pass
        time.sleep(0.05)


def press_at(mc, x, y, z):
    """Quick press: hover → press → release → hover."""
    hover_z = z + HOVER_Z_OFFSET
    press_z = z - PRESS_Z_OFFSET
    move_to(mc, [x, y, hover_z, 0, 180, 90], MOVE_SPEED)
    move_to(mc, [x, y, press_z, 0, 180, 90], PRESS_SPEED)
    time.sleep(0.05)
    move_to(mc, [x, y, hover_z, 0, 180, 90], PRESS_SPEED)


def display_status():
    """Print current status."""
    print(f"\r  [{active_arm.upper()}] "
          f"X={current_pos[0]:7.1f}  Y={current_pos[1]:7.1f}  Z={current_pos[2]:7.1f}  "
          f"step={step_size}mm     ", end="", flush=True)


def print_help():
    print("""
╔══════════════════════════════════════════════════════╗
║         ROBOT ARM FINE-TUNE CONTROLLER               ║
╠══════════════════════════════════════════════════════╣
║  W/S — Y+/Y- (forward/back)   Q/E — Z+/Z- (up/down)║
║  A/D — X-/X+ (left/right)                           ║
║  1=0.5mm  2=1mm  3=2mm  4=5mm    step size           ║
║  P — press key    G — go to key    T — save position ║
║  H — home         L/R — switch arm    C — read pos   ║
║  X — exit                                            ║
╚══════════════════════════════════════════════════════╝""")


def main():
    global active_mc, active_arm, current_pos, step_size, taught_keys, corrections

    # Load taught positions
    with open(TAUGHT_PATH) as f:
        taught_keys = json.load(f)["keys"]

    # Load existing corrections
    if os.path.exists(CORRECTIONS_PATH):
        with open(CORRECTIONS_PATH) as f:
            corrections = json.load(f)

    # Parse args
    start_arm = "right"
    start_key = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--left":
            start_arm = "left"
        elif arg == "--right":
            start_arm = "right"
        elif arg == "--key" and i + 1 < len(sys.argv) - 1:
            start_key = sys.argv[i + 2]

    # Connect
    connect_arms()
    active_arm = start_arm
    active_mc = mc_right if active_arm == "right" else mc_left
    active_mc.set_color(0, 255, 0)

    # Read initial position
    pos = read_position(active_mc)
    if pos:
        current_pos = pos
    print(f"Starting with {active_arm} arm at {[round(c,1) for c in current_pos[:3]]}")

    # Go to key if specified
    if start_key and start_key in taught_keys:
        key_data = taught_keys[start_key]
        coords = key_data["coords"][:3]
        print(f"Moving to key '{start_key}' at ({coords[0]:.1f}, {coords[1]:.1f}, {coords[2]:.1f})...")
        hover_z = coords[2] + HOVER_Z_OFFSET
        move_to(active_mc, [coords[0], coords[1], hover_z, 0, 180, 90])
        current_pos[:3] = [coords[0], coords[1], hover_z]

    print_help()
    display_status()

    while True:
        if msvcrt.kbhit():
            key = msvcrt.getch()

            if key == b"\xe0" or key == b"\x00":
                # Arrow key prefix — read next byte
                key2 = msvcrt.getch()
                # Map arrow keys: H=up, P=down, K=left, M=right
                if key2 == b"H":    # Up arrow = Y+
                    key = b"w"
                elif key2 == b"P":  # Down arrow = Y-
                    key = b"s"
                elif key2 == b"K":  # Left arrow = X-
                    key = b"a"
                elif key2 == b"M":  # Right arrow = X+
                    key = b"d"

            key_lower = key.lower()

            # Movement
            if key_lower == b"w":
                current_pos[1] += step_size
                move_to(active_mc, current_pos, MOVE_SPEED)
            elif key_lower == b"s":
                current_pos[1] -= step_size
                move_to(active_mc, current_pos, MOVE_SPEED)
            elif key_lower == b"a":
                current_pos[0] -= step_size
                move_to(active_mc, current_pos, MOVE_SPEED)
            elif key_lower == b"d":
                current_pos[0] += step_size
                move_to(active_mc, current_pos, MOVE_SPEED)
            elif key_lower == b"q":
                current_pos[2] += step_size
                move_to(active_mc, current_pos, MOVE_SPEED)
            elif key_lower == b"e":
                current_pos[2] -= step_size
                move_to(active_mc, current_pos, MOVE_SPEED)

            # Step size
            elif key in STEP_SIZES:
                step_size = STEP_SIZES[key]

            # Press
            elif key_lower == b"p":
                print(f"\n  Pressing at ({current_pos[0]:.1f}, {current_pos[1]:.1f}, {current_pos[2]:.1f})...")
                press_at(active_mc, current_pos[0], current_pos[1], current_pos[2] - HOVER_Z_OFFSET)
                print("  Done")

            # Go to key
            elif key_lower == b"g":
                print("\n  Enter key name: ", end="", flush=True)
                name = input().strip().lower()
                if name in taught_keys:
                    coords = taught_keys[name]["coords"][:3]
                    # Apply saved correction if exists
                    if name in corrections:
                        corr = corrections[name]
                        coords = [coords[0] + corr.get("dx", 0),
                                  coords[1] + corr.get("dy", 0),
                                  coords[2] + corr.get("dz", 0)]
                    hover_z = coords[2] + HOVER_Z_OFFSET
                    print(f"  Moving to '{name}' hover at ({coords[0]:.1f}, {coords[1]:.1f}, {hover_z:.1f})")
                    try:
                        move_to(active_mc, [coords[0], coords[1], hover_z, 0, 180, 90])
                        current_pos[:3] = [coords[0], coords[1], hover_z]
                    except Exception as ex:
                        print(f"  Move failed: {ex}")
                else:
                    print(f"  Key '{name}' not found")

            # Save correction
            elif key_lower == b"t":
                print("\n  Save correction for which key? ", end="", flush=True)
                name = input().strip().lower()
                if name in taught_keys:
                    orig = taught_keys[name]["coords"][:3]
                    # Current hover pos — Z should be hover, key Z is current - offset
                    key_z = current_pos[2] - HOVER_Z_OFFSET
                    dx = current_pos[0] - orig[0]
                    dy = current_pos[1] - orig[1]
                    dz = key_z - orig[2]
                    corrections[name] = {
                        "dx": round(dx, 2),
                        "dy": round(dy, 2),
                        "dz": round(dz, 2),
                        "corrected_coords": [
                            round(current_pos[0], 2),
                            round(current_pos[1], 2),
                            round(key_z, 2)
                        ],
                    }
                    with open(CORRECTIONS_PATH, "w") as f:
                        json.dump(corrections, f, indent=2)
                    print(f"  Saved: '{name}' correction dx={dx:+.2f} dy={dy:+.2f} dz={dz:+.2f}")
                    print(f"  New coords: ({current_pos[0]:.1f}, {current_pos[1]:.1f}, {key_z:.1f})")
                else:
                    print(f"  Key '{name}' not found")

            # Home
            elif key_lower == b"h":
                print("\n  Going home...")
                move_to(active_mc, [200, 0, SAFE_Z, 0, 180, 90])
                current_pos[:3] = [200.0, 0.0, SAFE_Z]

            # Switch arm
            elif key_lower == b"l":
                active_arm = "left"
                active_mc = mc_left
                active_mc.set_color(0, 255, 0)
                mc_right.set_color(50, 50, 50)
                pos = read_position(active_mc)
                if pos:
                    current_pos = pos
                print(f"\n  Switched to LEFT arm")

            elif key_lower == b"r":
                active_arm = "right"
                active_mc = mc_right
                active_mc.set_color(0, 255, 0)
                mc_left.set_color(50, 50, 50)
                pos = read_position(active_mc)
                if pos:
                    current_pos = pos
                print(f"\n  Switched to RIGHT arm")

            # Read current coords from robot
            elif key_lower == b"c":
                pos = read_position(active_mc)
                if pos:
                    current_pos = pos
                    print(f"\n  Read: {[round(c,1) for c in pos]}")
                else:
                    print("\n  Could not read position")

            # Exit
            elif key_lower == b"x":
                print("\n  Exiting...")
                break

            display_status()

    # Cleanup
    for mc in [mc_right, mc_left]:
        try:
            mc.set_color(255, 255, 255)
        except:
            pass
    print("\nDone. Corrections saved to:", CORRECTIONS_PATH)
    if corrections:
        print("Saved corrections:")
        for k, v in sorted(corrections.items()):
            print(f"  {k}: dx={v['dx']:+.2f}  dy={v['dy']:+.2f}  dz={v['dz']:+.2f}")


if __name__ == "__main__":
    main()
