"""Record typing demo with 4 views: RealSense color, RealSense depth, Pi side, Overview."""
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

# Frame storage
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
            # Convert depth to colormap for visualization
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
        print("  Overview camera not found, skipping.")
        return
    while recording:
        ret, frame = cap.read()
        if ret:
            ov_frames.append(frame.copy())
        time.sleep(0.1)
    cap.release()


def type_for_recording(mc, text):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "keyboard_taught.json")) as f:
        data = json.load(f)
    keys = data["keys"]
    HOVER_Z = 145
    SLIDE_SPEED = 12
    PRESS_SPEED = 6
    PRESS_Z_OFFSET = 3

    positions = []
    for ch in text:
        k = 'space' if ch == ' ' else ch.lower()
        if k in keys:
            positions.append((k, keys[k]["coords"][:3]))

    if not positions:
        return

    x, y, z = positions[0][1]
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], 8, 0)
    time.sleep(3)

    for key, (x, y, z) in positions:
        press_z = z - PRESS_Z_OFFSET
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], SLIDE_SPEED, 0)
        time.sleep(1.5)
        mc.send_coords([x, y, press_z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(1.2)
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(1.0)

    mc.send_coords([x, y, 200, 0, 180, 90], 10, 0)
    time.sleep(2)


print("=" * 60)
print("  RECORDING 4-VIEW TYPING DEMO (with depth)")
print("=" * 60)

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)
mc.set_color(255, 100, 0)

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

# Go home
mc.send_angles([0, 0, 0, 0, 0, 0], 10)
time.sleep(4)

# Start recording
print("Starting recording from all 4 views...")
recording = True
threads = [
    threading.Thread(target=record_rs, args=(pipeline, aligner), daemon=True),
    threading.Thread(target=record_pi, daemon=True),
    threading.Thread(target=record_overview, daemon=True),
]
for t in threads:
    t.start()
time.sleep(1)

# Type "sad"
print('Typing "sad"...')
type_for_recording(mc, "sad")

# Stop
time.sleep(1)
recording = False
for t in threads:
    t.join(timeout=3)

print(f"Captured: RS_color={len(rs_color_frames)}, RS_depth={len(rs_depth_frames)}, "
      f"Pi={len(pi_frames)}, OV={len(ov_frames)}")

mc.send_angles([0, 0, 0, 0, 0, 0], 10)
time.sleep(3)
mc.set_color(255, 255, 255)
pipeline.stop()

# Build 2x2 grid GIF: [Overhead Color | Depth] / [Side View | Overview]
n = min(len(rs_color_frames), len(rs_depth_frames), len(pi_frames))
has_ov = len(ov_frames) > 0
print(f"\nBuilding 2x2 grid GIF from {n} frames...")

cell_w, cell_h = 320, 240
combined_frames = []

for i in range(0, n, 2):  # every other frame
    rc = cv2.resize(rs_color_frames[i], (cell_w, cell_h))
    rd = cv2.resize(rs_depth_frames[i], (cell_w, cell_h))
    pi = cv2.resize(pi_frames[min(i, len(pi_frames)-1)], (cell_w, cell_h))

    if has_ov and i < len(ov_frames):
        ov = cv2.resize(ov_frames[i], (cell_w, cell_h))
    else:
        ov = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)

    # Labels
    cv2.putText(rc, "Overhead RGB", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(rd, "Depth Map", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(pi, "Side View", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(ov, "Overview", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    top_row = np.hstack([rc, rd])
    bot_row = np.hstack([pi, ov])
    grid = np.vstack([top_row, bot_row])

    grid_rgb = cv2.cvtColor(grid, cv2.COLOR_BGR2RGB)
    combined_frames.append(grid_rgb)

# Save GIF
fps = 8
pil_frames = [Image.fromarray(f).quantize(colors=128, method=Image.Quantize.MEDIANCUT)
              for f in combined_frames]

gif_path = "demo_typing_4view.gif"
pil_frames[0].save(
    gif_path,
    save_all=True,
    append_images=pil_frames[1:],
    duration=int(1000 / fps),
    loop=0,
    optimize=True,
)
size_kb = os.path.getsize(gif_path) / 1024
print(f"GIF saved: {gif_path} ({len(pil_frames)} frames, {size_kb:.0f}KB)")

# Compress if needed
if size_kb > 5000:
    smaller = pil_frames[::2]
    smaller[0].save(gif_path, save_all=True, append_images=smaller[1:],
                    duration=250, loop=0, optimize=True)
    size_kb = os.path.getsize(gif_path) / 1024
    print(f"Compressed: {size_kb:.0f}KB ({len(smaller)} frames)")

print("\nDone!")
