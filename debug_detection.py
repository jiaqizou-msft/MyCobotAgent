"""Debug: Move robot to a visible position with LED on, capture from RealSense,
analyze the color to find the right detection thresholds."""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs
import cv2
import numpy as np
import time
import os

os.makedirs("temp", exist_ok=True)

# Connect
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(1)

# Start RealSense
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
profile = pipeline.start(config)
align = rs.align(rs.stream.color)
for _ in range(30):
    pipeline.wait_for_frames()

# Move to a position and set LED bright green
print("Moving to (150, 0, 180) slowly...")
mc.send_angles([0, 0, 0, 0, 0, 0], 10)
time.sleep(5)
mc.set_color(0, 255, 0)
time.sleep(1)
mc.send_coords([150, 0, 180, 0, 180, 90], 10, 0)
time.sleep(6)
mc.set_color(0, 255, 0)
time.sleep(1)

# Capture multiple frames
print("Capturing from RealSense...")
for _ in range(5):
    pipeline.wait_for_frames()

frames = pipeline.wait_for_frames()
aligned = align.process(frames)
color = np.asanyarray(aligned.get_color_frame().get_data())
depth = np.asanyarray(aligned.get_depth_frame().get_data())

cv2.imwrite("temp/debug_rs_color.jpg", color)
depth_cm = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.03), cv2.COLORMAP_JET)
cv2.imwrite("temp/debug_rs_depth.jpg", depth_cm)

# Analyze HSV
hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)

# Try multiple green ranges
ranges = [
    ("narrow_green", np.array([35, 80, 80]), np.array([85, 255, 255])),
    ("wide_green", np.array([25, 50, 50]), np.array([95, 255, 255])),
    ("bright_any", np.array([0, 0, 200]), np.array([180, 80, 255])),
    ("saturated_green", np.array([35, 120, 120]), np.array([85, 255, 255])),
]

for name, lower, upper in ranges:
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    areas = sorted([cv2.contourArea(c) for c in contours], reverse=True)[:5]
    cv2.imwrite(f"temp/debug_mask_{name}.jpg", mask)
    print(f"  {name}: {len(contours)} contours, top areas: {areas}")

# Also try detecting any bright spot (the LED is very bright)
gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
_, bright_mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
cv2.imwrite("temp/debug_mask_bright.jpg", bright_mask)
contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
areas = sorted([cv2.contourArea(c) for c in contours], reverse=True)[:5]
print(f"  bright_thresh: {len(contours)} contours, top areas: {areas}")

# Try to find any bright green/white spot manually
# Look at the max brightness region
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(gray)
print(f"\n  Brightest pixel: {max_loc} = {max_val}")
print(f"  BGR at brightest: {color[max_loc[1], max_loc[0]]}")
print(f"  HSV at brightest: {hsv[max_loc[1], max_loc[0]]}")

# Draw the brightest spot
vis = color.copy()
cv2.circle(vis, max_loc, 15, (0, 0, 255), 2)
cv2.putText(vis, "brightest", (max_loc[0]+15, max_loc[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
cv2.imwrite("temp/debug_rs_annotated.jpg", vis)

# Also try with RED LED since green might be hard to see from side
print("\nSwitching LED to RED...")
mc.set_color(255, 0, 0)
time.sleep(1)
frames = pipeline.wait_for_frames()
aligned = align.process(frames)
color2 = np.asanyarray(aligned.get_color_frame().get_data())
cv2.imwrite("temp/debug_rs_red_led.jpg", color2)

# Try BLUE LED
print("Switching LED to BLUE...")
mc.set_color(0, 0, 255)
time.sleep(1)
frames = pipeline.wait_for_frames()
aligned = align.process(frames)
color3 = np.asanyarray(aligned.get_color_frame().get_data())
cv2.imwrite("temp/debug_rs_blue_led.jpg", color3)

# Try WHITE LED (brightest)
print("Switching LED to WHITE (brightest)...")
mc.set_color(255, 255, 255)
time.sleep(1)
frames = pipeline.wait_for_frames()
aligned = align.process(frames)
color4 = np.asanyarray(aligned.get_color_frame().get_data())
cv2.imwrite("temp/debug_rs_white_led.jpg", color4)

# Diff between green and off
mc.set_color(0, 0, 0)
time.sleep(1)
frames = pipeline.wait_for_frames()
aligned = align.process(frames)
color_off = np.asanyarray(aligned.get_color_frame().get_data())
cv2.imwrite("temp/debug_rs_led_off.jpg", color_off)

# Compute difference image (green_on - off)
diff = cv2.absdiff(color, color_off)
diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
_, diff_mask = cv2.threshold(diff_gray, 30, 255, cv2.THRESH_BINARY)
cv2.imwrite("temp/debug_rs_diff.jpg", diff)
cv2.imwrite("temp/debug_rs_diff_mask.jpg", diff_mask)
contours, _ = cv2.findContours(diff_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
areas = sorted([cv2.contourArea(c) for c in contours], reverse=True)[:5]
print(f"\n  LED on-off diff: {len(contours)} contours, top areas: {areas}")
if contours:
    largest = max(contours, key=cv2.contourArea)
    M = cv2.moments(largest)
    if M["m00"] > 0:
        cx = int(M["m10"]/M["m00"])
        cy = int(M["m01"]/M["m00"])
        print(f"  LED detected via differencing at pixel ({cx}, {cy})!")
        # Check depth there
        depth_m = depth[cy, cx] * 0.001
        print(f"  Depth at LED: {depth_m*1000:.0f}mm")

pipeline.stop()
mc.send_angles([0, 0, 0, 0, 0, 0], 10)

print("\nDebug complete! Check temp/debug_*.jpg files")
