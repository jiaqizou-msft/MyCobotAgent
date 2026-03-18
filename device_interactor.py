"""
DeviceInteractor: Auto-detect keyboard + touchpad from overhead RealSense,
calibrate RealSense-to-robot transform, and provide precise key pressing
and touchpad interaction.

Camera setup:
  - RealSense D435i (laptop USB, overhead): RGBD for detection + depth
  - Pi webcam (network): side view for verification
  - Overview cam (laptop USB): monitoring

Calibration flow:
  1. Robot moves to N positions with green LED
  2. RealSense overhead detects LED in RGB → pixel (u,v)
  3. RealSense depth at (u,v) → full 3D point in camera frame
  4. Robot TCP coords → robot 3D
  5. SVD rigid transform: camera 3D → robot 3D

Detection flow:
  1. Capture RGBD from overhead RealSense
  2. Detect keyboard region (edge density + contour)
  3. Detect key grid (adaptive threshold on keyboard region)
  4. Measure key pitch, fit to QWERTY template
  5. Each key: pixel (u,v) + depth → camera 3D → robot 3D
  6. Detect touchpad below keyboard (smooth region)
"""
import pyrealsense2 as rs
import cv2
import numpy as np
import httpx
import time
import json
import os
from pymycobot import MyCobot280Socket

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
PI_SNAPSHOT = 'http://10.105.230.93:8080/snapshot'

os.makedirs("temp", exist_ok=True)


