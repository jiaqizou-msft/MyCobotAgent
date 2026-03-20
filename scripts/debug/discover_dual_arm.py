"""Discover all devices in the new dual-arm setup."""
import socket
import time
import cv2
import numpy as np
import os

os.makedirs("temp", exist_ok=True)

print("=" * 60)
print("  DUAL-ARM SETUP DISCOVERY")
print("=" * 60)

# --- Robot Arms ---
print("\n--- Robot Arms ---")
robots = {
    "right_arm (original)": ("10.105.230.93", 9000),
    "left_arm (new)": ("10.105.228.111", 9000),
}

for name, (ip, port) in robots.items():
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((ip, port))
        print(f"  {name}: {ip}:{port} - CONNECTED")
        s.close()
    except Exception as e:
        print(f"  {name}: {ip}:{port} - FAILED ({e})")

# --- Intel RealSense Cameras ---
print("\n--- Intel RealSense Cameras ---")
try:
    import pyrealsense2 as rs
    ctx = rs.context()
    devs = ctx.query_devices()
    print(f"  Found {len(devs)} RealSense devices:")
    for d in devs:
        sn = d.get_info(rs.camera_info.serial_number)
        name = d.get_info(rs.camera_info.name)
        if sn == "335222075369":
            role = "OVERHEAD"
        elif sn == "335522073146":
            role = "FRONT"
        else:
            role = "UNKNOWN"
        print(f"    {name} SN:{sn} -> {role}")
except Exception as e:
    print(f"  RealSense error: {e}")

# --- USB Webcams on laptop ---
print("\n--- USB Webcams (laptop) ---")
for idx in range(6):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret and frame is not None:
            cv2.imwrite(f"temp/cam_{idx}.jpg", frame)
            print(f"  Camera {idx}: {frame.shape[1]}x{frame.shape[0]} -> temp/cam_{idx}.jpg")
        cap.release()

# --- Pi webcam (right arm, original) ---
print("\n--- Pi Webcam (right arm) ---")
try:
    import httpx
    r = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/pi_right_arm.jpg", img)
    print(f"  Right arm Pi cam: OK ({img.shape})")
except Exception as e:
    print(f"  Right arm Pi cam: FAILED ({e})")

# --- Check if new arm Pi has a camera server ---
print("\n--- Pi Webcam (left arm, new) ---")
try:
    import httpx
    r = httpx.get("http://10.105.228.111:8080/snapshot", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/pi_left_arm.jpg", img)
    print(f"  Left arm Pi cam: OK ({img.shape})")
except Exception as e:
    print(f"  Left arm Pi cam: No camera server ({e})")

# --- Test robot connections with pymycobot ---
print("\n--- Robot Connection Tests ---")
from pymycobot import MyCobot280Socket

for name, (ip, port) in robots.items():
    try:
        mc = MyCobot280Socket(ip, port)
        time.sleep(1)
        mc.power_on()
        time.sleep(1)
        power = mc.is_power_on()
        time.sleep(0.3)
        angles = mc.get_angles()
        time.sleep(0.3)
        print(f"  {name} ({ip}): power={power}, angles={angles}")
        mc.set_color(0, 255, 0)
        time.sleep(0.5)
        mc.set_color(255, 255, 255)
    except Exception as e:
        print(f"  {name} ({ip}): FAILED ({e})")

print("\n" + "=" * 60)
print("  SETUP SUMMARY")
print("=" * 60)
print("""
  Layout (top view):
  
       [Left Arm]    [Laptop/DUT]    [Right Arm]
     10.105.228.111                10.105.230.93
     (new)                         (original)
     
  Cameras:
    Overhead RealSense (SN:335222075369) -> dev laptop USB
    Front RealSense (SN:335522073146) -> dev laptop USB
    Right arm Pi webcam -> http://10.105.230.93:8080
    Dev laptop webcam(s) -> local USB
""")
