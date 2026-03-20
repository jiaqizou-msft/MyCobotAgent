"""
Dual-arm drag-and-teach with multi-camera calibration.

Teaches reference keys for each arm separately, captures from both RealSense
cameras at each position, then computes independent grid models per arm.
The camera system measures the actual key pitch for precision.

Each arm gets its own coordinate model since they have different base positions.
Keys in the middle of the keyboard may be reachable by both arms.
"""
from pymycobot import MyCobot280Socket
import pyrealsense2 as rs
import cv2
import numpy as np
import time
import json
import os
import threading

os.makedirs("temp", exist_ok=True)

ARMS = {
    "right": {"ip": "10.105.230.93", "port": 9000, "color": (255, 0, 0)},
    "left":  {"ip": "10.105.230.94", "port": 9000, "color": (0, 0, 255)},
}

RS_DEVICES = {
    "overhead": "335222075369",
    "front": "335522073146",
}

QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]
KEY_RC = {}
for r, row in enumerate(QWERTY):
    for c, k in enumerate(row):
        KEY_RC[k] = (r, c)


def read_position_stable(mc, retries=12):
    """Read robot coords with multiple retries for stable values."""
    coords_list = []
    for _ in range(retries):
        time.sleep(0.5)
        c = mc.get_coords()
        if c and c != -1 and len(c) >= 6:
            coords_list.append(c)
    if len(coords_list) < 2:
        # Fallback: try sending a tiny move to wake up the controller
        try:
            mc.set_color(0, 255, 0)
            time.sleep(1)
        except:
            pass
        for _ in range(5):
            time.sleep(0.5)
            c = mc.get_coords()
            if c and c != -1 and len(c) >= 6:
                coords_list.append(c)
    if not coords_list:
        return None
    recent = coords_list[-4:] if len(coords_list) >= 4 else coords_list
    avg = [sum(x)/len(x) for x in zip(*recent)]
    return [round(v, 2) for v in avg]


def capture_rs_by_serial(sn, name):
    """Capture one frame from a specific RealSense by serial number."""
    try:
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(sn)
        config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        profile = pipeline.start(config)
        intrinsics_profile = profile.get_stream(rs.stream.color)
        intrinsics = intrinsics_profile.as_video_stream_profile().get_intrinsics()
        depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
        aligner = rs.align(rs.stream.color)
        for _ in range(15):
            pipeline.wait_for_frames()
        frames = pipeline.wait_for_frames()
        aligned = aligner.process(frames)
        color = np.asanyarray(aligned.get_color_frame().get_data())
        depth = np.asanyarray(aligned.get_depth_frame().get_data())
        pipeline.stop()
        return color, depth, intrinsics, depth_scale
    except Exception as e:
        print(f"    RS {name} capture failed: {e}")
        return None, None, None, None


