"""
Calibration using DEPTH-BASED end-effector detection.

Instead of detecting the LED (not visible from side), we detect the
end-effector TIP as the closest point in a region of interest.
The finger tip is the closest object to the camera when the arm is
extended into the workspace.

Strategy:
1. Capture depth frame with arm OUT OF THE WAY (background)
2. Move arm to calibration position
3. Capture depth frame → subtract background
4. The new closest point is the finger tip
5. Deproject that pixel to 3D → that's the camera-frame position
"""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs
import cv2
import numpy as np
import time
import json
import os

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
SLOW_SPEED = 10
os.makedirs("temp", exist_ok=True)


def start_realsense():
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    profile = pipeline.start(config)
    depth_sensor = profile.get_device().first_depth_sensor()
    depth_scale = depth_sensor.get_depth_scale()
    color_stream = profile.get_stream(rs.stream.color)
    intrinsics = color_stream.as_video_stream_profile().get_intrinsics()
    aligner = rs.align(rs.stream.color)
    for _ in range(30):
        pipeline.wait_for_frames()
    return pipeline, aligner, intrinsics, depth_scale


def capture_aligned(pipeline, aligner):
    frames = pipeline.wait_for_frames()
    aligned = aligner.process(frames)
    color = np.asanyarray(aligned.get_color_frame().get_data())
    depth = np.asanyarray(aligned.get_depth_frame().get_data())
    return color, depth


