"""
MCP (Model Context Protocol) Server for myCobot 280 Pi.

Exposes all robot atomic actions, VLM pipelines, camera, and agent
as tools that an LLM can call agentically.

Usage:
    python -m src.mcp_server          # stdio transport (for Claude Desktop)
    python -m src.mcp_server --http   # HTTP transport (for remote clients)

Test with MCP Inspector:
    mcp dev src/mcp_server.py
"""

import sys
import os
import time
import json
import logging
from typing import List, Dict, Any, Optional

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

# Import all modules
from src.cobot.config import get_config
from src.cobot import actions
from src.cobot.camera import get_camera
from src.cobot.realsense import get_realsense, HAS_REALSENSE
from src.vlm import pipeline
from src.vlm.vlm_client import get_vlm_client
from src.calibration.eye2hand import get_eye2hand
from src.agent.planner import get_planner
from src.agent.executor import run_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Create the MCP server
# ──────────────────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "MyCobot 280 Agent",
    description="Control a myCobot 280 Pi robot arm with VLM-based vision and agentic planning.",
)


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM / POWER TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_power_on() -> str:
    """Power on the robot arm. Call this first before any motion commands."""
    return actions.power_on()


@mcp.tool()
def robot_power_off() -> str:
    """Power off the robot arm. All servos will be de-energized."""
    return actions.power_off()


@mcp.tool()
def robot_release_servos() -> str:
    """Release all servos so the arm can be moved freely by hand."""
    return actions.release_all_servos()


@mcp.tool()
def robot_lock_servos() -> str:
    """Lock (energize) all servos to hold position."""
    return actions.focus_all_servos()


@mcp.tool()
def robot_get_error() -> str:
    """Check if the robot has any error conditions."""
    info = actions.get_error_info()
    return json.dumps(info)


@mcp.tool()
def robot_clear_error() -> str:
    """Clear any robot error conditions."""
    return actions.clear_error()


# ══════════════════════════════════════════════════════════════════════════════
# STATUS TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_get_status() -> str:
    """
    Get comprehensive robot status including: power state, joint angles,
    TCP coordinates, servo temperatures, and whether it's moving.
    """
    status = actions.get_robot_status()
    return json.dumps(status, default=str)


@mcp.tool()
def robot_get_angles() -> str:
    """Get current joint angles [J1, J2, J3, J4, J5, J6] in degrees."""
    angles = actions.get_angles()
    return json.dumps({"angles": angles})


@mcp.tool()
def robot_get_coords() -> str:
    """Get current TCP coordinates [x, y, z, rx, ry, rz] in mm and degrees."""
    coords = actions.get_coords()
    return json.dumps({"coords": coords})


@mcp.tool()
def robot_is_moving() -> str:
    """Check if the robot is currently in motion."""
    moving = actions.is_moving()
    return json.dumps({"is_moving": moving})


@mcp.tool()
def robot_get_servo_temps() -> str:
    """Get temperature of all 6 servos in degrees Celsius."""
    temps = actions.get_servo_temps()
    return json.dumps({"servo_temperatures_c": temps})


# ══════════════════════════════════════════════════════════════════════════════
# MOTION TOOLS — JOINT SPACE
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_home() -> str:
    """Move all joints to the home/zero position [0, 0, 0, 0, 0, 0]."""
    return actions.back_zero()


@mcp.tool()
def robot_send_angle(joint_id: int, angle: float, speed: int = 30) -> str:
    """
    Move a single joint to a target angle.

    Args:
        joint_id: Joint number (1-6)
        angle: Target angle in degrees
        speed: Movement speed (1-100, default 30)
    """
    return actions.send_angle(joint_id, angle, speed)


@mcp.tool()
def robot_send_angles(angles: list[float], speed: int = 30) -> str:
    """
    Move all 6 joints simultaneously to target angles.

    Args:
        angles: List of 6 target angles in degrees [J1, J2, J3, J4, J5, J6]
        speed: Movement speed (1-100, default 30)
    """
    return actions.send_angles(angles, speed)


# ══════════════════════════════════════════════════════════════════════════════
# MOTION TOOLS — CARTESIAN SPACE
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_send_coords(coords: list[float], speed: int = 20, mode: int = 0) -> str:
    """
    Move end-effector to Cartesian coordinates.

    Args:
        coords: [x, y, z, rx, ry, rz] in mm and degrees
        speed: Movement speed (1-100, default 20)
        mode: 0 = angular path (moveJ), 1 = linear path (moveL)
    """
    return actions.send_coords(coords, speed, mode)


