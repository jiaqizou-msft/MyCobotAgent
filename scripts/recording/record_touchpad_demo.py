"""Record touchpad demo: swipe down then swipe up, with 4-view recording."""
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import threading
import os
from pymycobot import MyCobot280Socket
from PIL import Image

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
PI_SNAPSHOT = 'http://10.105.230.93:8080/snapshot'
os.makedirs("temp", exist_ok=True)

TP_Z = 131.5
HOVER_Z = 145
PRESS_DEPTH = 2
SLOW = 10

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

print("=" * 55)
print("  RECORDING TOUCHPAD DEMO")
print("=" * 55)

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)
mc.set_color(255, 0, 255)

pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
aligner = rs.align(rs.stream.color)
for _ in range(30): pipeline.wait_for_frames()

mc.send_angles([0, 0, 0, 0, 0, 0], 12)
time.sleep(4)

# Start recording
recording = True
for t in [threading.Thread(target=record_rs, args=(pipeline, aligner), daemon=True),
          threading.Thread(target=record_pi, daemon=True),
          threading.Thread(target=record_ov, daemon=True)]:
    t.start()
time.sleep(1)

press_z = TP_Z - PRESS_DEPTH

# Swipe down
print("Swipe down...")
mc.send_coords([245, -25, HOVER_Z, 0, 180, 90], 12, 0)
time.sleep(3)
mc.send_coords([245, -25, press_z, 0, 180, 90], SLOW, 0)
time.sleep(1.5)
mc.send_coords([245, -55, press_z, 0, 180, 90], SLOW, 0)
time.sleep(3)
mc.send_coords([245, -55, HOVER_Z, 0, 180, 90], SLOW, 0)
time.sleep(2)

# Swipe up
print("Swipe up...")
mc.send_coords([245, -55, press_z, 0, 180, 90], SLOW, 0)
time.sleep(1.5)
mc.send_coords([245, -25, press_z, 0, 180, 90], SLOW, 0)
time.sleep(3)
mc.send_coords([245, -25, HOVER_Z, 0, 180, 90], SLOW, 0)
time.sleep(2)

# Tap center
print("Tap center...")
mc.send_coords([245, -40, HOVER_Z, 0, 180, 90], 12, 0)
time.sleep(2)
mc.send_coords([255, -45, press_z, 0, 180, 90], SLOW, 0)
time.sleep(0.8)
mc.send_coords([255, -45, HOVER_Z, 0, 180, 90], SLOW, 0)
time.sleep(1.5)

# Stop recording
time.sleep(1)
recording = False
time.sleep(1)

mc.send_angles([0, 0, 0, 0, 0, 0], 12)
time.sleep(3)
mc.set_color(255, 255, 255)
pipeline.stop()

print(f"Captured: RS={len(rs_color_frames)}, Pi={len(pi_frames)}, OV={len(ov_frames)}")

# Build GIF
n = min(len(rs_color_frames), len(rs_depth_frames), len(pi_frames))
cell_w, cell_h = 320, 240
combined = []
for i in range(0, n, 2):
    rc = cv2.resize(rs_color_frames[i], (cell_w, cell_h))
    rd = cv2.resize(rs_depth_frames[i], (cell_w, cell_h))
    pi = cv2.resize(pi_frames[min(i, len(pi_frames)-1)], (cell_w, cell_h))
    ov = cv2.resize(ov_frames[min(i, len(ov_frames)-1)], (cell_w, cell_h)) if ov_frames else np.zeros((cell_h, cell_w, 3), np.uint8)
    cv2.putText(rc, "Overhead RGB", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(rd, "Depth Map", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(pi, "Side View", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(ov, "Overview", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    grid = np.vstack([np.hstack([rc, rd]), np.hstack([pi, ov])])
    combined.append(cv2.cvtColor(grid, cv2.COLOR_BGR2RGB))

# Resize and compress
pil = [Image.fromarray(f).resize((480, 360), Image.LANCZOS).quantize(colors=64, method=Image.Quantize.MEDIANCUT) for f in combined[::2]]
pil[0].save("demo_touchpad.gif", save_all=True, append_images=pil[1:], duration=200, loop=0, optimize=True)
sz = os.path.getsize("demo_touchpad.gif") // 1024
print(f"GIF: demo_touchpad.gif ({len(pil)} frames, {sz}KB)")
print("Done!")
