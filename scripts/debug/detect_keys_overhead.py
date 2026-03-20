"""
Detect individual keyboard keys from overhead RealSense image.
Steps:
  1. Capture overhead RGBD
  2. Isolate keyboard surface via depth
  3. Detect individual key rectangles via adaptive threshold
  4. Arrange into grid rows/cols
  5. Match to QWERTY layout
  6. For each key: pixel center + depth -> camera 3D
  7. Use taught reference keys to compute pixel->robot affine per arm
  8. Save all key positions in both pixel and robot coords
"""
import pyrealsense2 as rs
import cv2
import numpy as np
import json
import os
import time

os.makedirs("temp", exist_ok=True)

RS_OVERHEAD_SN = "335222075369"

print("=" * 60)
print("  OVERHEAD KEY DETECTION")
print("=" * 60)

# Capture from overhead RealSense
print("\nCapturing overhead RGBD...")
pipeline = rs.pipeline()
config = rs.config()
config.enable_device(RS_OVERHEAD_SN)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
cs = profile.get_stream(rs.stream.color)
intrinsics = cs.as_video_stream_profile().get_intrinsics()
aligner = rs.align(rs.stream.color)
for _ in range(30):
    pipeline.wait_for_frames()

# Capture multiple and average for noise reduction
frames = pipeline.wait_for_frames()
aligned = aligner.process(frames)
color = np.asanyarray(aligned.get_color_frame().get_data())
depth = np.asanyarray(aligned.get_depth_frame().get_data())
pipeline.stop()

cv2.imwrite("temp/overhead_full.jpg", color)
depth_vis = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.05), cv2.COLORMAP_JET)
cv2.imwrite("temp/overhead_depth.jpg", depth_vis)
print(f"  Color: {color.shape}, Depth scale: {depth_scale}")

# The RealSense is mounted upside down — flip both color and depth 180 degrees
color = cv2.rotate(color, cv2.ROTATE_180)
depth = cv2.rotate(depth, cv2.ROTATE_180)
cv2.imwrite("temp/overhead_flipped.jpg", color)
print("  Flipped 180 degrees (camera mounted upside down)")

# Step 1: Find keyboard surface depth
depth_m = depth.astype(float) * depth_scale
valid = depth_m[depth_m > 0]
print(f"  Depth range: {valid.min()*1000:.0f}-{valid.max()*1000:.0f}mm")

# Histogram to find dominant flat surface (the keyboard)
valid_mm = valid * 1000
hist, bins = np.histogram(valid_mm[(valid_mm > 200) & (valid_mm < 800)], bins=100)
peak_idx = np.argmax(hist)
kbd_depth_mm = (bins[peak_idx] + bins[peak_idx + 1]) / 2
print(f"  Keyboard surface depth: {kbd_depth_mm:.0f}mm")

# Step 2: Mask the keyboard surface (+/- 15mm)
surface_mask = ((depth_m * 1000 > kbd_depth_mm - 15) & 
                (depth_m * 1000 < kbd_depth_mm + 15) &
                (depth_m > 0)).astype(np.uint8) * 255
kernel = np.ones((5, 5), np.uint8)
surface_mask = cv2.morphologyEx(surface_mask, cv2.MORPH_CLOSE, kernel)
surface_mask = cv2.morphologyEx(surface_mask, cv2.MORPH_OPEN, kernel)
cv2.imwrite("temp/keyboard_surface_mask.jpg", surface_mask)

