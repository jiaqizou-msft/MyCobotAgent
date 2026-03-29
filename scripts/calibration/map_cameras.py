"""
Camera Discovery & Assignment Tool
====================================
Detects all available cameras, captures a frame from each,
displays them in a window, and lets the user assign roles.

Roles:
  - front_workspace: Front view of desk/workspace (for demo GIF)
  - overhead:        Top-down view (RealSense or similar)
  - side_view:       Side angle showing DUT screen + keyboard
  - close_up:        Close-up of keyboard (Pi network camera)
  - skip:            Don't use this camera (e.g. built-in webcam)

Saves camera mapping to data/camera_map.json

Usage:
  python scripts/calibration/map_cameras.py          # interactive UI
  python scripts/calibration/map_cameras.py --auto    # auto-detect only, no UI
"""

import cv2
import json
import os
import sys
import time
import httpx
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
MAP_PATH = os.path.join(DATA_DIR, "camera_map.json")
PI_CAM_URL = "http://10.105.230.93:8080/snapshot"

ROLES = ["front_workspace", "overhead", "side_view", "skip"]
ROLE_COLORS = {
    "front_workspace": (0, 255, 0),
    "overhead": (255, 165, 0),
    "side_view": (0, 165, 255),
    "close_up": (255, 0, 255),
    "skip": (100, 100, 100),
    "unassigned": (200, 200, 200),
}


def detect_all_cameras(max_index=6):
    """Detect all working USB cameras. Returns list of (index, frame)."""
    cameras = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if cap.isOpened():
            # Warm up
            for _ in range(5):
                cap.grab()
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                cameras.append({"index": idx, "frame": frame, "type": "usb",
                                "resolution": f"{frame.shape[1]}x{frame.shape[0]}"})
                print(f"  USB Camera {idx}: {frame.shape[1]}x{frame.shape[0]} OK")
            else:
                print(f"  USB Camera {idx}: opens but no frames — SKIPPED")
        # else: not available
    return cameras