@mcp.tool()
def robot_move_to_xy(x: float, y: float, z: float = 230) -> str:
    """
    Move end-effector to a workspace XY position at a given height.
    Orientation defaults to pointing straight down.

    Args:
        x: X coordinate in mm
        y: Y coordinate in mm
        z: Height in mm (default 230 = safe height)
    """
    return actions.move_to_coords(x, y, z)


@mcp.tool()
def robot_move_to_top_view() -> str:
    """Move arm to the overhead camera viewing position for taking photos."""
    return actions.move_to_top_view()


# ══════════════════════════════════════════════════════════════════════════════
# JOG TOOLS (INCREMENTAL MOTION)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_jog_angle(joint_id: int, direction: int, speed: int = 20) -> str:
    """
    Continuously jog a joint in one direction until stopped.

    Args:
        joint_id: Joint 1-6
        direction: 0 = negative, 1 = positive
        speed: Speed 1-100
    """
    return actions.jog_angle(joint_id, direction, speed)


@mcp.tool()
def robot_jog_coord(axis_id: int, direction: int, speed: int = 20) -> str:
    """
    Continuously jog a Cartesian axis until stopped.

    Args:
        axis_id: 1=x, 2=y, 3=z, 4=rx, 5=ry, 6=rz
        direction: 0 = negative, 1 = positive
        speed: Speed 1-100
    """
    return actions.jog_coord(axis_id, direction, speed)


@mcp.tool()
def robot_increment_angle(joint_id: int, increment: float, speed: int = 20) -> str:
    """
    Move a joint by an incremental step.

    Args:
        joint_id: Joint 1-6
        increment: Step size in degrees (positive or negative)
        speed: Speed 1-100
    """
    return actions.jog_increment_angle(joint_id, increment, speed)


@mcp.tool()
def robot_increment_coord(axis_id: int, increment: float, speed: int = 20) -> str:
    """
    Move a Cartesian axis by an incremental step.

    Args:
        axis_id: 1=x, 2=y, 3=z, 4=rx, 5=ry, 6=rz
        increment: Step size in mm or degrees
        speed: Speed 1-100
    """
    return actions.jog_increment_coord(axis_id, increment, speed)


@mcp.tool()
def robot_stop() -> str:
    """Emergency stop — halt all robot motion immediately."""
    return actions.stop_motion()


@mcp.tool()
def robot_pause() -> str:
    """Pause current robot motion (can be resumed)."""
    return actions.pause_motion()


@mcp.tool()
def robot_resume() -> str:
    """Resume previously paused robot motion."""
    return actions.resume_motion()


# ══════════════════════════════════════════════════════════════════════════════
# END-EFFECTOR TOOLS (FINGER)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_finger_touch(x: float, y: float, touch_z: float = 90) -> str:
    """
    Lower the finger end-effector to touch a point, then retract.
    Moves above the target at safe height, descends to touch, pauses briefly,
    then retracts.

    Args:
        x: X coordinate in mm (robot base frame)
        y: Y coordinate in mm (robot base frame)
        touch_z: Height to descend to for touch (mm, default 90)
    """
    return actions.finger_touch(x, y, touch_z)


@mcp.tool()
def robot_finger_move(
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    touch_z: float = 90,
) -> str:
    """
    Slide/push motion: descend at start point, slide to end point, retract.
    Useful for pushing objects across the workspace.

    Args:
        start_x, start_y: Starting XY in mm
        end_x, end_y: Ending XY in mm
        touch_z: Height for the sliding motion (mm, default 90)
    """
    return actions.finger_move(start_x, start_y, end_x, end_y, touch_z)


# ══════════════════════════════════════════════════════════════════════════════
# GESTURE TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_head_shake() -> str:
    """Make the robot do a head-shake (no) gesture."""
    return actions.head_shake()


@mcp.tool()
def robot_head_nod() -> str:
    """Make the robot do a head-nod (yes) gesture."""
    return actions.head_nod()


@mcp.tool()
def robot_head_dance() -> str:
    """Make the robot perform a fun dance animation."""
    return actions.head_dance()


# ══════════════════════════════════════════════════════════════════════════════
# LED / VISUAL FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_set_led(r: int, g: int, b: int) -> str:
    """
    Set the RGB LED color on the robot's end-effector.

    Args:
        r: Red value (0-255)
        g: Green value (0-255)
        b: Blue value (0-255)
    """
    return actions.set_led_color(r, g, b)


