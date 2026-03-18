"""
RealSense + Robot extrinsic calibration.

The robot moves to several known positions. At each position, we:
  1. Read the robot's TCP coords (robot frame, mm)
  2. Detect the end-effector in the RealSense color image
  3. Deproject the pixel + depth to a 3D point (camera frame, m)
  4. Collect point pairs → compute rigid transform (camera → robot)

With the D435i providing depth, we get FULL 3D correspondences, not just 2D.
This means we calibrate X, Y, AND Z in one shot — no more fragile 2-point interp.
"""
from pymycobot import MyCobot280Socket
from src.cobot.realsense import RealSenseCamera
import cv2
import numpy as np
import time
import json
import os

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000

# Grid of robot positions to visit — need to be reachable and in camera FOV
# Format: (X, Y, Z) in mm, orientation always (0, 180, 90) = pointing down
CALIBRATION_POSITIONS = [
    (100, 50, 150),
    (100, -50, 150),
    (150, 0, 150),
    (150, -100, 150),
    (200, -50, 150),
    (200, 50, 150),
    (100, 0, 200),
    (150, -50, 200),
    (200, 0, 200),
    (150, 50, 120),
    (100, -100, 150),
    (200, -100, 150),
]


def detect_end_effector(color_img, led_color='green'):
    """Detect the robot's LED end-effector in the color image using HSV."""
    hsv = cv2.cvtColor(color_img, cv2.COLOR_BGR2HSV)
    
    if led_color == 'green':
        lower = np.array([35, 100, 100])
        upper = np.array([85, 255, 255])
    elif led_color == 'red':
        mask1 = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([160, 100, 100]), np.array([180, 255, 255]))
        mask = mask1 | mask2
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 30:
            return None
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None
        return (int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"]))
    
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 30:
        return None
    
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    
    return (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))


def main():
    os.makedirs("temp", exist_ok=True)
    
    print("=" * 60)
    print("  REALSENSE + ROBOT EXTRINSIC CALIBRATION")
    print("=" * 60)
    
    # Connect robot
    print("\nConnecting to robot...")
    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)
    
    # Start RealSense
    print("Starting RealSense...")
    rs_cam = RealSenseCamera(640, 480, 30)
    rs_cam.start()
    print(f"  Intrinsics: {rs_cam.get_intrinsics_dict()}")
    
    # Set bright green LED for detection
    mc.set_color(0, 255, 0)
    time.sleep(0.5)
    
    # Go home
    print("Going home...")
    mc.send_angles([0, 0, 0, 0, 0, 0], 30)
    time.sleep(4)
    
    # Collect point pairs
    camera_points = []  # 3D in camera frame (meters)
    robot_points = []   # 3D in robot frame (mm)
    pixel_points = []   # 2D pixel coords
    
    print(f"\nVisiting {len(CALIBRATION_POSITIONS)} calibration positions...\n")
    
    for i, (rx, ry, rz) in enumerate(CALIBRATION_POSITIONS):
        print(f"--- Point {i+1}/{len(CALIBRATION_POSITIONS)}: robot ({rx}, {ry}, {rz})mm ---")
        
        # Move to position
        mc.send_coords([rx, ry, rz, 0, 180, 90], 20, 0)
        time.sleep(4)
        
        # Ensure LED is on
        mc.set_color(0, 255, 0)
        time.sleep(0.5)
        
        # Capture from RealSense
        color, depth_mm, depth_frame = rs_cam.capture()
        
        # Detect LED in color image
        center = detect_end_effector(color, 'green')
        
        if center is None:
            print(f"  WARNING: Could not detect LED. Skipping.")
            cv2.imwrite(f"temp/rs_calib_{i}_fail.jpg", color)
            continue
        
        u, v = center
        
        # Get depth at detected pixel
        depth_m = rs_cam._robust_depth(depth_mm, u, v, radius=5)
        
        if depth_m <= 0:
            print(f"  WARNING: No valid depth at ({u},{v}). Skipping.")
            continue
        
        # Deproject to 3D camera point
        import pyrealsense2 as rs2
        cam_3d = rs2.rs2_deproject_pixel_to_point(rs_cam._intrinsics, [u, v], depth_m)
        
        print(f"  Pixel: ({u}, {v}), depth: {depth_m*1000:.0f}mm")
        print(f"  Camera 3D: ({cam_3d[0]*1000:.1f}, {cam_3d[1]*1000:.1f}, {cam_3d[2]*1000:.1f})mm")
        print(f"  Robot  3D: ({rx}, {ry}, {rz})mm")
        
        camera_points.append(cam_3d)
        robot_points.append((rx, ry, rz))
        pixel_points.append((u, v))
        
        # Save annotated image
        vis = color.copy()
        cv2.circle(vis, (u, v), 10, (0, 0, 255), 2)
        cv2.putText(vis, f"R({rx},{ry},{rz})", (u+12, v-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        cv2.imwrite(f"temp/rs_calib_{i}.jpg", vis)
    
    # Return home
    mc.send_angles([0, 0, 0, 0, 0, 0], 30)
    time.sleep(3)
    mc.set_color(255, 255, 255)
    
    # Compute calibration
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {len(camera_points)} valid point pairs")
    print(f"{'=' * 60}")
    
    if len(camera_points) < 3:
        print("  ERROR: Need at least 3 points!")
        rs_cam.stop()
        return
    
    # Compute rigid transform
    T = rs_cam.calibrate_extrinsics(camera_points, robot_points)
    
    print(f"\n  Camera→Robot transform (4x4):")
    for row in T:
        print(f"    [{row[0]:8.4f} {row[1]:8.4f} {row[2]:8.4f} {row[3]:8.4f}]")
    
    # Verify: transform each camera point and compare to robot point
    print(f"\n  Verification:")
    errors = []
    for cp, rp, pp in zip(camera_points, robot_points, pixel_points):
        cam_h = np.array([cp[0], cp[1], cp[2], 1.0])
        pred = T @ cam_h
        pred_mm = pred[:3] * 1000
        actual = np.array(rp)
        err = np.linalg.norm(pred_mm - actual)
        errors.append(err)
        print(f"    pixel{pp} -> pred({pred_mm[0]:.1f},{pred_mm[1]:.1f},{pred_mm[2]:.1f}) "
              f"vs actual({rp[0]},{rp[1]},{rp[2]}) err={err:.1f}mm")
    
    print(f"\n  Mean error: {np.mean(errors):.1f}mm")
    print(f"  Max error:  {np.max(errors):.1f}mm")
    
    # Save
    rs_cam.save_calibration("calibration_realsense.json")
    
    # Also save raw data
    raw_data = {
        "camera_points_m": [list(p) for p in camera_points],
        "robot_points_mm": [list(p) for p in robot_points],
        "pixel_points": pixel_points,
        "errors_mm": errors,
        "mean_error_mm": float(np.mean(errors)),
        "transform_4x4": T.tolist(),
    }
    with open("calibration_realsense_data.json", "w") as f:
        json.dump(raw_data, f, indent=2)
    print(f"\n  Full data saved to calibration_realsense_data.json")
    
    rs_cam.stop()
    print("\nCalibration complete!")


if __name__ == "__main__":
    main()
