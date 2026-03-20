"""
Detect individual keyboard keys from front webcam (cam 4).
The keyboard has gray key caps on a silver body — detect by color segmentation.
"""
import cv2
import numpy as np
import json
import os

os.makedirs("temp", exist_ok=True)

print("=" * 60)
print("  KEY DETECTION (color segmentation)")
print("=" * 60)

# Capture
cap = cv2.VideoCapture(4, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
for _ in range(10):
    cap.read()
ret, frame = cap.read()
cap.release()
cv2.imwrite("temp/front_raw.jpg", frame)
h, w = frame.shape[:2]
print(f"Captured: {w}x{h}")

gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

# Step 1: The keyboard keys are DARKER gray than the silver laptop body
# Keys are roughly 120-180 brightness, body is 190-230
# Find pixels in the "key cap" brightness range

# Blur to reduce noise
blurred = cv2.GaussianBlur(gray, (5, 5), 0)

# Key caps: darker than the body but not as dark as the screen/bezels
# Threshold to isolate key-colored pixels
key_mask = cv2.inRange(blurred, 100, 185)

# Clean up
kernel = np.ones((3, 3), np.uint8)
key_mask = cv2.morphologyEx(key_mask, cv2.MORPH_CLOSE, kernel)
key_mask = cv2.morphologyEx(key_mask, cv2.MORPH_OPEN, kernel)
cv2.imwrite("temp/key_color_mask.jpg", key_mask)

# Step 2: Find contours of key-shaped blobs
contours, _ = cv2.findContours(key_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Filter for key-sized rectangles
# At 1080p from ~40cm, a standard key is roughly 40-70px wide and 30-55px tall
all_rects = []
for cnt in contours:
    area = cv2.contourArea(cnt)
    if area < 500 or area > 15000:
        continue
    x, y, rw, rh = cv2.boundingRect(cnt)
    aspect = max(rw, rh) / (min(rw, rh) + 1)
    if aspect > 4:  # skip too elongated (spacebar will be handled separately)
        # Might be spacebar
        if area > 5000 and rw > 150:
            all_rects.append({"x": x, "y": y, "w": rw, "h": rh, 
                             "cx": x + rw//2, "cy": y + rh//2, "area": area, "type": "wide"})
        continue
    all_rects.append({"x": x, "y": y, "w": rw, "h": rh,
                      "cx": x + rw//2, "cy": y + rh//2, "area": area, "type": "key"})

print(f"Found {len(all_rects)} key-shaped blobs")

# Step 3: Sort into rows by Y coordinate
all_rects.sort(key=lambda r: r["cy"])

# Cluster into rows (keys within ~25px Y are same row)
rows = []
if all_rects:
    current_row = [all_rects[0]]
    for r in all_rects[1:]:
        if abs(r["cy"] - current_row[-1]["cy"]) < 25:
            current_row.append(r)
        else:
            rows.append(sorted(current_row, key=lambda r: r["cx"]))
            current_row = [r]
    rows.append(sorted(current_row, key=lambda r: r["cx"]))

print(f"Organized into {len(rows)} rows:")
for i, row in enumerate(rows):
    print(f"  Row {i}: {len(row)} keys, Y~{row[0]['cy']}, widths: {[r['w'] for r in row[:5]]}...")

# Step 4: Match to QWERTY layout
# Standard keyboard rows (what we expect to see):
KEYBOARD_ROWS = [
    # row 0: function keys (small)
    ["esc"] + [f"f{i}" for i in range(1, 13)] + ["del"],
    # row 1: number row
    list("`1234567890-=") + ["backspace"],
    # row 2: QWERTY
    ["tab"] + list("qwertyuiop[]\\"),
    # row 3: home row
    ["caps"] + list("asdfghjkl;'") + ["enter"],
    # row 4: bottom row
    ["shift_l"] + list("zxcvbnm,./") + ["shift_r"],
    # row 5: modifier row
    ["ctrl", "fn", "win", "alt", "space", "alt_r", "copilot", "left", "up", "down", "right"],
]

detected_keys = {}
vis = frame.copy()

# Match detected rows to keyboard rows
# Skip very small rows (< 5 keys) unless they're the function row
main_rows = [r for r in rows if len(r) >= 3]
print(f"\nMain rows (>= 3 keys): {len(main_rows)}")

# Try to identify rows by key count and position
for ri, det_row in enumerate(main_rows):
    # Best match: find the KEYBOARD_ROW with closest key count
    if ri < len(KEYBOARD_ROWS):
        template_row = KEYBOARD_ROWS[ri]
    else:
        continue
    
    n_det = len(det_row)
    n_tmpl = len(template_row)
    
    for ki, kr in enumerate(det_row):
        # Map detected key index to template
        tmpl_idx = min(int(round(ki * n_tmpl / max(n_det, 1))), n_tmpl - 1)
        key_name = template_row[tmpl_idx]
        
        detected_keys[key_name] = {
            "pixel": [kr["cx"], kr["cy"]],
            "bbox": [kr["x"], kr["y"], kr["w"], kr["h"]],
            "row": ri,
            "det_col": ki,
            "source": "vision_detected",
        }
        
        # Draw
        cv2.rectangle(vis, (kr["x"], kr["y"]), (kr["x"]+kr["w"], kr["y"]+kr["h"]), (0, 255, 0), 2)
        cv2.circle(vis, (kr["cx"], kr["cy"]), 4, (0, 0, 255), -1)
        # Label
        label = key_name if len(key_name) <= 3 else key_name[:3]
        cv2.putText(vis, label, (kr["cx"]-10, kr["cy"]-10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)

cv2.imwrite("temp/keys_annotated.jpg", vis)

# Also draw just the key map overlay on a clean background
key_map = np.zeros((h, w, 3), dtype=np.uint8)
for key_name, kdata in detected_keys.items():
    bx, by, bw, bh = kdata["bbox"]
    cv2.rectangle(key_map, (bx, by), (bx+bw, by+bh), (0, 255, 0), 2)
    cv2.putText(key_map, key_name, (bx+3, by+bh-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
cv2.imwrite("temp/key_map_overlay.jpg", key_map)

# Save
output = {
    "camera_index": 4,
    "resolution": [w, h],
    "detected_keys": detected_keys,
    "num_keys": len(detected_keys),
    "num_rows": len(main_rows),
    "keys_per_row": [len(r) for r in main_rows],
}
with open("data/keyboard_vision_detected.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\n{'='*60}")
print(f"  DETECTED {len(detected_keys)} KEYS")
print(f"{'='*60}")
for ri, det_row in enumerate(main_rows):
    row_keys = [k for k, v in detected_keys.items() if v["row"] == ri]
    print(f"  Row {ri} ({len(det_row)} keys): {' '.join(row_keys)}")

print(f"\nVisualization: temp/keys_annotated.jpg")
print(f"Key map: temp/key_map_overlay.jpg")
