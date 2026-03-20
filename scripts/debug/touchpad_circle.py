"""Touchpad circle motion + 4-view recording."""
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import threading
import math
import os
from pymycobot import MyCobot280Socket
from PIL import Image

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
PI_SNAPSHOT = 'http://10.105.230.93:8080/snapshot'
os.makedirs("temp", exist_ok=True)

# Touchpad bounds (from taught points)
# lower left: (232.1, -77.0, 131.6)
# center: (282.1, -41.1, 132.0)
# Top-left estimate: (232, -10)
# Bottom-left: (232, -77)
# Center: (260, -41)
TP_Z = 131.5
HOVER_Z = 145
PRESS_DEPTH = 2

# Circle path through: top-left → center → bottom-left → back
# Using 3 anchor points, generate a smooth elliptical path
TOP_LEFT = (235, -15)
CENTER = (255, -41)
BOTTOM_LEFT = (235, -70)

# Generate circle points: ellipse centered between the 3 points
cx = 245  # circle center X
cy = -42  # circle center Y
rx = 15   # radius X
ry = 28   # radius Y
N_POINTS = 16  # points around the circle

circle_points = []
for i in range(N_POINTS + 1):  # +1 to close the loop
    angle = 2 * math.pi * i / N_POINTS
    x = cx + rx * math.cos(angle)
    y = cy + ry * math.sin(angle)
    circle_points.append((x, y))

# Recording storage
rs_color_frames = []
rs_depth_frames = []
pi_frames = []
ov_frames = []
recording = False


def record_rs(pipeline, aligner):
    global recording
    while recording:
        try:
            frames = pipeline.wait_for_frames()
            aligned = aligner.process(frames)
            color = np.asanyarray(aligned.get_color_frame().get_data())
            depth = np.asanyarray(aligned.get_depth_frame().get_data())
            rs_color_frames.append(color.copy())
            depth_cm = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.05), cv2.COLORMAP_JET)
            rs_depth_frames.append(depth_cm)
        except:
            pass
        time.sleep(0.1)


def record_pi():
    global recording
    while recording:
        try:
            resp = httpx.get(PI_SNAPSHOT, timeout=2)
            img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
            pi_frames.append(img)
        except:
            pass
        time.sleep(0.1)


def record_overview():
    global recording
    cap = cv2.VideoCapture(3, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return
    while recording:
        ret, frame = cap.read()
        if ret:
            ov_frames.append(frame.copy())
        time.sleep(0.1)
    cap.release()


print("=" * 55)
print("  TOUCHPAD CIRCLE DEMO")
print("=" * 55)

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)
mc.set_color(255, 0, 255)

# Start RealSense
print("Starting RealSense...")
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
aligner = rs.align(rs.stream.color)
for _ in range(30):
    pipeline.wait_for_frames()

# Go home first
mc.send_angles([0, 0, 0, 0, 0, 0], 12)
time.sleep(4)

# Start recording
print("Starting recording...")
recording = True
threads = [
    threading.Thread(target=record_rs, args=(pipeline, aligner), daemon=True),
    threading.Thread(target=record_pi, daemon=True),
    threading.Thread(target=record_overview, daemon=True),
]
for t in threads:
    t.start()
time.sleep(1)

# Move above touchpad
print("Moving above touchpad...")
start_x, start_y = circle_points[0]
mc.send_coords([start_x, start_y, HOVER_Z, 0, 180, 90], 12, 0)
time.sleep(4)

# Lower to hover
mc.send_coords([start_x, start_y, TP_Z + 8, 0, 180, 90], 10, 0)
time.sleep(2)

# Touch down
press_z = TP_Z - PRESS_DEPTH
print("Touching down...")
mc.send_coords([start_x, start_y, press_z, 0, 180, 90], 8, 0)
time.sleep(1.5)

# Draw circle (stay pressed on touchpad)
print("Drawing circle on touchpad...")
for i, (px, py) in enumerate(circle_points[1:], 1):
    mc.send_coords([px, py, press_z, 0, 180, 90], 10, 0)
    time.sleep(0.6)
    if i % 4 == 0:
        print(f"  Point {i}/{N_POINTS}")

# Lift up
print("Lifting...")
mc.send_coords([circle_points[-1][0], circle_points[-1][1], HOVER_Z, 0, 180, 90], 10, 0)
time.sleep(2)

# Stop recording
time.sleep(1)
recording = False
for t in threads:
    t.join(timeout=3)

mc.send_angles([0, 0, 0, 0, 0, 0], 12)
time.sleep(3)
mc.set_color(255, 255, 255)
pipeline.stop()

print(f"Captured: RS={len(rs_color_frames)}, Pi={len(pi_frames)}, OV={len(ov_frames)}")

# Build 2x2 GIF
n = min(len(rs_color_frames), len(rs_depth_frames), len(pi_frames))
print(f"Building GIF from {n} frames...")

cell_w, cell_h = 320, 240
combined_frames = []

for i in range(0, n, 2):
    rc = cv2.resize(rs_color_frames[i], (cell_w, cell_h))
    rd = cv2.resize(rs_depth_frames[i], (cell_w, cell_h))
    pi = cv2.resize(pi_frames[min(i, len(pi_frames)-1)], (cell_w, cell_h))
    ov = cv2.resize(ov_frames[min(i, len(ov_frames)-1)], (cell_w, cell_h)) if ov_frames else np.zeros((cell_h, cell_w, 3), dtype=np.uint8)

    cv2.putText(rc, "Overhead RGB", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(rd, "Depth Map", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(pi, "Side View", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(ov, "Overview", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    grid = np.vstack([np.hstack([rc, rd]), np.hstack([pi, ov])])
    combined_frames.append(cv2.cvtColor(grid, cv2.COLOR_BGR2RGB))

fps = 8
pil_frames = [Image.fromarray(f).quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in combined_frames]
gif_path = "demo_touchpad_circle.gif"
pil_frames[0].save(gif_path, save_all=True, append_images=pil_frames[1:], duration=int(1000/fps), loop=0, optimize=True)
size_kb = os.path.getsize(gif_path) / 1024
print(f"GIF saved: {gif_path} ({len(pil_frames)} frames, {size_kb:.0f}KB)")

if size_kb > 5000:
    smaller = pil_frames[::2]
    smaller[0].save(gif_path, save_all=True, append_images=smaller[1:], duration=250, loop=0, optimize=True)
    size_kb = os.path.getsize(gif_path) / 1024
    print(f"Compressed: {size_kb:.0f}KB ({len(smaller)} frames)")

print("\nDone!")
