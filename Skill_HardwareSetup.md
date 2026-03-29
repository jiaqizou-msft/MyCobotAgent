# Surface Laptop Robot — Hardware Setup & Connection Skill

## Last Updated: 2026-03-23

This skill documents all hardware connections, troubleshooting, and reconnection procedures for the dual-arm robot keyboard/touchpad testing system.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Dev Machine (Windows, this PC)                             │
│  IP: 10.105.230.1 (Ethernet) + 192.168.0.100               │
│                                                             │
│  USB connections:                                           │
│    Camera 0 — Built-in webcam (640x480)                     │
│    Camera 1 — USB camera (640x480)                          │
│    Camera 2 — Intel RealSense D435i RGB (640x480)           │
│    Camera 3 — Overview cam (UNRELIABLE — often fails)       │
│                                                             │
│  Ethernet (USB-to-Ethernet adapter → switch):               │
│    10.105.230.93 — Right arm Pi (myCobot 280 Pi)            │
│    10.105.230.94 — Left arm Pi (myCobot 280 Pi)             │
│    192.168.0.4   — DUT (Surface laptop, runs Gambit)        │
└─────────────────────────────────────────────────────────────┘
```

### Network Topology
- Dev machine connects via **USB-to-Ethernet adapter** to a switch
- Both robot Pis and the DUT are on the same switch
- Two subnets coexist on the same adapter:
  - `10.105.230.0/24` — robot arms
  - `192.168.0.0/24` — DUT

---

## 2. Robot Arms (myCobot 280 Pi)

### Hardware
| Component | Right Arm | Left Arm |
|-----------|-----------|----------|
| IP Address | 10.105.230.93 | 10.105.230.94 |
| TCP Port | 9000 | 9000 |
| Pi User | er | er |
| Pi Password | Elephant | Elephant |
| Serial Port | /dev/ttyAMA0 | /dev/ttyAMA0 |
| Serial Baud | 1000000 | 1000000 |
| Keyboard Side | Right half (7-0, U-P, J-', M-/) | Left half (`-6, Q-T, A-G, Z-B) |
| Key Z Height | ~60-65mm | ~47mm |

### Connection Chain
```
Dev Machine → TCP (port 9000) → Pi Raspberry Pi → serial (/dev/ttyAMA0) → myCobot 280
```

The TCP-serial bridge (`tcp_serial_bridge.py`) runs on each Pi, relaying `pymycobot` protocol frames.

### Connect Procedure

```python
from pymycobot import MyCobot280Socket
import time

# Connect (may timeout ~21s if Pi is booting)
mc = MyCobot280Socket("10.105.230.93", 9000)  # right arm
time.sleep(1)

# Power on servos
mc.power_on()
time.sleep(1)

# Verify — angles read is flaky, use retries
for _ in range(15):
    a = mc.get_angles()
    if a and a != -1:
        print(f"OK: {a}")
        break
    time.sleep(0.3)
```

### Reconnection After Disconnect

**Symptom: `TimeoutError: [WinError 10060]`**

1. **Check USB Ethernet adapter** — is it plugged in?
   ```powershell
   ipconfig | Select-String "10.105"
   # Should show 10.105.230.1
   ```
   If missing: replug the USB-to-Ethernet adapter.

2. **Check Pi is on the network:**
   ```powershell
   ping -n 1 10.105.230.93   # right arm
   ping -n 1 10.105.230.94   # left arm
   ```

3. **If Pi pings but port 9000 fails** — restart the TCP bridge:
   ```python
   import paramiko
   ssh = paramiko.SSHClient()
   ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
   ssh.connect("10.105.230.93", username="er", password="Elephant", timeout=10)
   ssh.exec_command("pkill -f tcp_serial_bridge; sleep 1; nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
   time.sleep(3)
   ssh.close()
   ```
   Or use helper scripts:
   ```powershell
   python scripts/deploy/start_left_bridge.py
   python scripts/deploy/restart_bridges.py
   ```

4. **If Pi doesn't ping** — the Pi lost its IP or is powered off:
   - Check Pi power (red LED = power, green LED = SD activity)
   - Check Ethernet cable from switch to Pi
   - If Pi booted without static IP:
     ```bash
     sudo ip addr add 10.105.230.94/24 dev eth0
     sudo ip link set eth0 up
     ```
   - For persistent static IP, edit `/etc/dhcpcd.conf` on the Pi:
     ```
     interface eth0
     static ip_address=10.105.230.93/24
     ```

5. **If nothing works** — power cycle the Pi (unplug/replug USB-C power).

### Common Robot Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `get_angles()` returns `-1` | Servos not powered | `mc.power_on()` then retry with 0.3s delays |
| `get_coords()` returns `-1` | Need a move first | Send `send_angles([0,0,0,0,0,0], 15)` then re-read |
| Arm doesn't move | Servos locked/released | `mc.power_on()` or `mc.focus_all_servos()` |
| `MyCobot280DataException` | Position out of reach | X must be -281.45 to 281.45 |
| Multiple chars typed | Key auto-repeat | Reduce hold: `time.sleep(0.03)` max after press |
| Wrong key pressed | Calibration offset | Use `iterative_calibration.py` to learn corrections |

---

## 3. Cameras

### Available Sources

| Camera | Index/URL | Role | Reliability |
|--------|-----------|------|-------------|
| Built-in webcam | `cv2.VideoCapture(1)` | skip (face cam) | Reliable but useless |
| USB camera (front) | `cv2.VideoCapture(0)` | front_workspace | Reliable |
| Intel RealSense D435i | varies (2 or 3) | overhead | Reliable but INDEX SHIFTS |
| USB camera (side) | `cv2.VideoCapture(4)` | side_view | Reliable |
| Pi camera (EMEET) | `http://10.105.230.93:8080/snapshot` | close_up | Reliable |
| DUT screen | Gambit API + PowerShell | dut_screen | Slow (~10s) |

