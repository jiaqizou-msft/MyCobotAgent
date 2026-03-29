"""
Touchpad Teach: Drag left arm to touchpad, detect via cursor stream.
================================================================
1. Release left arm servos
2. Monitor Gambit cursor stream for movement
3. When cursor moves → arm is touching touchpad
4. Record position → save as touchpad center
5. Test swipe gestures

Run: python teach_touchpad.py
"""
import json
import time
import os
import socket
import re
import threading
import httpx
from pymycobot import MyCobot280Socket

LEFT_IP = "10.105.230.94"
PORT = 9000
GAMBIT_HOST = "192.168.0.4"
GAMBIT_PORT = 22133

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
CORRECTIONS_PATH = os.path.join(DATA_DIR, "learned_corrections.json")


def get_cursor():
    try:
        r = httpx.get(f"http://{GAMBIT_HOST}:{GAMBIT_PORT}/streams/cursor/current", timeout=5)
        return r.json()
    except:
        return None


def read_stable(mc):
    coords_list = []
    for _ in range(8):
        time.sleep(0.5)
        c = mc.get_coords()
        if c and c != -1:
            coords_list.append(c)
    if not coords_list:
        return None
    recent = coords_list[-3:] if len(coords_list) >= 3 else coords_list
    avg = [sum(x) / len(x) for x in zip(*recent)]
    return [round(v, 2) for v in avg]


print("╔═══════════════════════════════════════════╗")
print("║  TOUCHPAD TEACH — Left Arm + Cursor Stream ║")
print("╚═══════════════════════════════════════════╝")

# Connect left arm
print("\n  Connecting left arm...", end="", flush=True)
mc = MyCobot280Socket(LEFT_IP, PORT)
time.sleep(1)
mc.power_on()
time.sleep(1)
print(" OK")

# Get initial cursor position
cur_baseline = get_cursor()
if cur_baseline:
    print(f"  Cursor baseline: ({cur_baseline['X']}, {cur_baseline['Y']})")
else:
    print("  ⚠ Can't read cursor!")

# Release servos
print("\n  *** RELEASING LEFT ARM SERVOS ***")
print("  Drag the arm tip to the CENTER of the touchpad.")
print("  I'm watching the cursor stream — when it moves, I know you're there.")
print("  Press Enter when positioned on touchpad center.\n")

mc.release_all_servos()
time.sleep(1)
mc.set_color(0, 255, 255)

# Monitor cursor while waiting for Enter
cursor_moved = False
last_cursor = cur_baseline


def monitor_cursor():
    global cursor_moved, last_cursor
    while not cursor_moved:
        cur = get_cursor()
        if cur and cur_baseline:
            dx = abs(cur["X"] - cur_baseline["X"])
            dy = abs(cur["Y"] - cur_baseline["Y"])
            if dx > 10 or dy > 10:
                print(f"  >>> CURSOR MOVED! ({cur['X']}, {cur['Y']}) — touchpad contact detected!")
                last_cursor = cur
                cursor_moved = True
        time.sleep(0.5)


monitor_thread = threading.Thread(target=monitor_cursor, daemon=True)
monitor_thread.start()

input("  → Press ENTER when arm is on touchpad center...")

# Stop monitoring
cursor_moved = True
time.sleep(0.5)

# Read arm position
print("\n  Reading arm position (hold still 4s)...", end="", flush=True)
time.sleep(1)
coords = read_stable(mc)

# Lock servos
mc.focus_all_servos()
time.sleep(0.5)

if coords:
    tp_x, tp_y, tp_z = coords[0], coords[1], coords[2]
    print(f" ({tp_x:.1f}, {tp_y:.1f}, {tp_z:.1f})")

    # Get cursor position
    cur_now = get_cursor()
    if cur_now:
        print(f"  Cursor at: ({cur_now['X']}, {cur_now['Y']})")

    # Save touchpad position
    learned = {}
    if os.path.exists(CORRECTIONS_PATH):
        with open(CORRECTIONS_PATH) as f:
            learned = json.load(f)

    learned["__touchpad__"] = {
        "center": [tp_x, tp_y, tp_z],
        "arm": "left",
        "cursor_at_center": [cur_now["X"], cur_now["Y"]] if cur_now else None,
    }
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(learned, f, indent=2)
    print(f"\n  ✓ Touchpad center saved: ({tp_x:.1f}, {tp_y:.1f}, {tp_z:.1f})")

    # Test: swipe up
    print("\n  Testing swipe UP...")
    mc.set_color(255, 165, 0)
    hover_z = tp_z + 15
    touch_z = tp_z - 3
    swipe_dist = 20

    # Get cursor before
    cur_before = get_cursor()

    # Move to start
    mc.send_coords([tp_x, tp_y + swipe_dist/2, hover_z, 0, 180, 90], 15, 0)
    time.sleep(1.5)
    # Touch down
    mc.send_coords([tp_x, tp_y + swipe_dist/2, touch_z, 0, 180, 90], 8, 0)
    time.sleep(0.5)
    # Swipe
    mc.send_coords([tp_x, tp_y - swipe_dist/2, touch_z, 0, 180, 90], 5, 0)
    time.sleep(1.0)
    # Lift
    mc.send_coords([tp_x, tp_y - swipe_dist/2, hover_z, 0, 180, 90], 10, 0)
    time.sleep(0.5)

    # Check cursor
    cur_after = get_cursor()
    if cur_before and cur_after:
        dx = cur_after["X"] - cur_before["X"]
        dy = cur_after["Y"] - cur_before["Y"]
        print(f"  Cursor: ({cur_before['X']},{cur_before['Y']}) → ({cur_after['X']},{cur_after['Y']})")
        print(f"  Movement: dx={dx}, dy={dy}")
        if abs(dx) > 5 or abs(dy) > 5:
            print(f"  ✓ SWIPE DETECTED!")
        else:
            print(f"  ✗ No movement — swipe may need adjustment")

    # Test: swipe down
    print("\n  Testing swipe DOWN...")
    cur_before = get_cursor()
    mc.send_coords([tp_x, tp_y - swipe_dist/2, hover_z, 0, 180, 90], 15, 0)
    time.sleep(1.5)
    mc.send_coords([tp_x, tp_y - swipe_dist/2, touch_z, 0, 180, 90], 8, 0)
    time.sleep(0.5)
    mc.send_coords([tp_x, tp_y + swipe_dist/2, touch_z, 0, 180, 90], 5, 0)
    time.sleep(1.0)
    mc.send_coords([tp_x, tp_y + swipe_dist/2, hover_z, 0, 180, 90], 10, 0)
    time.sleep(0.5)

    cur_after = get_cursor()
    if cur_before and cur_after:
        dx = cur_after["X"] - cur_before["X"]
        dy = cur_after["Y"] - cur_before["Y"]
        print(f"  Cursor: ({cur_before['X']},{cur_before['Y']}) → ({cur_after['X']},{cur_after['Y']})")
        print(f"  Movement: dx={dx}, dy={dy}")
        if abs(dx) > 5 or abs(dy) > 5:
            print(f"  ✓ SWIPE DETECTED!")
        else:
            print(f"  ✗ No movement")

else:
    print(" FAILED to read position!")

# Home
mc.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(3)
mc.set_color(255, 255, 255)
print("\nDone!")
