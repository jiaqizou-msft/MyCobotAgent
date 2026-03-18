"""
Hand-eye calibration: move robot to known positions, detect LED in
overhead camera, and compute a pixel-to-robot affine transform.

The robot moves to a grid of positions with a bright GREEN LED.
The overhead camera captures each position and detects the green blob.
We collect (pixel_x, pixel_y) <-> (robot_x, robot_y) pairs and
fit a 2D affine transform.
"""
from pymycobot import MyCobot280Socket
import httpx
import cv2
import numpy as np
import time
import json

# ── Config ──
ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000
CAMERA_URL = f'http://{ROBOT_IP}:8080/snapshot'
SAFE_Z = 200        # height during moves
CALIB_Z = 120       # height at calibration points (finger visible from above)
SPEED = 20
LED_COLOR = (0, 255, 0)  # bright green for detection

# Grid of robot XY positions to visit (spread across reachable workspace)
# These should be positions the arm can actually reach
CALIBRATION_POSITIONS = [
    (100, -150),
    (100, -50),
    (100, 50),
    (200, -150),
    (200, -50),
    (200, 50),
    (150, -200),
    (150, 0),
    (150, -100),
    (50, -100),
]


def capture():
    resp = httpx.get(CAMERA_URL, timeout=5.0)
    return cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)


def detect_green_led(img):
    """Detect the bright green LED blob in the image."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Bright green in HSV
    lower = np.array([35, 100, 100])
    upper = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower, upper)

    # Clean up
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask

    # Largest bright green blob
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    if area < 20:
        return None, mask

    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None, mask
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return (cx, cy), mask


def compute_affine(pixel_points, robot_points):
    """Compute affine transform: pixel (u,v) -> robot (x,y).
    
    Solves: [u, v, 1] @ M = [x, y]
    M is a 3x2 matrix.
    """
    n = len(pixel_points)
    A = np.zeros((n, 3))
    B = np.zeros((n, 2))
    for i in range(n):
        A[i] = [pixel_points[i][0], pixel_points[i][1], 1]
        B[i] = [robot_points[i][0], robot_points[i][1]]

    M, residuals, rank, sv = np.linalg.lstsq(A, B, rcond=None)
    
    # Compute error
    predicted = A @ M
    errors = np.sqrt(np.sum((predicted - B) ** 2, axis=1))
    
    return M, errors


def apply_affine(M, u, v):
    """Apply affine transform to a pixel coordinate."""
    pt = np.array([u, v, 1.0])
    result = pt @ M
    return float(result[0]), float(result[1])


# ===== MAIN CALIBRATION =====
print("=" * 60)
print("  HAND-EYE CALIBRATION")
print("=" * 60)

print("\nConnecting to robot...")
mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)

# Set LED bright green
mc.set_color(*LED_COLOR)
time.sleep(0.5)

# Go home first
print("Going home...")
mc.send_angles([0, 0, 0, 0, 0, 0], 30)
time.sleep(4)

pixel_points = []
robot_points = []
images = []

print(f"\nCalibrating with {len(CALIBRATION_POSITIONS)} positions...\n")

for i, (rx, ry) in enumerate(CALIBRATION_POSITIONS):
    print(f"--- Point {i+1}/{len(CALIBRATION_POSITIONS)}: robot ({rx}, {ry}) ---")

    # Move to safe height above target
    mc.send_coords([rx, ry, SAFE_Z, 0, 180, 90], SPEED, 0)
    time.sleep(3)

    # Lower to calibration height
    mc.send_coords([rx, ry, CALIB_Z, 0, 180, 90], SPEED, 0)
    time.sleep(3)

    # Make sure LED is green
    mc.set_color(*LED_COLOR)
    time.sleep(1)

    # Capture image
    img = capture()
    images.append(img)

    # Detect the green LED
    center, mask = detect_green_led(img)

    if center is None:
        print(f"  WARNING: Could not detect LED! Skipping this point.")
        cv2.imwrite(f"temp/calib_mask_{i}.jpg", mask)
        cv2.imwrite(f"temp/calib_img_{i}.jpg", img)
        continue

    px, py = center
    print(f"  Detected LED at pixel ({px}, {py})")
    pixel_points.append((px, py))
    robot_points.append((rx, ry))

    # Draw and save
    vis = img.copy()
    cv2.circle(vis, (px, py), 10, (0, 0, 255), 2)
    cv2.putText(vis, f"R({rx},{ry}) P({px},{py})", (px + 15, py),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    cv2.imwrite(f"temp/calib_{i}.jpg", vis)

# Return home
print("\nReturning home...")
mc.send_angles([0, 0, 0, 0, 0, 0], 30)
time.sleep(3)
mc.set_color(255, 255, 255)

# ── Compute calibration ──
print(f"\n{'=' * 60}")
print(f"  CALIBRATION RESULTS")
print(f"{'=' * 60}")
print(f"  Collected {len(pixel_points)} valid point pairs")

if len(pixel_points) < 3:
    print("  ERROR: Need at least 3 points! Re-run with better positions.")
else:
    M, errors = compute_affine(pixel_points, robot_points)

    print(f"\n  Affine transform matrix (3x2):")
    print(f"    {M[0]}")
    print(f"    {M[1]}")
    print(f"    {M[2]}")

    print(f"\n  Per-point errors (mm):")
    for i, (pp, rp, err) in enumerate(zip(pixel_points, robot_points, errors)):
        print(f"    Point {i+1}: pixel{pp} -> robot{rp}, error={err:.1f}mm")
    print(f"\n  Mean error: {np.mean(errors):.1f}mm")
    print(f"  Max error:  {np.max(errors):.1f}mm")

    # Save calibration data
    calib_data = {
        "affine_matrix": M.tolist(),
        "pixel_points": pixel_points,
        "robot_points": robot_points,
        "errors_mm": errors.tolist(),
        "mean_error_mm": float(np.mean(errors)),
    }
    with open("calibration_data.json", "w") as f:
        json.dump(calib_data, f, indent=2)
    print(f"\n  Calibration saved to calibration_data.json")

    # Quick verification — transform each pixel point back
    print(f"\n  Verification:")
    for pp, rp in zip(pixel_points, robot_points):
        pred_x, pred_y = apply_affine(M, pp[0], pp[1])
        print(f"    pixel{pp} -> pred({pred_x:.1f},{pred_y:.1f}) vs actual({rp[0]},{rp[1]})")

    # Create a visualization of all calibration points
    overview = images[0].copy() if images else capture()
    for pp, rp in zip(pixel_points, robot_points):
        cv2.circle(overview, (int(pp[0]), int(pp[1])), 6, (0, 255, 0), -1)
        cv2.putText(overview, f"({rp[0]},{rp[1]})", (int(pp[0])+8, int(pp[1])-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)
    cv2.imwrite("temp/calibration_overview.jpg", overview)
    print(f"\n  Overview saved to temp/calibration_overview.jpg")

print("\nCalibration complete!")