class DeviceInteractor:

    def __init__(self):
        self.mc = None

        # RealSense
        self.rs_pipeline = None
        self.rs_align = None
        self.rs_intrinsics = None
        self.rs_depth_scale = 0.001

        # Camera-to-robot rigid transform (4x4)
        self.cam_to_robot = None

        # Detected device layout
        self.keyboard_keys = {}   # key_name -> {"pixel": (u,v), "robot": (x,y,z)}
        self.touchpad = None      # {"pixel_bounds": (x,y,w,h), "robot_bounds": {...}, "robot_z": z}
        self.keyboard_bounds_px = None  # (x,y,w,h) in pixel coords

        # Motion params
        self.safe_z = 200
        self.hover_offset = 20    # mm above surface for hover
        self.press_depth = 3      # mm below surface to register press
        self.travel_speed = 15
        self.approach_speed = 10
        self.press_speed = 6

    # ── Connection ───────────────────────────────────────────────────────

    def connect_robot(self):
        print("Connecting to robot...")
        self.mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
        time.sleep(1)

    def start_realsense(self):
        print("Starting RealSense...")
        self.rs_pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        profile = self.rs_pipeline.start(config)
        self.rs_depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
        cs = profile.get_stream(rs.stream.color)
        self.rs_intrinsics = cs.as_video_stream_profile().get_intrinsics()
        self.rs_align = rs.align(rs.stream.color)
        for _ in range(30):
            self.rs_pipeline.wait_for_frames()
        print(f"  RealSense ready. Scale={self.rs_depth_scale}, "
              f"fx={self.rs_intrinsics.fx:.1f}, fy={self.rs_intrinsics.fy:.1f}")

    def stop(self):
        if self.rs_pipeline:
            self.rs_pipeline.stop()

    # ── Capture ──────────────────────────────────────────────────────────

    def capture_rgbd(self):
        """Capture aligned color + depth from overhead RealSense."""
        frames = self.rs_pipeline.wait_for_frames()
        aligned = self.rs_align.process(frames)
        color = np.asanyarray(aligned.get_color_frame().get_data())
        depth = np.asanyarray(aligned.get_depth_frame().get_data())
        return color, depth

    def capture_side(self):
        """Capture from Pi side-view webcam."""
        resp = httpx.get(PI_SNAPSHOT, timeout=5)
        return cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)

    def capture_overview(self):
        """Capture from overview camera (laptop idx 3)."""
        cap = cv2.VideoCapture(3, cv2.CAP_DSHOW)
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None

    def robust_depth_m(self, depth_mm, u, v, radius=5):
        """Get robust depth in meters at pixel (u,v)."""
        h, w = depth_mm.shape
        u = max(radius, min(w - radius - 1, int(u)))
        v = max(radius, min(h - radius - 1, int(v)))
        patch = depth_mm[v-radius:v+radius+1, u-radius:u+radius+1]
        valid = patch[patch > 0].astype(float)
        if len(valid) == 0:
            return 0.0
        return float(np.median(valid)) * self.rs_depth_scale

    def deproject(self, u, v, depth_m):
        """Pixel + depth -> 3D point in camera frame (meters)."""
        return rs.rs2_deproject_pixel_to_point(self.rs_intrinsics, [float(u), float(v)], depth_m)

    def cam3d_to_robot(self, cam_point):
        """Camera 3D (meters) -> robot 3D (mm)."""
        pt = np.array([cam_point[0], cam_point[1], cam_point[2], 1.0])
        robot = self.cam_to_robot @ pt
        return robot[:3] * 1000  # mm

    def pixel_to_robot(self, u, v, depth_mm_map=None):
        """Full pipeline: pixel -> depth -> camera 3D -> robot 3D (mm)."""
        if depth_mm_map is not None:
            depth_m = self.robust_depth_m(depth_mm_map, u, v)
        else:
            _, d = self.capture_rgbd()
            depth_m = self.robust_depth_m(d, u, v)
        if depth_m <= 0:
            raise ValueError(f"No valid depth at pixel ({u},{v})")
        cam3d = self.deproject(u, v, depth_m)
        return self.cam3d_to_robot(cam3d)

    # ── Calibration ──────────────────────────────────────────────────────

    def calibrate(self, positions=None):
        """
        Calibrate RealSense overhead -> robot frame using green LED detection.
        Robot moves to known positions, RealSense captures LED pixel + depth,
        compute rigid transform via SVD.
        """
        mc = self.mc
        print("\n" + "=" * 60)
        print("  REALSENSE-TO-ROBOT CALIBRATION")
        print("=" * 60)

        if positions is None:
            positions = [
                (120, 50, 170),
                (120, -50, 170),
                (170, 0, 170),
                (170, 60, 150),
                (170, -60, 150),
                (220, 0, 170),
                (220, 50, 150),
                (150, 30, 130),
                (150, -30, 130),
            ]

        mc.set_color(0, 255, 0)
        time.sleep(0.5)
        mc.send_angles([0, 0, 0, 0, 0, 0], 15)
        time.sleep(4)

        cam_points = []
        rob_points = []

        for i, (rx, ry, rz) in enumerate(positions):
            print(f"\n  Point {i+1}/{len(positions)}: robot ({rx}, {ry}, {rz})")
            mc.send_coords([rx, ry, self.safe_z, 0, 180, 90], self.travel_speed, 0)
            time.sleep(3)
            mc.send_coords([rx, ry, rz, 0, 180, 90], self.approach_speed, 0)
            time.sleep(4)

            # Use LED on/off differencing for robust detection from overhead
            mc.set_color(0, 0, 0)  # LED OFF
            time.sleep(1)
            color_off, depth = self.capture_rgbd()

            mc.set_color(0, 255, 0)  # LED ON (green)
            time.sleep(1)
            color_on, _ = self.capture_rgbd()

            # Difference image reveals the LED location
            diff = cv2.absdiff(color_on, color_off)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, diff_mask = cv2.threshold(diff_gray, 20, 255, cv2.THRESH_BINARY)
            kernel = np.ones((5, 5), np.uint8)
            diff_mask = cv2.morphologyEx(diff_mask, cv2.MORPH_OPEN, kernel)
            diff_mask = cv2.morphologyEx(diff_mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(diff_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            center = None
            if contours:
                largest = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest) >= 5:
                    M = cv2.moments(largest)
                    if M["m00"] > 0:
                        center = (int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"]))

            if center is None:
                # Fallback: try pure green detection on the ON image
                center = self._detect_green_led(color_on)

            if center is None:
                print(f"    LED not detected. Skipping.")
                cv2.imwrite(f"temp/cal_{i}_fail.jpg", color_on)
                cv2.imwrite(f"temp/cal_{i}_diff.jpg", diff_mask)
                continue

            u, v = center
            depth_m = self.robust_depth_m(depth, u, v)
            if depth_m <= 0:
                print(f"    No depth at ({u},{v}). Skipping.")
                continue

            cam3d = self.deproject(u, v, depth_m)
            print(f"    LED pixel: ({u},{v}), depth: {depth_m*1000:.0f}mm")
            print(f"    Camera 3D: ({cam3d[0]*1000:.1f}, {cam3d[1]*1000:.1f}, {cam3d[2]*1000:.1f})")

            cam_points.append(cam3d)
            rob_points.append((rx, ry, rz))

            vis = color_on.copy()
            cv2.circle(vis, (u, v), 8, (0, 0, 255), 2)
            cv2.imwrite(f"temp/cal_{i}.jpg", vis)

        mc.send_angles([0, 0, 0, 0, 0, 0], 12)
        time.sleep(4)
        mc.set_color(255, 255, 255)

        if len(cam_points) < 3:
            print(f"\n  Only {len(cam_points)} points. Need >= 3.")
            return False

        # SVD rigid transform
        cam = np.array(cam_points)
        rob = np.array(rob_points) / 1000.0
        cc = cam.mean(axis=0)
        rc = rob.mean(axis=0)
        H = (cam - cc).T @ (rob - rc)
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        t = rc - R @ cc

        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = t
        self.cam_to_robot = T

        # Verify
        errors = []
        for cp, rp in zip(cam_points, rob_points):
            pred = self.cam3d_to_robot(cp)
            err = np.linalg.norm(pred - np.array(rp))
            errors.append(err)
            print(f"  pred({pred[0]:.1f},{pred[1]:.1f},{pred[2]:.1f}) "
                  f"vs actual({rp[0]},{rp[1]},{rp[2]}) err={err:.1f}mm")

        print(f"\n  Mean error: {np.mean(errors):.1f}mm")
        print(f"  Max error:  {np.max(errors):.1f}mm")

        self.save_calibration()
        return True

    def _detect_green_led(self, color_img):
        """Detect bright green LED blob, return center pixel or None."""
        hsv = cv2.cvtColor(color_img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 20:
            return None
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None
        return (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))

    def save_calibration(self, path="calibration_realsense.json"):
        data = {"cam_to_robot_4x4": self.cam_to_robot.tolist(),
                "intrinsics": {"fx": self.rs_intrinsics.fx, "fy": self.rs_intrinsics.fy,
                               "ppx": self.rs_intrinsics.ppx, "ppy": self.rs_intrinsics.ppy,
                               "depth_scale": self.rs_depth_scale}}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Calibration saved to {path}")

    def load_calibration(self, path="calibration_realsense.json"):
        with open(path, "r") as f:
            data = json.load(f)
        self.cam_to_robot = np.array(data["cam_to_robot_4x4"])
        print(f"  Calibration loaded from {path}")

    # ── Keyboard Detection ───────────────────────────────────────────────

    def detect_keyboard(self, color=None, depth=None):
        """
        Auto-detect keyboard from overhead RealSense image.
        Returns dict of key_name -> {"pixel": (u,v), "robot": (x,y,z)}
        """
        print("\n  Detecting keyboard...")
        if color is None or depth is None:
            color, depth = self.capture_rgbd()

        cv2.imwrite("temp/detect_input.jpg", color)

        # Step 1: Find keyboard region using depth
        # Keyboard is a flat surface at a specific depth — isolate it
        depth_m = depth.astype(float) * self.rs_depth_scale
        valid_depths = depth_m[depth_m > 0]
        if len(valid_depths) == 0:
            print("    No depth data!")
            return {}

        # Find the keyboard depth plane (between 300-800mm typically)
        valid_mm = valid_depths * 1000
        hist, bins = np.histogram(valid_mm[(valid_mm > 200) & (valid_mm < 900)], bins=100)
        if len(hist) == 0:
            print("    No valid depth in range.")
            return {}

        # The keyboard surface is one of the dominant flat surfaces
        peak_idx = np.argmax(hist)
        kbd_depth_mm = (bins[peak_idx] + bins[peak_idx + 1]) / 2
        print(f"    Dominant surface depth: {kbd_depth_mm:.0f}mm")

        # Mask pixels at the keyboard surface depth (+/- 15mm tolerance)
        depth_mm_map = depth_m * 1000
        surface_mask = ((depth_mm_map > kbd_depth_mm - 15) &
                        (depth_mm_map < kbd_depth_mm + 15) &
                        (depth_mm_map > 0)).astype(np.uint8) * 255

        # Clean up the mask
        kernel_big = np.ones((10, 10), np.uint8)
        surface_mask = cv2.morphologyEx(surface_mask, cv2.MORPH_CLOSE, kernel_big)
        surface_mask = cv2.morphologyEx(surface_mask, cv2.MORPH_OPEN, kernel_big)
        cv2.imwrite("temp/keyboard_depth_mask.jpg", surface_mask)

        # Find contours on the surface mask
        contours, _ = cv2.findContours(surface_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Also try edge-based detection within the depth-masked region
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        masked_gray = cv2.bitwise_and(gray, gray, mask=surface_mask)
        edges = cv2.Canny(masked_gray, 30, 100)
        kernel = np.ones((15, 15), np.uint8)
        density = cv2.dilate(edges, kernel, iterations=2)
        density = cv2.erode(density, kernel, iterations=1)

        # Find the rectangular keyboard-shaped contour from depth surface
        kbd_rect = None
        max_area = 0
        # Check the depth-isolated surface contours first
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 2000:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / h if h > 0 else 0
            # Keyboard is wider than tall (aspect > 1.5)
            if 1.2 < aspect < 8 and area > max_area:
                max_area = area
                kbd_rect = (x, y, w, h)

        # If depth-based detection found something big, use edge density to refine
        if kbd_rect is not None:
            kx, ky, kw, kh = kbd_rect
            # Check if this region has enough edge density (keys have lots of edges)
            roi_edges = edges[ky:ky+kh, kx:kx+kw]
            edge_density = np.sum(roi_edges > 0) / (kw * kh + 1)
            print(f"    Candidate from depth: ({kx},{ky}) {kw}x{kh}, edge_density={edge_density:.3f}")
            if edge_density < 0.01:
                # Very low edge density — probably the touchpad or flat surface, not keyboard
                print(f"    Low edge density, likely not keyboard. Trying edge-based fallback.")
                kbd_rect = None

        if kbd_rect is None:
            # Fallback: use edge density on the full masked region
            kernel = np.ones((15, 15), np.uint8)
            density = cv2.dilate(edges, kernel, iterations=2)
            density = cv2.erode(density, kernel, iterations=1)
            edge_contours, _ = cv2.findContours(density, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in edge_contours:
                area = cv2.contourArea(cnt)
                if area < 2000:
                    continue
                x, y, w, h = cv2.boundingRect(cnt)
                aspect = w / h if h > 0 else 0
                if 1.2 < aspect < 6 and area > max_area:
                    max_area = area
                    kbd_rect = (x, y, w, h)

        if kbd_rect is None:
            print("    Keyboard not auto-detected.")
            print("    Will use depth-based detection as fallback...")
            # Fallback: find the flat surface closest to camera (keyboard is elevated)
            kbd_rect = self._detect_keyboard_by_depth(depth, color)
            if kbd_rect is None:
                print("    Keyboard detection failed completely.")
                return {}

        kx, ky, kw, kh = kbd_rect
        self.keyboard_bounds_px = kbd_rect
        print(f"    Keyboard region: ({kx},{ky}) {kw}x{kh}")

        # Step 2: Map QWERTY keys to pixel positions within keyboard bounds
        QWERTY = [
            list("`1234567890-="),
            list("qwertyuiop[]\\"),
            list("asdfghjkl;'"),
            list("zxcvbnm,./"),
        ]

        key_positions = {}
        n_cols = 13  # typical key columns
        n_rows = len(QWERTY)

        # Measure average key surface depth for this keyboard
        kbd_depths = []
        for py in range(ky + 5, ky + kh - 5, 10):
            for px in range(kx + 5, kx + kw - 5, 10):
                d = self.robust_depth_m(depth, px, py, radius=3)
                if d > 0:
                    kbd_depths.append(d)

        if kbd_depths:
            avg_kbd_depth_m = np.median(kbd_depths)
            print(f"    Keyboard surface depth: {avg_kbd_depth_m*1000:.0f}mm from camera")
        else:
            avg_kbd_depth_m = 0.5  # default 500mm
            print(f"    Using default keyboard depth: {avg_kbd_depth_m*1000:.0f}mm")

        # Compute the keyboard surface Z in robot frame ONCE using the uniform depth
        kbd_center_u = kx + kw // 2
        kbd_center_v = ky + kh // 2
        kbd_cam3d = self.deproject(kbd_center_u, kbd_center_v, avg_kbd_depth_m)
        kbd_robot = self.cam3d_to_robot(kbd_cam3d)
        kbd_surface_z = float(kbd_robot[2])
        print(f"    Keyboard surface Z in robot frame: {kbd_surface_z:.1f}mm")

        for r, row in enumerate(QWERTY):
            for c, key in enumerate(row):
                # Pixel position of key center
                px = int(kx + (c + 0.5) / n_cols * kw)
                py = int(ky + (r + 0.5) / n_rows * kh)

                # Convert to robot coords using UNIFORM keyboard depth
                try:
                    cam3d = self.deproject(px, py, avg_kbd_depth_m)
                    robot_xyz = self.cam3d_to_robot(cam3d)
                    key_positions[key] = {
                        "pixel": (px, py),
                        "robot": (float(robot_xyz[0]), float(robot_xyz[1]), kbd_surface_z),
                        "depth_m": avg_kbd_depth_m,
                    }
                except Exception:
                    pass

        # Special keys
        specials = {
            "space": (3.5, 5.0),
            "enter": (2.0, 12.5),
            "backspace": (0.0, 13.0),
            "tab": (1.0, -0.3),
            "shift": (3.0, -0.5),
            "esc": (-0.5, -0.5),
        }
        for name, (r, c) in specials.items():
            px = int(kx + (c + 0.5) / n_cols * kw)
            py = int(ky + (r + 0.5) / n_rows * kh)
            try:
                cam3d = self.deproject(px, py, avg_kbd_depth_m)
                robot_xyz = self.cam3d_to_robot(cam3d)
                key_positions[name] = {
                    "pixel": (px, py),
                    "robot": (float(robot_xyz[0]), float(robot_xyz[1]), kbd_surface_z),
                    "depth_m": avg_kbd_depth_m,
                }
            except Exception:
                pass

        self.keyboard_keys = key_positions
        print(f"    Detected {len(key_positions)} keys")

        # Draw visualization
        self._draw_keyboard_detection(color, kbd_rect, key_positions)
        return key_positions

    def _detect_keyboard_by_depth(self, depth, color):
        """Fallback: detect keyboard by finding a flat elevated surface in depth."""
        valid = depth[depth > 0].astype(float) * self.rs_depth_scale * 1000
        if len(valid) == 0:
            return None
        # Keyboard is typically closer than the table
        hist, bins = np.histogram(valid, bins=50)
        # Find second peak (first is table, second is keyboard sitting on it)
        peaks = []
        for i in range(1, len(hist) - 1):
            if hist[i] > hist[i-1] and hist[i] > hist[i+1] and hist[i] > len(valid) * 0.02:
                peaks.append((hist[i], (bins[i] + bins[i+1]) / 2))
        if not peaks:
            return None

        # The keyboard surface is the closest major surface
        peaks.sort(key=lambda x: x[1])
        kbd_depth = peaks[0][1]  # mm from camera

        # Mask pixels at keyboard depth (within 20mm)
        depth_mm = depth.astype(float) * self.rs_depth_scale * 1000
        kbd_mask = ((depth_mm > kbd_depth - 20) & (depth_mm < kbd_depth + 20)).astype(np.uint8) * 255
        kernel = np.ones((10, 10), np.uint8)
        kbd_mask = cv2.morphologyEx(kbd_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(kbd_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        return cv2.boundingRect(largest)

    def _draw_keyboard_detection(self, color, kbd_rect, key_positions):
        """Draw detection visualization."""
        vis = color.copy()
        kx, ky, kw, kh = kbd_rect
        cv2.rectangle(vis, (kx, ky), (kx+kw, ky+kh), (0, 255, 0), 2)

        for name, data in key_positions.items():
            px, py = data["pixel"]
            cv2.circle(vis, (px, py), 3, (0, 0, 255), -1)
            if name in ('q', 'a', 'z', 'w', 's', 'x', 'd', 'f', '1', '5', 'space', 'enter'):
                cv2.putText(vis, name, (px + 4, py - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 0), 1)

        cv2.imwrite("temp/keyboard_detected.jpg", vis)
        print(f"    Visualization saved to temp/keyboard_detected.jpg")

    # ── Touchpad Detection ───────────────────────────────────────────────

    def detect_touchpad(self, color=None, depth=None):
        """
        Detect touchpad below keyboard region.
        Touchpad is typically a smooth, uniform rectangle below the keyboard.
        """
        print("\n  Detecting touchpad...")
        if color is None or depth is None:
            color, depth = self.capture_rgbd()

        if self.keyboard_bounds_px is None:
            print("    Need keyboard detection first!")
            return None

        kx, ky, kw, kh = self.keyboard_bounds_px
        h, w = color.shape[:2]

        # Search below keyboard for a smooth uniform region
        search_top = ky + kh + 5
        search_bottom = min(h - 5, search_top + kh)
        search_left = kx
        search_right = kx + kw

        if search_top >= h:
            print("    No space below keyboard for touchpad.")
            return None

        roi = color[search_top:search_bottom, search_left:search_right]
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # Touchpad: low texture variance, uniform color
        blur = cv2.GaussianBlur(gray_roi, (15, 15), 0)
        variance = cv2.Laplacian(blur, cv2.CV_64F)
        low_var_mask = (np.abs(variance) < 5).astype(np.uint8) * 255

        kernel = np.ones((15, 15), np.uint8)
        low_var_mask = cv2.morphologyEx(low_var_mask, cv2.MORPH_CLOSE, kernel)
        low_var_mask = cv2.morphologyEx(low_var_mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(low_var_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            print("    Touchpad not detected (no smooth region found).")
            return None

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 1000:
            print("    Touchpad region too small.")
            return None

        tx, ty, tw, th = cv2.boundingRect(largest)
        # Convert back to full image coords
        tp_x = search_left + tx
        tp_y = search_top + ty
        tp_bounds = (tp_x, tp_y, tw, th)

        # Get touchpad surface depth
        tp_depth = self.robust_depth_m(depth, tp_x + tw // 2, tp_y + th // 2)
        if tp_depth <= 0:
            tp_depth = self.robust_depth_m(depth,
                                           self.keyboard_bounds_px[0] + self.keyboard_bounds_px[2] // 2,
                                           self.keyboard_bounds_px[1] + self.keyboard_bounds_px[3] // 2)

        # Convert corners to robot coords
        try:
            tl_robot = self.pixel_to_robot(tp_x, tp_y, depth)
            br_robot = self.pixel_to_robot(tp_x + tw, tp_y + th, depth)
            center_robot = self.pixel_to_robot(tp_x + tw // 2, tp_y + th // 2, depth)

            self.touchpad = {
                "pixel_bounds": tp_bounds,
                "robot_tl": tl_robot.tolist(),
                "robot_br": br_robot.tolist(),
                "robot_center": center_robot.tolist(),
                "robot_z": float(center_robot[2]),
            }
            print(f"    Touchpad: pixel ({tp_x},{tp_y}) {tw}x{th}")
            print(f"    Robot center: ({center_robot[0]:.1f}, {center_robot[1]:.1f}, {center_robot[2]:.1f})")
        except Exception as e:
            print(f"    Touchpad depth/transform failed: {e}")
            self.touchpad = {"pixel_bounds": tp_bounds}

        # Visualize
        vis = color.copy()
        cv2.rectangle(vis, (tp_x, tp_y), (tp_x + tw, tp_y + th), (255, 0, 255), 2)
        cv2.putText(vis, "TOUCHPAD", (tp_x + 5, tp_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        cv2.imwrite("temp/touchpad_detected.jpg", vis)
        return self.touchpad

    # ── Key Pressing ─────────────────────────────────────────────────────

    def press_key(self, key_name):
        """Press a key using the auto-detected position."""
        mc = self.mc
        key = key_name.lower()

        if key not in self.keyboard_keys:
            print(f"  Key '{key}' not detected!")
            return False

        data = self.keyboard_keys[key]
        x, y, z = data["robot"]
        surface_z = z
        hover_z = surface_z + self.hover_offset
        press_z = surface_z - self.press_depth

        print(f"  Pressing '{key}' at ({x:.1f}, {y:.1f}, {z:.1f})")

        # Travel above
        mc.send_coords([x, y, self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)

        # Approach
        mc.send_coords([x, y, hover_z, 0, 180, 90], self.approach_speed, 0)
        time.sleep(2)

        # Press
        mc.send_coords([x, y, press_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1)

        # Release to hover
        mc.send_coords([x, y, hover_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1)

        return True

    def type_text(self, text):
        """Type text smoothly — slide between keys at hover height."""
        mc = self.mc
        keys = []
        for ch in text:
            k = 'space' if ch == ' ' else ch.lower()
            if k in self.keyboard_keys:
                keys.append((k, self.keyboard_keys[k]))
            else:
                print(f"  Skipping unknown key '{k}'")

        if not keys:
            return

        # Go to first key hover height
        first = keys[0][1]["robot"]
        surface_z = first[2]
        hover_z = surface_z + self.hover_offset
        press_z = surface_z - self.press_depth

        mc.send_coords([first[0], first[1], self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)
        mc.send_coords([first[0], first[1], hover_z, 0, 180, 90], self.approach_speed, 0)
        time.sleep(2)

        for i, (key, data) in enumerate(keys):
            x, y, z = data["robot"]
            press_z = z - self.press_depth
            hover_z = z + self.hover_offset

            # Slide to key
            mc.send_coords([x, y, hover_z, 0, 180, 90], 12, 0)
            time.sleep(1.2)

            # Press
            mc.send_coords([x, y, press_z, 0, 180, 90], self.press_speed, 0)
            time.sleep(0.8)

            # Release to hover
            mc.send_coords([x, y, hover_z, 0, 180, 90], self.press_speed, 0)
            time.sleep(0.8)

            print(f"  '{key}' ({i+1}/{len(keys)})")

        # Retreat
        mc.send_coords([x, y, self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(2)

    # ── Touchpad Actions ─────────────────────────────────────────────────

    def _touchpad_xy(self, x_frac, y_frac):
        """Convert touchpad fractional coords (0-1) to robot XY."""
        if self.touchpad is None or "robot_tl" not in self.touchpad:
            raise RuntimeError("Touchpad not calibrated!")
        tl = np.array(self.touchpad["robot_tl"])
        br = np.array(self.touchpad["robot_br"])
        x = tl[0] + x_frac * (br[0] - tl[0])
        y = tl[1] + y_frac * (br[1] - tl[1])
        z = self.touchpad["robot_z"]
        return x, y, z

    def touchpad_tap(self, x_frac=0.5, y_frac=0.5):
        """Tap the touchpad at fractional position (0,0)=top-left, (1,1)=bottom-right."""
        mc = self.mc
        x, y, z = self._touchpad_xy(x_frac, y_frac)
        hover_z = z + self.hover_offset
        press_z = z - self.press_depth

        print(f"  Touchpad tap at ({x_frac:.2f}, {y_frac:.2f}) -> robot ({x:.1f}, {y:.1f}, {z:.1f})")

        mc.send_coords([x, y, self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)
        mc.send_coords([x, y, hover_z, 0, 180, 90], self.approach_speed, 0)
        time.sleep(2)
        mc.send_coords([x, y, press_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(0.5)
        mc.send_coords([x, y, hover_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1)
        return True

    def touchpad_drag(self, x1=0.5, y1=0.2, x2=0.5, y2=0.8):
        """Drag on touchpad from (x1,y1) to (x2,y2) in fractional coords."""
        mc = self.mc
        sx, sy, sz = self._touchpad_xy(x1, y1)
        ex, ey, ez = self._touchpad_xy(x2, y2)
        press_z = sz - self.press_depth
        hover_z = sz + self.hover_offset

        print(f"  Touchpad drag ({x1:.1f},{y1:.1f})->({x2:.1f},{y2:.1f})")

        # Move above start
        mc.send_coords([sx, sy, self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)
        mc.send_coords([sx, sy, hover_z, 0, 180, 90], self.approach_speed, 0)
        time.sleep(2)

        # Press down at start
        mc.send_coords([sx, sy, press_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1)

        # Drag to end (stay pressed)
        mc.send_coords([ex, ey, press_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(2)

        # Release
        mc.send_coords([ex, ey, hover_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1)
        return True

    def touchpad_double_tap(self, x_frac=0.5, y_frac=0.5):
        """Double-tap the touchpad."""
        self.touchpad_tap(x_frac, y_frac)
        time.sleep(0.2)
        self.touchpad_tap(x_frac, y_frac)

    # ── Full Detection Pipeline ──────────────────────────────────────────

    def detect_devices(self):
        """Auto-detect keyboard + touchpad from overhead RGBD."""
        print("\n" + "=" * 60)
        print("  DEVICE DETECTION")
        print("=" * 60)

        color, depth = self.capture_rgbd()
        cv2.imwrite("temp/detect_color.jpg", color)
        depth_vis = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.03), cv2.COLORMAP_JET)
        cv2.imwrite("temp/detect_depth.jpg", depth_vis)

        self.detect_keyboard(color, depth)
        self.detect_touchpad(color, depth)

        # Save layout
        layout = {
            "keyboard": {k: v for k, v in self.keyboard_keys.items()},
            "touchpad": self.touchpad,
            "keyboard_bounds_px": self.keyboard_bounds_px,
        }
        with open("device_layout.json", "w") as f:
            json.dump(layout, f, indent=2, default=str)
        print(f"\n  Layout saved to device_layout.json")

        # Check reachability
        reachable = sum(1 for v in self.keyboard_keys.values()
                       if 80 <= v["robot"][0] <= 270 and abs(v["robot"][1]) <= 200)
        print(f"  Reachable keys: {reachable}/{len(self.keyboard_keys)}")

    # ── Full Setup ───────────────────────────────────────────────────────

    def setup(self, recalibrate=False):
        """Full setup: connect, calibrate (or load), detect devices."""
        self.connect_robot()
        self.start_realsense()

        if recalibrate or not os.path.exists("calibration_realsense.json"):
            self.calibrate()
        else:
            self.load_calibration()

        self.detect_devices()

        self.mc.send_angles([0, 0, 0, 0, 0, 0], 12)
        time.sleep(3)
        print("\n  Setup complete!")

    def save_all(self):
        """Save calibration + device layout."""
        if self.cam_to_robot is not None:
            self.save_calibration()
        layout = {
            "keyboard": self.keyboard_keys,
            "touchpad": self.touchpad,
            "keyboard_bounds_px": self.keyboard_bounds_px,
        }
        with open("device_layout.json", "w") as f:
            json.dump(layout, f, indent=2, default=str)


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    di = DeviceInteractor()

    recal = "--recalibrate" in sys.argv
    di.setup(recalibrate=recal)

    if "--type" in sys.argv:
        idx = sys.argv.index("--type")
        text = " ".join(sys.argv[idx+1:])
        di.type_text(text)
    elif "--key" in sys.argv:
        idx = sys.argv.index("--key")
        di.press_key(sys.argv[idx+1])
    elif "--tap" in sys.argv:
        di.touchpad_tap(0.5, 0.5)
    elif "--drag" in sys.argv:
        di.touchpad_drag(0.5, 0.2, 0.5, 0.8)
    else:
        print("\nInteractive mode. Commands: key <k>, type <text>, tap, drag, detect, quit")
        while True:
            cmd = input("> ").strip()
            if not cmd or cmd == "quit":
                break
            parts = cmd.split(maxsplit=1)
            if parts[0] == "key" and len(parts) > 1:
                di.press_key(parts[1])
            elif parts[0] == "type" and len(parts) > 1:
                di.type_text(parts[1])
            elif parts[0] == "tap":
                di.touchpad_tap(0.5, 0.5)
            elif parts[0] == "drag":
                di.touchpad_drag(0.5, 0.2, 0.5, 0.8)
            elif parts[0] == "detect":
                di.detect_devices()
            else:
                print("  Unknown command.")

    di.mc.send_angles([0, 0, 0, 0, 0, 0], 12)
    time.sleep(3)
    di.mc.set_color(255, 255, 255)
    di.stop()
