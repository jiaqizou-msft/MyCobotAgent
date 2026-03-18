"""Find the red marker using HSV color detection and iteratively point at it."""
from pymycobot import MyCobot280Socket
import httpx
import cv2
import numpy as np
import time

def capture_image(filename="temp/vl_now.jpg"):
    """Capture overhead image from Pi camera."""
    resp = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5.0)
    img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite(filename, img)
    return img

def find_red_marker(img):
    """Detect the red marker using HSV color thresholding."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Red wraps around in HSV, so we need two ranges
    lower_red1 = np.array([0, 80, 80])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([160, 80, 80])
    upper_red2 = np.array([180, 255, 255])
    
    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    mask = mask1 | mask2
    
    # Clean up noise
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None, mask
    
    # Get the largest red contour
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    
    if area < 100:  # too small, probably noise
        return None, None, mask
    
    # Get center
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None, None, mask
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    
    # Get bounding rect
    x, y, w, h = cv2.boundingRect(largest)
    
    print(f"  Red object: center=({cx},{cy}), area={area:.0f}, bbox=({x},{y},{w},{h})")
    return (cx, cy), (x, y, w, h), mask

def draw_detection(img, center, bbox, label="RED MARKER", iteration=0):
    """Draw detection visualization."""
    vis = img.copy()
    if center:
        cx, cy = center
        x, y, w, h = bbox
        cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.circle(vis, (cx, cy), 8, (0, 0, 255), -1)
        cv2.putText(vis, f"{label} ({cx},{cy})", (cx+10, cy-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    path = f"temp/detect_iter{iteration}.jpg"
    cv2.imwrite(path, vis)
    return path


# ===== MAIN =====
print("Connecting to robot...")
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(1)

# Step 1: Move to top-view
print("\n--- Step 1: Move to top-view ---")
mc.send_angles([-62.13, 8.96, -87.71, -14.41, 2.54, -16.34], 15)
time.sleep(5)

# Step 2: Capture and detect
print("\n--- Step 2: Capture and detect red marker ---")
img = capture_image()
center, bbox, mask = find_red_marker(img)
cv2.imwrite("temp/red_mask.jpg", mask)

if center is None:
    print("No red marker detected! Saving mask for debugging.")
    print("Check temp/red_mask.jpg to see what the color filter found.")
else:
    path = draw_detection(img, center, bbox, iteration=0)
    print(f"  Detection saved to {path}")
    
    cx, cy = center
    img_h, img_w = img.shape[:2]
    print(f"  Image size: {img_w}x{img_h}")
    print(f"  Marker pixel: ({cx}, {cy})")
    
    # Step 3: Eye-to-hand transform
    print("\n--- Step 3: Convert pixel to robot coords ---")
    from src.calibration.eye2hand import get_eye2hand
    e2h = get_eye2hand()
    robot_x, robot_y = e2h.pixel_to_robot(cx, cy)
    print(f"  Estimated robot coords: ({robot_x:.1f}, {robot_y:.1f})")
    
    # Step 4: Go home first
    print("\n--- Step 4: Go home ---")
    mc.send_angles([0, 0, 0, 0, 0, 0], 30)
    time.sleep(4)
    
    # Step 5: Move above marker
    print(f"\n--- Step 5: Move above marker ({robot_x:.1f}, {robot_y:.1f}, 200) ---")
    mc.send_coords([robot_x, robot_y, 200, 0, 180, 90], 20, 0)
    time.sleep(5)
    
    # Step 6: Lower toward marker
    print(f"\n--- Step 6: Lower to z=130 ---")
    mc.send_coords([robot_x, robot_y, 130, 0, 180, 90], 15, 0)
    time.sleep(4)
    
    # Step 7: Verify — capture another image
    print("\n--- Step 7: Verify position ---")
    time.sleep(1)
    for i in range(5):
        angles = mc.get_angles()
        time.sleep(0.3)
        if angles and angles != -1:
            break
    print(f"  Current angles: {angles}")
    for i in range(5):
        coords = mc.get_coords()
        time.sleep(0.3)
        if coords and coords != -1:
            break
    print(f"  Current coords: {coords}")

print("\nDone! Check if the finger is near the red marker.")
print("If it's off, we need to calibrate. Tell me which direction it's off.")
