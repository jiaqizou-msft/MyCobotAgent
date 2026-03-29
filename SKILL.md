---
description: "Control dual myCobot 280 robot arms to physically interact with a Surface laptop — press keyboard keys, type text, swipe/tap touchpad, open/close lid, dance, and verify via Gambit HID stream. Supports drag-teach recording, iterative calibration, multi-camera GIF capture, and autonomous agent planning. IMPORTANT: Decompose complex requests into sequential tool calls."
applyTo: "**"
tools:
  - keyboard_press_key
  - keyboard_type_text
  - touchpad_swipe
  - touchpad_tap
  - robot_home
  - robot_power_on
  - robot_send_coords
  - robot_send_angles
  - robot_get_status
  - robot_finger_touch
  - robot_set_led
  - robot_head_shake
  - robot_head_nod
  - robot_head_dance
  - robot_stop
  - realsense_capture
  - camera_capture
  - vlm_ask_question
  - agent_execute
  - record_action
---

# Surface Laptop Robot — Physical Device Interaction Skill

Dual **myCobot 280 Pi** robot arms physically interact with a Surface laptop keyboard, touchpad, and lid.

## Architecture Overview

See [visualizations/architecture.png](visualizations/architecture.png) for the full diagram.

```
Windows PC ──TCP JSON :9000──► Pi (robot_cache_server.py) ──Serial──► myCobot 280
                                  └─ 10Hz angle cache (works with released servos)

Surface Laptop (DUT) ──Gambit API :22133──► /streams/keyboard (HID verify)
                                           /streams/cursor   (touchpad verify)
```

### Hardware

| Component | Address | Role |
|-----------|---------|------|
| Right arm Pi | 10.105.230.93:9000 | Keyboard right-half, lid open/close |
| Left arm Pi | 10.105.230.94:9000 | Keyboard left-half, touchpad |
| DUT (Surface) | 192.168.0.4:22133 | Gambit API for HID verification |
| SSH creds | er / Elephant | Both Pis |

### Communication Stack

```
CachedRobot (src/cobot/cached_robot.py)
    │  JSON-over-TCP, newline-delimited
    ▼
robot_cache_server.py (on each Pi)
    │  pymycobot direct serial, 10Hz cache poller
    ▼
myCobot 280 (/dev/ttyAMA0 @ 1M baud)
```

**Key commands**: `get_angles` (cached, instant), `send_angles`, `send_coords`, `release` (free servos), `focus` (lock servos), `color`, `power_on`, `ping`.

**Why caching**: `get_angles()` returns -1 when servos are released via the old TCP bridge. The cache server reads angles locally at 10Hz, caches the last valid reading, and serves it to any TCP client — instant, 100% reliable, even with released servos.

### Data Files

| File | Purpose |
|------|---------|
| `data/keyboard_taught.json` | 78 manually drag-taught key positions |
| `data/learned_corrections.json` | 32 per-key Gambit-verified offset corrections |
| `data/taught_actions.json` | Lid open/close dual-arm trajectories |
| `data/keyboard_layout_xml.json` | CAD mm positions from Ortler XML |
| `data/camera_map.json` | USB camera index → role mapping |
| `data/calibration_data.json` | Affine transforms (pixel → robot XY) |

### Gambit Integration

Gambit runs on the DUT and provides HID-level verification:

- **Keyboard stream**: `GET /streams/keyboard` → `{"Key":"A","IsPressed":true}`
  - VK names are PascalCase: `Space`, `Oemcomma`, `Oem1`
  - Single-consumer — must restart Gambit between stream sessions
- **Cursor stream**: `GET /streams/cursor/current` → `{"X":681,"Y":505}`
- **Process run**: `POST /Process/run` — execute commands on DUT

### Camera System

| Camera | Role | Notes |
|--------|------|-------|
| Index 3 | Front workspace | Wide view of both arms |
| Index 4 | Overhead | Flipped 180°, top-down keyboard |
| Index 6 | RealSense D435i | Close-up depth + RGB |

---

## CRITICAL: Action Planning

**Decompose every user request into atomic tool calls.** Each tool = ONE action.

