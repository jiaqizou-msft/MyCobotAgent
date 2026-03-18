"""
Atomic robot actions for myCobot 280 Pi.

Every action is a standalone function that can be called independently.
These map 1:1 to MCP tools and to the agent's action space.

Categories:
  - System / Power
  - Motion (joint & coordinate)
  - Jog (incremental)
  - Status queries
  - Gripper / End-effector
  - LED / IO
  - Gestures (pre-programmed animations)
  - Servo control
  - Coordinate frames
  - Drag teaching
"""

import time
import logging
from typing import List, Optional, Tuple, Dict, Any

from src.cobot.connection import get_mc
from src.cobot.config import get_config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Joint angle limits for myCobot 280
# ──────────────────────────────────────────────────────────────────────────────
JOINT_LIMITS = {
    1: (-168, 168),
    2: (-135, 135),
    3: (-150, 150),
    4: (-145, 145),
    5: (-155, 160),
    6: (-180, 180),
}

COORD_LIMITS = {
    "x": (-281.45, 281.45),
    "y": (-281.45, 281.45),
    "z": (-70, 412.67),
    "rx": (-180, 180),
    "ry": (-180, 180),
    "rz": (-180, 180),
}


def _validate_speed(speed: int) -> int:
    return max(1, min(100, speed))


def _validate_joint_angle(joint_id: int, angle: float) -> float:
    lo, hi = JOINT_LIMITS.get(joint_id, (-180, 180))
    return max(lo, min(hi, angle))


def _validate_angles(angles: List[float]) -> List[float]:
    return [_validate_joint_angle(i + 1, a) for i, a in enumerate(angles)]


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM / POWER
# ══════════════════════════════════════════════════════════════════════════════

def power_on() -> str:
    """Power on the robot arm."""
    mc = get_mc()
    mc.power_on()
    time.sleep(1)
    return "Robot powered on."


def power_off() -> str:
    """Power off the robot arm (all servos de-energized)."""
    mc = get_mc()
    mc.power_off()
    return "Robot powered off."


def is_power_on() -> bool:
    """Check if the robot is powered on."""
    mc = get_mc()
    return mc.is_power_on() == 1


def release_all_servos() -> str:
    """Release all servos — arm can be moved by hand freely."""
    mc = get_mc()
    mc.release_all_servos()
    return "All servos released. Robot is in free-move mode."


def focus_all_servos() -> str:
    """Lock (energize) all servos."""
    mc = get_mc()
    mc.focus_all_servos()
    return "All servos locked."


def get_error_info() -> Dict[str, Any]:
    """Get robot error information. 0 = no error."""
    mc = get_mc()
    err = mc.get_error_information()
    return {"error_code": err, "description": _error_desc(err)}


def clear_error() -> str:
    """Clear robot error information."""
    mc = get_mc()
    mc.clear_error_information()
    return "Error cleared."


def _error_desc(code) -> str:
    if code == 0:
        return "No error"
    elif 1 <= code <= 6:
        return f"Joint {code} reached limit"
    elif code == 16:
        return "Collision detected (joint 1-2)"
    elif code == 17:
        return "Collision detected (joint 2-3)"
    elif code == 18:
        return "Collision detected (joint 3-4)"
    elif code == 19:
        return "Collision detected (joint 4-6)"
    elif code == 32:
        return "Inverse kinematics error — no solution"
    return f"Unknown error code {code}"


# ══════════════════════════════════════════════════════════════════════════════
# MOTION — JOINT SPACE
# ══════════════════════════════════════════════════════════════════════════════

def get_angles() -> List[float]:
    """Get all 6 joint angles in degrees."""
    mc = get_mc()
    return mc.get_angles()


def send_angle(joint_id: int, angle: float, speed: int = 30) -> str:
    """
    Move a single joint to the specified angle.

    Args:
        joint_id: Joint number 1-6
        angle: Target angle in degrees
        speed: Movement speed 1-100
    """
    mc = get_mc()
    angle = _validate_joint_angle(joint_id, angle)
    speed = _validate_speed(speed)
    mc.send_angle(joint_id, angle, speed)
    return f"Joint {joint_id} moving to {angle}° at speed {speed}."


