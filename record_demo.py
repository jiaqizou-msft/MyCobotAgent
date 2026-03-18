"""
Record a typing demo from both cameras simultaneously, then create a
side-by-side GIF for the README.

1. Start recording from RealSense (side view) + Pi camera (overhead)
2. Robot types "sad" 
3. Stop recording, combine into side-by-side frames
4. Export as GIF
"""
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import threading
import os
from pymycobot import MyCobot280Socket

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
CAMERA_URL = 'http://10.105.230.93:8080/snapshot'
os.makedirs("temp", exist_ok=True)

# --- Global frame storage ---
rs_frames = []
pi_frames = []
timestamps = []
recording = False


def record_realsense(pipeline, align):
    """Background thread: capture RealSense frames."""
    global recording
    while recording:
        try:
            frames = pipeline.wait_for_frames()
            aligned = align.process(frames)
            color = np.asanyarray(aligned.get_color_frame().get_data())
            rs_frames.append(color.copy())
            timestamps.append(time.time())
        except:
            pass
        time.sleep(0.1)  # ~10fps


def record_pi():
    """Background thread: capture Pi camera frames."""
    global recording
    while recording:
        try:
            resp = httpx.get(CAMERA_URL, timeout=3.0)
            img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
            pi_frames.append(img.copy())
        except:
            pass
        time.sleep(0.1)  # ~10fps


def type_text_for_recording(mc, text):
    """Type text using the press_key module logic."""
    import json
    with open("keyboard_taught.json", "r") as f:
        data = json.load(f)
    keys = data["keys"]

    HOVER_Z = 85
    SLIDE_SPEED = 12
    PRESS_SPEED = 6
    PRESS_Z_OFFSET = 3

    positions = []
    for char in text:
        key = 'space' if char == ' ' else char.lower()
        if key in keys and keys[key].get("coords"):
            coords = keys[key]["coords"][:3]
            positions.append((key, coords))

    if not positions:
        return

    # Move to start
    x, y, z = positions[0][1]
    mc.send_coords([x, y, HOVER_Z, 0, 180, 90], 8, 0)
    time.sleep(3)

    for key, (x, y, z) in positions:
        press_z = z - PRESS_Z_OFFSET
        # Slide
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], SLIDE_SPEED, 0)
        time.sleep(1.2)
        # Press
        mc.send_coords([x, y, press_z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(0.8)
        # Release
        mc.send_coords([x, y, HOVER_Z, 0, 180, 90], PRESS_SPEED, 0)
        time.sleep(0.8)

    # Retreat
    mc.send_coords([x, y, 200, 0, 180, 90], 10, 0)
    time.sleep(2)


def create_side_by_side_gif(output_path="demo_typing.gif", fps=8, max_width=800):
    """Combine RS and Pi frames into a side-by-side GIF."""
    n = min(len(rs_frames), len(pi_frames))
    if n == 0:
        print("No frames captured!")
        return

    print(f"Creating GIF from {n} frame pairs...")

    # Subsample to target fps (we recorded at ~10fps, want ~8fps for GIF)
    step = max(1, n // (fps * 10))  # aim for ~10 seconds of GIF

    combined_frames = []
    for i in range(0, n, step):
        rs_img = rs_frames[i]
        pi_img = pi_frames[i]

        # Resize both to same height
        target_h = 360
        rs_h, rs_w = rs_img.shape[:2]
        pi_h, pi_w = pi_img.shape[:2]

        rs_resized = cv2.resize(rs_img, (int(rs_w * target_h / rs_h), target_h))
        pi_resized = cv2.resize(pi_img, (int(pi_w * target_h / pi_h), target_h))

        # Add labels
        cv2.putText(rs_resized, "RealSense (side)", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(pi_resized, "Pi Camera (overhead)", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        combined = np.hstack([rs_resized, pi_resized])

        # Limit total width
        if combined.shape[1] > max_width:
            scale = max_width / combined.shape[1]
            combined = cv2.resize(combined, (max_width, int(combined.shape[0] * scale)))

        # Convert BGR to RGB for PIL
        combined_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
        combined_frames.append(combined_rgb)

    # Save as GIF using PIL
    from PIL import Image
    pil_frames = [Image.fromarray(f) for f in combined_frames]
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=int(1000 / fps),
        loop=0,
        optimize=True,
    )
    print(f"GIF saved: {output_path} ({len(pil_frames)} frames, {os.path.getsize(output_path) / 1024:.0f}KB)")

    # Also save as MP4 for better quality
    mp4_path = output_path.replace(".gif", ".mp4")
    h, w = combined_frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(mp4_path, fourcc, fps, (w, h))
    for f in combined_frames:
        writer.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    writer.release()
    print(f"MP4 saved: {mp4_path} ({os.path.getsize(mp4_path) / 1024:.0f}KB)")


# ===== MAIN =====
print("=" * 60)
print("  RECORDING TYPING DEMO")
print("=" * 60)

# Connect
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
align = rs.align(rs.stream.color)
for _ in range(30):
    pipeline.wait_for_frames()

# Go home first
print("Going home...")
mc.send_angles([0, 0, 0, 0, 0, 0], 10)
time.sleep(4)

# Start recording
print("Starting recording...")
recording = True
rs_thread = threading.Thread(target=record_realsense, args=(pipeline, align), daemon=True)
pi_thread = threading.Thread(target=record_pi, daemon=True)
rs_thread.start()
pi_thread.start()
time.sleep(1)

# Type "sad"
print('Typing "sad"...')
type_text_for_recording(mc, "sad")

# Stop recording
time.sleep(1)
recording = False
rs_thread.join(timeout=3)
pi_thread.join(timeout=3)
print(f"Recorded: {len(rs_frames)} RealSense frames, {len(pi_frames)} Pi frames")

# Go home
mc.send_angles([0, 0, 0, 0, 0, 0], 10)
time.sleep(3)
mc.set_color(255, 255, 255)

# Stop RealSense
pipeline.stop()

# Create GIF
create_side_by_side_gif("demo_typing.gif", fps=8)

print("\nDone!")