| User says | You call (in order) |
|-----------|-------------------|
| "swipe up and down" | `touchpad_swipe("up")` → `touchpad_swipe("down")` |
| "type hello then scroll" | `keyboard_type_text("hello")` → `touchpad_swipe("down")` |
| "open and close lid 5 times" | Replay `open_lid` → `close_lid` × 5 |
| "press A, B, C" | `keyboard_press_key("a")` → `"b"` → `"c"` |

### Planning rules

- **"and"** = multiple actions, call each separately
- **"then"** = sequential order
- **"X times"** = repeat N times
- **"a few"** = 3, **"several"** = 5, **"many"** = 10
- Call `robot_home()` after multi-step sequences

---

## Available Tools

### Keyboard

| Tool | Args | Description |
|------|------|-------------|
| `keyboard_type_text(text, speed)` | text: string, speed: slow/medium/fast | Type a character string |
| `keyboard_press_key(key)` | key: a-z, 0-9, esc, tab, space, enter | Press single key |

**Typing script**: `python scripts/gambit/type_text.py "text to type"`

**Arm assignments** (avoids center-column collisions):
- Left arm (192.168.0.6): `` ` 1 2 3 4 5 6 Q W E R T Y A S D F G H Caps Tab Shift_L Ctrl_L Fn Win Alt_L Z X C V B ``
- Right arm (192.168.0.5): `` 7 8 9 0 - = U I O P [ ] \ J K L ; ' Enter N M , . / Shift_R ``
- H and Y are on the **left arm** to avoid collision in the center column

**Key press standards**:
- **Short press (default)**: 100ms contact time — press down, sleep 100ms, lift immediately
- **Long press / hold**: Not yet implemented — will be a separate skill when needed
- Key repeat = press held too long. Keep contact at 100ms to avoid repeats.

### Key Press Timing

| Press Type | Contact Duration | Use Case |
|------------|-----------------|----------|
| **Short press** | ~100ms | Standard character/number input (default) |
| **Long press** | >500ms | Not implemented yet — future skill |

The typing script uses a two-stage tap: hover → low hover (8mm) → strike at speed 80 → lift. This ensures contact is ~100ms to avoid key repeats.

**Typing script**: `python scripts/gambit/type_text.py "text to type"`

**Collision avoidance**: For center keys (6, 7, Y, U, G, H, B, N, T, J), the other arm nudges sideways 30mm instead of full retract.

**Concurrency**: While one arm presses, the other arm pre-positions to its next key for faster overall typing speed.

**Arm assignments** (to avoid center-column collisions):
- Left arm (31 keys): \` 1-6, Q W E R T Y, A S D F G H, Z X C V B, Caps, Tab, Shift_L, Ctrl_L, Fn, Win, Alt_L
- Right arm (47 keys): 7-0, U I O P, J K L, N M, and all keys right of center

**Calibration**:
- `python scripts/gambit/quick_recalibrate.py` — teach 3 left + 4 right anchors, affine fit to XML layout
- `python annotate_keys.py` — visual annotation GUI, click 2+ keys on overhead image
- `python scripts/gambit/vision_to_robot.py` — convert annotated pixel positions to robot coords
- Anchor keys: Left = Q, Z, 6 | Right = P, /, 9, N
- All positions stored in `data/keyboard_taught.json` (78 keys)
- Z height: ~47mm for both arms (same end effector)

**Network**: Right arm = 192.168.0.5, Left arm = 192.168.0.6 (cache server on port 9000)

**Cameras**: Camera 1 = overhead (flipped), Camera 2 = front view

### Touchpad

| Tool | Args | Description |
|------|------|-------------|
| `touchpad_swipe(direction)` | up/down/left/right | Scroll gesture |
| `touchpad_tap(x_frac, y_frac)` | 0.0-1.0 each | Click at position |

### Lid Actions

Taught trajectories stored in `data/taught_actions.json`. **Played sequentially** — close first, then open.

| Action | Arm | Description |
|--------|-----|-------------|
| `close_lid` | Left arm (right parks home) | Close laptop lid |
| `open_lid` | Right arm (left parks home) | Open laptop lid |

**Replay code pattern** (sequential close → open):
```python
from src.cobot.cached_robot import CachedRobot
import json, time

with open('data/taught_actions.json') as f:
    actions = json.load(f)

mc_r = CachedRobot('10.105.230.93', 9000)
mc_l = CachedRobot('10.105.230.94', 9000)
mc_r.power_on(); mc_l.power_on()
time.sleep(1)