def send_angles(angles: List[float], speed: int = 30) -> str:
    """
    Move all 6 joints to the specified angles simultaneously.

    Args:
        angles: List of 6 target angles in degrees [J1, J2, J3, J4, J5, J6]
        speed: Movement speed 1-100
    """
    mc = get_mc()
    if len(angles) != 6:
        return f"Error: expected 6 angles, got {len(angles)}"
    angles = _validate_angles(angles)
    speed = _validate_speed(speed)
    mc.send_angles(angles, speed)
    return f"Moving to angles {angles} at speed {speed}."


def sync_send_angles(angles: List[float], speed: int = 30, timeout: float = 15) -> str:
    """
    Move all joints to target angles and BLOCK until reached (or timeout).

    Args:
        angles: List of 6 target angles
        speed: Speed 1-100
        timeout: Max wait time in seconds
    """
    mc = get_mc()
    angles = _validate_angles(angles)
    speed = _validate_speed(speed)
    mc.sync_send_angles(angles, speed, timeout=timeout)
    return f"Reached angles {angles}."


# ══════════════════════════════════════════════════════════════════════════════
# MOTION — CARTESIAN SPACE
# ══════════════════════════════════════════════════════════════════════════════

def get_coords() -> List[float]:
    """Get TCP coordinates [x, y, z, rx, ry, rz] in mm and degrees."""
    mc = get_mc()
    return mc.get_coords()


def send_coord(axis_id: int, value: float, speed: int = 20) -> str:
    """
    Move a single Cartesian axis.

    Args:
        axis_id: 1=x, 2=y, 3=z, 4=rx, 5=ry, 6=rz
        value: Target value (mm or degrees)
        speed: Speed 1-100
    """
    mc = get_mc()
    speed = _validate_speed(speed)
    mc.send_coord(axis_id, value, speed)
    axis_names = {1: "x", 2: "y", 3: "z", 4: "rx", 5: "ry", 6: "rz"}
    return f"Moving {axis_names.get(axis_id, axis_id)} to {value} at speed {speed}."


def send_coords(coords: List[float], speed: int = 20, mode: int = 0) -> str:
    """
    Move to Cartesian coordinates [x, y, z, rx, ry, rz].

    Args:
        coords: [x, y, z, rx, ry, rz] in mm and degrees
        speed: Speed 1-100
        mode: 0 = angular (moveJ), 1 = linear (moveL)
    """
    mc = get_mc()
    if len(coords) != 6:
        return f"Error: expected 6 coords, got {len(coords)}"
    speed = _validate_speed(speed)
    mc.send_coords(coords, speed, mode)
    return f"Moving to coords {coords} at speed {speed}, mode={'linear' if mode else 'angular'}."


def sync_send_coords(coords: List[float], speed: int = 20, mode: int = 0, timeout: float = 15) -> str:
    """
    Move to Cartesian coordinates and BLOCK until reached (or timeout).
    """
    mc = get_mc()
    speed = _validate_speed(speed)
    mc.sync_send_coords(coords, speed, mode=mode, timeout=timeout)
    return f"Reached coords {coords}."


def move_to_coords(x: float, y: float, z: float = None, speed: int = 20) -> str:
    """
    Move end-effector to workspace XY (and optionally Z) at safe height.
    Uses default orientation (pointing straight down).

    Args:
        x: Target X in mm
        y: Target Y in mm
        z: Target Z in mm (defaults to safe_height from config)
        speed: Speed 1-100
    """
    cfg = get_config().robot
    if z is None:
        z = cfg.safe_height
    coords = [x, y, z, cfg.default_rx, cfg.default_ry, cfg.default_rz]
    return send_coords(coords, speed=speed, mode=0)


