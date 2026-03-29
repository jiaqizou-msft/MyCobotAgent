"""
Teach lid close (left arm) and open (right arm) separately.
Played sequentially: close first, then open.
"""
import json, time, sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000
ACTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "taught_actions.json")


def record_arm(mc, arm_name, action_name):
    """Release arm, record drag, return downsampled waypoints."""
    print(f"\n  {arm_name.upper()} ARM RELEASED")
    print(f"  Drag it through the {action_name} motion.")
    print(f"  Press ENTER to START, ENTER again to STOP.\n")
    mc.release_all_servos()
    mc.set_color(255, 100, 0)
    time.sleep(0.5)

    input(f"  >>> Press ENTER to START recording...")
    print("  *** RECORDING — drag now! ***")
    mc.set_color(255, 0, 0)

    recording = [True]
    waypoints = []

    def loop():
        while recording[0]:
            a = mc.get_angles()
            if a and a != -1 and isinstance(a, list) and len(a) == 6:
                waypoints.append([round(v, 2) for v in a])
            time.sleep(0.1)

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    input("  >>> Press ENTER to STOP recording...")
    recording[0] = False
    time.sleep(0.3)
    mc.focus_all_servos()
    mc.set_color(0, 255, 0)

    print(f"  Recorded {len(waypoints)} samples ({len(waypoints)/10:.1f}s)")
    if len(waypoints) < 3:
        print("  Too few samples!")
        return None

    step = max(1, len(waypoints) // 20)
    wp = waypoints[::step]
    if waypoints[-1] != wp[-1]:
        wp.append(waypoints[-1])
    print(f"  Downsampled to {len(wp)} waypoints")
    return wp


print("=" * 55)
print("  TEACH LID: Left arm closes, Right arm opens")
print("  Played sequentially: close -> open")
print("=" * 55)

mc_r = CachedRobot(RIGHT_IP, PORT)
mc_l = CachedRobot(LEFT_IP, PORT)
mc_r.power_on()
mc_l.power_on()
time.sleep(1)

# Park right arm home
print("\nParking right arm home...")
mc_r.send_angles([0, 0, 0, 0, 0, 0], 25)
time.sleep(3)
right_home = mc_r.get_angles()

# STEP 1: Left arm closes lid
print("\n" + "=" * 55)
print("  STEP 1: LEFT arm — CLOSE LID")
print("=" * 55)
wp_l_close = record_arm(mc_l, "left", "close_lid")
if wp_l_close is None:
    sys.exit(1)

# Park left arm home
print("\nParking left arm home...")
mc_l.send_angles([0, 0, 0, 0, 0, 0], 25)
time.sleep(3)
left_home = mc_l.get_angles()

# STEP 2: Right arm opens lid
print("\n" + "=" * 55)
print("  STEP 2: RIGHT arm — OPEN LID")
print("=" * 55)
wp_r_open = record_arm(mc_r, "right", "open_lid")
if wp_r_open is None:
    sys.exit(1)

# Save
actions = {}
if os.path.exists(ACTIONS_PATH):
    with open(ACTIONS_PATH) as f:
        actions = json.load(f)

actions["close_lid"] = {
    "type": "dual_arm_trajectory",
    "right_waypoints": [right_home] * len(wp_l_close),
    "left_waypoints": wp_l_close,
    "num_waypoints": len(wp_l_close),
    "method": "left_arm_only",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}
actions["open_lid"] = {
    "type": "dual_arm_trajectory",
    "right_waypoints": wp_r_open,
    "left_waypoints": [left_home] * len(wp_r_open),
    "num_waypoints": len(wp_r_open),
    "method": "right_arm_only",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
}

with open(ACTIONS_PATH, "w") as f:
    json.dump(actions, f, indent=2)
print(f"\nSaved close_lid (left arm) + open_lid (right arm)!")

# Replay sequentially
r = input("\nReplay close then open (sequential)? (y/n): ").strip().lower()
if r == "y":
    print("Replaying close_lid (left arm)...")
    mc_l.set_color(255, 0, 0)
    for wl in wp_l_close:
        mc_l.send_angles(wl, 25)
        time.sleep(0.4)
    time.sleep(1)

    print("Replaying open_lid (right arm)...")
    mc_r.set_color(0, 255, 0)
    for wr in wp_r_open:
        mc_r.send_angles(wr, 25)
        time.sleep(0.4)
    print("Replay done!")

mc_r.set_color(255, 255, 255)
mc_l.set_color(255, 255, 255)
print("\nAll done!")
