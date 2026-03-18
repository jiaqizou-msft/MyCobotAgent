"""Discover all cameras: RealSense + USB webcams on laptop, Pi webcam over network."""
import cv2
import numpy as np
import httpx
import os

os.makedirs("temp", exist_ok=True)

print("=" * 60)
print("  CAMERA DISCOVERY")
print("=" * 60)

# --- RealSense on laptop ---
print("\n--- Intel RealSense (laptop USB) ---")
try:
    import pyrealsense2 as rs
    ctx = rs.context()
    devs = ctx.query_devices()
    print(f"  RealSense devices: {len(devs)}")
    for d in devs:
        print(f"    {d.get_info(rs.camera_info.name)} SN:{d.get_info(rs.camera_info.serial_number)}")
except Exception as e:
    print(f"  RealSense: {e}")

# --- USB webcams on laptop ---
print("\n--- USB Webcams (laptop) ---")
found_webcams = []
for idx in range(5):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # DirectShow on Windows
    if cap.isOpened():
        ret, frame = cap.read()
        if ret and frame is not None:
            name = f"webcam_{idx}"
            cv2.imwrite(f"temp/laptop_cam{idx}.jpg", frame)
            found_webcams.append(idx)
            print(f"  Camera {idx}: {frame.shape[1]}x{frame.shape[0]} - saved temp/laptop_cam{idx}.jpg")
        cap.release()

# --- Pi webcam (overhead, via network) ---
print("\n--- Pi Webcam (overhead, network) ---")
try:
    r = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/pi_overhead.jpg", img)
    print(f"  Pi overhead: {img.shape[1]}x{img.shape[0]} - saved temp/pi_overhead.jpg")
except Exception as e:
    print(f"  Pi overhead: FAILED {e}")

# --- Summary ---
print(f"\n{'='*60}")
print("  CAMERA SUMMARY")
print(f"{'='*60}")
print(f"  RealSense D435i (laptop USB): RGBD, for depth measurements")
print(f"  Laptop webcam(s): {found_webcams} - overview camera(s)")
print(f"  Pi webcam (network): overhead view of workspace")
print(f"\nOpen temp/ folder to see all camera views.")