@mcp.tool()
def robot_set_led_by_description(description: str) -> str:
    """
    Set the LED color using a natural language description.
    The LLM will determine the appropriate RGB values.

    Args:
        description: Color description (e.g. "ocean blue", "sunset orange", "forest green")
    """
    return pipeline.llm_led(description)


# ══════════════════════════════════════════════════════════════════════════════
# CAMERA TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def camera_capture() -> str:
    """
    Move to overhead position and capture an image from the Pi camera.
    Returns the path to the saved image.
    """
    return pipeline.capture_image()


@mcp.tool()
def camera_snapshot_only() -> str:
    """
    Capture a snapshot from the Pi camera WITHOUT moving the arm.
    Useful when the arm is already in position.
    """
    camera = get_camera()
    path = camera.capture_snapshot("snapshot.jpg")
    return f"Snapshot saved to {path}" if path else "Error: failed to capture."


# ══════════════════════════════════════════════════════════════════════════════
# VLM VISION TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def vlm_move_object(instruction: str) -> str:
    """
    Use vision (VLM) to identify objects and move/push one object to another.

    The full pipeline:
    1. Moves arm to overhead camera position
    2. Takes a photo of the workspace
    3. Sends photo + instruction to GPT-4o for object detection
    4. Converts pixel coordinates to robot coordinates
    5. Executes a finger-slide motion from start to end object

    Args:
        instruction: Natural language instruction describing what to move where.
                    e.g. "push the red block onto the star"
                    e.g. "move the pen to the notebook"
    """
    return pipeline.vlm_move(instruction)


@mcp.tool()
def vlm_touch_object(description: str) -> str:
    """
    Use vision (VLM) to find an object and touch it with the finger.

    1. Takes overhead photo
    2. Detects the described object via GPT-4o
    3. Converts to robot coordinates
    4. Touches the object and retracts

    Args:
        description: What object to touch (e.g. "the green ball", "the small red cube")
    """
    return pipeline.vlm_touch(description)


@mcp.tool()
def vlm_ask_question(question: str) -> str:
    """
    Visual question answering — ask a question about what's on the workspace.

    Takes an overhead photo and sends it with your question to GPT-4o.

    Args:
        question: Any question about the workspace
                 e.g. "How many objects are on the table?"
                 e.g. "What color is the largest block?"
                 e.g. "Describe everything you see"
    """
    return pipeline.vlm_vqa(question)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT TOOL (META — PLANS AND EXECUTES MULTI-STEP ACTIONS)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def agent_execute(instruction: str) -> str:
    """
    Give a high-level instruction and the agent will plan and execute
    a sequence of atomic actions autonomously.

    The agent understands all available robot functions and can chain
    them together. Examples:
    - "Go home, do a dance, then check what's on the table"
    - "Push the red block to the star, then nod"
    - "Set the LED to ocean blue and wave hello"

    Args:
        instruction: Natural language instruction for the agent
    """
    result = run_agent(instruction)
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATION TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def calibration_pixel_to_robot(u: float, v: float) -> str:
    """
    Convert pixel coordinates from the overhead camera to robot workspace
    coordinates using the current eye-to-hand calibration.

    Args:
        u: Pixel X coordinate (horizontal, from left)
        v: Pixel Y coordinate (vertical, from top)
    """
    e2h = get_eye2hand()
    x, y = e2h.pixel_to_robot(u, v)
    return json.dumps({"pixel": [u, v], "robot_xy": [round(x, 2), round(y, 2)]})


@mcp.tool()
def calibration_update_points(
    pixel_1: list[float], robot_1: list[float],
    pixel_2: list[float], robot_2: list[float],
) -> str:
    """
    Update the 2-point eye-to-hand calibration.

    You need two corresponding points where you know both the pixel position
    (from the overhead camera image) and the robot position (from get_coords).

    Args:
        pixel_1: First calibration point pixel coords [u, v]
        robot_1: First calibration point robot coords [x, y] in mm
        pixel_2: Second calibration point pixel coords [u, v]
        robot_2: Second calibration point robot coords [x, y] in mm
    """
    e2h = get_eye2hand()
    e2h.update_linear_calibration(pixel_1, robot_1, pixel_2, robot_2)
    return "Calibration updated successfully."


# ══════════════════════════════════════════════════════════════════════════════
# SERVO TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_focus_servo(servo_id: int) -> str:
    """Lock (energize) a single servo. servo_id: 1-6."""
    return actions.focus_servo(servo_id)


