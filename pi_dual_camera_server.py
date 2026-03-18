# coding: utf-8
"""
Dual-camera streaming server for Raspberry Pi.

Serves:
  - RealSense D435i (overhead): color + depth as aligned RGBD
  - EMEET webcam (side view): color stream

Endpoints:
  GET /realsense/color        - RealSense color JPEG snapshot
  GET /realsense/depth        - RealSense depth as 16-bit PNG
  GET /realsense/depth_colormap - Depth visualization
  GET /realsense/rgbd         - Both color + depth in one JSON response
  GET /realsense/intrinsics   - Camera intrinsics
  GET /webcam/snapshot        - Webcam side-view JPEG snapshot
  GET /webcam/video           - Webcam MJPEG stream
  GET /                       - Status
"""
import time
import threading
import json
import base64

import cv2
import numpy as np
import pyrealsense2 as rs
from flask import Flask, Response, jsonify

app = Flask(__name__)

# --- RealSense State ---
rs_pipeline = None
rs_align = None
rs_intrinsics = None
rs_depth_scale = 0.001
rs_color_frame = None
rs_depth_frame = None
rs_lock = threading.Lock()

# --- Webcam State ---
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
    for _ in range(30):
        rs_pipeline.wait_for_frames()
    print("RealSense started. depth_scale={}".format(rs_depth_scale))


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
            print("RS error: {}".format(e))
        time.sleep(0.03)


def webcam_capture_loop(cam_index=0):
    global webcam_frame
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        print("WARNING: Cannot open webcam at index {}".format(cam_index))
        return
    print("Webcam {} opened.".format(cam_index))
    while True:
        ret, frame = cap.read()
        if ret:
            with webcam_lock:
                webcam_frame = frame
        time.sleep(0.03)


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
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpeg.tobytes() + b"\r\n")
            time.sleep(0.033)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


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
        },
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--webcam", type=int, default=0)
    args = parser.parse_args()

    start_realsense()

    threading.Thread(target=rs_capture_loop, daemon=True).start()
    threading.Thread(target=webcam_capture_loop, args=(args.webcam,), daemon=True).start()
    time.sleep(2)

    print("Dual camera server starting on 0.0.0.0:{}".format(args.port))
    app.run(host="0.0.0.0", port=args.port, threaded=True)
