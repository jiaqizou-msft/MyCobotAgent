"""Capture from both cameras to see the current workspace layout."""
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import os
import time

os.makedirs("temp", exist_ok=True)

# --- RealSense (side view, USB to laptop) ---
print("Capturing from RealSense (side view)...")
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
align = rs.align(rs.stream.color)

# Let auto-exposure settle
for _ in range(30):
    pipeline.wait_for_frames()

frames = pipeline.wait_for_frames()
aligned = align.process(frames)
rs_color = np.asanyarray(aligned.get_color_frame().get_data())
rs_depth = np.asanyarray(aligned.get_depth_frame().get_data())

cv2.imwrite("temp/dual_rs_color.jpg", rs_color)
depth_cm = cv2.applyColorMap(cv2.convertScaleAbs(rs_depth, alpha=0.03), cv2.COLORMAP_JET)
cv2.imwrite("temp/dual_rs_depth.jpg", depth_cm)
print(f"  RealSense color: {rs_color.shape}")
print(f"  RealSense depth range: {rs_depth[rs_depth>0].min() if (rs_depth>0).any() else 0}-{rs_depth.max()}mm")

pipeline.stop()

# --- Pi camera (overhead view) ---
print("\nCapturing from Pi camera (overhead view)...")
try:
    resp = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5.0)
    pi_color = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/dual_pi_color.jpg", pi_color)
    print(f"  Pi color: {pi_color.shape}")
except Exception as e:
    print(f"  Pi camera failed: {e}")

# --- Create a side-by-side comparison ---
try:
    pi_resized = cv2.resize(pi_color, (640, 480))
    combined = np.hstack([rs_color, pi_resized])
    cv2.putText(combined, "RealSense (side)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(combined, "Pi Camera (overhead)", (650, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.imwrite("temp/dual_combined.jpg", combined)
    print("\nSide-by-side saved to temp/dual_combined.jpg")
except Exception:
    pass

print("\nDone! Opening images...")