def find_fingertip_by_depth_diff(bg_depth, fg_depth, min_area=50):
    """
    Find the fingertip by comparing background (arm away) vs foreground (arm in position).
    The fingertip is the NEW closest point.
    """
    # Both are uint16 depth in mm (raw units)
    # Where the arm is: depth got CLOSER (smaller value) or appeared where there was nothing
    bg = bg_depth.astype(np.float32)
    fg = fg_depth.astype(np.float32)

    # Mask where foreground is significantly closer than background
    # or where foreground has depth but background didn't
    diff_mask = np.zeros(fg.shape, dtype=np.uint8)

    # Case 1: both valid, foreground is closer by > 30mm
    both_valid = (bg > 0) & (fg > 0)
    closer = both_valid & ((bg - fg) > 30)
    diff_mask[closer] = 255

    # Case 2: only foreground has depth (arm appeared in front of empty space)
    new_object = (bg == 0) & (fg > 0)
    diff_mask[new_object] = 255

    # Clean up
    kernel = np.ones((7, 7), np.uint8)
    diff_mask = cv2.morphologyEx(diff_mask, cv2.MORPH_OPEN, kernel)
    diff_mask = cv2.morphologyEx(diff_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(diff_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, diff_mask

    # Among the detected regions, find the one with the closest (smallest) depth
    best_center = None
    best_depth = 1e9

    for cnt in contours:
        if cv2.contourArea(cnt) < min_area:
            continue
        # Get the minimum depth pixel within this contour
        mask_cnt = np.zeros(fg.shape, dtype=np.uint8)
        cv2.drawContours(mask_cnt, [cnt], -1, 255, -1)
        region_depth = fg.copy()
        region_depth[mask_cnt == 0] = 0
        valid_depth = region_depth[region_depth > 0]
        if len(valid_depth) == 0:
            continue
        # The fingertip is the closest part
        min_depth = np.min(valid_depth)
        if min_depth < best_depth:
            best_depth = min_depth
            # Find the pixel with minimum depth in this region
            ys, xs = np.where((region_depth > 0) & (region_depth <= min_depth + 5))
            if len(xs) > 0:
                best_center = (int(np.mean(xs)), int(np.mean(ys)))

    return best_center, diff_mask


def robust_depth(depth_mm, u, v, scale, radius=5):
    h, w = depth_mm.shape
    u = max(radius, min(w - radius - 1, u))
    v = max(radius, min(h - radius - 1, v))
    patch = depth_mm[v-radius:v+radius+1, u-radius:u+radius+1]
    valid = patch[patch > 0].astype(float)
    if len(valid) == 0:
        return 0.0
    return float(np.median(valid)) * scale


def main():
    print("=" * 60)
    print("  DEPTH-BASED MULTI-CAMERA CALIBRATION")
    print("  (detects finger tip via depth differencing)")
    print("=" * 60)

    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)

    pipeline, aligner, intrinsics, depth_scale = start_realsense()
    print(f"RealSense ready. depth_scale={depth_scale}")

    # Step 1: Move arm out of the way and capture BACKGROUND
    print("\nStep 1: Capturing background (arm at home)...")
    mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
    time.sleep(6)
    bg_color, bg_depth = capture_aligned(pipeline, aligner)
    cv2.imwrite("temp/cal_bg_color.jpg", bg_color)
    print(f"  Background captured.")

    # Calibration positions
    positions = [
        (120, 50, 180),
        (120, -50, 180),
        (150, 0, 180),
        (150, 50, 150),
        (150, -50, 150),
        (180, 0, 180),
        (180, 30, 150),
        (180, -30, 150),
        (120, 0, 140),
    ]

    camera_points = []
    robot_points = []

    for i, (rx, ry, rz) in enumerate(positions):
        print(f"\n--- Point {i+1}/{len(positions)}: robot ({rx}, {ry}, {rz})mm ---")

        # Move to safe height first
        mc.send_coords([rx, ry, 250, 0, 180, 90], SLOW_SPEED, 0)
        time.sleep(5)

        # Lower slowly
        mc.send_coords([rx, ry, rz, 0, 180, 90], SLOW_SPEED, 0)
        time.sleep(5)

        # Capture with arm in position
        fg_color, fg_depth = capture_aligned(pipeline, aligner)

        # Detect fingertip via depth differencing
        tip, diff_mask = find_fingertip_by_depth_diff(bg_depth, fg_depth)

        cv2.imwrite(f"temp/cal_fg_{i}.jpg", fg_color)
        cv2.imwrite(f"temp/cal_diff_{i}.jpg", diff_mask)

        if tip is None:
            print(f"  Could not detect fingertip. Skipping.")
            continue

        u, v = tip
        depth_m = robust_depth(fg_depth, u, v, depth_scale)
        if depth_m <= 0:
            print(f"  No valid depth at ({u},{v}). Skipping.")
            continue

        cam_3d = rs.rs2_deproject_pixel_to_point(intrinsics, [u, v], depth_m)

        print(f"  Fingertip pixel: ({u},{v}), depth: {depth_m*1000:.0f}mm")
        print(f"  Camera 3D: ({cam_3d[0]*1000:.1f}, {cam_3d[1]*1000:.1f}, {cam_3d[2]*1000:.1f})mm")

        camera_points.append(cam_3d)
        robot_points.append((rx, ry, rz))

        # Save annotated
        vis = fg_color.copy()
        cv2.circle(vis, (u, v), 10, (0, 0, 255), 2)
        cv2.putText(vis, f"TIP ({u},{v})", (u+12, v-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        cv2.imwrite(f"temp/cal_detect_{i}.jpg", vis)

    # Return home
    mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
    time.sleep(5)

    # Compute rigid transform
    print(f"\n{'='*60}")
    print(f"  RESULTS: {len(camera_points)} valid points")
    print(f"{'='*60}")

    if len(camera_points) < 3:
        print("  Not enough points! Check temp/cal_diff_*.jpg to debug.")
        pipeline.stop()
        return

    cam_pts = np.array(camera_points)
    rob_pts = np.array(robot_points) / 1000.0

    cam_c = cam_pts.mean(axis=0)
    rob_c = rob_pts.mean(axis=0)
    H = (cam_pts - cam_c).T @ (rob_pts - rob_c)
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = rob_c - R @ cam_c

    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t

    # Verify
    errors = []
    for cp, rp in zip(camera_points, robot_points):
        pt = np.array([cp[0], cp[1], cp[2], 1.0])
        pred = T @ pt
        pred_mm = pred[:3] * 1000
        actual = np.array(rp)
        err = np.linalg.norm(pred_mm - actual)
        errors.append(err)
        print(f"  pred({pred_mm[0]:.1f},{pred_mm[1]:.1f},{pred_mm[2]:.1f}) vs actual({rp[0]},{rp[1]},{rp[2]}) err={err:.1f}mm")

    print(f"\n  Mean error: {np.mean(errors):.1f}mm")
    print(f"  Max error:  {np.max(errors):.1f}mm")

    # Save
    data = {
        "cam_to_robot_4x4": T.tolist(),
        "camera_points_m": [list(p) for p in camera_points],
        "robot_points_mm": [list(p) for p in robot_points],
        "errors_mm": errors,
        "mean_error_mm": float(np.mean(errors)),
        "intrinsics": {
            "fx": intrinsics.fx, "fy": intrinsics.fy,
            "ppx": intrinsics.ppx, "ppy": intrinsics.ppy,
            "width": intrinsics.width, "height": intrinsics.height,
        },
    }
    with open("calibration_dual.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Saved to calibration_dual.json")

    pipeline.stop()
    print("\nCalibration complete!")


if __name__ == "__main__":
    main()
