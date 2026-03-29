"""
Teach lid open/close using left arm through the hoop.
Right arm parks at home. Records continuous drag trajectory.
Auto-saves reverse as the opposite action.
"""
import json, time, sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

mc_r = CachedRobot("10.105.230.93", 9000)
mc_l = CachedRobot("10.105.230.94", 9000)
mc_r.power_on()
mc_l.power_on()
time.sleep(1)

# Park right arm at home
print("Moving right arm to home (out of way)...")
mc_r.send_angles([0, 0, 0, 0, 0, 0], 25)
mc_r.set_color(0, 0, 255)
time.sleep(3)
right_safe = mc_r.get_angles()
print(f"Right arm parked: {right_safe}")

# Select action (can pass as arg: python teach_hoop_lid.py close or open)
if len(sys.argv) > 1 and sys.argv[1] in ("close", "open", "1", "2"):
    choice = "1" if sys.argv[1] in ("close", "1") else "2"
else:
    print("\n  Which action to teach?")
    print("    1. Close lid (drag from open -> closed)")
    print("    2. Open lid  (drag from closed -> open)")
    choice = input("  Enter 1 or 2: ").strip()
action_name = "close_lid" if choice == "1" else "open_lid"
reverse_name = "open_lid" if choice == "1" else "close_lid"
print(f"\n  Teaching: {action_name}")

# Release left arm
print()
print("=" * 55)
print("  LEFT ARM RELEASED")
print(f"  Recording: {action_name}")
print("  1. Thread the end effector through the hoop")
print(f"  2. Position at the START of the {action_name} motion")
print("  3. Press ENTER to start recording")
print("  4. Drag smoothly through the motion")
print("  5. Press ENTER to stop")
print("=" * 55)
mc_l.release_all_servos()
mc_l.set_color(255, 100, 0)
time.sleep(0.5)

input(f"\n>>> Position left arm for {action_name}, press ENTER to START recording...")

print("*** RECORDING — drag now! ***")
mc_l.set_color(255, 0, 0)

recording = True
waypoints_l = []

def record_loop():
    while recording:
        a = mc_l.get_angles()
        if a and a != -1 and isinstance(a, list) and len(a) == 6:
            waypoints_l.append([round(v, 2) for v in a])
        time.sleep(0.1)

t = threading.Thread(target=record_loop, daemon=True)
t.start()
input(">>> Press ENTER to STOP recording...")
recording = False
time.sleep(0.3)

mc_l.focus_all_servos()
mc_l.set_color(0, 255, 0)

print(f"\nRecorded {len(waypoints_l)} samples ({len(waypoints_l)/10:.1f}s)")

if len(waypoints_l) < 3:
    print("Too few samples!")
    sys.exit(1)

# Downsample to ~20 waypoints
step = max(1, len(waypoints_l) // 20)
wp_l = waypoints_l[::step]
if waypoints_l[-1] != wp_l[-1]:
    wp_l.append(waypoints_l[-1])
wp_r = [right_safe] * len(wp_l)

print(f"Downsampled to {len(wp_l)} waypoints")

# Save
actions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "taught_actions.json")
actions = {}
if os.path.exists(actions_path):
    with open(actions_path) as f:
        actions = json.load(f)

actions[action_name] = {
    "type": "dual_arm_trajectory",
    "right_waypoints": wp_r,
    "left_waypoints": wp_l,
    "num_waypoints": len(wp_l),
    "method": "left_arm_hoop",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}
actions[reverse_name] = {
    "type": "dual_arm_trajectory",
    "right_waypoints": wp_r,
    "left_waypoints": list(reversed(wp_l)),
    "num_waypoints": len(wp_l),
    "method": "left_arm_hoop_reverse",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}
with open(actions_path, "w") as f:
    json.dump(actions, f, indent=2)
print(f"Saved '{action_name}' + '{reverse_name}' (reversed)!")

# Replay
replay = input(f"\nReplay {action_name}? (y/n): ").strip().lower()
if replay == "y":
    print(f"Replaying {action_name}...")
    mc_l.set_color(0, 255, 255)
    for i, wl in enumerate(wp_l):
        print(f"  {i+1}/{len(wp_l)}")
        mc_l.send_angles(wl, 20)
        time.sleep(0.5)
    print("Done!")

    time.sleep(1)
    rev = input(f"Replay {reverse_name} (reverse)? (y/n): ").strip().lower()
    if rev == "y":
        rev_wp = list(reversed(wp_l))
        mc_l.set_color(255, 255, 0)
        for i, wl in enumerate(rev_wp):
            print(f"  {i+1}/{len(rev_wp)}")
            mc_l.send_angles(wl, 20)
            time.sleep(0.5)
        print("Done!")

mc_l.set_color(255, 255, 255)
mc_r.set_color(255, 255, 255)
print("\nAll saved!")
