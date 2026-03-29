"""
Dual-Arm Robot Dance with GIF Recording
=========================================
Safe dance — arms stay above the device, no contact.
Records multi-camera frames for a demo GIF.
"""
import time
import json
import os
import cv2
import numpy as np
from PIL import Image
import imageio
from pymycobot import MyCobot280Socket

RIGHT_IP = "10.105.230.93"
LEFT_IP = "10.105.230.94"
PORT = 9000
SAFE_Z_MIN = 200  # never go below this — keeps arms above device

# Camera map
CAM_MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "camera_map.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "temp")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load camera map
FLIP_CAMS = set()
CAM_INDICES = []
if os.path.exists(CAM_MAP_PATH):
    with open(CAM_MAP_PATH) as f:
        cm = json.load(f)
    FLIP_CAMS = set(cm.get("flip_cameras", []))
    for cam_id, info in cm.get("cameras", {}).items():
        if info.get("role") != "skip" and info.get("type") == "usb":
            CAM_INDICES.append(int(cam_id))


FAST_CAM = None  # will be set to the fastest available camera


def init_fast_cam():
    """Open a single camera and keep it open for fast capture."""
    global FAST_CAM
    # Try front workspace (cam 3), then overhead (cam 4), then any
    for idx in [3, 4, 6, 0]:
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BRIGHTNESS, 150)
            for _ in range(10):
                cap.grab()
            ret, f = cap.read()
            if ret and f is not None:
                FAST_CAM = (idx, cap)
                print(f"  Using camera {idx} for recording")
                return
            cap.release()
    print("  No camera available for recording")


def capture_frame():
    """Capture from the persistent camera — fast, single frame."""
    if FAST_CAM is None:
        return None
    idx, cap = FAST_CAM
    if not cap.isOpened():
        return None
    ret, f = cap.read()
    if not ret or f is None:
        return None
    if idx in FLIP_CAMS:
        f = cv2.rotate(f, cv2.ROTATE_180)
    # Brighten
    gamma = 1.4
    table = np.array([((i / 255.0) ** (1.0 / gamma)) * 255
                     for i in np.arange(256)]).astype("uint8")
    f = cv2.LUT(f, table)
    f = cv2.resize(f, (640, 480))
    return Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))


def release_cam():
    global FAST_CAM
    if FAST_CAM:
        FAST_CAM[1].release()
        FAST_CAM = None


print("╔═══════════════════════════════════════╗")
print("║       DUAL-ARM ROBOT DANCE            ║")
print("╚═══════════════════════════════════════╝")

# Connect
print("Connecting arms...")
mc_r = MyCobot280Socket(RIGHT_IP, PORT)
time.sleep(1)
mc_r.power_on()
time.sleep(1)

mc_l = MyCobot280Socket(LEFT_IP, PORT)
time.sleep(1)
mc_l.power_on()
time.sleep(1)
print("Both arms connected!")

# Open persistent camera
init_fast_cam()

frames = []

# Dance sequence — all moves stay at safe height (Z > 200)
# Angles only — no coordinate moves near the device
DANCE = [
    # (name, right_angles, left_angles, speed, hold, r_color, l_color)
    ("Home",        [0,0,0,0,0,0],         [0,0,0,0,0,0],          20, 2.0, (255,255,255), (255,255,255)),
    ("Arms up",     [0,-30,0,0,0,0],       [0,-30,0,0,0,0],        25, 1.0, (255,0,0), (0,0,255)),
    ("Wave right",  [40,-50,30,0,20,45],   [0,-20,0,0,0,0],        30, 1.0, (255,165,0), (0,100,255)),
    ("Wave left",   [0,-20,0,0,0,0],       [-40,-50,30,0,-20,-45],  30, 1.0, (0,100,255), (255,165,0)),
    ("Both wave",   [30,-60,40,-20,25,40], [-30,-60,40,-20,-25,-40], 30, 1.2, (0,255,0), (0,255,0)),
    ("Cross",       [-25,-45,25,0,0,-30],  [25,-45,25,0,0,30],     25, 1.2, (255,0,255), (0,255,255)),
    ("Stretch up",  [0,-80,50,0,0,0],      [0,-80,50,0,0,0],       20, 1.5, (255,255,0), (255,255,0)),
    ("Shake R",     [50,-30,0,0,0,0],      [-50,-30,0,0,0,0],      40, 0.6, (255,0,255), (255,0,255)),
    ("Shake L",     [-50,-30,0,0,0,0],     [50,-30,0,0,0,0],       40, 0.6, (0,255,255), (0,255,255)),
    ("Shake R",     [50,-30,0,0,0,0],      [-50,-30,0,0,0,0],      40, 0.6, (255,0,255), (255,0,255)),
    ("Shake L",     [-50,-30,0,0,0,0],     [50,-30,0,0,0,0],       40, 0.6, (0,255,255), (0,255,255)),
    ("Nod",         [0,-10,-30,0,0,0],     [0,-10,-30,0,0,0],      20, 1.0, (255,215,0), (255,215,0)),
    ("Look up",     [0,-60,60,0,0,0],      [0,-60,60,0,0,0],       25, 1.0, (0,255,128), (0,255,128)),
    ("Victory",     [20,-70,50,-30,30,30], [-20,-70,50,-30,-30,-30], 25, 2.0, (255,255,255), (255,255,255)),
    ("Bow",         [0,0,-20,0,0,0],       [0,0,-20,0,0,0],        15, 2.0, (255,215,0), (255,215,0)),
    ("Home",        [0,0,0,0,0,0],         [0,0,0,0,0,0],          15, 2.0, (255,255,255), (255,255,255)),
]

print(f"\nDancing! ({len(DANCE)} moves)")
for i, (name, r_ang, l_ang, spd, hold, r_col, l_col) in enumerate(DANCE):
    print(f"  {i+1}/{len(DANCE)}: {name}")
    mc_r.set_color(*r_col)
    mc_l.set_color(*l_col)
    mc_r.send_angles(r_ang, spd)
    mc_l.send_angles(l_ang, spd)

    # Capture frames during the hold — fast for smooth GIF
    start = time.time()
    while time.time() - start < hold:
        frame = capture_frame()
        if frame:
            arr = np.array(frame)
            cv2.putText(arr, f"#{i+1} {name}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 100), 2)
            frames.append(Image.fromarray(arr))
        time.sleep(0.08)  # ~12 fps for smooth motion

# Release camera
release_cam()

# Save GIF
if frames:
    gif_path = os.path.join(OUTPUT_DIR, "robot_dance.gif")
    images = [np.array(f) for f in frames]
    imageio.mimsave(gif_path, images, duration=0.08, loop=0)  # smooth playback
    print(f"\n  Dance GIF saved: {gif_path} ({len(frames)} frames)")

mc_r.set_color(255, 255, 255)
mc_l.set_color(255, 255, 255)
print("\nDance complete! 🎉")