@mcp.tool()
def robot_release_servo(servo_id: int) -> str:
    """Release (unlock) a single servo for free movement. servo_id: 1-6."""
    return actions.release_servo(servo_id)


@mcp.tool()
def robot_emergency_brake(joint_id: int) -> str:
    """Apply emergency brake to a specific moving joint. joint_id: 1-6."""
    return actions.joint_brake(joint_id)


# ══════════════════════════════════════════════════════════════════════════════
# IO TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def robot_set_digital_output(pin: int, signal: int) -> str:
    """
    Set a digital output pin on the end-effector.

    Args:
        pin: Pin number
        signal: 0 = LOW, 1 = HIGH
    """
    return actions.set_digital_output(pin, signal)


@mcp.tool()
def robot_get_digital_input(pin: int) -> str:
    """Read a digital input pin on the end-effector."""
    val = actions.get_digital_input(pin)
    return json.dumps({"pin": pin, "value": val})


# ══════════════════════════════════════════════════════════════════════════════
# REALSENSE DEPTH CAMERA TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def realsense_capture() -> str:
    """
    Capture a color + depth image from the Intel RealSense D435i.
    Returns paths to the saved color and depth images.
    The RealSense is connected to the laptop via USB and provides
    high-quality RGB + aligned depth maps.
    """
    rs_cam = get_realsense()
    color, depth_mm, _ = rs_cam.capture()
    import cv2
    os.makedirs("temp", exist_ok=True)
    cv2.imwrite("temp/rs_color.jpg", color)
    depth_cm = cv2.applyColorMap(cv2.convertScaleAbs(depth_mm, alpha=0.03), cv2.COLORMAP_JET)
    cv2.imwrite("temp/rs_depth.jpg", depth_cm)
    return json.dumps({
        "color_path": "temp/rs_color.jpg",
        "depth_path": "temp/rs_depth.jpg",
        "shape": list(color.shape),
    })


@mcp.tool()
def realsense_get_depth_at(u: int, v: int) -> str:
    """
    Get the depth (distance) at a specific pixel in the RealSense image.

    Args:
        u: Pixel X coordinate (0 = left)
        v: Pixel Y coordinate (0 = top)

    Returns depth in millimeters.
    """
    rs_cam = get_realsense()
    depth_m = rs_cam.get_depth_at(u, v)
    return json.dumps({"pixel": [u, v], "depth_mm": round(depth_m * 1000, 1)})


@mcp.tool()
def realsense_pixel_to_3d(u: int, v: int) -> str:
    """
    Convert a pixel coordinate to a 3D point in the camera frame using depth.
    Requires the RealSense camera.

    Args:
        u: Pixel X coordinate
        v: Pixel Y coordinate

    Returns 3D point in camera frame (mm) and robot frame (mm) if calibrated.
    """
    rs_cam = get_realsense()
    cam_pt = rs_cam.pixel_to_3d_camera(u, v)
    result = {
        "pixel": [u, v],
        "camera_frame_mm": [round(c * 1000, 1) for c in cam_pt],
    }
    try:
        robot_pt = rs_cam.pixel_to_3d_robot(u, v)
        result["robot_frame_mm"] = [round(r, 1) for r in robot_pt]
    except RuntimeError:
        result["robot_frame_mm"] = "Not calibrated — run extrinsic calibration first"
    return json.dumps(result)


@mcp.tool()
def realsense_get_workspace_depth() -> str:
    """
    Get depth statistics for the workspace visible to the RealSense.
    Useful for understanding the scene layout and table distance.
    """
    rs_cam = get_realsense()
    stats = rs_cam.get_workspace_depth_stats()
    return json.dumps(stats)


@mcp.tool()
def realsense_get_intrinsics() -> str:
    """Get the RealSense camera intrinsic parameters (focal length, principal point, etc.)."""
    rs_cam = get_realsense()
    return json.dumps(rs_cam.get_intrinsics_dict())


# ══════════════════════════════════════════════════════════════════════════════
# KEYBOARD & TOUCHPAD INTERACTION TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def keyboard_press_key(key: str) -> str:
    """
    Press a single key on the laptop keyboard.

    The robot moves its finger to the key position and presses it.
    Supports letters (a-z), numbers (0-9), and special keys.

    Args:
        key: The key to press. Examples: "a", "d", "1", "esc", "tab"

    Reachable keys (left side of keyboard):
        Row 1: ` 1 2 3 4 5 6
        Row 2: q w e r t y
        Row 3: a s d f g h
        Row 4: z x c v b
    """
    import subprocess
    result = subprocess.run(
        [sys.executable, "press_key.py", "--fast", key],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)),
        timeout=30
    )
    return result.stdout + result.stderr


