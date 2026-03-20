"""Record demo with correct 3 camera views: overhead RS (flipped), front RS, overhead webcam."""
import pyrealsense2 as rs
import cv2
import numpy as np
import time
import threading
import json
import os
from pymycobot import MyCobot280Socket
from PIL import Image

os.makedirs("temp", exist_ok=True)

RS_OVERHEAD = "335222075369"
RS_FRONT = "335522073146"
WEBCAM_OVERHEAD_IDX = 2  # overhead webcam on laptop USB

overhead_frames, front_frames, webcam_frames = [], [], []
recording = False

def record_rs(sn, store, flip=False):
    global recording
    p = rs.pipeline(); c = rs.config(); c.enable_device(sn)
    c.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    p.start(c)
    for _ in range(15): p.wait_for_frames()
    while recording:
        try:
            f = np.asanyarray(p.wait_for_frames().get_color_frame().get_data()).copy()
            if flip:
                f = cv2.rotate(f, cv2.ROTATE_180)
            store.append(f)
        except: pass
        time.sleep(0.1)
    p.stop()

def record_webcam(idx, store):
    global recording
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened(): return
    while recording:
        ret, f = cap.read()
        if ret: store.append(f.copy())
        time.sleep(0.1)
    cap.release()

def wait_done(mc, timeout=2.0, min_wait=0.15):
    time.sleep(min_wait)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if mc.is_moving() == 0: return
        except: pass
        time.sleep(0.05)

print("=" * 55)
print("  DUAL-ARM DEMO: SAD Enter Z Backspace BYE")
print("=" * 55)

with open("data/keyboard_dual_arm.json") as f:
    layout = json.load(f)
merged = layout["merged_keys"]

mc_right = MyCobot280Socket("10.105.230.93", 9000)
time.sleep(1)
mc_left = MyCobot280Socket("10.105.230.94", 9000)
time.sleep(1)
arm_mc = {"right": mc_right, "left": mc_left}

mc_right.send_angles([0, 0, 0, 0, 0, 0], 15)
mc_left.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(4)

print("Recording (OH flipped + Front RS + Overhead webcam)...")
recording = True
threads = [
    threading.Thread(target=record_rs, args=(RS_OVERHEAD, overhead_frames, True), daemon=True),
    threading.Thread(target=record_rs, args=(RS_FRONT, front_frames, False), daemon=True),
    threading.Thread(target=record_webcam, args=(WEBCAM_OVERHEAD_IDX, webcam_frames), daemon=True),
]
for t in threads: t.start()
time.sleep(1)

KEYS = ["s", "a", "d", "enter", "z", "backspace", "b", "y", "e"]
HOVER_OFFSET = 15
PRESS_OFFSET = 3
current_arm = None

for key in KEYS:
    if key not in merged:
        print(f"  '{key}' not mapped, skip")
        continue
    data = merged[key]
    robot = data.get("robot", data.get("coords", [0,0,0]))[:3]
    x, y, z = robot
    arm = data["arm"]
    mc = arm_mc[arm]

    if not (-281 <= x <= 281):
        print(f"  '{key}' out of reach, skip")
        continue

    hover_z = z + HOVER_OFFSET
    press_z = z - PRESS_OFFSET

    if current_arm and current_arm != arm:
        # Just retract current arm to hover instead of going home
        arm_mc[current_arm].send_coords([200, 0, 200, 0, 180, 90], 25, 0)
        time.sleep(1)

    mc.set_color(255, 100, 0)
    if current_arm != arm:
        mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
        wait_done(mc, timeout=3, min_wait=0.5)
    else:
        mc.send_coords([x, y, hover_z, 0, 180, 90], 30, 0)
        wait_done(mc, timeout=2, min_wait=0.2)

    mc.send_coords([x, y, press_z, 0, 180, 90], 20, 0)
    wait_done(mc, timeout=2, min_wait=0.4)
    time.sleep(0.1)
    mc.send_coords([x, y, hover_z, 0, 180, 90], 20, 0)
    wait_done(mc, timeout=2, min_wait=0.3)
    current_arm = arm
    print(f"  [{arm[0].upper()}] '{key}'")

# Touchpad (try right arm)
print("  Touchpad swipe (right arm)...")
right_data = layout["arms"].get("right", {})
if right_data and "affine" in right_data:
    with open("data/keyboard_vision_detected.json") as f:
        anno = json.load(f)
    tp = anno.get("touchpad")
    if tp:
        M = np.array(right_data["affine"])
        kbd_z = right_data["kbd_z"]
        tp_px = tp["pixel"]
        tp_robot = np.array([tp_px[0], tp_px[1], 1]) @ M
        tp_x, tp_y = float(tp_robot[0]), float(tp_robot[1])
        tp_z = kbd_z
        if -281 <= tp_x <= 281:
            if current_arm != "right":
                arm_mc[current_arm].send_angles([0, 0, 0, 0, 0, 0], 20)
                time.sleep(2)
            mc_right.set_color(0, 255, 255)
            mc_right.send_coords([tp_x, tp_y - 15, tp_z + 15, 0, 180, 90], 15, 0)
            time.sleep(3)
            mc_right.send_coords([tp_x, tp_y - 15, tp_z - 2, 0, 180, 90], 10, 0)
            time.sleep(1)
            mc_right.send_coords([tp_x, tp_y + 15, tp_z - 2, 0, 180, 90], 10, 0)
            time.sleep(2)
            mc_right.send_coords([tp_x, tp_y + 15, tp_z + 15, 0, 180, 90], 10, 0)
            time.sleep(1)
            print(f"  [R] touchpad swipe at ({tp_x:.0f},{tp_y:.0f})")
        else:
            print(f"  Touchpad out of reach ({tp_x:.0f})")

mc_right.send_angles([0, 0, 0, 0, 0, 0], 15)
mc_left.send_angles([0, 0, 0, 0, 0, 0], 15)
time.sleep(3)
mc_right.set_color(255, 255, 255)
mc_left.set_color(255, 255, 255)

time.sleep(1)
recording = False
for t in threads: t.join(timeout=3)

print(f"\nCaptured: OH={len(overhead_frames)}, FR={len(front_frames)}, WC={len(webcam_frames)}")

# Build 3-panel GIF
n = min(len(overhead_frames), len(front_frames)) if front_frames else len(overhead_frames)
n = min(n, len(webcam_frames)) if webcam_frames else n
cell_h = 240
combined = []
for i in range(0, n, 3):
    panels = []
    for frames, label in [(overhead_frames, "Overhead (RS)"), (front_frames, "Front (RS)"), (webcam_frames, "Overview (WC)")]:
        if not frames: continue
        f = cv2.resize(frames[min(i, len(frames)-1)], (320, cell_h))
        cv2.putText(f, label, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        panels.append(f)
    if panels:
        combined.append(cv2.cvtColor(np.hstack(panels), cv2.COLOR_BGR2RGB))

pil = [Image.fromarray(f).quantize(colors=64) for f in combined]
gif_path = "demo_dual_arm_keys.gif"
pil[0].save(gif_path, save_all=True, append_images=pil[1:], duration=200, loop=0, optimize=True)
sz = os.path.getsize(gif_path) // 1024
print(f"GIF: {gif_path} ({len(pil)} frames, {sz}KB)")
if sz > 5000:
    pil2 = pil[::2]
    pil2[0].save(gif_path, save_all=True, append_images=pil2[1:], duration=300, loop=0, optimize=True)
    sz = os.path.getsize(gif_path) // 1024
    print(f"Compressed: {sz}KB")

print("Done!")
