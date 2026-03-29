"""
Lid open/close demo with multi-camera GIF recording.
Runs N cycles of close→open, records from all available cameras,
outputs a combined GIF.

Usage: python scripts/gambit/lid_demo.py [cycles]
"""
import json, time, sys, os, cv2, imageio
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 5
CAMERA_IDS = [1, 2]  # overhead + front
FLIP_CAMS = {1}  # overhead upside down, needs 180 flip
FPS = 5
GAMMA = 1.4

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000
ACTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "taught_actions.json")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "visualizations")

# Load actions
with open(ACTIONS_PATH) as f:
    actions = json.load(f)

# Connect arms
mc_r = CachedRobot(RIGHT_IP, PORT)
mc_l = CachedRobot(LEFT_IP, PORT)
mc_r.power_on()
mc_l.power_on()
time.sleep(1)

# Open cameras
caps = {}
for cid in CAMERA_IDS:
    cap = cv2.VideoCapture(cid, cv2.CAP_DSHOW)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        # Warm up
        for _ in range(10):
            cap.read()
        caps[cid] = cap
        print(f"Camera {cid}: OK")
    else:
        print(f"Camera {cid}: FAILED")

if not caps:
    print("No cameras!")
    sys.exit(1)

print(f"\nRecording {CYCLES} close/open cycles from {len(caps)} cameras...")

# Gamma LUT
lut = np.array([((i / 255.0) ** (1.0 / GAMMA)) * 255 for i in range(256)]).astype("uint8")


def capture_frame():
    """Capture from all cameras, stitch side by side."""
    frames = []
    for cid, cap in caps.items():
        for _ in range(2):
            cap.read()
        ret, frame = cap.read()
        if ret:
            if cid in FLIP_CAMS:
                frame = cv2.flip(frame, -1)
            # Resize to consistent height
            frame = cv2.resize(frame, (320, 240))
            # Gamma brighten
            frame = cv2.LUT(frame, lut)
            # BGR to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame)
    if frames:
        return np.hstack(frames)
    return None


def replay_with_frames(name, all_frames):
    """Replay action sequentially — only move the active arm, wait until done."""
    a = actions[name]
    wp_r = a["right_waypoints"]
    wp_l = a["left_waypoints"]
    method = a.get("method", "")

    for idx, (wr, wl) in enumerate(zip(wp_r, wp_l)):
        try:
            if "right_arm" in method:
                mc_r.send_angles(wr, 25)
            elif "left_arm" in method:
                mc_l.send_angles(wl, 25)
            else:
                mc_r.send_angles(wr, 25)
                mc_l.send_angles(wl, 25)
        except Exception:
            pass
        if idx % 2 == 0:
            f = capture_frame()
            if f is not None:
                all_frames.append(f)
        time.sleep(0.4)

    # Wait for arm to fully stop before returning
    active = mc_r if "right_arm" in method else mc_l
    for _ in range(30):
        try:
            if not active.is_moving():
                break
        except Exception:
            break
        time.sleep(0.2)
    time.sleep(1)


all_frames = []

# Initial frame
f = capture_frame()
if f is not None:
    all_frames.append(f)

try:
    for i in range(CYCLES):
        print(f"  Cycle {i+1}/{CYCLES}")

        try:
            mc_l.set_color(255, 0, 0)
            mc_r.set_color(0, 0, 255)
        except Exception:
            pass
        replay_with_frames("close_lid", all_frames)

        try:
            mc_r.set_color(0, 255, 0)
            mc_l.set_color(0, 0, 255)
        except Exception:
            pass
        replay_with_frames("open_lid", all_frames)
except KeyboardInterrupt:
    print("\n  Interrupted — saving what we have...")
except Exception as e:
    print(f"\n  Error: {e} — saving what we have...")

# Close cameras
for cap in caps.values():
    cap.release()

mc_r.set_color(255, 255, 255)
mc_l.set_color(255, 255, 255)

# Save GIF
ts = time.strftime("%Y%m%d_%H%M%S")
gif_path = os.path.join(OUT_DIR, f"lid_demo_{ts}.gif")
print(f"\nSaving {len(all_frames)} frames to GIF...")
imageio.mimsave(gif_path, all_frames, duration=1.0 / FPS, loop=0)
print(f"Saved: {gif_path}")
print(f"Size: {os.path.getsize(gif_path) / 1024:.0f} KB")
print("Done!")