# ══════════════════════════════════════════════════════════════════════════════
# MOTION — JOG (INCREMENTAL)
# ══════════════════════════════════════════════════════════════════════════════

def jog_angle(joint_id: int, direction: int, speed: int = 20) -> str:
    """
    Continuously jog a joint in one direction.

    Args:
        joint_id: Joint 1-6
        direction: 0 = negative, 1 = positive
        speed: Speed 1-100
    """
    mc = get_mc()
    mc.jog_angle(joint_id, direction, _validate_speed(speed))
    return f"Jogging joint {joint_id} {'positive' if direction else 'negative'}."


def jog_coord(axis_id: int, direction: int, speed: int = 20) -> str:
    """
    Continuously jog a Cartesian axis.

    Args:
        axis_id: 1=x, 2=y, 3=z, 4=rx, 5=ry, 6=rz
        direction: 0 = negative, 1 = positive
        speed: Speed 1-100
    """
    mc = get_mc()
    mc.jog_coord(axis_id, direction, _validate_speed(speed))
    return f"Jogging axis {axis_id} {'positive' if direction else 'negative'}."


def jog_increment_angle(joint_id: int, increment: float, speed: int = 20) -> str:
    """Move a joint by an incremental step (degrees)."""
    mc = get_mc()
    mc.jog_increment_angle(joint_id, increment, _validate_speed(speed))
    return f"Joint {joint_id} incremented by {increment}°."


def jog_increment_coord(axis_id: int, increment: float, speed: int = 20) -> str:
    """Move a Cartesian axis by an incremental step (mm or degrees)."""
    mc = get_mc()
    mc.jog_increment_coord(axis_id, increment, _validate_speed(speed))
    return f"Axis {axis_id} incremented by {increment}."


# ══════════════════════════════════════════════════════════════════════════════
# MOTION CONTROL
# ══════════════════════════════════════════════════════════════════════════════

def pause_motion() -> str:
    """Pause the current movement."""
    mc = get_mc()
    mc.pause()
    return "Motion paused."


def resume_motion() -> str:
    """Resume paused movement."""
    mc = get_mc()
    mc.resume()
    return "Motion resumed."


def stop_motion() -> str:
    """Stop all movement immediately."""
    mc = get_mc()
    mc.stop()
    return "All motion stopped."


def is_moving() -> bool:
    """Check if the robot is currently moving."""
    mc = get_mc()
    return mc.is_moving() == 1


def is_in_position(data: List[float], is_coords: bool = False) -> bool:
    """
    Check if robot is at the specified position.

    Args:
        data: 6 joint angles or 6 Cartesian coords
        is_coords: True if data is coords, False if angles
    """
    mc = get_mc()
    flag = 1 if is_coords else 0
    return mc.is_in_position(data, flag) == 1


# ══════════════════════════════════════════════════════════════════════════════
# STATUS / QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def get_angles_and_coords() -> Dict[str, List[float]]:
    """Get both joint angles and Cartesian coords in one call."""
    mc = get_mc()
    data = mc.get_angles_coords()
    if data and len(data) >= 12:
        return {
            "angles": data[:6],
            "coords": data[6:12],
        }
    return {"angles": get_angles(), "coords": get_coords()}


def get_joint_limits(joint_id: int) -> Dict[str, float]:
    """Get the min/max angle limits for a joint."""
    mc = get_mc()
    return {
        "min": mc.get_joint_min_angle(joint_id),
        "max": mc.get_joint_max_angle(joint_id),
    }


def forward_kinematics(angles: List[float]) -> List[float]:
    """Compute forward kinematics: joint angles → Cartesian coords."""
    mc = get_mc()
    return mc.angles_to_coords(angles)


def inverse_kinematics(coords: List[float], current_angles: List[float] = None) -> List[float]:
    """Compute inverse kinematics: Cartesian coords → joint angles."""
    mc = get_mc()
    if current_angles is None:
        current_angles = mc.get_angles()
    return mc.solve_inv_kinematics(coords, current_angles)