@mcp.tool()
def keyboard_type_text(text: str, speed: str = "fast") -> str:
    """
    Type a string of text on the laptop keyboard.

    The robot slides its finger between keys at hover height, pressing each
    key in sequence. Supports slow, medium, and fast speeds.

    Args:
        text: The text to type. Only reachable keys will be pressed.
              Unreachable characters are skipped with a warning.
        speed: Speed mode - "slow", "medium", or "fast" (default: "fast")

    Examples:
        keyboard_type_text("sad")
        keyboard_type_text("qwerty", speed="slow")
    """
    import subprocess
    result = subprocess.run(
        [sys.executable, "press_key.py", f"--{speed}", text],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)),
        timeout=120
    )
    return result.stdout + result.stderr


@mcp.tool()
def touchpad_swipe(direction: str = "down") -> str:
    """
    Perform a swipe gesture on the laptop touchpad.

    Args:
        direction: "down" (scroll down), "up" (scroll up),
                   "left" (swipe left), "right" (swipe right)
    """
    from pymycobot import MyCobot280Socket
    mc = MyCobot280Socket('10.105.230.93', 9000)
    time.sleep(0.5)

    TP_Z = 131.5
    HOVER = 145
    PRESS = TP_Z - 2

    # Direction vectors
    dirs = {
        "down":  ((245, -25), (245, -55)),
        "up":    ((245, -55), (245, -25)),
        "left":  ((260, -40), (235, -40)),
        "right": ((235, -40), (260, -40)),
    }
    if direction not in dirs:
        return f"Unknown direction '{direction}'. Use: down, up, left, right"

    start, end = dirs[direction]
    mc.send_coords([start[0], start[1], HOVER, 0, 180, 90], 12, 0)
    time.sleep(2)
    mc.send_coords([start[0], start[1], PRESS, 0, 180, 90], 8, 0)
    time.sleep(1)
    mc.send_coords([end[0], end[1], PRESS, 0, 180, 90], 8, 0)
    time.sleep(2)
    mc.send_coords([end[0], end[1], HOVER, 0, 180, 90], 8, 0)
    time.sleep(1)

    return f"Swiped {direction} on touchpad."


@mcp.tool()
def touchpad_tap(x_frac: float = 0.5, y_frac: float = 0.5) -> str:
    """
    Tap the touchpad at a specific position.

    Args:
        x_frac: Horizontal position (0.0 = left edge, 1.0 = right edge)
        y_frac: Vertical position (0.0 = top edge, 1.0 = bottom edge)
    """
    from pymycobot import MyCobot280Socket
    mc = MyCobot280Socket('10.105.230.93', 9000)
    time.sleep(0.5)

    # Touchpad bounds in robot frame
    TP_LEFT, TP_RIGHT = 235, 260
    TP_TOP, TP_BOTTOM = -25, -55
    TP_Z = 131.5
    HOVER = 145

    x = TP_LEFT + x_frac * (TP_RIGHT - TP_LEFT)
    y = TP_TOP + y_frac * (TP_BOTTOM - TP_TOP)
    press_z = TP_Z - 2

    mc.send_coords([x, y, HOVER, 0, 180, 90], 12, 0)
    time.sleep(2)
    mc.send_coords([x, y, press_z, 0, 180, 90], 8, 0)
    time.sleep(0.5)
    mc.send_coords([x, y, HOVER, 0, 180, 90], 8, 0)
    time.sleep(1)

    return f"Tapped touchpad at ({x_frac:.1f}, {y_frac:.1f})."


# ══════════════════════════════════════════════════════════════════════════════
# RESOURCES (read-only data endpoints)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.resource("robot://status")
def resource_robot_status() -> str:
    """Current robot status as JSON."""
    return json.dumps(actions.get_robot_status(), default=str)


@mcp.resource("robot://config")
def resource_config() -> str:
    """Current robot configuration."""
    cfg = get_config()
    return json.dumps({
        "robot_host": cfg.robot.host,
        "robot_port": cfg.robot.port,
        "camera_stream": cfg.camera.stream_url,
        "vlm_model": cfg.vlm.model,
        "safe_height": cfg.robot.safe_height,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    transport = "stdio"
    if "--http" in sys.argv:
        transport = "streamable-http"
    mcp.run(transport=transport)
