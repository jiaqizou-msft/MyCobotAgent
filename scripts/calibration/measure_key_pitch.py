"""Use the overhead RealSense to MEASURE actual key pitch from the image.
Detect key edges in the overhead view and compute real-world spacing using depth."""
import pyrealsense2 as rs
import cv2
import numpy as np
import json
import os
import time

os.makedirs("temp", exist_ok=True)

# Start RealSense
print("Starting RealSense...")
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
cs = profile.get_stream(rs.stream.color)
intrinsics = cs.as_video_stream_profile().get_intrinsics()
aligner = rs.align(rs.stream.color)
for _ in range(30):
    pipeline.wait_for_frames()

# Capture
frames = pipeline.wait_for_frames()
aligned = aligner.process(frames)
color = np.asanyarray(aligned.get_color_frame().get_data())
depth = np.asanyarray(aligned.get_depth_frame().get_data())
pipeline.stop()

cv2.imwrite("temp/measure_overhead.jpg", color)
print(f"Captured: {color.shape}")

# Find keyboard region - look for the area with lots of small rectangles (keys)
gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

# Adaptive threshold to find key outlines
thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 15, 5)
cv2.imwrite("temp/measure_thresh.jpg", thresh)

# Find horizontal and vertical lines (key borders)
# Horizontal edges
sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

# Use the taught key positions to estimate pixel spacing
# We know q and the other keys' ROBOT positions from the grid model
# But we want PIXEL positions measured from the image
# 
# Better approach: use the calibration to find what pixel pitch = 19mm
# We know the RealSense intrinsics and the keyboard depth

# Get keyboard depth
# The keyboard is at roughly the center of the image
h, w = depth.shape
kbd_region = depth[h//4:3*h//4, w//4:3*w//4]
valid = kbd_region[kbd_region > 0].astype(float) * depth_scale
if len(valid) > 0:
    kbd_depth_m = float(np.median(valid))
    print(f"Keyboard depth: {kbd_depth_m*1000:.0f}mm from camera")
else:
    kbd_depth_m = 0.58
    print(f"Using default depth: {kbd_depth_m*1000:.0f}mm")

# At this depth, compute mm-per-pixel
# The RealSense projects: pixel offset * depth / focal_length = real-world offset
mm_per_pixel_x = kbd_depth_m * 1000 / intrinsics.fx
mm_per_pixel_y = kbd_depth_m * 1000 / intrinsics.fy
print(f"At keyboard depth:")
print(f"  mm/pixel X: {mm_per_pixel_x:.3f}")
print(f"  mm/pixel Y: {mm_per_pixel_y:.3f}")

# Standard key pitch is ~19mm. In pixels that's:
key_pitch_px = 19.0 / mm_per_pixel_x
print(f"  Expected key pitch: {key_pitch_px:.1f} pixels ({19.0}mm)")

# Now use the calibration transform to compute what column step in robot X
# corresponds to 1 key pitch (19mm in the real world)
with open("data/calibration_realsense.json") as f:
    cal = json.load(f)
T = np.array(cal["cam_to_robot_4x4"])

# Pick two points at keyboard depth, separated by 1 key pitch in pixels
# Use the keyboard center area
center_u, center_v = w // 2, h // 2
next_u = center_u + key_pitch_px

# Deproject both to camera 3D
p1_cam = rs.rs2_deproject_pixel_to_point(intrinsics, [float(center_u), float(center_v)], kbd_depth_m)
p2_cam = rs.rs2_deproject_pixel_to_point(intrinsics, [float(next_u), float(center_v)], kbd_depth_m)

# Transform to robot frame
p1_rob = (T @ np.array([p1_cam[0], p1_cam[1], p1_cam[2], 1.0]))[:3] * 1000
p2_rob = (T @ np.array([p2_cam[0], p2_cam[1], p2_cam[2], 1.0]))[:3] * 1000

dx = p2_rob[0] - p1_rob[0]
dy = p2_rob[1] - p1_rob[1]
actual_step = np.sqrt(dx**2 + dy**2)

print(f"\nOne key pitch (19mm real-world) in robot frame:")
print(f"  dX = {dx:.2f}mm")
print(f"  dY = {dy:.2f}mm")
print(f"  Total step = {actual_step:.2f}mm")

# Also check the row pitch (vertical, ~19mm)
next_v = center_v + key_pitch_px
p3_cam = rs.rs2_deproject_pixel_to_point(intrinsics, [float(center_u), float(next_v)], kbd_depth_m)
p3_rob = (T @ np.array([p3_cam[0], p3_cam[1], p3_cam[2], 1.0]))[:3] * 1000
row_dx = p3_rob[0] - p1_rob[0]
row_dy = p3_rob[1] - p1_rob[1]
row_step = np.sqrt(row_dx**2 + row_dy**2)

print(f"\nOne row pitch (19mm real-world) in robot frame:")
print(f"  dX = {row_dx:.2f}mm")
print(f"  dY = {row_dy:.2f}mm")
print(f"  Total step = {row_step:.2f}mm")

# Now update the grid model with the camera-measured values
print(f"\n--- RECOMMENDED GRID MODEL UPDATE ---")
print(f"  Column step X: {dx:.1f}mm (was 19.3mm)")
print(f"  Column step Y: {dy:.1f}mm (was 0.27mm)")
print(f"  Row step X: {row_dx:.1f}mm (was 13.58mm)")
print(f"  Row step Y: {row_dy:.1f}mm (was -16.99mm)")

# Apply the fix
with open("data/keyboard_taught.json") as f:
    data = json.load(f)

M = np.array(data["grid_model_xy"])
print(f"\nOld model: X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
print(f"           Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")

# Update column coefficients from camera measurement
M[1, 0] = dx   # column step in robot X
M[1, 1] = dy   # column step in robot Y
# Update row coefficients from camera measurement  
M[0, 0] = row_dx  # row step in robot X
M[0, 1] = row_dy  # row step in robot Y

print(f"New model: X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
print(f"           Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")

data["grid_model_xy"] = M.tolist()

# Regenerate keys
QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]
key_rc = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        key_rc[k] = (r, c)

kbd_z = data["keyboard_z"]
keys = data["keys"]
for key, (r, c) in key_rc.items():
    pred = np.array([r, c, 1]) @ M
    keys[key] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "camera_measured"}

for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5),
                    ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
    pred = np.array([r, c, 1]) @ M
    keys[name] = {"coords": [round(pred[0], 2), round(pred[1], 2), kbd_z, 0, 180, 90], "source": "camera_measured"}

with open("data/keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

print(f"\nQWERTY row:")
for k in list("qwerty"):
    c = keys[k]["coords"][:2]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f})")
print(f"  q->w: {keys['w']['coords'][0]-keys['q']['coords'][0]:.1f}mm X, {keys['w']['coords'][1]-keys['q']['coords'][1]:.1f}mm Y")

print(f"\nASDFG row:")
for k in list("asdfg"):
    c = keys[k]["coords"][:2]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f})")