# ══════════════════════════════════════════════════════════════════════════════
# SERVO CONTROL
# ══════════════════════════════════════════════════════════════════════════════

def is_servo_enabled(servo_id: int) -> bool:
    """Check if a specific servo is enabled."""
    mc = get_mc()
    return mc.is_servo_enable(servo_id) == 1


def is_all_servos_enabled() -> bool:
    """Check if all servos are enabled."""
    mc = get_mc()
    return mc.is_all_servo_enable() == 1


def focus_servo(servo_id: int) -> str:
    """Enable (lock) a single servo."""
    mc = get_mc()
    mc.focus_servo(servo_id)
    return f"Servo {servo_id} enabled."


def release_servo(servo_id: int) -> str:
    """Release (unlock) a single servo for free movement."""
    mc = get_mc()
    mc.release_servo(servo_id)
    return f"Servo {servo_id} released."


def get_servo_temps() -> List[float]:
    """Get temperature of all servos in °C."""
    mc = get_mc()
    return mc.get_servo_temps()


def get_servo_voltages() -> List[float]:
    """Get voltage of all servos."""
    mc = get_mc()
    return mc.get_servo_voltages()


def get_servo_speeds() -> List[float]:
    """Get speed of all servos in steps/s."""
    mc = get_mc()
    return mc.get_servo_speeds()


def joint_brake(joint_id: int) -> str:
    """Emergency brake on a moving joint."""
    mc = get_mc()
    mc.joint_brake(joint_id)
    return f"Emergency brake applied to joint {joint_id}."


# ══════════════════════════════════════════════════════════════════════════════
# LED / COLOR
# ══════════════════════════════════════════════════════════════════════════════

def set_led_color(r: int, g: int, b: int) -> str:
    """
    Set the RGB LED color on the end-effector (Atom).

    Args:
        r, g, b: Color values 0-255
    """
    mc = get_mc()
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    mc.set_color(r, g, b)
    return f"LED set to RGB({r}, {g}, {b})."


# ══════════════════════════════════════════════════════════════════════════════
# END-EFFECTOR IO
# ══════════════════════════════════════════════════════════════════════════════

def set_digital_output(pin: int, signal: int) -> str:
    """Set a digital output pin on the end-effector (Atom). 0=LOW, 1=HIGH."""
    mc = get_mc()
    mc.set_digital_output(pin, signal)
    return f"Pin {pin} set to {signal}."


def get_digital_input(pin: int) -> int:
    """Read a digital input pin on the end-effector."""
    mc = get_mc()
    return mc.get_digital_input(pin)


def set_basic_output(pin: int, signal: int) -> str:
    """Set a digital output on the base (M5/Pi). 0=LOW, 1=HIGH."""
    mc = get_mc()
    mc.set_basic_output(pin, signal)
    return f"Base pin {pin} set to {signal}."


def get_basic_input(pin: int) -> int:
    """Read a digital input on the base."""
    mc = get_mc()
    return mc.get_basic_input(pin)


# ══════════════════════════════════════════════════════════════════════════════
# GRIPPER / END-EFFECTOR (fake finger — no gripper hardware)
# ══════════════════════════════════════════════════════════════════════════════

def set_gripper_state(state: int, speed: int = 50, gripper_type: int = 1) -> str:
    """
    Set gripper open/close state.
    state: 0=open, 1=close
    gripper_type: 1=adaptive, 2=five-finger, 3=parallel, 4=flexible
    """
    mc = get_mc()
    mc.set_gripper_state(state, _validate_speed(speed), gripper_type)
    return f"Gripper {'closed' if state else 'opened'}."


def set_gripper_value(value: int, speed: int = 50, gripper_type: int = 1) -> str:
    """Set gripper position (0-100)."""
    mc = get_mc()
    mc.set_gripper_value(value, _validate_speed(speed), gripper_type)
    return f"Gripper set to {value}."


def get_gripper_value(gripper_type: int = 1) -> int:
    """Read current gripper position."""
    mc = get_mc()
    return mc.get_gripper_value(gripper_type)


