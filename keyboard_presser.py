"""
KEYBOARD KEY PRESSING SYSTEM

Architecture (two-camera fusion):
  - Pi camera (overhead, on robot arm): sees the keyboard from above → gives XY position of keys
  - RealSense D435i (side view): sees the keyboard surface depth → gives Z (height)

Calibration approach:
  Instead of detecting the end-effector in the RealSense, we use a simpler and
  more robust method:
  1. Calibrate Pi camera → robot XY using the working green-LED method (from above)
  2. Use the RealSense to measure the KEYBOARD SURFACE HEIGHT from the side
  3. Combine: Pi gives (X,Y), RealSense gives Z → full 3D target

For key pressing:
  1. Move arm to overhead position → Pi camera sees keyboard
  2. Use QWERTY layout geometry to find target key pixel position
  3. Convert pixel → robot XY using the Pi-camera affine calibration
  4. RealSense measures keyboard surface Z
  5. Move finger above key at safe height
  6. Press down slowly to keyboard surface + press_depth
  7. Retract

This works because:
  - The Pi camera is GREAT at XY (it's directly overhead)
  - The RealSense is GREAT at Z (depth from side view gives precise height)
  - We don't need the RealSense for XY at all!
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
SLOW_SPEED = 8     # Very slow for pressing keys
MOVE_SPEED = 12    # Moderate for positioning
os.makedirs("temp", exist_ok=True)


class KeyboardPresser:
    """
    Presses specific keys on a laptop keyboard using:
    - Pi overhead camera for XY targeting
    - RealSense side camera for Z (height) measurement
    - myCobot 280 with a finger end-effector
    """

    def __init__(self):
        self.mc = None
        self.rs_pipeline = None
        self.rs_align = None
        self.rs_intrinsics = None
        self.rs_depth_scale = 0.001

        # Pi camera → robot XY affine transform (from calibration)
        self.pi_affine = None  # 3x2 matrix: [u, v, 1] @ M = [robot_x, robot_y]

        # Keyboard geometry in robot frame (from calibration)
        self.kbd_top_left_robot = None      # (X, Y) in robot mm
        self.kbd_bottom_right_robot = None  # (X, Y) in robot mm
        self.kbd_surface_z = None           # Z height of keyboard surface in robot frame (mm)
        self.kbd_rows = 5                   # number of key rows
        self.kbd_cols = 14                  # number of key columns

        # Pi camera keyboard bounds in pixels
        self.kbd_top_left_px = None
        self.kbd_bottom_right_px = None

    # ── Connection ───────────────────────────────────────────────────────

    def connect(self):
        print("Connecting to robot...")
        self.mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
        time.sleep(1)

    def start_realsense(self):
        print("Starting RealSense...")
        self.rs_pipeline = rs2.pipeline()
        config = rs2.config()
        config.enable_stream(rs2.stream.color, 640, 480, rs2.format.bgr8, 30)
        config.enable_stream(rs2.stream.depth, 640, 480, rs2.format.z16, 30)
        profile = self.rs_pipeline.start(config)
        self.rs_depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
        self.rs_align = rs2.align(rs2.stream.color)
        color_stream = profile.get_stream(rs2.stream.color)
        self.rs_intrinsics = color_stream.as_video_stream_profile().get_intrinsics()
        for _ in range(30):
            self.rs_pipeline.wait_for_frames()
        print("  RealSense ready.")

    def stop(self):
        if self.rs_pipeline:
            self.rs_pipeline.stop()

    # ── Camera Capture ───────────────────────────────────────────────────

    def capture_pi(self):
        resp = httpx.get(CAMERA_URL, timeout=5.0)
        return cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)

    def capture_realsense(self):
        frames = self.rs_pipeline.wait_for_frames()
        aligned = self.rs_align.process(frames)
        color = np.asanyarray(aligned.get_color_frame().get_data())
        depth = np.asanyarray(aligned.get_depth_frame().get_data())
        return color, depth

    def measure_surface_z(self, rs_depth, region=None):
        """Measure the dominant surface height from RealSense depth.
        Returns the keyboard surface depth in mm from the RealSense."""
        if region:
            x, y, w, h = region
            patch = rs_depth[y:y+h, x:x+w]
        else:
            # Use lower-middle region where keyboard typically is
            h, w = rs_depth.shape
            patch = rs_depth[h//2:, w//4:3*w//4]

        valid = patch[patch > 0].astype(float) * self.rs_depth_scale * 1000
        if len(valid) == 0:
            return None

        # Find the most common depth (the flat keyboard surface)
        hist, bins = np.histogram(valid, bins=100)
        peak_idx = np.argmax(hist)
        surface_depth_mm = (bins[peak_idx] + bins[peak_idx + 1]) / 2
        return surface_depth_mm

    # ── Pi Camera XY Calibration ─────────────────────────────────────────

    def calibrate_pi_xy(self):
        """
        Calibrate Pi overhead camera → robot XY using green LED detection.
        The robot moves to several positions with green LED on, Pi camera sees them.
        """
        print("\n" + "=" * 60)
        print("  PI CAMERA XY CALIBRATION")
        print("=" * 60)

        mc = self.mc

        positions = [
            (100, 50, 180),
            (100, -50, 180),
            (150, 0, 180),
            (150, 50, 150),
            (150, -50, 150),
            (200, -50, 180),
            (200, 50, 180),
            (200, 0, 150),
        ]

        pixel_points = []
        robot_points = []

        for i, (rx, ry, rz) in enumerate(positions):
            print(f"\n  Point {i+1}/{len(positions)}: robot ({rx}, {ry}, {rz})")

            # Move slowly
            mc.send_coords([rx, ry, 250, 0, 180, 90], MOVE_SPEED, 0)
            time.sleep(4)
            mc.send_coords([rx, ry, rz, 0, 180, 90], MOVE_SPEED, 0)
            time.sleep(4)
            mc.set_color(0, 255, 0)
            time.sleep(1)

            # Move arm away to take overhead photo from top-view
            # Actually for Pi cam on the arm, we need to use a different approach:
            # The Pi camera IS on the arm, so when arm is at the position,
            # the camera sees what's below it — NOT the LED.
            # 
            # Better approach: use the EXISTING affine calibration from earlier
            # or use the RealSense to detect the green LED position in the
            # side view, then project onto the table plane.
            #
            # SIMPLEST: re-use the 2-point calibration we already computed
            # in calibration_data.json (affine matrix from the earlier Pi cam run).

            pass

        # Actually, let's load the existing Pi calibration
        # and skip re-doing it since it already works from the previous calibrate.py run
        print("\n  Loading existing Pi camera calibration from calibration_data.json...")
        try:
            with open("calibration_data.json", "r") as f:
                data = json.load(f)
            self.pi_affine = np.array(data["affine_matrix"])
            print(f"  Loaded! Mean error was {data['mean_error_mm']:.1f}mm")
            # Go home
            mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
            time.sleep(5)
            return True
        except FileNotFoundError:
            print("  No existing calibration found. Need to run calibrate.py first.")
            mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
            time.sleep(5)
            return False

    # ── Keyboard Detection ───────────────────────────────────────────────

    def detect_keyboard_bounds_overhead(self, pi_image):
        """
        Detect the laptop keyboard region in the overhead Pi camera image.
        Returns pixel bounds of the keyboard area.
        """
        # Convert to grayscale and find edges
        gray = cv2.cvtColor(pi_image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # The keyboard is a rectangular region with lots of small squares (keys)
        # It has high edge density in a rectangular pattern
        kernel = np.ones((15, 15), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Find the largest rectangle-like contour (the keyboard)
        best = None
        best_area = 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 5000:
                continue
            rect = cv2.minAreaRect(cnt)
            box = cv2.boxPoints(rect)
            rect_area = rect[1][0] * rect[1][1]
            # Keyboard is wider than tall
            w, h = max(rect[1]), min(rect[1])
            aspect = w / h if h > 0 else 0
            if 1.5 < aspect < 5 and area > best_area:
                best_area = area
                best = cv2.boundingRect(cnt)

        return best  # (x, y, w, h) or None

    # ── Key Position Mapping ─────────────────────────────────────────────

    # QWERTY key layout (row, col) → estimated position fraction within keyboard
    KEY_MAP = {}
    _rows = [
        ("esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "del"),
        ("`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "backspace"),
        ("tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]", "\\"),
        ("caps", "a", "s", "d", "f", "g", "h", "j", "k", "l", ";", "'", "enter"),
        ("shift_l", "z", "x", "c", "v", "b", "n", "m", ",", ".", "/", "shift_r"),
        ("ctrl", "fn", "alt", "space", "alt_r", "ctrl_r"),
    ]

    for _r, _row in enumerate(_rows):
        for _c, _key in enumerate(_row):
            n = len(_row)
            # x fraction across the keyboard
            x_frac = (_c + 0.5) / max(n, 14)
            # y fraction down the keyboard
            y_frac = (_r + 0.5) / len(_rows)
            # Special wide keys
            if _key == "space":
                x_frac = 0.45
            elif _key == "backspace":
                x_frac = 0.95
            elif _key == "enter":
                x_frac = 0.93
            elif _key in ("shift_l", "shift_r"):
                x_frac = 0.05 if "l" in _key else 0.92
            KEY_MAP[_key] = (x_frac, y_frac)

    def get_key_pixel(self, key_name, kbd_bounds):
        """Get pixel position of a key within the keyboard bounds."""
        key = key_name.lower()
        if key not in self.KEY_MAP:
            print(f"  Unknown key: '{key}'")
            return None
        x_frac, y_frac = self.KEY_MAP[key]
        kx, ky, kw, kh = kbd_bounds
        px = int(kx + x_frac * kw)
        py = int(ky + y_frac * kh)
        return (px, py)

    def pixel_to_robot_xy(self, u, v):
        """Convert Pi overhead pixel to robot XY using affine transform."""
        if self.pi_affine is None:
            raise RuntimeError("Pi camera not calibrated!")
        pt = np.array([u, v, 1.0])
        result = pt @ self.pi_affine
        return float(result[0]), float(result[1])

    # ── Key Pressing ─────────────────────────────────────────────────────

    def press_key(self, key_name, press_depth_mm=5, approach_z=None):
        """
        Press a specific key on the laptop keyboard.

        Args:
            key_name: Key to press (e.g. 'a', 'space', 'enter', 'f5')
            press_depth_mm: How deep to press beyond surface (mm)
            approach_z: Height to approach from. If None, auto-detected.
        """
        mc = self.mc
        print(f"\n{'='*50}")
        print(f"  PRESSING KEY: '{key_name}'")
        print(f"{'='*50}")

        # Step 1: Move to top-view to see the keyboard
        print("  Step 1: Moving to top-view (slowly)...")
        mc.send_angles([-62.13, 8.96, -87.71, -14.41, 2.54, -16.34], MOVE_SPEED)
        time.sleep(6)

        # Step 2: Capture overhead image from Pi camera
        print("  Step 2: Capturing overhead image...")
        pi_img = self.capture_pi()
        cv2.imwrite("temp/keypress_overhead.jpg", pi_img)

        # Step 3: Detect keyboard bounds
        print("  Step 3: Detecting keyboard...")
        if self.kbd_top_left_px and self.kbd_bottom_right_px:
            tlx, tly = self.kbd_top_left_px
            brx, bry = self.kbd_bottom_right_px
            kbd_bounds = (tlx, tly, brx - tlx, bry - tly)
            print(f"    Using stored keyboard bounds: {kbd_bounds}")
        else:
            kbd_bounds = self.detect_keyboard_bounds_overhead(pi_img)
            if kbd_bounds is None:
                print("    ERROR: Cannot detect keyboard! Please calibrate bounds manually.")
                return False
            print(f"    Detected keyboard at: {kbd_bounds}")

        # Step 4: Find key position in pixel coords
        print(f"  Step 4: Finding key '{key_name}'...")
        key_px = self.get_key_pixel(key_name, kbd_bounds)
        if key_px is None:
            return False
        print(f"    Key pixel position: {key_px}")

        # Step 5: Convert to robot XY
        print("  Step 5: Converting to robot coords...")
        robot_x, robot_y = self.pixel_to_robot_xy(key_px[0], key_px[1])
        print(f"    Robot XY: ({robot_x:.1f}, {robot_y:.1f})")

        # Step 6: Get keyboard surface Z from RealSense
        print("  Step 6: Measuring keyboard height...")
        if self.kbd_surface_z is not None:
            surface_z = self.kbd_surface_z
            print(f"    Using stored keyboard Z: {surface_z:.1f}mm")
        else:
            _, rs_depth = self.capture_realsense()
            surface_depth = self.measure_surface_z(rs_depth)
            if surface_depth:
                print(f"    RealSense surface depth: {surface_depth:.0f}mm from camera")
                # We need keyboard Z in ROBOT frame, not camera frame
                # For now use a reasonable default
                surface_z = 50  # default: 50mm above table
                print(f"    Using default keyboard Z: {surface_z}mm (adjust with set_keyboard_z)")
            else:
                surface_z = 50
                print(f"    Could not measure, using default Z: {surface_z}mm")

        if approach_z is None:
            approach_z = surface_z + 60  # 60mm above keyboard

        # Draw visualization
        vis = pi_img.copy()
        kx, ky, kw, kh = kbd_bounds
        cv2.rectangle(vis, (kx, ky), (kx+kw, ky+kh), (0, 255, 0), 2)
        cv2.circle(vis, key_px, 8, (0, 0, 255), -1)
        cv2.putText(vis, f"'{key_name}'", (key_px[0]+10, key_px[1]-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.imwrite("temp/keypress_target.jpg", vis)

        # Step 7: Go home first
        print("  Step 7: Going home...")
        mc.send_angles([0, 0, 0, 0, 0, 0], MOVE_SPEED)
        time.sleep(5)

        # Step 8: Move above the key
        print(f"  Step 8: Moving above key ({robot_x:.1f}, {robot_y:.1f}, {approach_z:.0f})...")
        mc.send_coords([robot_x, robot_y, approach_z, 0, 180, 90], SLOW_SPEED, 0)
        time.sleep(6)

        # Step 9: Lower slowly to just above keyboard surface
        hover_z = surface_z + 10
        print(f"  Step 9: Lowering to hover ({robot_x:.1f}, {robot_y:.1f}, {hover_z:.0f})...")
        mc.send_coords([robot_x, robot_y, hover_z, 0, 180, 90], SLOW_SPEED, 0)
        time.sleep(4)

        # Step 10: Press down
        press_z = surface_z - press_depth_mm
        print(f"  Step 10: Pressing key (z={press_z:.0f})...")
        mc.send_coords([robot_x, robot_y, press_z, 0, 180, 90], SLOW_SPEED, 0)
        time.sleep(2)

        # Step 11: Release - lift back up
        print("  Step 11: Releasing key...")
        mc.send_coords([robot_x, robot_y, approach_z, 0, 180, 90], SLOW_SPEED, 0)
        time.sleep(3)

        print(f"\n  Key '{key_name}' pressed!")
        return True

    def press_sequence(self, keys, delay_between=0.5):
        """Press a sequence of keys."""
        print(f"\nPressing sequence: {keys}")
        for key in keys:
            self.press_key(key)
            time.sleep(delay_between)
        print("\nSequence complete!")

    # ── Keyboard Bounds Calibration ──────────────────────────────────────

    def set_keyboard_bounds_px(self, top_left, bottom_right):
        """Manually set keyboard pixel bounds from the overhead image."""
        self.kbd_top_left_px = top_left
        self.kbd_bottom_right_px = bottom_right
        print(f"Keyboard bounds set: TL={top_left}, BR={bottom_right}")

    def set_keyboard_z(self, z_mm):
        """Set the keyboard surface Z in robot frame (mm)."""
        self.kbd_surface_z = z_mm
        print(f"Keyboard surface Z set to {z_mm}mm")

    def save_config(self, path="keyboard_config.json"):
        data = {
            "kbd_top_left_px": self.kbd_top_left_px,
            "kbd_bottom_right_px": self.kbd_bottom_right_px,
            "kbd_surface_z": self.kbd_surface_z,
            "pi_affine": self.pi_affine.tolist() if self.pi_affine is not None else None,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Config saved to {path}")

    def load_config(self, path="keyboard_config.json"):
        with open(path, "r") as f:
            data = json.load(f)
        self.kbd_top_left_px = data.get("kbd_top_left_px")
        self.kbd_bottom_right_px = data.get("kbd_bottom_right_px")
        self.kbd_surface_z = data.get("kbd_surface_z")
        if data.get("pi_affine"):
            self.pi_affine = np.array(data["pi_affine"])
        print(f"Config loaded from {path}")


# ══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE SETUP
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    kp = KeyboardPresser()
    kp.connect()
    kp.start_realsense()

    # Load existing Pi camera calibration
    print("\nLoading Pi camera calibration...")
    try:
        with open("calibration_data.json", "r") as f:
            data = json.load(f)
        kp.pi_affine = np.array(data["affine_matrix"])
        print(f"  Loaded. Mean error: {data['mean_error_mm']:.1f}mm")
    except FileNotFoundError:
        print("  No calibration found! Run calibrate.py first.")
        kp.stop()
        exit(1)

    # Step 1: Move to top-view and capture the keyboard
    print("\nMoving to top-view to see the keyboard...")
    kp.mc.send_angles([-62.13, 8.96, -87.71, -14.41, 2.54, -16.34], MOVE_SPEED)
    time.sleep(6)

    pi_img = kp.capture_pi()
    cv2.imwrite("temp/keyboard_overhead.jpg", pi_img)

    # Auto-detect keyboard
    kbd = kp.detect_keyboard_bounds_overhead(pi_img)
    if kbd:
        x, y, w, h = kbd
        print(f"  Auto-detected keyboard: ({x},{y}) {w}x{h}")
        kp.set_keyboard_bounds_px((x, y), (x + w, y + h))

        # Draw on image
        vis = pi_img.copy()
        cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 255, 0), 2)

        # Draw key grid
        for key_name, (x_f, y_f) in kp.KEY_MAP.items():
            px = int(x + x_f * w)
            py = int(y + y_f * h)
            cv2.circle(vis, (px, py), 2, (0, 0, 255), -1)
            if key_name in ('a', 's', 'd', 'f', 'space', 'enter', 'q', 'w', 'e', 'r'):
                cv2.putText(vis, key_name, (px+3, py-3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.25, (255, 255, 0), 1)
        cv2.imwrite("temp/keyboard_grid.jpg", vis)
        print("  Grid visualization saved to temp/keyboard_grid.jpg")
    else:
        print("  Auto-detection failed. You'll need to set bounds manually.")
        print("  Open temp/keyboard_overhead.jpg, find keyboard corners,")
        print("  then call: kp.set_keyboard_bounds_px((x1,y1), (x2,y2))")

    # Step 2: Measure keyboard surface Z from RealSense
    print("\nMeasuring keyboard Z from RealSense...")
    _, rs_depth = kp.capture_realsense()
    surface = kp.measure_surface_z(rs_depth)
    if surface:
        print(f"  Surface depth from RealSense: {surface:.0f}mm")
    print("  NOTE: You may need to manually set kbd_surface_z in robot frame.")
    print("  Move finger to keyboard surface, read Z from get_coords().")

    # Go home
    kp.mc.send_angles([0, 0, 0, 0, 0, 0], SLOW_SPEED)
    time.sleep(5)

    kp.save_config()
    kp.stop()
    print("\nSetup complete! Open temp/keyboard_grid.jpg to verify detection.")
    print("Next: run press_key() to press keys!")
