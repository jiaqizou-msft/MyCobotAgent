"""
Lid Open/Close Cycle — 10 reps with GIF recording.
Left arm closes, right arm opens, played sequentially.
"""
import json, time, sys, os, cv2, numpy as np, imageio
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000
CYCLES = 10

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "taught_actions.json")) as f:
    actions = json.load(f)

mc_r = CachedRobot(RIGHT_IP, PORT)
mc_l = CachedRobot(LEFT_IP, PORT)
mc_r.power_on()
mc_l.power_on()
time.sleep(1)

# Open camera
cap = cv2.VideoCapture(4, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
for _ in range(15):
    cap.read()

frames = []

def grab_frame():
    for _ in range(3):
        cap.read()
    ret, frame = cap.read()
    if ret:
        frame = cv2.flip(frame, -1)
        # Brighten
        frame = np.clip(frame.astype(np.float32) * 1.3, 0, 255).astype(np.uint8)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Resize for smaller GIF
        h, w = rgb.shape[:2]
        rgb = cv2.resize(rgb, (w // 2, h // 2))
        frames.append(rgb)


def replay_action(name, arm_mc, arm_name):
    a = actions[name]
    wp = a["left_waypoints"] if "left" in a.get("method", "") else a["right_waypoints"]
    for wp_item in wp:
        arm_mc.send_angles(wp_item, 30)
        grab_frame()
        time.sleep(0.3)


print(f"Running {CYCLES} lid close/open cycles with GIF recording...")
grab_frame()  # initial frame

for i in range(CYCLES):
    print(f"=== Cycle {i+1}/{CYCLES} ===")

    # Close lid (left arm)
    print(f"  Close lid (left arm)...")
    mc_l.set_color(255, 0, 0)
    a = actions["close_lid"]
    for wl in a["left_waypoints"]:
        mc_l.send_angles(wl, 30)
        grab_frame()
        time.sleep(0.3)
    time.sleep(0.5)
    grab_frame()

    # Open lid (right arm)
    print(f"  Open lid (right arm)...")
    mc_r.set_color(0, 255, 0)
    a = actions["open_lid"]
    for wr in a["right_waypoints"]:
        mc_r.send_angles(wr, 30)
        grab_frame()
        time.sleep(0.3)
    time.sleep(0.5)
    grab_frame()

cap.release()

mc_r.set_color(255, 255, 255)
mc_l.set_color(255, 255, 255)

# Save GIF
ts = time.strftime("%Y%m%d_%H%M%S")
gif_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "visualizations", f"lid_cycles_{ts}.gif")
print(f"\nSaving GIF: {len(frames)} frames...")
imageio.mimsave(gif_path, frames, duration=0.08, loop=0)
print(f"Saved: {gif_path}")
print(f"\nAll {CYCLES} cycles complete!")
