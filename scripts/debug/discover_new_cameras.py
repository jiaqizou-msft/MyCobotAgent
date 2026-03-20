"""Discover the new camera setup and capture from all cameras."""
import cv2
import numpy as np
import os

os.makedirs("temp", exist_ok=True)

print("=" * 60)
print("  CAMERA DISCOVERY (updated setup)")
print("=" * 60)

# RealSense
print("\n--- RealSense ---")
try:
    import pyrealsense2 as rs
    ctx = rs.context()
    for d in ctx.query_devices():
        sn = d.get_info(rs.camera_info.serial_number)
        print(f"  {d.get_info(rs.camera_info.name)} SN:{sn}")
except Exception as e:
    print(f"  {e}")

# USB webcams
print("\n--- USB Webcams ---")
for idx in range(8):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if cap.isOpened():
        # Try higher resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        ret, frame = cap.read()
        if ret and frame is not None:
            cv2.imwrite(f"temp/cam_{idx}.jpg", frame)
            print(f"  Camera {idx}: {frame.shape[1]}x{frame.shape[0]} -> temp/cam_{idx}.jpg")
        cap.release()

print("\nOpen temp/cam_*.jpg to identify which is the new front webcam.")