def replay(name):
    a = actions[name]
    for wr, wl in zip(a['right_waypoints'], a['left_waypoints']):
        mc_r.send_angles(wr, 25)
        mc_l.send_angles(wl, 25)
        time.sleep(0.4)
    time.sleep(1)

# Sequential: close first, then open
replay('close_lid')   # left arm closes
replay('open_lid')    # right arm opens
```

**Teaching**: Run `python scripts/gambit/teach_lid_dual.py` to re-teach. Left arm closes, right arm opens. Each is drag-taught separately with continuous recording via CachedRobot.

**Demo script**: `python scripts/gambit/lid_demo.py` — runs N cycles with multi-camera GIF recording.

### Robot Motion

| Tool | Description |
|------|-------------|
| `robot_home()` | Return arm to [0,0,0,0,0,0] |
| `robot_send_coords(coords, speed)` | Move to [x,y,z,rx,ry,rz] |
| `robot_send_angles(angles, speed)` | Move to joint angles |
| `robot_finger_touch(x, y)` | Touch workspace point |
| `robot_stop()` | Emergency stop |

### Gestures & LED

| Tool | Description |
|------|-------------|
| `robot_head_shake()` | Shake (no) |
| `robot_head_nod()` | Nod (yes) |
| `robot_head_dance()` | Dance animation |
| `robot_set_led(r, g, b)` | LED color 0-255 |

### Vision

| Tool | Description |
|------|-------------|
| `realsense_capture()` | Overhead RGBD image |
| `camera_capture()` | Side-view image |
| `vlm_ask_question(question)` | GPT-4o visual Q&A |

### Recording

| Tool | Description |
|------|-------------|
| `record_action(action, args)` | Execute action with multi-camera GIF recording |

Supported: `"type <text>"`, `"press <key>"`, `"swipe <dir>"`, `"tap"`, `"dance"`, `"shake"`, `"nod"`

---

## Key Scripts

### Teaching & Calibration

| Script | Purpose |
|--------|---------|
| `scripts/gambit/teach_lid.py` | Drag-teach lid open/close (CachedRobot, continuous recording) |
| `scripts/gambit/teach_touchpad.py` | Teach touchpad center via cursor stream |
| `scripts/gambit/anchor_calibrate.py` | 3-anchor teach → affine → stream verify |
| `scripts/gambit/stream_calibrate.py` | Per-key Gambit stream verification |
| `scripts/gambit/quick_calibrate.py` | Fast all-key calibration |
| `scripts/calibration/teach_keyboard.py` | Manual drag-teach single arm |
| `scripts/calibration/teach_dual_arm.py` | Manual drag-teach both arms |

### Demos

| Script | Purpose |
|--------|---------|
| `scripts/gambit/type_demo.py` | Type strings with 3-camera GIF + stream verify |
| `scripts/gambit/robot_dance.py` | Dual-arm synchronized dance with GIF |

### Deployment

| Script | Purpose |
|--------|---------|
| `scripts/deploy/deploy_cache_server.py` | Deploy robot_cache_server.py to both Pis |
| `scripts/deploy/restart_bridges.py` | Restart old TCP bridges (fallback) |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection timeout to Pi | Run `python scripts/deploy/deploy_cache_server.py` |
| `get_angles()` returns -1 | Cache server not running; redeploy |
| Gambit stream "unable to add consumer" | Restart Gambit: `GET /installer/restart` |
| Camera index shifted | Run `python scripts/calibration/map_cameras.py` |
| Key misses in stream | Clear events before press, wait 1s after release |
| Left arm unreachable | Check dhcpcd.conf static IP on Pi |

## Workspace Constants

- **Key pitch**: 19mm horizontal, 18.5mm row pitch
- **Hover Z**: 145mm, **Press Z**: 142mm, **Safe Z**: 200mm
- **Touchpad offset**: (84mm, 110mm) from keyboard origin, size 111×90mm
- **Joint limits**: J1 ±168°, J2 ±135°, J3 ±150°, J4 ±145°, J5 ±160°, J6 ±180°

## MCP Server Configuration

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mycobot": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "C:\\Users\\jiaqizou\\MyCobotAgent"
    }
  }
}
```