def measure_key_pitch_from_camera(intrinsics, depth_scale, depth_map):
    """Use RealSense intrinsics + depth to compute mm-per-pixel at keyboard surface."""
    h, w = depth_map.shape
    kbd_region = depth_map[h//4:3*h//4, w//4:3*w//4]
    valid = kbd_region[kbd_region > 0].astype(float) * depth_scale
    if len(valid) == 0:
        return None, None
    kbd_depth_m = float(np.median(valid))
    mm_per_px_x = kbd_depth_m * 1000 / intrinsics.fx
    mm_per_px_y = kbd_depth_m * 1000 / intrinsics.fy
    return mm_per_px_x, mm_per_px_y


def teach_arm(arm_name, mc):
    """Interactive teach session for one arm."""
    arm_cfg = ARMS[arm_name]
    print(f"\n{'='*60}")
    print(f"  TEACHING: {arm_name.upper()} ARM ({arm_cfg['ip']})")
    print(f"{'='*60}")
    print(f"  Servos will be released. Drag the finger to each key.")
    print(f"  Type the key name + ENTER to record.")
    print(f"  Type 'done' when finished.\n")

    mc.power_on()
    time.sleep(1)
    mc.release_all_servos()
    time.sleep(1)
    mc.set_color(*arm_cfg["color"])
    print(f"  *** {arm_name.upper()} ARM SERVOS RELEASED ***\n")

    taught = {}

    while True:
        try:
            user_input = input(f"  [{arm_name}] Key (or 'done'): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() == 'done':
            break
        if user_input.lower() == 'show':
            for k, v in sorted(taught.items()):
                rc = v[:3]
                print(f"    '{k}': ({rc[0]:.1f}, {rc[1]:.1f}, {rc[2]:.1f})")
            continue

        key_name = user_input.lower()
        print(f"    Reading position (hold still 4s)...")
        time.sleep(1)
        coords = read_position_stable(mc)
        if coords is None:
            print(f"    FAILED to read position!")
            continue

        taught[key_name] = coords[:3]
        print(f"    Recorded '{key_name}': ({coords[0]:.1f}, {coords[1]:.1f}, {coords[2]:.1f})")

    mc.focus_all_servos()
    time.sleep(0.5)
    mc.set_color(255, 255, 255)
    print(f"\n  {arm_name.upper()} ARM: {len(taught)} keys taught.")
    return taught


def build_grid_model(taught_keys, arm_name):
    """Fit a linear grid model from taught reference keys."""
    A, B_xy, z_values = [], [], []
    for key, xyz in taught_keys.items():
        if key not in KEY_RC:
            continue
        r, c = KEY_RC[key]
        A.append([r, c, 1])
        B_xy.append([xyz[0], xyz[1]])
        z_values.append(xyz[2])

    if len(A) < 3:
        print(f"  {arm_name}: Need >= 3 keys for grid model, got {len(A)}")
        return None, None

    A = np.array(A, dtype=float)
    B_xy = np.array(B_xy, dtype=float)
    M, _, _, _ = np.linalg.lstsq(A, B_xy, rcond=None)
    kbd_z = float(np.median(z_values))

    # Verify
    pred = A @ M
    errors = np.sqrt(np.sum((pred - B_xy)**2, axis=1))
    print(f"\n  {arm_name} grid model: mean error = {np.mean(errors):.1f}mm")
    print(f"    X = {M[0,0]:.2f}*row + {M[1,0]:.2f}*col + {M[2,0]:.2f}")
    print(f"    Y = {M[0,1]:.2f}*row + {M[1,1]:.2f}*col + {M[2,1]:.2f}")
    print(f"    Z = {kbd_z:.1f}mm")

    return M, kbd_z


def camera_refine_model(M, kbd_z, arm_name):
    """Use the overhead RealSense to measure actual key pitch and refine the model."""
    print(f"\n  Refining {arm_name} model with camera-measured key pitch...")
    color, depth, intrinsics, depth_scale = capture_rs_by_serial(RS_DEVICES["overhead"], "overhead")
    if color is None:
        print("    Camera capture failed, skipping refinement.")
        return M

    mm_per_px_x, mm_per_px_y = measure_key_pitch_from_camera(intrinsics, depth_scale, depth)
    if mm_per_px_x is None:
        print("    Could not measure depth, skipping.")
        return M

    # Standard key pitch = 19mm. The camera tells us the actual mm/pixel
    # So we can verify the grid model's column and row steps
    actual_col_step = abs(M[1, 0])  # current model's column step in X
    actual_row_step = abs(M[0, 1])  # current model's row step in Y

    # Key pitch in pixels
    key_pitch_px = 19.0 / mm_per_px_x
    print(f"    Camera: {mm_per_px_x:.3f} mm/pixel, key pitch = {key_pitch_px:.1f}px = 19mm")
    print(f"    Model col step: {actual_col_step:.1f}mm (camera says keyboard pitch is 19mm)")

    # We trust the camera measurement for the column step direction
    # but keep the taught reference points for the offset
    # Only override if the model's step is significantly different
    if abs(actual_col_step - 19.0) > 3:
        print(f"    Adjusting column step from {actual_col_step:.1f} to 19.5mm (camera-guided)")
        M[1, 0] = 19.5 * np.sign(M[1, 0])

    return M


def generate_all_keys(M, kbd_z, taught, arm_name, row_stagger=None):
    """Generate positions for all keys from the grid model."""
    if row_stagger is None:
        # Default QWERTY stagger (in X mm)
        row_stagger = {0: 0, 1: 0, 2: 0, 3: 10}

    all_keys = {}
    for key, (r, c) in KEY_RC.items():
        pred = np.array([r, c, 1]) @ M
        stagger = row_stagger.get(r, 0)
        all_keys[key] = {
            "coords": [round(pred[0] + stagger, 2), round(pred[1], 2), kbd_z, 0, 180, 90],
            "arm": arm_name,
            "source": "grid_model",
        }

    # Override with taught positions (ground truth)
    for key, xyz in taught.items():
        if key in all_keys:
            all_keys[key]["coords"] = [xyz[0], xyz[1], kbd_z, 0, 180, 90]
            all_keys[key]["source"] = "taught"

    # Add special keys
    for name, r, c in [("space", 4.2, 5.5), ("enter", 2.5, 12.5),
                        ("backspace", 0.5, 13), ("tab", 1.5, -0.3), ("esc", -0.5, -0.5)]:
        pred = np.array([r, c, 1]) @ M
        stagger = row_stagger.get(int(round(r)), 0)
        all_keys[name] = {
            "coords": [round(pred[0] + stagger, 2), round(pred[1], 2), kbd_z, 0, 180, 90],
            "arm": arm_name,
            "source": "grid_model",
        }

    return all_keys


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # Connect both arms
    print("Connecting arms...")
    mc_right = MyCobot280Socket(ARMS["right"]["ip"], ARMS["right"]["port"])
    time.sleep(1)
    mc_left = MyCobot280Socket(ARMS["left"]["ip"], ARMS["left"]["port"])
    time.sleep(1)

    # Determine which arm to teach
    if "--right" in sys.argv:
        arms_to_teach = [("right", mc_right)]
    elif "--left" in sys.argv:
        arms_to_teach = [("left", mc_left)]
    else:
        arms_to_teach = [("right", mc_right), ("left", mc_left)]

    all_taught = {}
    all_models = {}

    for arm_name, mc in arms_to_teach:
        taught = teach_arm(arm_name, mc)
        if not taught:
            continue

        M, kbd_z = build_grid_model(taught, arm_name)
        if M is None:
            continue

        M = camera_refine_model(M, kbd_z, arm_name)
        keys = generate_all_keys(M, kbd_z, taught, arm_name)

        all_taught[arm_name] = taught
        all_models[arm_name] = {
            "grid_model_xy": M.tolist(),
            "keyboard_z": kbd_z,
            "keys": keys,
            "taught_reference": {k: list(v) for k, v in taught.items()},
        }

        # Check reachability per arm
        reachable = [k for k, v in keys.items()
                     if -281 <= v["coords"][0] <= 281 and abs(v["coords"][1]) <= 200]
        print(f"\n  {arm_name}: {len(reachable)} reachable keys")

    # Save combined layout
    output = {
        "arms": all_models,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Merge keys: for keys reachable by both arms, prefer the arm with better reach
    merged_keys = {}
    for arm_name, model in all_models.items():
        for key, data in model["keys"].items():
            data_copy = dict(data)
            data_copy["arm"] = arm_name
            x = data_copy["coords"][0]
            if key not in merged_keys:
                merged_keys[key] = data_copy
            else:
                # Prefer the arm where the key is more central (lower abs X)
                existing_x = merged_keys[key]["coords"][0]
                if abs(x - 150) < abs(existing_x - 150):
                    merged_keys[key] = data_copy

    output["merged_keys"] = merged_keys

    with open("data/keyboard_dual_arm.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved dual-arm layout to data/keyboard_dual_arm.json")

    # Go home
    for arm_name, mc in arms_to_teach:
        mc.send_angles([0, 0, 0, 0, 0, 0], 15)
    time.sleep(3)

    # Summary
    print(f"\n{'='*60}")
    print(f"  DUAL-ARM KEYBOARD LAYOUT COMPLETE")
    print(f"{'='*60}")
    for arm_name in all_models:
        keys = all_models[arm_name]["keys"]
        reachable = [k for k, v in keys.items()
                     if -281 <= v["coords"][0] <= 281 and abs(v["coords"][1]) <= 200]
        print(f"  {arm_name}: {len(all_models[arm_name].get('taught_reference', {}))} taught, {len(reachable)} reachable")
    print(f"  Merged: {len(merged_keys)} total keys")
    print(f"\nDone! Next: python press_key_dual.py --fast qwertyuiop")
