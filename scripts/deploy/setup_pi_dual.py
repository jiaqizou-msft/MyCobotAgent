"""Install pyrealsense2 on the Pi and deploy the updated dual-camera streaming server."""
import paramiko
import time
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

def run(cmd, timeout=120):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out[-500:] if len(out) > 500 else out)  # truncate long output
    if err and 'Warning' not in err: print(f"STDERR: {err[-300:]}")
    return out

# Install pyrealsense2 on Pi
print("Installing pyrealsense2 on Pi (this may take a while)...")
run("pip3 install pyrealsense2", timeout=300)

# Verify
run("python3 -c 'import pyrealsense2 as rs; print(rs.__version__)'")

# Test RealSense connection
run("python3 -c 'import pyrealsense2 as rs; ctx=rs.context(); devs=ctx.query_devices(); print(len(devs), \"devices\"); [print(d.get_info(rs.camera_info.name)) for d in devs]'")

# Upload the new streaming server
sftp = ssh.open_sftp()

# Create the new server that serves both RealSense RGBD and webcam
server_code = '''#!/usr/bin/env python3
"""
Dual-camera streaming server for Raspberry Pi.

Serves:
  - RealSense D435i (overhead): color + depth as aligned RGBD
  - EMEET webcam (side view): color stream

Endpoints:
  GET /realsense/color    — RealSense color JPEG snapshot
  GET /realsense/depth    — RealSense depth as 16-bit PNG
  GET /realsense/rgbd     — Both color + depth in one response (JSON with base64)
  GET /webcam/snapshot    — Webcam side-view JPEG snapshot
  GET /webcam/video       — Webcam MJPEG stream
  GET /                   — Status
"""
import time
import threading
import json
import base64
import io

import cv2
import numpy as np
import pyrealsense2 as rs
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# --- RealSense State ---
rs_pipeline = None
rs_align = None
rs_intrinsics = None
rs_depth_scale = 0.001
rs_color_frame = None
rs_depth_frame = None  # raw uint16
rs_lock = threading.Lock()

# --- Webcam State ---
webcam_cap = None
webcam_frame = None
webcam_lock = threading.Lock()


def start_realsense():
    global rs_pipeline, rs_align, rs_intrinsics, rs_depth_scale
    rs_pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    profile = rs_pipeline.start(config)
    rs_depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
    cs = profile.get_stream(rs.stream.color)
    rs_intrinsics = cs.as_video_stream_profile().get_intrinsics()
    rs_align = rs.align(rs.stream.color)
    # Auto-exposure settle
    for _ in range(30):
        rs_pipeline.wait_for_frames()
    print(f"RealSense started. depth_scale={rs_depth_scale}")


def rs_capture_loop():
    global rs_color_frame, rs_depth_frame
    while True:
        try:
            frames = rs_pipeline.wait_for_frames()
            aligned = rs_align.process(frames)
            color = np.asanyarray(aligned.get_color_frame().get_data())
            depth = np.asanyarray(aligned.get_depth_frame().get_data())
            with rs_lock:
                rs_color_frame = color
                rs_depth_frame = depth
        except Exception as e:
            print(f"RS error: {e}")
        time.sleep(0.03)


def webcam_capture_loop(cam_index=0):
    global webcam_cap, webcam_frame
    webcam_cap = cv2.VideoCapture(cam_index)
    if not webcam_cap.isOpened():
        print(f"WARNING: Cannot open webcam at index {cam_index}")
        return
    print(f"Webcam {cam_index} opened.")
    while True:
        ret, frame = webcam_cap.read()
        if ret:
            with webcam_lock:
                webcam_frame = frame
        time.sleep(0.03)


# --- RealSense Endpoints ---

@app.route("/realsense/color")
def rs_color_snapshot():
    with rs_lock:
        frame = rs_color_frame
    if frame is None:
        return "No frame", 503
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(jpeg.tobytes(), mimetype="image/jpeg")


@app.route("/realsense/depth")
def rs_depth_snapshot():
    with rs_lock:
        frame = rs_depth_frame
    if frame is None:
        return "No frame", 503
    # Encode depth as 16-bit PNG (lossless)
    _, png = cv2.imencode(".png", frame)
    return Response(png.tobytes(), mimetype="image/png")


@app.route("/realsense/depth_colormap")
def rs_depth_colormap():
    with rs_lock:
        frame = rs_depth_frame
    if frame is None:
        return "No frame", 503
    colormap = cv2.applyColorMap(cv2.convertScaleAbs(frame, alpha=0.03), cv2.COLORMAP_JET)
    _, jpeg = cv2.imencode(".jpg", colormap, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(jpeg.tobytes(), mimetype="image/jpeg")


@app.route("/realsense/rgbd")
def rs_rgbd():
    """Return aligned color + depth as JSON with base64-encoded images."""
    with rs_lock:
        color = rs_color_frame
        depth = rs_depth_frame
    if color is None or depth is None:
        return jsonify({"error": "No frames"}), 503

    _, color_jpg = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 90])
    _, depth_png = cv2.imencode(".png", depth)

    return jsonify({
        "color_b64": base64.b64encode(color_jpg).decode("utf-8"),
        "depth_b64": base64.b64encode(depth_png).decode("utf-8"),
        "width": color.shape[1],
        "height": color.shape[0],
        "depth_scale": rs_depth_scale,
        "intrinsics": {
            "fx": rs_intrinsics.fx,
            "fy": rs_intrinsics.fy,
            "ppx": rs_intrinsics.ppx,
            "ppy": rs_intrinsics.ppy,
        },
    })


@app.route("/realsense/intrinsics")
def rs_get_intrinsics():
    return jsonify({
        "fx": rs_intrinsics.fx,
        "fy": rs_intrinsics.fy,
        "ppx": rs_intrinsics.ppx,
        "ppy": rs_intrinsics.ppy,
        "width": 640,
        "height": 480,
        "depth_scale": rs_depth_scale,
    })


# --- Webcam Endpoints ---

@app.route("/webcam/snapshot")
def webcam_snapshot():
    with webcam_lock:
        frame = webcam_frame
    if frame is None:
        return "No frame", 503
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(jpeg.tobytes(), mimetype="image/jpeg")


@app.route("/webcam/video")
def webcam_video():
    def gen():
        while True:
            with webcam_lock:
                frame = webcam_frame
            if frame is not None:
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                yield (b"--frame\\r\\nContent-Type: image/jpeg\\r\\n\\r\\n"
                       + jpeg.tobytes() + b"\\r\\n")
            time.sleep(0.033)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


# Also keep backward-compatible endpoints
@app.route("/snapshot")
def legacy_snapshot():
    return rs_color_snapshot()

@app.route("/video")
def legacy_video():
    return webcam_video()


@app.route("/")
def index():
    return jsonify({
        "service": "myCobot Dual Camera Server",
        "cameras": {
            "realsense": "Intel RealSense D435i (overhead, RGBD)",
            "webcam": "EMEET C960 (side view, RGB)",
        },
        "endpoints": {
            "/realsense/color": "RealSense color JPEG",
            "/realsense/depth": "RealSense depth PNG (uint16)",
            "/realsense/depth_colormap": "RealSense depth colormap JPEG",
            "/realsense/rgbd": "RealSense RGBD JSON (base64)",
            "/realsense/intrinsics": "RealSense intrinsics",
            "/webcam/snapshot": "Webcam JPEG",
            "/webcam/video": "Webcam MJPEG stream",
            "/snapshot": "Legacy (= realsense/color)",
        },
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--webcam", type=int, default=0)
    args = parser.parse_args()

    start_realsense()

    # Start capture threads
    threading.Thread(target=rs_capture_loop, daemon=True).start()
    threading.Thread(target=webcam_capture_loop, args=(args.webcam,), daemon=True).start()
    time.sleep(2)

    print(f"Dual camera server starting on 0.0.0.0:{args.port}")
    app.run(host="0.0.0.0", port=args.port, threaded=True)
'''

# Write to a temp file and upload
temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_dual_camera_server.py")
with open(temp_path, "w") as f:
    f.write(server_code)
sftp.put(temp_path, "/home/er/pi_dual_camera_server.py")
sftp.close()
print("\nUploaded pi_dual_camera_server.py to Pi")

ssh.close()
print("\nDone! Next: kill old servers and start the new one.")
