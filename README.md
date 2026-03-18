# MyCobotAgent

**VLM/VLA Embodied Agent for myCobot 280 Pi** — Control a 6-DOF robot arm with natural language using vision-language models, served as MCP tools for agentic LLM interaction.

## Demo: Robot Typing on a Laptop Keyboard

![Robot typing demo — 3-camera view](demo_typing_3view.gif)

*The myCobot 280 types "sad" on a real laptop keyboard. Three simultaneous camera views: overhead RealSense D435i (RGBD), side-view webcam, and full workspace overview. The finger slides smoothly between keys, dipping to press each one.*

---

Inspired by [TommyZihao/vlm_arm](https://github.com/TommyZihao/vlm_arm). Adapted for remote control over Ethernet/TCP from a Windows host, with Azure OpenAI GPT-4o as the VLM backbone.

## Architecture

```
┌──────────────── Windows Laptop ─────────────────┐
│                                                   │
│  MCP Server (src/mcp_server.py)                   │
│    ├── 40+ MCP Tools (motion, VLM, camera, etc.)  │
│    ├── Azure GPT-4o (VLM + Agent LLM)             │
│    └── MyCobot280Socket ──── TCP ────┐            │
│                                       │            │
│  Camera Client (src/cobot/camera.py)  │            │
│    └── HTTP GET ──────────────────┐   │            │
└───────────────────────────────────┼───┼────────────┘
                                    │   │
                              Ethernet Link
                                    │   │
┌───────────────────────────────────┼───┼────────────┐
│          Raspberry Pi (on robot)  │   │             │
│                                   ▼   ▼             │
│  pi_camera_server.py (port 8080)  │   │             │
│    └── MJPEG stream + snapshots   │   │             │
│                                       │             │
│  myCobot TCP Server (port 9000)  ◄────┘             │
│    └── pymycobot commands                           │
└─────────────────────────────────────────────────────┘
```

## Project Structure

```
MyCobotAgent/
├── config.yaml                  # Robot IP, camera URL, Azure API keys
├── requirements.txt             # Python dependencies
├── pi_camera_server.py          # Deploy ON the Pi — camera MJPEG server
├── src/
│   ├── mcp_server.py            # MCP server — all tools exposed here
│   ├── cobot/
│   │   ├── config.py            # YAML config loader
│   │   ├── connection.py        # MyCobot280Socket connection manager
│   │   ├── camera.py            # Camera stream client (reads from Pi)
│   │   └── actions.py           # All atomic robot actions (50+ functions)
│   ├── vlm/
│   │   ├── vlm_client.py        # Azure GPT-4o VLM API calls
│   │   ├── grounding.py         # Bounding-box post-processing & visualization
│   │   └── pipeline.py          # High-level VLM pipelines (vlm_move, vlm_vqa)
│   ├── calibration/
│   │   └── eye2hand.py          # Pixel → robot coordinate transform
│   └── agent/
│       ├── planner.py           # LLM agent planner (GPT-4o)
│       └── executor.py          # Safe action dispatch (no eval!)
├── temp/                        # Runtime image captures
└── visualizations/              # Saved VLM detection visualizations
```

## Quick Start

### 1. Prerequisites

- **myCobot 280 Pi** connected to your laptop via Ethernet
- Both devices on the same subnet (e.g., Pi: `192.168.1.159`, Laptop: `192.168.1.x`)
- Python 3.10+ on Windows

### 2. Pi Setup (SSH into the Raspberry Pi)

```bash
# a) Start the myCobot TCP server (if not already running via MyStudio)
#    The server listens on port 9000 and bridges TCP commands to the robot's serial bus
python3 Server_280.py

# b) Start the camera streaming server
pip3 install flask opencv-python
python3 pi_camera_server.py --port 8080
```

The Pi should now be serving:
- Robot commands on `tcp://PI_IP:9000`
- Camera stream on `http://PI_IP:8080/video`

### 3. Laptop Setup (Windows)

```bash
cd MyCobotAgent

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure

Edit `config.yaml` with your Pi's IP address:

```yaml
robot:
  host: "192.168.1.159"   # ← Your Pi's IP
  port: 9000

camera:
  stream_url: "http://192.168.1.159:8080/video"
  snapshot_url: "http://192.168.1.159:8080/snapshot"
```

### 5. Run the MCP Server

```bash
# For use with Claude Desktop or MCP-compatible clients (stdio transport)
python -m src.mcp_server

# For remote/HTTP access
python -m src.mcp_server --http
```

### 6. Configure Claude Desktop (optional)

Add to your Claude Desktop config (`claude_desktop_config.json`):

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

## MCP Tools Reference

### System & Power
| Tool | Description |
|------|-------------|
| `robot_power_on` | Power on the robot |
| `robot_power_off` | Power off the robot |
| `robot_release_servos` | Release all servos for free movement |
| `robot_lock_servos` | Lock all servos |
| `robot_get_error` | Check error status |

### Motion — Joint Space
| Tool | Description |
|------|-------------|
| `robot_home` | Return to [0,0,0,0,0,0] |
| `robot_send_angle` | Move one joint (1-6) |
| `robot_send_angles` | Move all 6 joints |

### Motion — Cartesian Space
| Tool | Description |
|------|-------------|
| `robot_send_coords` | Move to [x,y,z,rx,ry,rz] |
| `robot_move_to_xy` | Move to XY at safe height |
| `robot_move_to_top_view` | Overhead camera position |

### End-Effector (Finger)
| Tool | Description |
|------|-------------|
| `robot_finger_touch` | Touch a point and retract |
| `robot_finger_move` | Slide/push from A to B |

### Vision (VLM) 🔥
| Tool | Description |
|------|-------------|
| `vlm_move_object` | Vision-guided push: "push red block to star" |
| `vlm_touch_object` | Vision-guided touch: find and touch an object |
| `vlm_ask_question` | Visual QA: ask about the workspace |

### Agent (Autonomous Planning) 🤖
| Tool | Description |
|------|-------------|
| `agent_execute` | Give high-level instruction, agent plans & executes |

### Camera
| Tool | Description |
|------|-------------|
| `camera_capture` | Move to top-view and capture image |
| `camera_snapshot_only` | Capture without moving arm |

### LED & Gestures
| Tool | Description |
|------|-------------|
| `robot_set_led` | Set RGB LED color |
| `robot_set_led_by_description` | Set LED by description ("ocean blue") |
| `robot_head_shake` / `nod` / `dance` | Gesture animations |

## Eye-to-Hand Calibration

The system uses a 2-point linear interpolation to convert pixel coordinates (from the overhead camera) to robot workspace coordinates. **You must calibrate for your setup:**

1. Move arm to a known position: use `robot_move_to_xy(x, y)` 
2. Note the robot coordinates from `robot_get_coords()`
3. Take a photo with `camera_capture()` and note the pixel coordinates of where the finger is pointing
4. Repeat for a second point
5. Update calibration: `calibration_update_points(pixel_1, robot_1, pixel_2, robot_2)`

For better accuracy with 3+ points, the system also supports affine transform calibration.

## VLM Pipeline

The vision pipeline works as follows:

```
User instruction: "push the red block onto the star"
         │
         ▼
┌─ Move to top-view position ─┐
│  Capture overhead photo      │
└──────────┬───────────────────┘
           ▼
┌─ GPT-4o Vision API ─────────────────────────┐
│  Image + prompt → detect start/end objects   │
│  Returns: bounding boxes (normalized 0-999)  │
└──────────┬───────────────────────────────────┘
           ▼
┌─ Post-processing ───────────────────────┐
│  Normalize → pixel coords → centers     │
│  Draw visualization with bboxes/arrows  │
└──────────┬──────────────────────────────┘
           ▼
┌─ Eye-to-hand calibration ───────┐
│  Pixel (u,v) → Robot (X,Y) mm  │
└──────────┬──────────────────────┘
           ▼
┌─ Robot motion ──────────────────────────────┐
│  finger_move(start_x,y → end_x,y) at z=90  │
│  (above → descend → slide → retract)        │
└─────────────────────────────────────────────┘
```

## Credits

- Inspired by [TommyZihao/vlm_arm](https://github.com/TommyZihao/vlm_arm) (同济子豪兄)
- Robot: [Elephant Robotics myCobot 280 Pi](https://www.elephantrobotics.com/en/mycobot-en/)
- VLM: Azure OpenAI GPT-4o
- Protocol: [Model Context Protocol (MCP)](https://modelcontextprotocol.io)

## License

MIT
