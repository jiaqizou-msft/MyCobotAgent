"""Test all devices in the dual-arm setup."""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import os

os.makedirs("temp", exist_ok=True)

print("=" * 60)
print("  DUAL-ARM FULL SYSTEM TEST")
print("=" * 60)

# --- Both Robot Arms ---
print("\n--- Robot Arms ---")
arms = {
    "RIGHT": ("10.105.230.93", 9000),
    "LEFT":  ("10.105.230.94", 9000),
}

mc_right = None
mc_left = None

for name, (ip, port) in arms.items():
    try:
        mc = MyCobot280Socket(ip, port)
        time.sleep(1)
        mc.power_on()
        time.sleep(1)
        for _ in range(5):
            a = mc.get_angles()
            time.sleep(0.3)
            if a and a != -1:
                break
        print(f"  {name} ({ip}): power={mc.is_power_on()}, angles={a}")
        if name == "RIGHT":
            mc.set_color(255, 0, 0)  # Red
            mc_right = mc
        else:
            mc.set_color(0, 0, 255)  # Blue
            mc_left = mc
    except Exception as e:
        print(f"  {name} ({ip}): FAILED ({e})")

time.sleep(1)

# --- Both RealSense Cameras ---
print("\n--- RealSense Cameras ---")
ctx = rs.context()
devs = ctx.query_devices()
for d in devs:
    sn = d.get_info(rs.camera_info.serial_number)
    role = "OVERHEAD" if sn == "335222075369" else "FRONT" if sn == "335522073146" else "?"
    print(f"  {role}: SN={sn}")

# Capture from each RealSense by serial number
for sn, role in [("335222075369", "overhead"), ("335522073146", "front")]:
    try:
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(sn)
        config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        profile = pipeline.start(config)
        for _ in range(15):
            pipeline.wait_for_frames()
        frames = pipeline.wait_for_frames()
        color = np.asanyarray(frames.get_color_frame().get_data())
        cv2.imwrite(f"temp/rs_{role}.jpg", color)
        print(f"  {role}: captured {color.shape}")
        pipeline.stop()
    except Exception as e:
        print(f"  {role}: FAILED ({e})")

# --- Pi Webcam (right arm) ---
print("\n--- Pi Webcam ---")
try:
    r = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/pi_webcam.jpg", img)
    print(f"  Right arm Pi cam: OK ({img.shape})")
except Exception as e:
    print(f"  Right arm Pi cam: {e}")

# --- Quick motion test: both arms wave ---
print("\n--- Motion Test ---")

if mc_right:
    print("  Right arm: waving...")
    mc_right.send_angles([0, -30, 0, 0, 0, 0], 30)

if mc_left:
    print("  Left arm: waving...")
    mc_left.send_angles([0, -30, 0, 0, 0, 0], 30)

time.sleep(3)

if mc_right:
    mc_right.send_angles([0, 0, 0, 0, 0, 0], 30)
if mc_left:
    mc_left.send_angles([0, 0, 0, 0, 0, 0], 30)

time.sleep(3)

if mc_right:
    mc_right.set_color(255, 255, 255)
if mc_left:
    mc_left.set_color(255, 255, 255)

# --- Summary ---
print(f"\n{'='*60}")
print("  SYSTEM STATUS")
print(f"{'='*60}")
print(f"  Right arm (10.105.230.93): {'OK' if mc_right else 'FAILED'}")
print(f"  Left arm  (10.105.230.94): {'OK' if mc_left else 'FAILED'}")
print(f"  Overhead RealSense (335222075369): check temp/rs_overhead.jpg")
print(f"  Front RealSense (335522073146): check temp/rs_front.jpg")
print(f"  Pi webcam: check temp/pi_webcam.jpg")
print(f"\n  Both arms should have waved!")
