"""Record typing demo from 3 cameras: RealSense overhead, Pi side, Overview."""
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
rs_frames = []
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
            rs_frames.append(color.copy())
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
        print("Overview camera not available")
        return
    while recording:
        ret, frame = cap.read()
        if ret:
            ov_frames.append(frame.copy())
        time.sleep(0.1)
    cap.release()


def type_for_recording(mc, text):
    with open("keyboard_taught.json") as f:
        data = json.load(f)
    keys = data["keys"]
    HOVER_Z = 145
    SLIDE_SPEED = 12
    PRESS_SPEED = 6
    PRESS_Z_OFFSET = 3
    kbd_z = data.get("keyboard_z", 130.3)

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
        time.sleep(1.2)
        mc.send_coords([x, y, press_z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(0.8)
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(0.8)

    mc.send_coords([x, y, 200, 0, 180, 90], 10, 0)
    time.sleep(2)


print("=" * 60)
print("  RECORDING 3-VIEW TYPING DEMO")
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

# Start recording all 3 cameras
print("Starting recording...")
recording = True
t1 = threading.Thread(target=record_rs, args=(pipeline, aligner), daemon=True)
t2 = threading.Thread(target=record_pi, daemon=True)
t3 = threading.Thread(target=record_overview, daemon=True)
t1.start()
t2.start()
t3.start()
time.sleep(1)

# Type "sad"
print('Typing "sad"...')
type_for_recording(mc, "sad")

# Stop recording
time.sleep(1)
recording = False
t1.join(timeout=3)
t2.join(timeout=3)
t3.join(timeout=3)

print(f"Captured: RS={len(rs_frames)}, Pi={len(pi_frames)}, OV={len(ov_frames)}")

mc.send_angles([0, 0, 0, 0, 0, 0], 10)
time.sleep(3)
mc.set_color(255, 255, 255)
pipeline.stop()

# Create 3-view GIF
n = min(len(rs_frames), len(pi_frames), len(ov_frames)) if ov_frames else min(len(rs_frames), len(pi_frames))
if n == 0:
    print("No frames!")
    exit()

print(f"Creating 3-view GIF from {n} frames...")

target_h = 240
combined_frames = []

for i in range(0, n, 2):  # Skip every other frame
    rs_img = rs_frames[i]
    pi_img = pi_frames[min(i, len(pi_frames)-1)]

    # Resize to same height
    rs_r = cv2.resize(rs_img, (int(rs_img.shape[1] * target_h / rs_img.shape[0]), target_h))
    pi_r = cv2.resize(pi_img, (int(pi_img.shape[1] * target_h / pi_img.shape[0]), target_h))

    # Add labels
    cv2.putText(rs_r, "Overhead (RealSense)", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    cv2.putText(pi_r, "Side View", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

    if ov_frames and i < len(ov_frames):
        ov_img = ov_frames[i]
        ov_r = cv2.resize(ov_img, (int(ov_img.shape[1] * target_h / ov_img.shape[0]), target_h))
        cv2.putText(ov_r, "Overview", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
        combined = np.hstack([rs_r, pi_r, ov_r])
    else:
        combined = np.hstack([rs_r, pi_r])

    # Cap width
    max_w = 960
    if combined.shape[1] > max_w:
        scale = max_w / combined.shape[1]
        combined = cv2.resize(combined, (max_w, int(combined.shape[0] * scale)))

    combined_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
    combined_frames.append(combined_rgb)

# Save GIF
fps = 8
pil_frames = [Image.fromarray(f).quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in combined_frames]
pil_frames[0].save(
    "demo_typing_3view.gif",
    save_all=True,
    append_images=pil_frames[1:],
    duration=int(1000 / fps),
    loop=0,
    optimize=True,
)
size_kb = os.path.getsize("demo_typing_3view.gif") / 1024
print(f"GIF saved: demo_typing_3view.gif ({len(pil_frames)} frames, {size_kb:.0f}KB)")

# If too big, create a smaller version
if size_kb > 5000:
    smaller = pil_frames[::2]
    smaller[0].save("demo_typing_3view.gif", save_all=True, append_images=smaller[1:],
                    duration=250, loop=0, optimize=True)
    size_kb = os.path.getsize("demo_typing_3view.gif") / 1024
    print(f"Reduced GIF: {size_kb:.0f}KB ({len(smaller)} frames)")

print("\nDone!")