def detect_pi_camera():
    """Check Pi network camera."""
    try:
        r = httpx.get(PI_CAM_URL, timeout=5)
        if r.status_code == 200:
            arr = np.frombuffer(r.content, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                print(f"  Pi camera: {frame.shape[1]}x{frame.shape[0]} OK")
                return {"index": "pi", "frame": frame, "type": "network",
                        "url": PI_CAM_URL,
                        "resolution": f"{frame.shape[1]}x{frame.shape[0]}"}
    except Exception as e:
        print(f"  Pi camera: unavailable ({e})")
    return None


def build_mosaic(cameras, assignments, selected_idx=None):
    """Build a tiled mosaic of all camera views with labels."""
    if not cameras:
        return np.zeros((480, 640, 3), dtype=np.uint8)

    TILE_W, TILE_H = 400, 300
    cols = min(3, len(cameras))
    rows = (len(cameras) + cols - 1) // cols
    canvas = np.zeros((rows * TILE_H + 60, cols * TILE_W, 3), dtype=np.uint8)

    # Title
    cv2.putText(canvas, "Camera Assignment — Press 1-4 to assign role, click camera to select",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.putText(canvas, "1=front_workspace  2=overhead  3=side_view  4=skip  S=save  Q=quit",
                (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    for i, cam in enumerate(cameras):
        r_idx = i // cols
        c_idx = i % cols
        x0 = c_idx * TILE_W
        y0 = r_idx * TILE_H + 60

        # Resize frame to tile
        frame = cam["frame"]
        tile = cv2.resize(frame, (TILE_W - 4, TILE_H - 30))

        # Place in canvas
        canvas[y0 + 25:y0 + 25 + tile.shape[0], x0 + 2:x0 + 2 + tile.shape[1]] = tile

        # Label
        cam_id = f"USB {cam['index']}" if cam["type"] == "usb" else "Pi Cam"
        role = assignments.get(str(cam["index"]), "unassigned")
        color = ROLE_COLORS.get(role, (200, 200, 200))

        # Highlight selected
        if i == selected_idx:
            cv2.rectangle(canvas, (x0, y0), (x0 + TILE_W - 1, y0 + TILE_H - 1), (0, 255, 255), 3)

        cv2.putText(canvas, f"{cam_id} [{cam['resolution']}]", (x0 + 5, y0 + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(canvas, f"Role: {role}", (x0 + 5, y0 + TILE_H - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Border
        cv2.rectangle(canvas, (x0, y0), (x0 + TILE_W - 1, y0 + TILE_H - 1), color, 1)

    return canvas


def save_mapping(cameras, assignments):
    """Save camera mapping to JSON."""
    mapping = {
        "cameras": {},
        "roles": {},
        "pi_camera": PI_CAM_URL,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    for cam in cameras:
        cam_id = str(cam["index"])
        role = assignments.get(cam_id, "skip")
        mapping["cameras"][cam_id] = {
            "type": cam["type"],
            "role": role,
            "resolution": cam["resolution"],
        }
        if cam["type"] == "network":
            mapping["cameras"][cam_id]["url"] = cam.get("url", PI_CAM_URL)
        if role != "skip" and role != "unassigned":
            mapping["roles"][role] = cam_id

    # Pi camera always gets close_up role
    mapping["roles"]["close_up"] = "pi"

    with open(MAP_PATH, "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"\nSaved camera mapping to {MAP_PATH}")
    print(f"Roles: {json.dumps(mapping['roles'], indent=2)}")
    return mapping


def interactive_ui(cameras):
    """Show camera mosaic and let user assign roles interactively."""
    assignments = {}

    # Load existing assignments if available
    if os.path.exists(MAP_PATH):
        with open(MAP_PATH) as f:
            existing = json.load(f)
        for cam_id, info in existing.get("cameras", {}).items():
            assignments[cam_id] = info.get("role", "unassigned")

    selected = 0  # currently selected camera index

    TILE_W, TILE_H = 400, 300
    cols = min(3, len(cameras))

    cv2.namedWindow("Camera Assignment", cv2.WINDOW_NORMAL)

    def on_mouse(event, mx, my, flags, param):
        nonlocal selected
        if event == cv2.EVENT_LBUTTONDOWN:
            # Figure out which tile was clicked
            col = mx // TILE_W
            row = (my - 60) // TILE_H
            if row >= 0:
                idx = row * cols + col
                if 0 <= idx < len(cameras):
                    selected = idx

    cv2.setMouseCallback("Camera Assignment", on_mouse)

    while True:
        mosaic = build_mosaic(cameras, assignments, selected)
        cv2.imshow("Camera Assignment", mosaic)

        key = cv2.waitKey(100) & 0xFF

        if key == ord("q") or key == 27:  # Q or Esc
            break
        elif key == ord("s"):  # Save
            save_mapping(cameras, assignments)
            break
        elif key == ord("1"):
            cam_id = str(cameras[selected]["index"])
            assignments[cam_id] = "front_workspace"
        elif key == ord("2"):
            cam_id = str(cameras[selected]["index"])
            assignments[cam_id] = "overhead"
        elif key == ord("3"):
            cam_id = str(cameras[selected]["index"])
            assignments[cam_id] = "side_view"
        elif key == ord("4"):
            cam_id = str(cameras[selected]["index"])
            assignments[cam_id] = "skip"

    cv2.destroyAllWindows()
    return assignments


def auto_assign(cameras):
    """Auto-assign based on known camera indices from previous detection."""
    assignments = {}
    for cam in cameras:
        idx = cam["index"]
        if idx == "pi":
            assignments["pi"] = "close_up"
        elif idx == 0:
            assignments["0"] = "front_workspace"
        elif idx == 1:
            assignments["1"] = "skip"  # built-in webcam (face)
        elif idx == 2:
            assignments["2"] = "overhead"
        elif idx == 4:
            assignments["4"] = "side_view"
        else:
            assignments[str(idx)] = "skip"
    return assignments


def main():
    auto_mode = "--auto" in sys.argv

    print("=" * 50)
    print("  CAMERA DISCOVERY & ASSIGNMENT")
    print("=" * 50)
    print()

    # Detect cameras
    print("Detecting USB cameras...")
    cameras = detect_all_cameras()

    print("\nDetecting network cameras...")
    pi = detect_pi_camera()
    if pi:
        cameras.append(pi)

    print(f"\nFound {len(cameras)} working cameras")

    if not cameras:
        print("No cameras found!")
        return

    if auto_mode:
        assignments = auto_assign(cameras)
        save_mapping(cameras, assignments)
    else:
        # Try to open UI
        try:
            assignments = interactive_ui(cameras)
            if assignments:
                save_mapping(cameras, assignments)
        except Exception as e:
            print(f"UI failed ({e}), falling back to auto-assign...")
            assignments = auto_assign(cameras)
            save_mapping(cameras, assignments)


if __name__ == "__main__":
    main()