# ══════════════════════════════════════════════════════════════════════════════
# COORDINATE FRAMES
# ══════════════════════════════════════════════════════════════════════════════

def set_tool_reference(coords: List[float]) -> str:
    """Set the tool coordinate reference frame [x,y,z,rx,ry,rz]."""
    mc = get_mc()
    mc.set_tool_reference(coords)
    return f"Tool reference set to {coords}."


def get_tool_reference() -> List[float]:
    """Get the current tool coordinate reference frame."""
    mc = get_mc()
    return mc.get_tool_reference()


def set_world_reference(coords: List[float]) -> str:
    """Set the world coordinate reference frame."""
    mc = get_mc()
    mc.set_world_reference(coords)
    return f"World reference set to {coords}."


def get_world_reference() -> List[float]:
    """Get the current world coordinate reference frame."""
    mc = get_mc()
    return mc.get_world_reference()


def set_movement_type(move_type: int) -> str:
    """Set movement type: 0 = moveJ (angular), 1 = moveL (linear)."""
    mc = get_mc()
    mc.set_movement_type(move_type)
    return f"Movement type set to {'linear' if move_type else 'angular'}."


def set_reference_frame(frame_type: int) -> str:
    """Set reference frame: 0 = base frame, 1 = tool frame."""
    mc = get_mc()
    mc.set_reference_frame(frame_type)
    return f"Reference frame set to {'tool' if frame_type else 'base'}."


# ══════════════════════════════════════════════════════════════════════════════
# ENCODER CONTROL
# ══════════════════════════════════════════════════════════════════════════════

def get_encoders() -> List[int]:
    """Get encoder values for all 6 joints."""
    mc = get_mc()
    return mc.get_encoders()


def set_encoders(encoders: List[int], speed: int = 30) -> str:
    """Set encoder values for all joints (0-4096 per joint)."""
    mc = get_mc()
    mc.set_encoders(encoders, _validate_speed(speed))
    return f"Encoders set to {encoders}."


# ══════════════════════════════════════════════════════════════════════════════
# PRE-PROGRAMMED GESTURES
# ══════════════════════════════════════════════════════════════════════════════

def back_zero(speed: int = 40) -> str:
    """Move all joints to home position [0,0,0,0,0,0]."""
    mc = get_mc()
    mc.send_angles([0, 0, 0, 0, 0, 0], _validate_speed(speed))
    time.sleep(3)
    return "Robot returned to zero position."


def move_to_top_view() -> str:
    """Move to the overhead / bird's-eye camera viewing position."""
    cfg = get_config()
    mc = get_mc()
    mc.send_angles(cfg.top_view_angles, 10)
    time.sleep(3)
    return "Moved to top-view position."


def head_shake() -> str:
    """Perform a head-shake gesture (left-right wrist motion)."""
    mc = get_mc()
    mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
    time.sleep(1)
    for _ in range(2):
        mc.send_angle(5, 30, 80)
        time.sleep(0.5)
        mc.send_angle(5, -30, 80)
        time.sleep(0.5)
    mc.send_angles([0, 0, 0, 0, 0, 0], 40)
    time.sleep(2)
    return "Head shake complete."


def head_nod() -> str:
    """Perform a head-nod gesture (up-down wrist motion)."""
    mc = get_mc()
    mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
    time.sleep(1)
    for _ in range(2):
        mc.send_angle(4, 13, 70)
        time.sleep(0.5)
        mc.send_angle(4, -20, 70)
        time.sleep(1)
        mc.send_angle(4, 13, 70)
        time.sleep(0.5)
    mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
    time.sleep(1)
    return "Head nod complete."


