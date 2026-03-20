"""Record dual-arm demo: press A, Enter, Z, K + touchpad swipe, all cameras."""
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import threading
import json
import os
from pymycobot import MyCobot280Socket
from PIL import Image

os.makedirs("temp", exist_ok=True)

RS_OVERHEAD = "335222075369"
RS_FRONT = "335522073146"
PI_SNAPSHOT = "http://10.105.230.93:8080/snapshot"

overhead_frames, front_frames, pi_frames = [], [], []
recording = False

def record_rs(sn, store):
    global recording
    p = rs.pipeline(); c = rs.config(); c.enable_device(sn)
    c.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    p.start(c)
    for _ in range(15): p.wait_for_frames()
    while recording:
        try: store.append(np.asanyarray(p.wait_for_frames().get_color_frame().get_data()).copy())
        except: pass
        time.sleep(0.1)
    p.stop()

def record_pi():
    global recording
    while recording:
        try:
            r = httpx.get(PI_SNAPSHOT, timeout=2)
            pi_frames.append(cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR))
        except: pass
        time.sleep(0.1)

def wait_done(mc, timeout=2.0, min_wait=0.15):
    time.sleep(min_wait)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0: return
        except: pass
        time.sleep(0.05)

print("=" * 55)
print("  DUAL-ARM DEMO: A, Enter, Z, K + Touchpad")
print("=" * 55)

# Load layout
with open("data/keyboard_dual_arm.json") as f:
    layout = json.load(f)
merged = layout["merged_keys"]

# Connect arms
mc_right = MyCobot280Socket("10.105.230.93", 9000)
time.sleep(1)
mc_left = MyCobot280Socket("10.105.230.94", 9000)
time.sleep(1)
arm_mc = {"right": mc_right, "left": mc_left}

# Home both
mc_right.send_angles([0, 0, 0, 0, 0, 0], 15)
mc_left.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(4)

# Start recording
print("Recording...")
recording = True
threads = [
    threading.Thread(target=record_rs, args=(RS_OVERHEAD, overhead_frames), daemon=True),
    threading.Thread(target=record_rs, args=(RS_FRONT, front_frames), daemon=True),
    threading.Thread(target=record_pi, daemon=True),
]
for t in threads: t.start()
time.sleep(1)

# Press keys
KEYS = ["a", "enter", "z", "k"]
HOVER_OFFSET = 15
PRESS_OFFSET = 3
current_arm = None

for key in KEYS:
    if key not in merged:
        print(f"  '{key}' not mapped, skipping")
        continue
    data = merged[key]
    robot = data.get("robot", data.get("coords", [0,0,0]))[:3]
    x, y, z = robot
    arm = data["arm"]
    mc = arm_mc[arm]
    hover_z = z + HOVER_OFFSET
    press_z = z - PRESS_OFFSET

    if not (-281 <= x <= 281):
        print(f"  '{key}' out of reach, skipping")
        continue

    if current_arm and current_arm != arm:
        arm_mc[current_arm].send_angles([0, 0, 0, 0, 0, 0], 20)
        time.sleep(2)

    mc.set_color(255, 100, 0)
    if current_arm != arm:
        mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
        wait_done(mc, timeout=3, min_wait=0.5)
    else:
        mc.send_coords([x, y, hover_z, 0, 180, 90], 30, 0)
        wait_done(mc, timeout=2, min_wait=0.2)

    mc.send_coords([x, y, press_z, 0, 180, 90], 20, 0)
    wait_done(mc, timeout=2, min_wait=0.4)
    time.sleep(0.1)
    mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
    wait_done(mc, timeout=2, min_wait=0.3)

    current_arm = arm
    print(f"  [{arm[0].upper()}] '{key}'")

# Retract current arm
if current_arm:
    arm_mc[current_arm].send_angles([0, 0, 0, 0, 0, 0], 20)
time.sleep(3)

# Touchpad swipe (use left arm since it's probably closer)
# Use the taught touchpad position or estimate from annotation
print("  Touchpad swipe...")
# Get touchpad from annotation
with open("data/keyboard_vision_detected.json") as f:
    anno = json.load(f)
tp = anno.get("touchpad")

# For touchpad, use the left arm's affine to convert touchpad pixel to robot coords
left_data = layout["arms"].get("left", {})
if left_data and "affine" in left_data and tp:
    M = np.array(left_data["affine"])
    kbd_z = left_data["kbd_z"]
    tp_px = tp["pixel"]
    tp_robot = np.array([tp_px[0], tp_px[1], 1]) @ M
    tp_x, tp_y = float(tp_robot[0]), float(tp_robot[1])
    tp_z = kbd_z  # touchpad is roughly same height as keyboard
    
    if -281 <= tp_x <= 281:
        press_tp = tp_z - 2
        hover_tp = tp_z + 15
        
        # Use left arm for touchpad
        mc_left.set_color(0, 255, 255)
        mc_left.send_coords([tp_x, tp_y - 15, hover_tp, 0, 180, 90], 15, 0)
        time.sleep(3)
        # Swipe down
        mc_left.send_coords([tp_x, tp_y - 15, press_tp, 0, 180, 90], 10, 0)
        time.sleep(1)
        mc_left.send_coords([tp_x, tp_y + 15, press_tp, 0, 180, 90], 10, 0)
        time.sleep(2)
        mc_left.send_coords([tp_x, tp_y + 15, hover_tp, 0, 180, 90], 10, 0)
        time.sleep(1)
        print(f"  [L] touchpad swipe at ({tp_x:.0f},{tp_y:.0f})")
    else:
        print(f"  Touchpad out of reach ({tp_x:.0f})")
else:
    print("  No touchpad data available")

# Home both
mc_right.send_angles([0, 0, 0, 0, 0, 0], 15)
mc_left.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(3)
mc_right.set_color(255, 255, 255)
mc_left.set_color(255, 255, 255)

# Stop recording
time.sleep(1)
recording = False
for t in threads: t.join(timeout=3)

print(f"\nCaptured: OH={len(overhead_frames)}, FR={len(front_frames)}, PI={len(pi_frames)}")

# Build 3-panel GIF
n = min(len(overhead_frames), len(front_frames), len(pi_frames))
cell_h = 240
combined = []
for i in range(0, n, 3):
    panels = []
    for frames, label in [(overhead_frames, "Overhead"), (front_frames, "Front"), (pi_frames, "Side")]:
        f = cv2.resize(frames[min(i, len(frames)-1)], (320, cell_h))
        cv2.putText(f, label, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
        panels.append(f)
    combined.append(cv2.cvtColor(np.hstack(panels), cv2.COLOR_BGR2RGB))

pil = [Image.fromarray(f).quantize(colors=64) for f in combined]
gif_path = "demo_dual_arm_keys.gif"
pil[0].save(gif_path, save_all=True, append_images=pil[1:], duration=200, loop=0, optimize=True)
sz = os.path.getsize(gif_path) // 1024
print(f"GIF: {gif_path} ({len(pil)} frames, {sz}KB)")
if sz > 5000:
    pil2 = pil[::2]
    pil2[0].save(gif_path, save_all=True, append_images=pil2[1:], duration=300, loop=0, optimize=True)
    sz = os.path.getsize(gif_path) // 1024
    print(f"Compressed: {sz}KB")

print("Done!")
