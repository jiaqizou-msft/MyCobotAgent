"""Record combined demo: type SADFAT, swipe up/down, dance — all in one GIF."""
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

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
PI_SNAPSHOT = 'http://10.105.230.93:8080/snapshot'
os.makedirs("temp", exist_ok=True)

rs_color_frames, rs_depth_frames, pi_frames, ov_frames = [], [], [], []
recording = False

def record_rs(pipeline, aligner):
    global recording
    while recording:
        try:
            frames = pipeline.wait_for_frames()
            aligned = aligner.process(frames)
            rs_color_frames.append(np.asanyarray(aligned.get_color_frame().get_data()).copy())
            d = np.asanyarray(aligned.get_depth_frame().get_data())
            rs_depth_frames.append(cv2.applyColorMap(cv2.convertScaleAbs(d, alpha=0.05), cv2.COLORMAP_JET))
        except: pass
        time.sleep(0.1)

def record_pi():
    global recording
    while recording:
        try:
            r = httpx.get(PI_SNAPSHOT, timeout=2)
            pi_frames.append(cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR))
        except: pass
        time.sleep(0.1)

def record_ov():
    global recording
    cap = cv2.VideoCapture(3, cv2.CAP_DSHOW)
    if not cap.isOpened(): return
    while recording:
        ret, f = cap.read()
        if ret: ov_frames.append(f.copy())
        time.sleep(0.1)
    cap.release()

def wait_done(mc, timeout=2.0, min_wait=0.15):
    time.sleep(min_wait)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0: return
        except: pass
        time.sleep(0.05)

print("=" * 55)
print("  RECORDING: type SADFAT + swipe + dance")
print("=" * 55)

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)
mc.set_color(255, 100, 0)

# Start RealSense
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
aligner = rs.align(rs.stream.color)
for _ in range(30): pipeline.wait_for_frames()

# Load keyboard
with open(os.path.join("data", "keyboard_taught.json")) as f:
    kbd = json.load(f)["keys"]

HOVER_Z = 145
PRESS_Z_OFFSET = 3
TP_Z = 131.5

mc.send_angles([0, 0, 0, 0, 0, 0], 12)
time.sleep(4)

# Start recording
recording = True
for t in [threading.Thread(target=record_rs, args=(pipeline, aligner), daemon=True),
          threading.Thread(target=record_pi, daemon=True),
          threading.Thread(target=record_ov, daemon=True)]:
    t.start()
time.sleep(1)

# === Part 1: Type SADFAT ===
print("Typing SADFAT...")
text = "sadfat"
positions = [(k, kbd[k]["coords"][:3]) for k in text if k in kbd]
x, y, z = positions[0][1]
mc.send_coords([x, y, HOVER_Z, 0, 180, 90], 30, 0)
time.sleep(1.5)

for key, (x, y, z) in positions:
    press_z = z - PRESS_Z_OFFSET
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], 40, 0)
    wait_done(mc, timeout=1.5, min_wait=0.2)
    mc.send_coords([x, y, press_z, 0, 180, 90], 30, 0)
    wait_done(mc, timeout=1.5, min_wait=0.4)
    time.sleep(0.1)
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], 30, 0)
    wait_done(mc, timeout=1.5, min_wait=0.3)

# Retract
mc.send_coords([x, y, 200, 0, 180, 90], 20, 0)
time.sleep(2)

# === Part 2: Swipe up then down ===
print("Swiping touchpad up...")
press_tp = TP_Z - 2
mc.send_coords([245, -55, HOVER_Z, 0, 180, 90], 15, 0)
time.sleep(2)
mc.send_coords([245, -55, press_tp, 0, 180, 90], 10, 0)
time.sleep(1)
mc.send_coords([245, -25, press_tp, 0, 180, 90], 10, 0)
time.sleep(2)
mc.send_coords([245, -25, HOVER_Z, 0, 180, 90], 10, 0)
time.sleep(1.5)

print("Swiping touchpad down...")
mc.send_coords([245, -25, press_tp, 0, 180, 90], 10, 0)
time.sleep(1)
mc.send_coords([245, -55, press_tp, 0, 180, 90], 10, 0)
time.sleep(2)
mc.send_coords([245, -55, HOVER_Z, 0, 180, 90], 10, 0)
time.sleep(1.5)

# Retract
mc.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(3)

# === Part 3: Dance ===
print("Dancing...")
mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
time.sleep(1)
mc.send_angles([-0.17, -94.3, 118.91, -39.9, 59.32, -0.52], 80)
time.sleep(1.2)
mc.send_angles([67.85, -3.42, -116.98, 106.52, 23.11, -0.52], 80)
time.sleep(1.7)
mc.send_angles([-38.14, -115.04, 116.63, 69.69, 3.25, -11.6], 80)
time.sleep(1.7)
mc.send_angles([0, 0, 0, 0, 0, 0], 80)
time.sleep(2)

# Stop recording
time.sleep(1)
recording = False
time.sleep(1)
mc.set_color(255, 255, 255)
pipeline.stop()

print(f"Captured: RS={len(rs_color_frames)}, Pi={len(pi_frames)}, OV={len(ov_frames)}")

# Build 2x2 GIF
n = min(len(rs_color_frames), len(rs_depth_frames), len(pi_frames))
cell_w, cell_h = 320, 240
combined = []
for i in range(0, n, 3):  # every 3rd frame to keep size down
    rc = cv2.resize(rs_color_frames[i], (cell_w, cell_h))
    rd = cv2.resize(rs_depth_frames[i], (cell_w, cell_h))
    pi = cv2.resize(pi_frames[min(i, len(pi_frames)-1)], (cell_w, cell_h))
    ov = cv2.resize(ov_frames[min(i, len(ov_frames)-1)], (cell_w, cell_h)) if ov_frames else np.zeros((cell_h, cell_w, 3), np.uint8)
    cv2.putText(rc, "Overhead RGB", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
    cv2.putText(rd, "Depth Map", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    cv2.putText(pi, "Side View", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
    cv2.putText(ov, "Overview", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
    grid = np.vstack([np.hstack([rc, rd]), np.hstack([pi, ov])])
    combined.append(cv2.cvtColor(grid, cv2.COLOR_BGR2RGB))

# Compress
pil = [Image.fromarray(f).resize((480, 360), Image.LANCZOS).quantize(colors=64) for f in combined]
gif_path = "demo_full.gif"
pil[0].save(gif_path, save_all=True, append_images=pil[1:], duration=200, loop=0, optimize=True)
sz = os.path.getsize(gif_path) // 1024
print(f"GIF: {gif_path} ({len(pil)} frames, {sz}KB)")

if sz > 5000:
    pil2 = pil[::2]
    pil2[0].save(gif_path, save_all=True, append_images=pil2[1:], duration=300, loop=0, optimize=True)
    sz = os.path.getsize(gif_path) // 1024
    print(f"Compressed: {sz}KB ({len(pil2)} frames)")

print("Done!")