def head_dance() -> str:
    """Perform a fun dance gesture."""
    mc = get_mc()
    mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
    time.sleep(1)
    mc.send_angles([-0.17, -94.3, 118.91, -39.9, 59.32, -0.52], 80)
    time.sleep(1.2)
    mc.send_angles([67.85, -3.42, -116.98, 106.52, 23.11, -0.52], 80)
    time.sleep(1.7)
    mc.send_angles([-38.14, -115.04, 116.63, 69.69, 3.25, -11.6], 80)
    time.sleep(1.7)
    mc.send_angles([2.72, -26.19, 140.27, -110.74, -6.15, -11.25], 80)
    time.sleep(1)
    mc.send_angles([0, 0, 0, 0, 0, 0], 80)
    time.sleep(2)
    return "Dance complete."


# ══════════════════════════════════════════════════════════════════════════════
# FINGER-TOUCH (replacement for pump pick-and-place)
# ══════════════════════════════════════════════════════════════════════════════

def finger_touch(x: float, y: float, touch_z: float = 90, speed: int = 20) -> str:
    """
    Move the fake-finger end-effector down to touch a point, then retract.

    1. Move above target at safe height
    2. Descend to touch_z
    3. Brief pause (touch)
    4. Retract to safe height

    Args:
        x: Target X in mm (robot base frame)
        y: Target Y in mm (robot base frame)
        touch_z: Z height to descend to for the touch (mm)
        speed: Movement speed 1-100
    """
    cfg = get_config().robot
    mc = get_mc()
    orientation = [cfg.default_rx, cfg.default_ry, cfg.default_rz]
    safe_z = cfg.safe_height

    # Move above target
    logger.info(f"Moving above ({x}, {y}) at safe height {safe_z}")
    mc.send_coords([x, y, safe_z] + orientation, speed, 0)
    time.sleep(3)

    # Descend to touch
    logger.info(f"Descending to touch at z={touch_z}")
    mc.send_coords([x, y, touch_z] + orientation, speed, 0)
    time.sleep(3)

    # Brief touch pause
    time.sleep(0.5)

    # Retract
    logger.info("Retracting to safe height")
    mc.send_coords([x, y, safe_z] + orientation, speed, 0)
    time.sleep(3)

    return f"Touched point ({x}, {y}) at z={touch_z}, retracted."


def finger_move(
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    touch_z: float = 90,
    speed: int = 20,
) -> str:
    """
    Move from start point to end point at touch height (drag/slide motion).
    Useful for pushing objects. The fake finger descends at start, slides to
    end, then retracts.

    Args:
        start_x, start_y: Start XY in robot frame (mm)
        end_x, end_y: End XY in robot frame (mm)
        touch_z: Height for the sliding motion
        speed: Speed 1-100
    """
    cfg = get_config().robot
    mc = get_mc()
    orientation = [cfg.default_rx, cfg.default_ry, cfg.default_rz]
    safe_z = cfg.safe_height

    # Move above start
    mc.send_coords([start_x, start_y, safe_z] + orientation, speed, 0)
    time.sleep(3)

    # Descend at start
    mc.send_coords([start_x, start_y, touch_z] + orientation, speed, 0)
    time.sleep(3)

    # Slide to end
    mc.send_coords([end_x, end_y, touch_z] + orientation, max(speed - 5, 1), 1)
    time.sleep(4)

    # Retract
    mc.send_coords([end_x, end_y, safe_z] + orientation, speed, 0)
    time.sleep(3)

    return f"Slid from ({start_x},{start_y}) to ({end_x},{end_y})."


def get_robot_status() -> Dict[str, Any]:
    """Get a comprehensive snapshot of the robot's current state."""
    mc = get_mc()
    try:
        angles = mc.get_angles()
    except Exception:
        angles = None
    try:
        coords = mc.get_coords()
    except Exception:
        coords = None
    try:
        powered = mc.is_power_on()
    except Exception:
        powered = None
    try:
        moving = mc.is_moving()
    except Exception:
        moving = None
    try:
        temps = mc.get_servo_temps()
    except Exception:
        temps = None

    return {
        "powered_on": powered,
        "is_moving": moving,
        "joint_angles": angles,
        "tcp_coords": coords,
        "servo_temps": temps,
    }
