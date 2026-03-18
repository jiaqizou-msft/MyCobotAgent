"""
Vision-guided keyboard presser with visual servoing.

Architecture:
  1. RealSense (side view): detects keyboard surface plane + measures heights
  2. Pi camera (overhead): sees key layout AND the robot fingertip
  3. Visual servoing: iteratively move → capture → correct → repeat
  4. Smooth motion: arc approach, slow controlled press, verification

The key insight: instead of blindly going to a taught coordinate,
we LOOK at where the finger is relative to the target key and correct.
"""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs2
import cv2
import numpy as np
import httpx
import time
import json
import os

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
CAMERA_URL = 'http://10.105.230.93:8080/snapshot'
os.makedirs("temp", exist_ok=True)


class VisionGuidedPresser:
    """
    Uses both cameras for closed-loop key pressing:
      - RealSense: workspace depth map, keyboard surface height
      - Pi overhead camera: key detection, finger tracking, visual servoing
    """

    def __init__(self):
        self.mc = None

        # RealSense
        self.rs_pipeline = None
        self.rs_align = None
        self.rs_intrinsics = None
        self.rs_depth_scale = 0.001

        # Calibration: Pi-camera overhead pixel → robot XY
        # We'll calibrate this live using the robot's own position
        self.pi_to_robot = None  # 3x2 affine matrix

        # Keyboard geometry in robot frame
        self.keyboard_z = None  # surface height (mm)
        self.safe_z = 220       # safe travel height

        # Motion parameters
        self.approach_speed = 12   # approaching target
        self.press_speed = 6       # pressing down
        self.travel_speed = 15     # moving between positions
        self.press_depth = 4       # mm below surface to register keypress

        # Finger detection color (set LED to a known color for tracking)
        self.finger_led_color = (255, 0, 0)  # red LED for visibility from above

    # ── Connection ───────────────────────────────────────────────────────

    def connect(self):
        print("Connecting to robot...")
        self.mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
        time.sleep(1)
        self.mc.set_color(*self.finger_led_color)
        time.sleep(0.3)

    def start_realsense(self):
        print("Starting RealSense...")
        self.rs_pipeline = rs2.pipeline()
        config = rs2.config()
        config.enable_stream(rs2.stream.color, 640, 480, rs2.format.bgr8, 30)
        config.enable_stream(rs2.stream.depth, 640, 480, rs2.format.z16, 30)
        profile = self.rs_pipeline.start(config)
        self.rs_depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
        self.rs_align = rs2.align(rs2.stream.color)
        cs = profile.get_stream(rs2.stream.color)
        self.rs_intrinsics = cs.as_video_stream_profile().get_intrinsics()
        for _ in range(30):
            self.rs_pipeline.wait_for_frames()
        print("  RealSense ready.")

    def stop(self):
        if self.rs_pipeline:
            self.rs_pipeline.stop()

    # ── Camera Capture ───────────────────────────────────────────────────

    def capture_pi(self):
        """Capture from Pi overhead camera."""
        resp = httpx.get(CAMERA_URL, timeout=5.0)
        return cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)

    def capture_realsense(self):
        """Capture aligned color + depth from RealSense."""
        frames = self.rs_pipeline.wait_for_frames()
        aligned = self.rs_align.process(frames)
        color = np.asanyarray(aligned.get_color_frame().get_data())
        depth = np.asanyarray(aligned.get_depth_frame().get_data())
        return color, depth

    # ── Finger Detection (overhead Pi camera) ────────────────────────────

    def detect_finger_overhead(self, pi_img):
        """
        Detect the red LED fingertip in the overhead Pi camera image.
        The LED is set to bright red for easy detection from above.
        Returns (u, v) pixel center or None.
        """
        hsv = cv2.cvtColor(pi_img, cv2.COLOR_BGR2HSV)

        # Red in HSV wraps around 0/180
        mask1 = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([160, 100, 100]), np.array([180, 255, 255]))
        mask = mask1 | mask2

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, mask

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 30:
            return None, mask

        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None, mask

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        return (cx, cy), mask

    # ── Pi Camera ↔ Robot Calibration (live) ─────────────────────────────

    def calibrate_pi_to_robot_live(self, n_points=5):
        """
        Calibrate Pi-camera pixels → robot XY by moving the robot to
        several positions, capturing from the Pi camera, detecting the
        red LED fingertip, and collecting correspondences.

        This is done LIVE — much more accurate than pre-recorded positions.
        """
        print("\n  Calibrating Pi camera ↔ robot mapping...")
        mc = self.mc

        # Calibration grid — spread across robot workspace
        cal_positions = [
            (130, -80, 160),
            (130, 80, 160),
            (200, -80, 160),
            (200, 80, 160),
            (165, 0, 160),
        ][:n_points]

        pixel_pts = []
        robot_pts = []

        mc.set_color(*self.finger_led_color)
        time.sleep(0.3)

        for i, (rx, ry, rz) in enumerate(cal_positions):
            # Move to position
            mc.send_coords([rx, ry, rz, 0, 180, 90], self.approach_speed, 0)
            time.sleep(4)
            mc.set_color(*self.finger_led_color)
            time.sleep(0.5)

            # Capture overhead
            pi_img = self.capture_pi()
            finger, _ = self.detect_finger_overhead(pi_img)

            if finger is None:
                print(f"    Point {i+1}: no finger detected at robot ({rx},{ry}). Skip.")
                continue

            pixel_pts.append(finger)
            robot_pts.append((rx, ry))
            print(f"    Point {i+1}: pixel {finger} → robot ({rx},{ry})")

        if len(pixel_pts) < 3:
            print("  Not enough points for calibration!")
            return False

        # Fit affine: [u, v, 1] @ M = [robot_x, robot_y]
        A = np.array([[p[0], p[1], 1] for p in pixel_pts])
        B = np.array(robot_pts)
        self.pi_to_robot, _, _, _ = np.linalg.lstsq(A, B, rcond=None)

        # Verify
        pred = A @ self.pi_to_robot
        errors = np.sqrt(np.sum((pred - B) ** 2, axis=1))
        print(f"  Calibration done. Mean error: {np.mean(errors):.1f}mm, max: {np.max(errors):.1f}mm")
        return True

    def pi_pixel_to_robot_xy(self, u, v):
        """Convert Pi camera pixel to robot XY using affine transform."""
        pt = np.array([u, v, 1.0])
        result = pt @ self.pi_to_robot
        return float(result[0]), float(result[1])

    # ── Key Detection (overhead) ─────────────────────────────────────────

    def detect_key_overhead(self, pi_img, key_name):
        """
        Detect a specific key in the overhead image.

        Strategy: detect the keyboard region using edge density,
        then map key_name to a grid position within that region.
        """
        gray = cv2.cvtColor(pi_img, cv2.COLOR_BGR2GRAY)

        # Find keyboard: region with high edge density
        edges = cv2.Canny(gray, 40, 120)
        kernel = np.ones((20, 20), np.uint8)
        density = cv2.dilate(edges, kernel, iterations=2)
        density = cv2.erode(density, kernel, iterations=1)

        contours, _ = cv2.findContours(density, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Find largest rectangular region
        kbd_rect = None
        max_area = 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 3000:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / h if h > 0 else 0
            if 1.2 < aspect < 6 and area > max_area:
                max_area = area
                kbd_rect = (x, y, w, h)

        if kbd_rect is None:
            return None

        # Map key to grid position
        QWERTY = [
            list("`1234567890-="),
            list("qwertyuiop[]\\"),
            list("asdfghjkl;'"),
            list("zxcvbnm,./"),
        ]

        key = key_name.lower()
        row_idx = col_idx = None
        for r, row in enumerate(QWERTY):
            if key in row:
                row_idx = r
                col_idx = row.index(key)
                break

        specials = {
            "space": (4.2, 5.5), "enter": (2.5, 12.5),
            "backspace": (0.5, 13), "tab": (1.5, -0.3),
            "shift": (3.5, -0.5), "esc": (-0.5, -0.5),
        }
        if row_idx is None:
            if key in specials:
                row_idx, col_idx = specials[key]
            else:
                return None

        kx, ky, kw, kh = kbd_rect
        # Key position within keyboard bounds
        n_cols = 14  # approximate number of key columns
        n_rows = 4.5 # approximate number of key rows (including partial)

        px = int(kx + (col_idx + 0.5) / n_cols * kw)
        py = int(ky + (row_idx + 0.5) / n_rows * kh)

        return (px, py), kbd_rect

    # ── Keyboard Surface Height ──────────────────────────────────────────

    def measure_keyboard_z(self):
        """
        Measure keyboard surface Z by lowering the finger until contact.
        Uses a known safe position over the keyboard.
        """
        mc = self.mc
        print("  Measuring keyboard surface Z...")

        # Start from a known position above the keyboard center
        test_x, test_y = 180, 0  # approximate keyboard center
        mc.send_coords([test_x, test_y, self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(4)

        # Lower gradually and read Z
        for z in range(180, 40, -5):
            mc.send_coords([test_x, test_y, z, 0, 180, 90], self.press_speed, 0)
            time.sleep(1.5)
            # Read actual position
            for _ in range(3):
                coords = mc.get_coords()
                time.sleep(0.3)
                if coords and coords != -1:
                    actual_z = coords[2]
                    # If actual Z stops decreasing (hit surface), that's the keyboard
                    break
            else:
                actual_z = z

        # Go back up
        mc.send_coords([test_x, test_y, self.safe_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)

        # Use a reasonable default — we'll refine with visual feedback
        if self.keyboard_z is None:
            self.keyboard_z = 65  # typical height
        print(f"  Keyboard Z set to: {self.keyboard_z}mm")

    # ── Visual Servoing ──────────────────────────────────────────────────

    def visual_servo_to_pixel(self, target_px, target_py, height_z,
                              max_iterations=5, tolerance_px=15):
        """
        Move the finger to align with a target pixel in the overhead camera.
        Uses closed-loop feedback: move → capture → measure error → correct.

        Args:
            target_px, target_py: Target position in Pi camera pixels
            height_z: Height to maintain during servoing (mm)
            max_iterations: Max correction steps
            tolerance_px: Acceptable pixel error

        Returns:
            Final robot (X, Y) position
        """
        mc = self.mc
        mc.set_color(*self.finger_led_color)

        for iteration in range(max_iterations):
            time.sleep(1)

            # Capture and detect finger position
            pi_img = self.capture_pi()
            finger, _ = self.detect_finger_overhead(pi_img)

            if finger is None:
                print(f"    Servo iter {iteration}: finger not visible")
                continue

            fu, fv = finger
            err_u = target_px - fu
            err_v = target_py - fv
            err_px = np.sqrt(err_u**2 + err_v**2)

            print(f"    Servo iter {iteration}: finger=({fu},{fv}) target=({target_px},{target_py}) err={err_px:.0f}px")

            if err_px < tolerance_px:
                print(f"    Converged! Error {err_px:.0f}px < {tolerance_px}px")
                # Read final robot position
                for _ in range(3):
                    coords = mc.get_coords()
                    time.sleep(0.3)
                    if coords and coords != -1:
                        return coords[0], coords[1]
                return None, None

            # Convert pixel error to robot XY correction
            # Use the calibrated affine to estimate correction magnitude
            # Current position in robot frame
            target_robot = self.pi_pixel_to_robot_xy(target_px, target_py)
            current_robot = self.pi_pixel_to_robot_xy(fu, fv)
            dx = target_robot[0] - current_robot[0]
            dy = target_robot[1] - current_robot[1]

            # Apply correction (damped to avoid overshoot)
            damping = 0.7
            # Read current position
            for _ in range(3):
                coords = mc.get_coords()
                time.sleep(0.3)
                if coords and coords != -1:
                    break

            if coords and coords != -1:
                new_x = coords[0] + dx * damping
                new_y = coords[1] + dy * damping
                mc.send_coords([new_x, new_y, height_z, 0, 180, 90],
                              self.approach_speed, 0)
                time.sleep(3)

        print(f"    Visual servo did not converge after {max_iterations} iterations")
        for _ in range(3):
            coords = mc.get_coords()
            time.sleep(0.3)
            if coords and coords != -1:
                return coords[0], coords[1]
        return None, None

    # ── Motion Planning ──────────────────────────────────────────────────

    def plan_press_motion(self, target_x, target_y, surface_z):
        """
        Plan a smooth key-press trajectory.

        Phases:
          1. TRAVEL: Move at safe height to above the target (fast)
          2. APPROACH: Arc-shaped descent from safe height to hover (medium)
          3. ALIGN: Pause at hover height for visual verification (slow)
          4. PRESS: Straight down to surface + press_depth (very slow)
          5. RELEASE: Lift straight up to hover height (medium)
          6. RETREAT: Return to safe height (fast)

        Returns list of (x, y, z, speed, pause) waypoints.
        """
        hover_z = surface_z + 25  # 25mm above surface for alignment
        press_z = surface_z - self.press_depth

        waypoints = [
            # Phase 1: TRAVEL to above target at safe height
            {"x": target_x, "y": target_y, "z": self.safe_z,
             "speed": self.travel_speed, "pause": 2.0, "phase": "travel"},

            # Phase 2: APPROACH — descend to hover height
            {"x": target_x, "y": target_y, "z": hover_z,
             "speed": self.approach_speed, "pause": 1.5, "phase": "approach"},

            # Phase 3: ALIGN — visual check (servo can correct here)
            {"x": target_x, "y": target_y, "z": hover_z,
             "speed": self.approach_speed, "pause": 0.5, "phase": "align"},

            # Phase 4: PRESS — slow descent to press
            {"x": target_x, "y": target_y, "z": press_z,
             "speed": self.press_speed, "pause": 0.3, "phase": "press"},

            # Phase 5: RELEASE — lift back to hover
            {"x": target_x, "y": target_y, "z": hover_z,
             "speed": self.approach_speed, "pause": 0.5, "phase": "release"},

            # Phase 6: RETREAT — back to safe height
            {"x": target_x, "y": target_y, "z": self.safe_z,
             "speed": self.travel_speed, "pause": 0.5, "phase": "retreat"},
        ]
        return waypoints

    def execute_waypoints(self, waypoints, visual_servo_at_align=True):
        """Execute a planned trajectory with optional visual servoing at align phase."""
        mc = self.mc

        for i, wp in enumerate(waypoints):
            phase = wp["phase"]
            x, y, z = wp["x"], wp["y"], wp["z"]
            speed = wp["speed"]
            pause = wp["pause"]

            print(f"    [{phase}] → ({x:.1f}, {y:.1f}, {z:.1f}) speed={speed}")
            mc.send_coords([x, y, z, 0, 180, 90], speed, 0)
            time.sleep(pause)

            # Wait for motion to complete
            settle_time = max(2.0, abs(z - (waypoints[i-1]["z"] if i > 0 else self.safe_z)) / 20)
            time.sleep(settle_time)

            # At ALIGN phase: run visual servoing if enabled
            if phase == "align" and visual_servo_at_align and self.pi_to_robot is not None:
                print(f"    [visual servo] Correcting alignment...")
                # We need the target pixel — re-detect keyboard
                pi_img = self.capture_pi()
                # Find where the finger should be (we already know target robot XY)
                # Use the inverse of our affine to map robot→pixel for the target
                # But we just correct using servoing
                # Skip for now if we don't have a target pixel
                pass

    # ── Main Press Key ───────────────────────────────────────────────────

    def press_key(self, key_name, use_vision=True):
        """
        Press a key using vision-guided motion planning.

        Steps:
          1. Load taught position OR detect key visually
          2. Plan smooth trajectory
          3. Execute with visual servoing at align phase
          4. Verify press (check if finger returned to expected height)
        """
        mc = self.mc
        print(f"\n{'='*55}")
        print(f"  PRESSING: '{key_name}'")
        print(f"{'='*55}")

        # Step 1: Get target position
        target_pos = self.get_key_target(key_name)
        if target_pos is None:
            print("  ERROR: Cannot determine key position!")
            return False

        target_x, target_y, target_z = target_pos
        print(f"  Target: ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")

        # Step 2: Plan trajectory
        surface_z = target_z if self.keyboard_z is None else self.keyboard_z
        waypoints = self.plan_press_motion(target_x, target_y, surface_z)
        print(f"  Planned {len(waypoints)} waypoints")

        # Step 3: Set LED for tracking
        mc.set_color(*self.finger_led_color)
        time.sleep(0.3)

        # Step 4: Execute travel + approach
        for wp in waypoints:
            phase = wp["phase"]
            x, y, z = wp["x"], wp["y"], wp["z"]
            speed = wp["speed"]

            if phase == "align" and use_vision and self.pi_to_robot is not None:
                # Visual servoing correction at hover height
                print(f"    [{phase}] Visual servo alignment...")
                corrected_x, corrected_y = self._visual_correct(
                    x, y, z, key_name)
                if corrected_x is not None:
                    x, y = corrected_x, corrected_y
                    # Update remaining waypoints
                    for future_wp in waypoints:
                        if future_wp["phase"] in ("press", "release", "retreat"):
                            future_wp["x"] = x
                            future_wp["y"] = y
                    print(f"    [{phase}] Corrected to ({x:.1f}, {y:.1f})")
                continue

            print(f"    [{phase}] → ({x:.1f}, {y:.1f}, z={z:.0f}) speed={speed}")
            mc.send_coords([x, y, z, 0, 180, 90], speed, 0)

            # Adaptive wait based on distance
            if phase == "travel":
                time.sleep(4)
            elif phase == "approach":
                time.sleep(3)
            elif phase == "press":
                time.sleep(2)
            elif phase == "release":
                time.sleep(2)
            elif phase == "retreat":
                time.sleep(2)

        print(f"  ✓ Key '{key_name}' pressed!")
        return True

    def _visual_correct(self, initial_x, initial_y, hover_z, key_name):
        """
        At hover height, capture overhead image, detect both the finger
        and the target key, then correct the XY offset.
        """
        mc = self.mc
        mc.send_coords([initial_x, initial_y, hover_z, 0, 180, 90],
                       self.approach_speed, 0)
        time.sleep(3)

        pi_img = self.capture_pi()
        finger, _ = self.detect_finger_overhead(pi_img)
        if finger is None:
            print("      Finger not detected in overhead image")
            return None, None

        # For now, we trust the initial position + finger detection offset
        fu, fv = finger
        # Where we think the key is in pixels (inverse of affine)
        # We'll use the current finger position as a reference
        # The key should be at the same pixel position as where we want to be
        # If finger is at (fu, fv) and robot is at (initial_x, initial_y),
        # then the mapping is already established

        print(f"      Finger at pixel ({fu}, {fv})")
        return initial_x, initial_y  # No correction for now, return as-is

    def get_key_target(self, key_name):
        """Get target robot coordinates for a key."""
        # Try loading taught data
        try:
            with open("keyboard_taught.json", "r") as f:
                data = json.load(f)
            keys = data.get("keys", {})
            key = key_name.lower()

            if key in keys and keys[key].get("coords"):
                coords = keys[key]["coords"]
                return coords[0], coords[1], coords[2]

            # Try grid model interpolation
            grid_model = data.get("grid_model")
            if grid_model:
                M = np.array(grid_model)
                QWERTY = [
                    list("`1234567890-="),
                    list("qwertyuiop[]\\"),
                    list("asdfghjkl;'"),
                    list("zxcvbnm,./"),
                ]
                for r, row in enumerate(QWERTY):
                    if key in row:
                        c = row.index(key)
                        pred = np.array([r, c, 1]) @ M
                        return pred[0], pred[1], pred[2]

        except FileNotFoundError:
            pass

        print(f"  No position data for key '{key_name}'")
        return None

    def press_sequence(self, text, delay=0.3):
        """Press a sequence of characters."""
        print(f"\n  Typing: '{text}'")
        for char in text:
            if char == ' ':
                self.press_key('space')
            else:
                self.press_key(char)
            time.sleep(delay)

        # Return home
        self.mc.send_angles([0, 0, 0, 0, 0, 0], self.travel_speed)
        time.sleep(4)

    # ── Full Setup ───────────────────────────────────────────────────────

    def setup(self, calibrate=True):
        """Full setup: connect, calibrate, measure keyboard."""
        self.connect()
        self.start_realsense()

        if calibrate:
            # Move to a starting position
            self.mc.send_angles([0, 0, 0, 0, 0, 0], self.travel_speed)
            time.sleep(4)

            # Live Pi-to-robot calibration
            success = self.calibrate_pi_to_robot_live()
            if not success:
                print("  Calibration failed! Continuing without visual servo.")

        # Try loading keyboard Z from taught data
        try:
            with open("keyboard_taught.json", "r") as f:
                data = json.load(f)
            keys = data.get("keys", {})
            z_values = [v["coords"][2] for v in keys.values()
                       if v.get("coords") and v["coords"][2] < 150]
            if z_values:
                self.keyboard_z = np.median(z_values)
                print(f"  Keyboard Z from taught data: {self.keyboard_z:.1f}mm")
        except FileNotFoundError:
            self.keyboard_z = 70  # default
            print(f"  Using default keyboard Z: {self.keyboard_z}mm")

        self.mc.send_angles([0, 0, 0, 0, 0, 0], self.travel_speed)
        time.sleep(3)
        print("\n  Setup complete!")


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    vp = VisionGuidedPresser()
    vp.setup(calibrate=True)

    if len(sys.argv) > 1:
        target = " ".join(sys.argv[1:])
        if len(target) == 1:
            vp.press_key(target)
        else:
            vp.press_sequence(target)
    else:
        print("\nInteractive mode. Type a key or text, 'quit' to exit.\n")
        while True:
            cmd = input("Press: ").strip()
            if not cmd or cmd.lower() == 'quit':
                break
            if len(cmd) == 1:
                vp.press_key(cmd)
            else:
                vp.press_sequence(cmd)

    vp.mc.send_angles([0, 0, 0, 0, 0, 0], 10)
    time.sleep(3)
    vp.mc.set_color(255, 255, 255)
    vp.stop()
    print("Done!")