### CRITICAL: Camera Indices Are NOT Stable

**USB camera indices shift when devices are plugged/unplugged.** The RealSense has appeared as index 2, 3, or even failed entirely across different sessions. **Never hardcode camera indices.**

### Camera Mapping System

Use `data/camera_map.json` to store the current camera→role mapping. Run the mapping tool after any USB change:

```powershell
python scripts/calibration/map_cameras.py          # interactive UI
python scripts/calibration/map_cameras.py --auto    # auto-assign
```

The mapping file stores:
```json
{
  "roles": {
    "front_workspace": "0",
    "overhead": "3",
    "side_view": "4",
    "close_up": "pi"
  }
}
```

All scripts (iterative_calibration.py, etc.) load from `camera_map.json` at startup and validate each camera works before using it.

### Capture Best Practices

```python
def capture_usb(idx):
    cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
    if cap.isOpened():
        for _ in range(3):   # always flush stale frames
            cap.grab()
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            return frame
    return None
```

### Pi Camera Server

Runs on the right arm Pi (`10.105.230.93:8080`):
- Snapshot: `GET http://10.105.230.93:8080/snapshot` → JPEG
- Stream: `GET http://10.105.230.93:8080/video` → MJPEG

---

## 4. DUT (Device Under Test)

| Item | Value |
|------|-------|
| IP | 192.168.0.4 |
| Device | Surface Laptop (900_MAA) |
| OS | Windows 11 Enterprise (26200) |
| Remote API | Gambit v2.26.319.300 on port 22133 |
| Swagger | http://192.168.0.4:22133/swagger |

### Gambit Quick Reference
```python
BASE = "http://192.168.0.4:22133"
httpx.get(f"{BASE}/alive")                                    # health check
httpx.post(f"{BASE}/Process/run", json={...})                  # run command
httpx.post(f"{BASE}/Process/start", json={...})                # start process
httpx.get(f"{BASE}/streams/cursor/current")                    # cursor pos
httpx.get(f"{BASE}/injection/keys/type", params={"text": "x"}) # inject key
```

### Gambit Plugins
- `Gambit.Plugin.Injection` — keyboard/mouse injection (13 endpoints)
- `Gambit.Plugin.Streams.Raw` — keyboard/mouse/touch streams (8 endpoints)
- `Gambit.Plugin.Sensors` — hardware sensors (19 endpoints)

---

## 5. Full Startup Checklist

```
1. ☐ Plug in USB-to-Ethernet adapter
     → Verify: ipconfig shows 10.105.230.1

2. ☐ Right arm Pi
     → ping 10.105.230.93
     → If no ping: check power + cable
     → If ping but no port 9000: restart bridge via SSH

3. ☐ Left arm Pi
     → ping 10.105.230.94
     → If IP lost: sudo ip addr add 10.105.230.94/24 dev eth0
     → Verify bridge: python scripts/deploy/start_left_bridge.py

4. ☐ DUT
     → curl http://192.168.0.4:22133/alive

5. ☐ Cameras
     → python scripts/calibration/map_cameras.py --auto
     → Or interactive: python scripts/calibration/map_cameras.py
     → Verify data/camera_map.json has correct roles

6. ☐ Robot servo test
     → mc.power_on() + retry get_angles() 15x

7. ☐ Ready for calibration/tests
```

---

## 6. Key Files

| File | Purpose |
|------|---------|
| `tcp_serial_bridge.py` | TCP↔serial relay, deploy to each Pi |
| `pi_camera_server.py` | MJPEG camera server, deploy to right arm Pi |
| `config.yaml` | Main configuration |
| `data/keyboard_taught.json` | Taught key positions (both arms) |
| `data/keyboard_layout_xml.json` | Parsed Ortler keyboard physical layout |
| `data/camera_map.json` | Camera index→role mapping (regenerate after USB changes) |
| `data/learned_corrections.json` | Iteratively learned position corrections |
| `Ortler[DV][English].xml` | Manufacturer keyboard layout |
| `scripts/calibration/reteach_right_arm.py` | Re-teach right arm positions |
| `scripts/calibration/map_cameras.py` | Camera discovery & role assignment UI |
| `scripts/gambit/iterative_calibration.py` | Full calibration + typing demo |
| `scripts/gambit/finetune_arm.py` | Interactive WASD fine-tune controller |
| `scripts/deploy/start_left_bridge.py` | Start bridge on left arm |
| `scripts/deploy/restart_bridges.py` | Restart bridges on both arms |

---

## 7. Learned Gotchas

1. **Camera indices shift on USB reconnect** — always use `camera_map.json`, never hardcode indices. Run `map_cameras.py` after any USB change.
2. **Left arm Pi loses IP on reboot** — needs manual `ip addr add`. Fix via `/etc/dhcpcd.conf`.
3. **`get_angles()` is flaky** — retry 10-15 times with 0.3s delays.
4. **SSH creds**: user `er`, password `Elephant` on both Pis.
5. **Key auto-repeat** — hold time must be <50ms.
6. **USB Ethernet disappears** — if `10.105.230.x` gone from ipconfig, replug adapter.
7. **Gambit plugins** — DLLs must be in `C:\gambit\Plugins\<name>\` directly. Restart Gambit after changes.
8. **DUT screenshot is slow** (~10s) — only capture when needed.
9. **pymycobot socket timeout** — 21s default. Retry once if Pi is booting.
10. **Two subnets on one adapter** — `10.105.230.0/24` (robots) and `192.168.0.0/24` (DUT).
