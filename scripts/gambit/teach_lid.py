"""
Teach Lid Open/Close — Continuous Drag Recording
=================================================
Uses CachedRobot (robot_cache_server on Pi) for reliable angle reads.
Angles are cached at 10Hz on the Pi, so reads work with released servos.

Flow:
  1. Release BOTH arms — drag them along the lid path
  2. Press Enter to START recording, drag smoothly
  3. Press Enter to STOP
  4. Saves dual-arm trajectory for synchronized replay

Usage:
  python teach_lid.py
"""
import json
import time
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
ACTIONS_PATH = os.path.join(DATA_DIR, "taught_actions.json")

# Load existing actions
actions = {}
if os.path.exists(ACTIONS_PATH):
    with open(ACTIONS_PATH) as f:
        actions = json.load(f)

print("╔═══════════════════════════════════════════╗")
print("║  TEACH LID — Continuous Drag Recording    ║")
print("║  Both arms, cached angle reads            ║")
print("╚═══════════════════════════════════════════╝")

# Connect both arms via cache server
print("\n  Connecting arms (cache server)...")
mc_r = CachedRobot(RIGHT_IP, PORT)
mc_r.power_on()
time.sleep(1)

mc_l = CachedRobot(LEFT_IP, PORT)
mc_l.power_on()
time.sleep(1)

# Wait for cache to warm up
print("  Waiting for angle cache...")
for _ in range(20):
    a = mc_r.get_angles()
    if a and a != -1:
        break
    time.sleep(0.5)
print("  Both arms connected")

# Select action
print("\n  Which action?")
print("    1. Open lid")
print("    2. Close lid")
choice = input("  Enter 1 or 2: ").strip()
action_name = "open_lid" if choice == "1" else "close_lid"

# Release both arms
print(f"\n  *** BOTH ARMS RELEASED ***")
print(f"  Position both arms on the lid edge.")
print(f"  Press ENTER to START recording, then drag smoothly.")
print(f"  Press ENTER again to STOP recording.\n")

mc_r.release_all_servos()
mc_l.release_all_servos()
time.sleep(1)
mc_r.set_color(255, 100, 0)
mc_l.set_color(255, 100, 0)

input("  → Position arms on lid, press ENTER to START recording...")

print("  *** RECORDING — drag now! ***")
mc_r.set_color(255, 0, 0)
mc_l.set_color(255, 0, 0)

# Record continuously — angles come from Pi-side cache, no servo lock needed
recording = True
waypoints_r = []
waypoints_l = []


def record_loop():
    while recording:
        a_r = mc_r.get_angles()
        a_l = mc_l.get_angles()
        if (a_r and a_r != -1 and isinstance(a_r, list) and len(a_r) == 6
                and a_l and a_l != -1 and isinstance(a_l, list) and len(a_l) == 6):
            waypoints_r.append([round(v, 2) for v in a_r])
            waypoints_l.append([round(v, 2) for v in a_l])
        time.sleep(0.1)


rec_thread = threading.Thread(target=record_loop, daemon=True)
rec_thread.start()

input("  → Press ENTER to STOP recording...")
recording = False
time.sleep(0.3)

# Lock servos
mc_r.focus_all_servos()
mc_l.focus_all_servos()
time.sleep(0.5)
mc_r.set_color(0, 255, 0)
mc_l.set_color(0, 255, 0)

print(f"\n  Recorded {len(waypoints_r)} raw samples ({len(waypoints_r)/10:.1f}s)")

if len(waypoints_r) < 3:
    print("  Too few waypoints!")
    sys.exit(1)

# Downsample to ~20 waypoints for smooth replay
step = max(1, len(waypoints_r) // 20)
wp_r = waypoints_r[::step]
wp_l = waypoints_l[::step]
if waypoints_r[-1] != wp_r[-1]:
    wp_r.append(waypoints_r[-1])
    wp_l.append(waypoints_l[-1])

print(f"  Downsampled to {len(wp_r)} waypoints")
actions[action_name] = {
    "type": "dual_arm_trajectory",
    "right_waypoints": wp_r,
    "left_waypoints": wp_l,
    "num_waypoints": len(wp_r),
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}
with open(ACTIONS_PATH, "w") as f:
    json.dump(actions, f, indent=2)
print(f"  Saved '{action_name}' to {ACTIONS_PATH}")

# Replay
replay = input("\n  Replay the action? (y/n): ").strip().lower()
if replay == "y":
    print(f"\n  Replaying '{action_name}'...")
    mc_r.set_color(0, 255, 255)
    mc_l.set_color(0, 255, 255)

    speed = 20
    for i, (wr, wl) in enumerate(zip(wp_r, wp_l)):
        print(f"    {i+1}/{len(wp_r)}")
        mc_r.send_angles(wr, speed)
        mc_l.send_angles(wl, speed)
        time.sleep(0.5)

    print("  Replay complete!")

# Also save the reverse as the opposite action
reverse_name = "close_lid" if action_name == "open_lid" else "open_lid"
do_reverse = input(f"\n  Save reverse as '{reverse_name}'? (y/n): ").strip().lower()
if do_reverse == "y":
    actions[reverse_name] = {
        "type": "dual_arm_trajectory",
        "right_waypoints": list(reversed(wp_r)),
        "left_waypoints": list(reversed(wp_l)),
        "num_waypoints": len(wp_r),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(ACTIONS_PATH, "w") as f:
        json.dump(actions, f, indent=2)
    print(f"  Saved '{reverse_name}' (reversed)")

# Home
mc_r.send_angles([0, 0, 0, 0, 0, 0], 15)
mc_l.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(3)
mc_r.set_color(255, 255, 255)
mc_l.set_color(255, 255, 255)
print("\nDone!")