# Step 3: Find the keyboard bounding box from the surface mask
contours, _ = cv2.findContours(surface_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
if not contours:
    print("  No keyboard surface found!")
    exit(1)

largest = max(contours, key=cv2.contourArea)
kbd_x, kbd_y, kbd_w, kbd_h = cv2.boundingRect(largest)
print(f"  Keyboard region: ({kbd_x},{kbd_y}) {kbd_w}x{kbd_h}")

# Step 4: Detect individual keys within keyboard region
kbd_roi = color[kbd_y:kbd_y+kbd_h, kbd_x:kbd_x+kbd_w]
kbd_gray = cv2.cvtColor(kbd_roi, cv2.COLOR_BGR2GRAY)

# Adaptive threshold to find key gaps (dark lines between keys)
thresh = cv2.adaptiveThreshold(kbd_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 11, 3)
cv2.imwrite("temp/keyboard_thresh.jpg", thresh)

# Invert: key gaps become white
gaps = cv2.bitwise_not(thresh)
# Thin the gaps
gap_kernel = np.ones((2, 2), np.uint8)
gaps = cv2.morphologyEx(gaps, cv2.MORPH_OPEN, gap_kernel)
cv2.imwrite("temp/keyboard_gaps.jpg", gaps)

# Find key contours on the thresholded image
key_contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

# Filter: keys are roughly square-ish rectangles of a certain size
key_min_area = (kbd_w / 20) * (kbd_h / 6) * 0.3  # min ~30% of expected key size
key_max_area = (kbd_w / 20) * (kbd_h / 6) * 3.0   # max ~300% of expected key size

key_rects = []
for cnt in key_contours:
    area = cv2.contourArea(cnt)
    if area < key_min_area or area > key_max_area:
        continue
    x, y, w, h = cv2.boundingRect(cnt)
    aspect = max(w, h) / (min(w, h) + 1)
    if aspect > 3:
        continue
    # Center in full image coords
    cx = kbd_x + x + w // 2
    cy = kbd_y + y + h // 2
    key_rects.append({"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy, "area": area})

print(f"  Found {len(key_rects)} key-like rectangles")

# Step 5: Sort into rows and columns
if key_rects:
    # Sort by Y to find rows
    key_rects.sort(key=lambda k: k["cy"])
    
    # Cluster into rows (Y values within ~15px are same row)
    rows = []
    current_row = [key_rects[0]]
    for kr in key_rects[1:]:
        if abs(kr["cy"] - current_row[-1]["cy"]) < 15:
            current_row.append(kr)
        else:
            rows.append(sorted(current_row, key=lambda k: k["cx"]))
            current_row = [kr]
    rows.append(sorted(current_row, key=lambda k: k["cx"]))
    
    print(f"  Organized into {len(rows)} rows:")
    for i, row in enumerate(rows):
        print(f"    Row {i}: {len(row)} keys, Y~{row[0]['cy']}")

# Step 6: Match to QWERTY layout
QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]

detected_keys = {}
vis = color.copy()

# Use only the main 4 rows (skip function row if detected)
main_rows = rows[-4:] if len(rows) >= 4 else rows

for row_idx, (row, qwerty_row) in enumerate(zip(main_rows, QWERTY)):
    n_keys = len(row)
    n_qwerty = len(qwerty_row)
    
    # Map detected keys to QWERTY names
    # If we have more/fewer keys than QWERTY, do best-effort mapping
    for ki, kr in enumerate(row):
        # Map to closest QWERTY column
        col_idx = int(round(ki * n_qwerty / n_keys)) if n_keys > 0 else ki
        col_idx = min(col_idx, n_qwerty - 1)
        key_name = qwerty_row[col_idx]
        
        px, py = kr["cx"], kr["cy"]
        
        # Get depth at this key
        key_depth = depth_m[py, px] if depth_m[py, px] > 0 else kbd_depth_mm / 1000.0
        
        detected_keys[key_name] = {
            "pixel": (px, py),
            "depth_m": float(key_depth),
            "bbox": (kr["x"] + kbd_x, kr["y"] + kbd_y, kr["w"], kr["h"]),
            "row": row_idx,
            "col": col_idx,
        }
        
        # Draw on visualization
        bx, by, bw, bh = kr["x"] + kbd_x, kr["y"] + kbd_y, kr["w"], kr["h"]
        cv2.rectangle(vis, (bx, by), (bx + bw, by + bh), (0, 255, 0), 1)
        cv2.circle(vis, (px, py), 3, (0, 0, 255), -1)
        cv2.putText(vis, key_name, (px - 5, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 0), 1)

cv2.imwrite("temp/keyboard_keys_detected.jpg", vis)
print(f"\n  Detected {len(detected_keys)} keys with labels")

# Step 7: Compute pixel->robot affine using taught reference keys
print("\n--- Computing pixel-to-robot transforms ---")

with open("data/keyboard_dual_arm.json") as f:
    dual_layout = json.load(f)

for arm_name in ["left", "right"]:
    arm_data = dual_layout["arms"].get(arm_name, {})
    taught = arm_data.get("taught_reference", {})
    kbd_z = arm_data.get("keyboard_z", 130)
    
    if len(taught) < 3:
        print(f"  {arm_name}: only {len(taught)} taught keys, need 3+ for affine. Skipping.")
        continue
    
    # Build pixel->robot affine from taught keys that we also detected
    A, B = [], []
    for key, robot_xyz in taught.items():
        if key in detected_keys:
            px, py = detected_keys[key]["pixel"]
            A.append([px, py, 1])
            B.append([robot_xyz[0], robot_xyz[1]])
            print(f"    {arm_name}/{key}: pixel=({px},{py}) -> robot=({robot_xyz[0]:.1f},{robot_xyz[1]:.1f})")
    
    if len(A) < 3:
        print(f"  {arm_name}: only {len(A)} matched points. Need 3+.")
        # Use all taught keys even if not detected, with estimated pixels
        continue
    
    A = np.array(A, dtype=float)
    B = np.array(B, dtype=float)
    M_pix, _, _, _ = np.linalg.lstsq(A, B, rcond=None)
    
    # Verify
    pred = A @ M_pix
    errors = np.sqrt(np.sum((pred - B)**2, axis=1))
    print(f"  {arm_name} pixel->robot affine: mean error={np.mean(errors):.1f}mm")
    
    # Generate robot coords for ALL detected keys using this affine
    for key, kdata in detected_keys.items():
        px, py = kdata["pixel"]
        robot_xy = np.array([px, py, 1]) @ M_pix
        kdata[f"robot_{arm_name}"] = [round(float(robot_xy[0]), 2), round(float(robot_xy[1]), 2), kbd_z]
        kdata[f"reachable_{arm_name}"] = -281 <= robot_xy[0] <= 281

# Step 8: Save everything
output = {
    "detected_keys": detected_keys,
    "keyboard_bounds_px": [kbd_x, kbd_y, kbd_w, kbd_h],
    "keyboard_depth_mm": kbd_depth_mm,
    "intrinsics": {"fx": intrinsics.fx, "fy": intrinsics.fy,
                   "ppx": intrinsics.ppx, "ppy": intrinsics.ppy},
    "num_rows": len(main_rows),
    "keys_per_row": [len(r) for r in main_rows],
}
with open("data/keyboard_vision_detected.json", "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nSaved {len(detected_keys)} detected keys to data/keyboard_vision_detected.json")
print(f"Visualization: temp/keyboard_keys_detected.jpg")

# Summary
left_reachable = [k for k, v in detected_keys.items() if v.get("reachable_left")]
right_reachable = [k for k, v in detected_keys.items() if v.get("reachable_right")]
print(f"\nReachable by left arm:  {len(left_reachable)} keys")
print(f"Reachable by right arm: {len(right_reachable)} keys")
print(f"Total unique reachable: {len(set(left_reachable + right_reachable))} keys")
