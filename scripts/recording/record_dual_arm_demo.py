"""Record dual-arm demo: press A, Enter, Q, L, 1, P with all cameras."""
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

RS_SERIALS = {"overhead": "335222075369", "front": "335522073146"}
PI_SNAPSHOT = "http://10.105.230.93:8080/snapshot"

# Frame storage
overhead_frames, front_frames, pi_frames = [], [], []
recording = False

def record_rs(sn, store):
    global recording
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(sn)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    profile = pipeline.start(config)
    for _ in range(15):
        pipeline.wait_for_frames()
    while recording:
        try:
            frames = pipeline.wait_for_frames()
            store.append(np.asanyarray(frames.get_color_frame().get_data()).copy())
        except: pass
        time.sleep(0.1)
    pipeline.stop()

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
print("  DUAL-ARM DEMO: A, Enter, Q, L, 1, P")
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

# Start recording all cameras
print("Starting recording...")
recording = True
threads = [
    threading.Thread(target=record_rs, args=(RS_SERIALS["overhead"], overhead_frames), daemon=True),
    threading.Thread(target=record_rs, args=(RS_SERIALS["front"], front_frames), daemon=True),
    threading.Thread(target=record_pi, daemon=True),
]
for t in threads:
    t.start()
time.sleep(1)

# Press keys: A, Enter, Q, L, 1, P
KEYS = ["a", "enter", "q", "l", "1", "p"]
HOVER_OFFSET = 15
PRESS_OFFSET = 3

current_arm = None

for key in KEYS:
    if key not in merged:
        print(f"  '{key}' not in layout, skipping")
        continue
    
    data = merged[key]
    x, y, z = data["coords"][:3]
    arm = data["arm"]

    if not (-281 <= x <= 281 and -281 <= y <= 281):
        print(f"  '{key}' out of reach (X={x:.0f}), skipping")
        continue

    mc = arm_mc[arm]
    hover_z = z + HOVER_OFFSET
    press_z = z - PRESS_OFFSET

    # Retract old arm if switching
    if current_arm and current_arm != arm:
        old_mc = arm_mc[current_arm]
        old_mc.send_angles([0, 0, 0, 0, 0, 0], 20)
        time.sleep(2)

    # Set LED
    mc.set_color(255, 100, 0)

    if current_arm != arm:
        mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
        wait_done(mc, timeout=3, min_wait=0.5)
    else:
        mc.send_coords([x, y, hover_z, 0, 180, 90], 30, 0)
        wait_done(mc, timeout=2, min_wait=0.2)

    # Press
    mc.send_coords([x, y, press_z, 0, 180, 90], 20, 0)
    wait_done(mc, timeout=2, min_wait=0.4)
    time.sleep(0.1)

    # Release
    mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
    wait_done(mc, timeout=2, min_wait=0.3)

    current_arm = arm
    print(f"  [{arm[0].upper()}] '{key}'")

# Home both
mc_right.send_angles([0, 0, 0, 0, 0, 0], 15)
mc_left.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(3)
mc_right.set_color(255, 255, 255)
mc_left.set_color(255, 255, 255)

# Stop recording
time.sleep(1)
recording = False
for t in threads:
    t.join(timeout=3)

print(f"\nCaptured: overhead={len(overhead_frames)}, front={len(front_frames)}, pi={len(pi_frames)}")

# Build 3-panel GIF: overhead + front + side
n = min(len(overhead_frames), len(front_frames), len(pi_frames))
if n == 0:
    n = max(len(overhead_frames), len(front_frames), len(pi_frames))

cell_h = 240
combined = []
for i in range(0, min(n, max(len(overhead_frames), len(front_frames), len(pi_frames))), 3):
    panels = []
    if overhead_frames:
        ov = cv2.resize(overhead_frames[min(i, len(overhead_frames)-1)], (320, cell_h))
        cv2.putText(ov, "Overhead", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,0), 1)
        panels.append(ov)
    if front_frames:
        fr = cv2.resize(front_frames[min(i, len(front_frames)-1)], (320, cell_h))
        cv2.putText(fr, "Front", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,0), 1)
        panels.append(fr)
    if pi_frames:
        pi = cv2.resize(pi_frames[min(i, len(pi_frames)-1)], (320, cell_h))
        cv2.putText(pi, "Side", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,0), 1)
        panels.append(pi)
    if panels:
        grid = np.hstack(panels)
        combined.append(cv2.cvtColor(grid, cv2.COLOR_BGR2RGB))

print(f"Building GIF from {len(combined)} frames...")
pil = [Image.fromarray(f).quantize(colors=64) for f in combined]
gif_path = "demo_dual_arm.gif"
pil[0].save(gif_path, save_all=True, append_images=pil[1:], duration=200, loop=0, optimize=True)
sz = os.path.getsize(gif_path) // 1024
print(f"GIF: {gif_path} ({len(pil)} frames, {sz}KB)")

if sz > 5000:
    pil2 = pil[::2]
    pil2[0].save(gif_path, save_all=True, append_images=pil2[1:], duration=300, loop=0, optimize=True)
    sz = os.path.getsize(gif_path) // 1024
    print(f"Compressed: {sz}KB ({len(pil2)} frames)")

print("Done!")
