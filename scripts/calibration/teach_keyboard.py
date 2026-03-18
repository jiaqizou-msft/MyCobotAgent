"""
Drag-and-teach keyboard calibration.

1. Servos released — you can drag the robot by hand
2. Continuously records position at ~5Hz
3. Press keys on THIS computer's keyboard to label positions:
   - Type any letter/number key to record that key's position
   - Press SPACE to record 'space' key position
   - Press ENTER to record 'enter' key position
   - Press ESC to finish recording
4. Saves all key positions to keyboard_taught.json

The microphone part: we'll use keyboard input instead since it's
more reliable. Just drag the finger to the key and type which key it is.
"""
from pymycobot import MyCobot280Socket
import time
import json
import os
import threading
import sys

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000

print("=" * 60)
print("  DRAG-AND-TEACH KEYBOARD CALIBRATION")
print("=" * 60)
print()
print("  1. Robot servos will be RELEASED - you can move it freely")
print("  2. Drag the fingertip to each key on the laptop keyboard")
print("  3. When the finger is touching a key, type that key here")
print("     (e.g. type 'a' when finger is on the 'a' key)")
print("  4. Special keys: type the name (space, enter, backspace, etc)")
print("  5. Type 'done' when finished")
print()

# Connect
print("Connecting to robot...")
mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)

# Power on and release servos
print("Powering on and releasing servos...")
mc.power_on()
time.sleep(1)
mc.release_all_servos()
time.sleep(1)
print("\n*** SERVOS RELEASED - You can move the robot freely! ***\n")

# Set LED to blue to indicate teaching mode
mc.set_color(0, 100, 255)

# Storage for key positions
key_positions = {}  # key_name -> {"angles": [...], "coords": [...]}

# Background thread to continuously display position
running = True
current_coords = None
current_angles = None

def position_monitor():
    global current_coords, current_angles, running
    while running:
        try:
            angles = mc.get_angles()
            time.sleep(0.2)
            coords = mc.get_coords()
            if angles and angles != -1:
                current_angles = angles
            if coords and coords != -1:
                current_coords = coords
        except:
            pass
        time.sleep(0.2)

monitor_thread = threading.Thread(target=position_monitor, daemon=True)
monitor_thread.start()

print("Position monitor started. Waiting for position data...\n")
time.sleep(2)

if current_angles:
    print(f"  Current angles: {current_angles}")
if current_coords:
    print(f"  Current coords: {current_coords}")

print("\n" + "-" * 60)
print("  Ready! Drag the finger to a key and type which key it is.")
print("  Type 'show' to see all recorded keys so far.")
print("  Type 'redo <key>' to re-record a key position.")
print("  Type 'done' to finish and save.")
print("-" * 60 + "\n")

while True:
    try:
        user_input = input("Key (or command): ").strip()
    except (EOFError, KeyboardInterrupt):
        break

    if not user_input:
        continue

    if user_input.lower() == 'done':
        break

    if user_input.lower() == 'show':
        print(f"\n  Recorded {len(key_positions)} keys:")
        for k, v in sorted(key_positions.items()):
            c = v['coords']
            if c:
                print(f"    '{k}': XYZ=({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")
            else:
                print(f"    '{k}': angles={v['angles']}")
        print()
        continue

    if user_input.lower().startswith('redo '):
        key_name = user_input[5:].strip().lower()
        if key_name in key_positions:
            del key_positions[key_name]
            print(f"  Deleted '{key_name}'. Move finger to it and type the key name again.")
        else:
            print(f"  Key '{key_name}' not found in recorded keys.")
        continue

    # Record current position for this key
    key_name = user_input.lower()

    # Read position multiple times for stability
    angles_list = []
    coords_list = []
    for _ in range(5):
        a = mc.get_angles()
        time.sleep(0.15)
        c = mc.get_coords()
        time.sleep(0.15)
        if a and a != -1:
            angles_list.append(a)
        if c and c != -1:
            coords_list.append(c)

    if angles_list:
        avg_angles = [sum(x)/len(x) for x in zip(*angles_list)]
    else:
        avg_angles = current_angles

    if coords_list:
        avg_coords = [sum(x)/len(x) for x in zip(*coords_list)]
    else:
        avg_coords = current_coords

    key_positions[key_name] = {
        "angles": [round(a, 2) for a in avg_angles] if avg_angles else None,
        "coords": [round(c, 2) for c in avg_coords] if avg_coords else None,
    }

    if avg_coords:
        print(f"  ✓ Recorded '{key_name}': XYZ=({avg_coords[0]:.1f}, {avg_coords[1]:.1f}, {avg_coords[2]:.1f})")
    elif avg_angles:
        print(f"  ✓ Recorded '{key_name}': angles={[round(a,1) for a in avg_angles]}")
    else:
        print(f"  ⚠ Recorded '{key_name}' but no position data available!")

# Finish
running = False
print(f"\n{'='*60}")
print(f"  RECORDING COMPLETE — {len(key_positions)} keys recorded")
print(f"{'='*60}")

# Lock servos back
print("Locking servos...")
mc.focus_all_servos()
time.sleep(0.5)
mc.set_color(255, 255, 255)

# Save
output = {
    "keys": key_positions,
    "num_keys": len(key_positions),
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}
with open("keyboard_taught.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\nSaved to keyboard_taught.json")

# Print summary
print(f"\nAll recorded keys:")
for k, v in sorted(key_positions.items()):
    c = v['coords']
    if c:
        print(f"  '{k}': XYZ=({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")
