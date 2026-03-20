"""
Detect individual keyboard keys from the front webcam (cam 4, 1920x1080).
High-res image with clear key visibility — detect key gaps and label each key.
"""
import cv2
import numpy as np
import json
import os

os.makedirs("temp", exist_ok=True)

FRONT_CAM_IDX = 4

print("=" * 60)
print("  HIGH-RES KEY DETECTION (front webcam)")
print("=" * 60)

# Capture at full resolution
print("\nCapturing from cam 4 at 1080p...")
cap = cv2.VideoCapture(FRONT_CAM_IDX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
# Let auto-exposure settle
for _ in range(10):
    cap.read()

ret, frame = cap.read()
cap.release()

if not ret:
    print("Failed to capture!")
    exit(1)

cv2.imwrite("temp/front_hires.jpg", frame)
print(f"  Captured: {frame.shape[1]}x{frame.shape[0]}")

# Convert to grayscale
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

# Step 1: Find keyboard region using edge density
print("\nStep 1: Finding keyboard region...")
edges = cv2.Canny(gray, 50, 150)
kernel = np.ones((20, 20), np.uint8)
density = cv2.dilate(edges, kernel, iterations=3)
density = cv2.erode(density, kernel, iterations=2)

contours, _ = cv2.findContours(density, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Find the largest rectangular region with high aspect ratio (wider than tall)
kbd_rect = None
max_area = 0
for cnt in contours:
    area = cv2.contourArea(cnt)
    if area < 50000:  # minimum ~230x230 pixels
        continue
    x, y, w, h = cv2.boundingRect(cnt)
    aspect = w / h if h > 0 else 0
    if 1.5 < aspect < 6 and area > max_area:
        max_area = area
        kbd_rect = (x, y, w, h)

if kbd_rect is None:
    # Fallback: just use the center region
    h, w = frame.shape[:2]
    kbd_rect = (w//6, h//4, 2*w//3, h//2)
    print(f"  Auto-detection failed, using center region: {kbd_rect}")
else:
    print(f"  Keyboard region: {kbd_rect}")

kx, ky, kw, kh = kbd_rect

# Step 2: Extract keyboard ROI
print("\nStep 2: Extracting keyboard ROI...")
kbd_roi = gray[ky:ky+kh, kx:kx+kw]
kbd_color = frame[ky:ky+kh, kx:kx+kw]
cv2.imwrite("temp/keyboard_roi.jpg", kbd_color)

# Step 3: Detect key gaps using multiple methods
print("\nStep 3: Detecting key gaps...")

# Method A: Adaptive threshold (works well for high contrast key gaps)
thresh_a = cv2.adaptiveThreshold(kbd_roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 21, 5)
cv2.imwrite("temp/keys_thresh_adaptive.jpg", thresh_a)

# Method B: Morphological gradient (highlights edges between keys)
morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
gradient = cv2.morphologyEx(kbd_roi, cv2.MORPH_GRADIENT, morph_kernel)
_, thresh_b = cv2.threshold(gradient, 20, 255, cv2.THRESH_BINARY)
cv2.imwrite("temp/keys_thresh_gradient.jpg", thresh_b)

# Method C: Canny on the ROI
edges_roi = cv2.Canny(kbd_roi, 30, 100)
# Close gaps in edges
close_kernel = np.ones((3, 3), np.uint8)
edges_closed = cv2.morphologyEx(edges_roi, cv2.MORPH_CLOSE, close_kernel)
cv2.imwrite("temp/keys_edges.jpg", edges_closed)

# Combine: use the method that finds key-sized rectangles
# Try adaptive threshold first (usually best for key detection)
# Clean up: close small gaps, remove noise
clean_kernel = np.ones((3, 3), np.uint8)
clean = cv2.morphologyEx(thresh_a, cv2.MORPH_CLOSE, clean_kernel)
clean = cv2.morphologyEx(clean, cv2.MORPH_OPEN, clean_kernel)

# Find contours
key_contours, hierarchy = cv2.findContours(clean, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

# Expected key size at 1080p from ~40cm: roughly 30-60px wide, 25-50px tall
expected_key_w = kw / 14  # ~14 keys across
expected_key_h = kh / 5   # ~5 rows
min_key_area = expected_key_w * expected_key_h * 0.2
max_key_area = expected_key_w * expected_key_h * 4.0

print(f"  Expected key size: ~{expected_key_w:.0f}x{expected_key_h:.0f}px")
print(f"  Area range: {min_key_area:.0f} - {max_key_area:.0f}")

key_rects = []
for cnt in key_contours:
    area = cv2.contourArea(cnt)
    if area < min_key_area or area > max_key_area:
        continue
    x, y, w, h = cv2.boundingRect(cnt)
    aspect = max(w, h) / (min(w, h) + 1)
    if aspect > 3.5:  # skip very elongated shapes
        continue
    cx = kx + x + w // 2
    cy = ky + y + h // 2
    key_rects.append({"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy, "area": area})

print(f"  Found {len(key_rects)} key candidates")

# If we didn't find enough, try the gradient method
if len(key_rects) < 20:
    print("  Trying gradient method...")
    clean_b = cv2.morphologyEx(thresh_b, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    inv_b = cv2.bitwise_not(clean_b)
    contours_b, _ = cv2.findContours(inv_b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours_b:
        area = cv2.contourArea(cnt)
        if area < min_key_area or area > max_key_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = max(w, h) / (min(w, h) + 1)
        if aspect > 3.5:
            continue
        cx = kx + x + w // 2
        cy = ky + y + h // 2
        # Avoid duplicates
        duplicate = False
        for kr in key_rects:
            if abs(kr["cx"] - cx) < 10 and abs(kr["cy"] - cy) < 10:
                duplicate = True
                break
        if not duplicate:
            key_rects.append({"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy, "area": area})
    print(f"  Total after gradient: {len(key_rects)} keys")

# Step 4: Sort into rows
print("\nStep 4: Organizing into rows...")
if not key_rects:
    print("  No keys detected! Falling back to grid template.")
    # Use a grid template based on keyboard bounds
    QWERTY = [
        list("`1234567890-="),
        list("qwertyuiop[]\\"),
        list("asdfghjkl;'"),
        list("zxcvbnm,./"),
    ]
    detected_keys = {}
    n_cols = 14
    n_rows = len(QWERTY)
    # QWERTY row stagger (fraction of key width)
    row_offsets = [0, 0.25, 0.5, 0.75]

    for r, row in enumerate(QWERTY):
        for c, key in enumerate(row):
            offset = row_offsets[r] * (kw / n_cols)
            px = int(kx + offset + (c + 0.5) / n_cols * kw)
            py = int(ky + (r + 0.5) / n_rows * kh)
            detected_keys[key] = {"pixel": (px, py), "row": r, "col": c, "source": "grid_template"}
    
    # Add special keys
    for name, r, c in [("space", 3.5, 5.5), ("enter", 1.5, 13), ("tab", 1, -0.3), ("esc", -0.3, -0.3)]:
        offset = row_offsets[min(int(r), 3)] * (kw / n_cols) if r >= 0 else 0
        px = int(kx + offset + (c + 0.5) / n_cols * kw)
        py = int(ky + (r + 0.5) / n_rows * kh)
        detected_keys[name] = {"pixel": (px, py), "source": "grid_template"}

    print(f"  Grid template: {len(detected_keys)} keys")

else:
    # Sort by Y
    key_rects.sort(key=lambda k: k["cy"])
    
    # Cluster into rows
    row_gap = expected_key_h * 0.6
    rows = []
    current_row = [key_rects[0]]
    for kr in key_rects[1:]:
        if abs(kr["cy"] - current_row[-1]["cy"]) < row_gap:
            current_row.append(kr)
        else:
            rows.append(sorted(current_row, key=lambda k: k["cx"]))
            current_row = [kr]
    rows.append(sorted(current_row, key=lambda k: k["cx"]))
    
    print(f"  {len(rows)} rows detected:")
    for i, row in enumerate(rows):
        print(f"    Row {i}: {len(row)} keys, Y~{row[0]['cy']}")
    
    # Match to QWERTY
    QWERTY = [
        list("`1234567890-="),
        list("qwertyuiop[]\\"),
        list("asdfghjkl;'"),
        list("zxcvbnm,./"),
    ]
    
    detected_keys = {}
    # Use main 4 rows (skip function keys if present)
    main_rows = rows[-4:] if len(rows) >= 4 else rows
    
    for row_idx, (det_row, qwerty_row) in enumerate(zip(main_rows, QWERTY)):
        n_det = len(det_row)
        n_q = len(qwerty_row)
        for ki, kr in enumerate(det_row):
            # Best-effort column mapping
            col_idx = min(int(round(ki * n_q / max(n_det, 1))), n_q - 1)
            key_name = qwerty_row[col_idx]
            detected_keys[key_name] = {
                "pixel": (kr["cx"], kr["cy"]),
                "bbox": (kr["x"] + kx, kr["y"] + ky, kr["w"], kr["h"]),
                "row": row_idx,
                "col": col_idx,
                "source": "detected",
            }

# Step 5: Visualize
print("\nStep 5: Drawing visualization...")
vis = frame.copy()
cv2.rectangle(vis, (kx, ky), (kx+kw, ky+kh), (0, 255, 0), 2)

for key_name, kdata in detected_keys.items():
    px, py = kdata["pixel"]
    cv2.circle(vis, (px, py), 5, (0, 0, 255), -1)
    cv2.putText(vis, key_name, (px + 6, py - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
    if "bbox" in kdata:
        bx, by, bw, bh = kdata["bbox"]
        cv2.rectangle(vis, (bx, by), (bx+bw, by+bh), (0, 255, 0), 1)

cv2.imwrite("temp/keys_detected_hires.jpg", vis)

# Save
output = {
    "camera_index": FRONT_CAM_IDX,
    "resolution": [frame.shape[1], frame.shape[0]],
    "keyboard_bounds_px": list(kbd_rect),
    "detected_keys": {k: v for k, v in detected_keys.items()},
    "num_keys": len(detected_keys),
}
with open("data/keyboard_vision_detected.json", "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDetected {len(detected_keys)} keys")
print(f"Saved to data/keyboard_vision_detected.json")
print(f"Visualization: temp/keys_detected_hires.jpg")
