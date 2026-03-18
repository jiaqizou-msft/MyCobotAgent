"""Test the RealSense D435i — capture color + depth frames."""
import pyrealsense2 as rs
import numpy as np
import cv2
import os

os.makedirs("temp", exist_ok=True)

# Configure streams
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

# Start streaming
print("Starting RealSense pipeline...")
profile = pipeline.start(config)

# Get depth sensor's depth scale
depth_sensor = profile.get_device().first_depth_sensor()
depth_scale = depth_sensor.get_depth_scale()
print(f"Depth scale: {depth_scale} (1 unit = {depth_scale*1000:.1f}mm)")

# Get intrinsics
color_profile = profile.get_stream(rs.stream.color)
intrinsics = color_profile.as_video_stream_profile().get_intrinsics()
print(f"Color intrinsics: {intrinsics.width}x{intrinsics.height}")
print(f"  fx={intrinsics.fx:.1f}, fy={intrinsics.fy:.1f}")
print(f"  ppx={intrinsics.ppx:.1f}, ppy={intrinsics.ppy:.1f}")

# Align depth to color
align = rs.align(rs.stream.color)

# Let auto-exposure settle
for _ in range(30):
    pipeline.wait_for_frames()

# Capture aligned frames
frames = pipeline.wait_for_frames()
aligned = align.process(frames)
color_frame = aligned.get_color_frame()
depth_frame = aligned.get_depth_frame()

color_image = np.asanyarray(color_frame.get_data())
depth_image = np.asanyarray(depth_frame.get_data())

# Save color image
cv2.imwrite("temp/rs_color.jpg", color_image)
print(f"\nColor image saved: {color_image.shape}")

# Save depth as colormap for visualization
depth_colormap = cv2.applyColorMap(
    cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET
)
cv2.imwrite("temp/rs_depth_colormap.jpg", depth_colormap)
print(f"Depth colormap saved: {depth_image.shape}")

# Save raw depth as numpy
np.save("temp/rs_depth_raw.npy", depth_image)
print(f"Raw depth saved (uint16, mm values after scaling)")

# Print some depth stats
valid = depth_image[depth_image > 0]
if len(valid) > 0:
    print(f"\nDepth stats (raw units):")
    print(f"  Min: {valid.min()} ({valid.min() * depth_scale * 1000:.0f}mm)")
    print(f"  Max: {valid.max()} ({valid.max() * depth_scale * 1000:.0f}mm)")
    print(f"  Mean: {valid.mean():.0f} ({valid.mean() * depth_scale * 1000:.0f}mm)")

# Sample center pixel depth
cx, cy = 320, 240
center_depth = depth_frame.get_distance(cx, cy)
print(f"\nCenter pixel ({cx},{cy}) depth: {center_depth:.3f}m = {center_depth*1000:.0f}mm")

# Deproject center pixel to 3D point (camera frame)
point_3d = rs.rs2_deproject_pixel_to_point(intrinsics, [cx, cy], center_depth)
print(f"Center 3D point (camera frame): x={point_3d[0]*1000:.1f}mm, y={point_3d[1]*1000:.1f}mm, z={point_3d[2]*1000:.1f}mm")

pipeline.stop()
print("\nRealSense test complete!")
