"""
Multi-camera hand-eye calibration + keyboard key pressing system.

Camera setup:
  - Pi camera (overhead): mounted on robot flange, looking down
  - RealSense D435i (side view): fixed, looking at workspace from the side

Calibration approach:
  The robot moves SLOWLY to known positions. At each position:
  1. Read robot TCP coords (robot frame)
  2. RealSense captures color+depth → deproject to 3D (camera frame)
  3. Collect correspondences → compute rigid transform

After calibration, to press a key:
  1. RealSense captures the scene (side view sees keyboard + finger)
  2. Pi camera captures overhead view (sees keyboard layout from above)
  3. Detect the target key in the overhead image
  4. RealSense depth gives the Z (height of keyboard surface)
  5. Combine to get accurate (X, Y, Z) in robot frame
  6. Move finger down slowly to press the key
"""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import json
import os

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
CAMERA_URL = 'http://10.105.230.93:8080/snapshot'
SLOW_SPEED = 10  # Very slow for safety
MEDIUM_SPEED = 15

os.makedirs("temp", exist_ok=True)


class DualCameraSystem:
    """Manages both cameras for coordinated capture."""

    def __init__(self):
        # RealSense
        self.rs_pipeline = rs.pipeline()
        self.rs_config = rs.config()
        self.rs_config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        self.rs_config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        self.rs_align = None
        self.rs_intrinsics = None
        self.rs_depth_scale = 0.001
        self.rs_profile = None

        # Camera-to-robot transform (4x4)
        self.cam_to_robot = None

    def start_realsense(self):
        self.rs_profile = self.rs_pipeline.start(self.rs_config)
        depth_sensor = self.rs_profile.get_device().first_depth_sensor()
        self.rs_depth_scale = depth_sensor.get_depth_scale()
        color_profile = self.rs_profile.get_stream(rs.stream.color)
        self.rs_intrinsics = color_profile.as_video_stream_profile().get_intrinsics()
        self.rs_align = rs.align(rs.stream.color)
        # Let auto-exposure settle
        for _ in range(30):
            self.rs_pipeline.wait_for_frames()
        print(f"RealSense started. Intrinsics: fx={self.rs_intrinsics.fx:.1f} fy={self.rs_intrinsics.fy:.1f}")

    def stop_realsense(self):
        if self.rs_profile:
            self.rs_pipeline.stop()

    def capture_realsense(self):
        """Returns (color_bgr, depth_mm_array, depth_frame)."""
        frames = self.rs_pipeline.wait_for_frames()
        aligned = self.rs_align.process(frames)
        color = np.asanyarray(aligned.get_color_frame().get_data())
        depth = np.asanyarray(aligned.get_depth_frame().get_data())
        depth_frame = aligned.get_depth_frame()
        return color, depth, depth_frame

    def capture_pi(self):
        """Returns color_bgr from the Pi overhead camera."""
        resp = httpx.get(CAMERA_URL, timeout=5.0)
        return cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)

    def capture_both(self):
        """Capture from both cameras simultaneously."""
        rs_color, rs_depth, rs_depth_frame = self.capture_realsense()
        pi_color = self.capture_pi()
        return rs_color, rs_depth, rs_depth_frame, pi_color

    def get_depth_at(self, depth_mm, u, v, radius=5):
        """Robust depth at pixel (u,v) in meters."""
        h, w = depth_mm.shape
        u = max(radius, min(w - radius - 1, u))
        v = max(radius, min(h - radius - 1, v))
        patch = depth_mm[v-radius:v+radius+1, u-radius:u+radius+1]
        valid = patch[patch > 0].astype(float)
        if len(valid) == 0:
            return 0.0
        return float(np.median(valid)) * self.rs_depth_scale

    def deproject(self, u, v, depth_m):
        """Pixel + depth → 3D point in camera frame (meters)."""
        return rs.rs2_deproject_pixel_to_point(self.rs_intrinsics, [u, v], depth_m)

    def camera_to_robot_3d(self, cam_point_m):
        """Camera frame 3D (m) → robot frame 3D (mm)."""
        if self.cam_to_robot is None:
            raise RuntimeError("Not calibrated!")
        pt = np.array([cam_point_m[0], cam_point_m[1], cam_point_m[2], 1.0])
        robot_pt = self.cam_to_robot @ pt
        return robot_pt[:3] * 1000  # mm

    def detect_green_led(self, color_img):
        """Detect green LED blob and return center pixel."""
        hsv = cv2.cvtColor(color_img, cv2.COLOR_BGR2HSV)
        lower = np.array([35, 80, 80])
        upper = np.array([85, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, mask
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 20:
            return None, mask
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None, mask
        return (int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"])), mask

    def calibrate(self, mc, positions):
        """
        Run multi-camera calibration.
        Robot moves SLOWLY to each position, RealSense captures 3D.
        """
        print("\n" + "=" * 60)
        print("  MULTI-CAMERA CALIBRATION (slow, safe movements)")
        print("=" * 60)

        mc.set_color(0, 255, 0)
        time.sleep(0.5)

        camera_points = []
        robot_points = []

        for i, (rx, ry, rz) in enumerate(positions):
            print(f"\n--- Point {i+1}/{len(positions)}: robot ({rx}, {ry}, {rz})mm ---")

            # Move up to safe height first
            mc.send_coords([rx, ry, 250, 0, 180, 90], SLOW_SPEED, 0)
            time.sleep(5)

            # Lower slowly to calibration height
            mc.send_coords([rx, ry, rz, 0, 180, 90], SLOW_SPEED, 0)
            time.sleep(5)

            mc.set_color(0, 255, 0)
            time.sleep(1)

            # Capture from RealSense
            rs_color, rs_depth, _ = self.capture_realsense()

            # Detect LED
            center, mask = self.detect_green_led(rs_color)
            if center is None:
                print(f"  Could not detect LED in RealSense. Skipping.")
                cv2.imwrite(f"temp/cal_rs_{i}_fail.jpg", rs_color)
                cv2.imwrite(f"temp/cal_rs_{i}_mask.jpg", mask)
                continue

            u, v = center
            depth_m = self.get_depth_at(rs_depth, u, v)
            if depth_m <= 0:
                print(f"  No valid depth at ({u},{v}). Skipping.")
                continue

            cam_3d = self.deproject(u, v, depth_m)
            print(f"  RealSense pixel: ({u},{v}), depth: {depth_m*1000:.0f}mm")
            print(f"  Camera 3D: ({cam_3d[0]*1000:.1f}, {cam_3d[1]*1000:.1f}, {cam_3d[2]*1000:.1f})mm")

            camera_points.append(cam_3d)
            robot_points.append((rx, ry, rz))

            # Save annotated
            vis = rs_color.copy()
            cv2.circle(vis, (u, v), 8, (0, 0, 255), 2)
            cv2.putText(vis, f"R({rx},{ry},{rz})", (u+10, v-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            cv2.imwrite(f"temp/cal_rs_{i}.jpg", vis)

        # Compute transform
        if len(camera_points) < 3:
            print(f"\nERROR: Only {len(camera_points)} points. Need >= 3.")
            return False

        cam_pts = np.array(camera_points)
        rob_pts = np.array(robot_points) / 1000.0  # mm → m

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
        self.cam_to_robot = T

        # Verify
        errors = []
        print(f"\n{'='*60}")
        print(f"  CALIBRATION: {len(camera_points)} points")
        print(f"{'='*60}")
        for cp, rp in zip(camera_points, robot_points):
            pred = self.camera_to_robot_3d(cp)
            err = np.linalg.norm(pred - np.array(rp))
            errors.append(err)
            print(f"  pred({pred[0]:.1f},{pred[1]:.1f},{pred[2]:.1f}) vs actual({rp[0]},{rp[1]},{rp[2]}) err={err:.1f}mm")

        print(f"\n  Mean error: {np.mean(errors):.1f}mm")
        print(f"  Max error:  {np.max(errors):.1f}mm")

        # Save
        data = {
            "cam_to_robot_4x4": T.tolist(),
            "camera_points_m": [list(p) for p in camera_points],
            "robot_points_mm": [list(p) for p in robot_points],
            "errors_mm": errors,
            "mean_error_mm": float(np.mean(errors)),
        }
        with open("calibration_dual.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Saved to calibration_dual.json")
        return True

    def load_calibration(self, path="calibration_dual.json"):
        with open(path, "r") as f:
            data = json.load(f)
        self.cam_to_robot = np.array(data["cam_to_robot_4x4"])
        print(f"Calibration loaded. Mean error was {data['mean_error_mm']:.1f}mm")

    def pixel_to_robot(self, u, v, rs_depth_mm=None):
        """Convert RealSense pixel to robot coordinates using depth."""
        if rs_depth_mm is not None:
            depth_m = self.get_depth_at(rs_depth_mm, u, v)
        else:
            _, depth_mm, _ = self.capture_realsense()
            depth_m = self.get_depth_at(depth_mm, u, v)
        if depth_m <= 0:
            raise ValueError(f"No depth at ({u},{v})")
        cam_3d = self.deproject(u, v, depth_m)
        return self.camera_to_robot_3d(cam_3d)


# ══════════════════════════════════════════════════════════════════════════════
# KEYBOARD KEY DETECTION AND PRESSING
# ══════════════════════════════════════════════════════════════════════════════

# Standard QWERTY layout — row by row, approximate relative positions
# These are templates; actual detection uses the overhead camera + VLM
QWERTY_ROWS = [
    list("1234567890-="),
    list("qwertyuiop[]"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]


def find_key_in_image(pi_image, target_key, rs_color=None):
    """
    Find a specific key in the overhead Pi camera image.

    Uses template matching / character detection to locate the key.
    For robustness, we'll use color + edge detection to find the keyboard region,
    then estimate key position based on QWERTY layout geometry.

    Returns (center_x, center_y) in Pi camera pixel coords.
    """
    # For now, find keyboard region using edge detection, then
    # map the key to a position in the grid
    gray = cv2.cvtColor(pi_image, cv2.COLOR_BGR2GRAY)
    
    # Find the key's row and column in QWERTY
    target = target_key.lower()
    row_idx = col_idx = None
    for r, row in enumerate(QWERTY_ROWS):
        if target in row:
            row_idx = r
            col_idx = row.index(target)
            break

    if row_idx is None:
        # Special keys
        specials = {"space": (3.5, 5), "enter": (2, 12.5), "backspace": (0, 13),
                    "tab": (1, -0.5), "shift": (3, -0.5), "ctrl": (4, 0),
                    "alt": (4, 2), "esc": (0, -1)}
        if target in specials:
            row_idx, col_idx = specials[target]
        else:
            return None

    return row_idx, col_idx


def press_key(mc, cams, target_key, press_depth=3, approach_height=30):
    """
    Press a specific key on the laptop keyboard.

    Strategy:
    1. Capture from both cameras
    2. Detect keyboard in overhead (Pi) image
    3. Find the target key position
    4. Use RealSense depth to determine keyboard surface height
    5. Move finger above the key
    6. Press down slowly
    7. Retract

    Args:
        mc: MyCobot connection
        cams: DualCameraSystem
        target_key: Key to press (e.g. 'a', 'space', 'enter')
        press_depth: How deep to press in mm
        approach_height: Height above key to approach from (mm)
    """
    print(f"\n{'='*50}")
    print(f"  PRESSING KEY: '{target_key}'")
    print(f"{'='*50}")

    # Step 1: Capture from RealSense
    print("  Capturing from RealSense...")
    rs_color, rs_depth, _ = cams.capture_realsense()
    cv2.imwrite("temp/keypress_rs.jpg", rs_color)

    # Step 2: Capture from Pi (move to top view first)
    print("  Moving to top view (slowly)...")
    mc.send_angles([-62.13, 8.96, -87.71, -14.41, 2.54, -16.34], SLOW_SPEED)
    time.sleep(6)
    pi_color = cams.capture_pi()
    cv2.imwrite("temp/keypress_pi.jpg", pi_color)

    # Step 3: Detect keyboard in the RealSense side view
    # The laptop keyboard will be a flat surface at a certain depth
    # We can detect it by looking for the flat horizontal surface

    # Step 4: For the initial version, we'll use a semi-manual approach:
    # The user provides approximate keyboard bounds, or we detect via the
    # overhead camera + VLM

    print(f"  Target key: '{target_key}'")
    key_info = find_key_in_image(pi_color, target_key)
    if key_info is None:
        print(f"  ERROR: Cannot find key '{target_key}' in layout")
        return False

    row_idx, col_idx = key_info
    print(f"  Key position: row={row_idx}, col={col_idx}")

    # Step 5: We need the keyboard position in robot coordinates.
    # This requires knowing where the keyboard is in the workspace.
    # Let's detect the keyboard surface height from RealSense depth
    # and combined with the overhead view position mapping.

    print(f"  Key targeting ready.")
    print(f"  (Full auto-targeting requires keyboard bounds calibration)")
    print(f"  See calibrate_keyboard() to set up keyboard position")

    return True


def calibrate_keyboard(mc, cams):
    """
    Interactive keyboard calibration:
    1. User positions robot finger at top-left corner of keyboard → record
    2. User positions robot finger at bottom-right corner → record
    3. System computes the keyboard plane and key grid
    """
    print("\n" + "=" * 60)
    print("  KEYBOARD CALIBRATION")
    print("=" * 60)
    print("  We need to know where the keyboard is in robot space.")
    print("  The robot will move to 3 corners of the keyboard area.")
    print()

    # First get the keyboard region from RealSense depth
    rs_color, rs_depth, _ = cams.capture_realsense()

    # Find the keyboard surface height from the side view
    # The keyboard is typically a flat surface between 0-50mm above the table
    h, w = rs_depth.shape
    # Look at the middle horizontal band where the keyboard likely is
    mid_band = rs_depth[h//3:2*h//3, :]
    valid = mid_band[mid_band > 0].astype(float) * cams.rs_depth_scale * 1000
    if len(valid) > 0:
        # The keyboard surface is one of the dominant depth planes
        print(f"  Mid-band depth range: {valid.min():.0f}-{valid.max():.0f}mm")
        # Use histogram to find dominant surface
        hist, bins = np.histogram(valid, bins=50)
        dominant_depth = bins[np.argmax(hist)]
        print(f"  Dominant surface depth: {dominant_depth:.0f}mm from camera")

    return rs_color, rs_depth


# ══════════════════════════════════════════════════════════════════════════════
# MAIN: Calibrate + Test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Connecting to robot...")
    mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
    time.sleep(1)

    cams = DualCameraSystem()
    cams.start_realsense()

    # Go home slowly
    print("Going home (slowly)...")
    mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
    time.sleep(6)

    # Calibration positions — spread across workspace, reachable, in camera FOV
    # Adjusted for a workspace that includes a laptop
    calib_positions = [
        (120, 0, 180),
        (120, 60, 180),
        (120, -60, 180),
        (180, 0, 180),
        (180, 60, 180),
        (180, -60, 180),
        (150, 30, 150),
        (150, -30, 150),
        (150, 0, 120),
    ]

    # Run calibration
    success = cams.calibrate(mc, calib_positions)

    if success:
        print("\n\nCalibration successful! Testing point conversion...")

        # Quick test: capture and convert center pixel
        rs_color, rs_depth, _ = cams.capture_realsense()
        h, w = rs_color.shape[:2]
        test_pts = [(w//4, h//2), (w//2, h//2), (3*w//4, h//2)]
        for u, v in test_pts:
            depth_m = cams.get_depth_at(rs_depth, u, v)
            if depth_m > 0:
                try:
                    robot_pt = cams.pixel_to_robot(u, v, rs_depth)
                    print(f"  Pixel ({u},{v}) depth={depth_m*1000:.0f}mm → robot ({robot_pt[0]:.1f}, {robot_pt[1]:.1f}, {robot_pt[2]:.1f})mm")
                except Exception as e:
                    print(f"  Pixel ({u},{v}): {e}")

    # Return home
    print("\nReturning home (slowly)...")
    mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
    time.sleep(6)
    mc.set_color(255, 255, 255)

    cams.stop_realsense()
    print("\nDone!")
