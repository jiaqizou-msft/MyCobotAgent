"""Press a key with robot while keyboard stream is listening."""
import socket
import time
import threading
import json
import sys
from pymycobot import MyCobot280Socket

HOST = "192.168.0.4"
PORT = 22133
key = sys.argv[1] if len(sys.argv) > 1 else "i"

# Load position
with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\keyboard_taught.json") as f:
    taught = json.load(f)["keys"]
with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\learned_corrections.json") as f:
    corr = json.load(f)

coords = list(taught[key]["coords"][:3])
arm = taught[key].get("arm", "right")
if key in corr:
    coords[0] += corr[key]["dx"]
    coords[1] += corr[key]["dy"]
x, y, z = coords
robot_ip = "10.105.230.93" if arm == "right" else "10.105.230.94"

print(f"╔═══════════════════════════════════════════╗")
print(f"║  STREAM KEY TEST: '{key}'")
print(f"║  Arm: {arm}  Robot: {robot_ip}")
print(f"║  Position: ({x:.1f}, {y:.1f}, {z:.1f})")
print(f"╚═══════════════════════════════════════════╝")

# Start keyboard stream in background
stream_data = []
stream_raw = b""


def listen_keyboard(duration=15):
    global stream_raw
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(duration + 5)
    s.connect((HOST, PORT))
    req = f"GET /streams/keyboard HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nAccept: */*\r\n\r\n"
    s.sendall(req.encode())

    start = time.time()
    s.settimeout(2)
    while time.time() - start < duration:
        try:
            chunk = s.recv(4096)
            if chunk:
                stream_raw += chunk
                text = chunk.decode("utf-8", errors="replace")
                # Parse out body content
                for line in text.split("\n"):
                    line = line.strip()
                    if line and len(line) > 5 and not line.startswith("HTTP"):
                        stream_data.append(line)
                        print(f"  [STREAM] {line[:150]}")
        except socket.timeout:
            pass
    s.close()


print("  Starting keyboard stream listener...")
t = threading.Thread(target=listen_keyboard, daemon=True)
t.start()
time.sleep(2)

# Connect robot
print(f"  Connecting {arm} arm...", end="", flush=True)
mc = MyCobot280Socket(robot_ip, 9000)
time.sleep(1)
mc.power_on()
time.sleep(1)
print(" OK")
mc.set_color(255, 165, 0)

# Press key
hover_z = z + 15
press_z = z - 3
print(f"  Moving to hover...")
mc.send_coords([x, y, hover_z, 0, 180, 90], 15, 0)
time.sleep(3)

print(f"  >>> PRESSING '{key}' <<<")
mc.send_coords([x, y, press_z, 0, 180, 90], 8, 0)
time.sleep(0.8)
print(f"  >>> RELEASING <<<")
mc.send_coords([x, y, hover_z, 0, 180, 90], 8, 0)
time.sleep(3)

# Wait for stream data
time.sleep(2)

# Results
print()
print(f"  ═══════════════════════════════════════")
print(f"  Stream data received: {len(stream_raw)} bytes")
print(f"  Parsed events: {len(stream_data)}")
for i, d in enumerate(stream_data[:15]):
    print(f"    {i+1}: {d[:200]}")
if not stream_data:
    print(f"    (no keyboard events detected)")
print(f"  ═══════════════════════════════════════")

mc.set_color(0, 255, 0) if stream_data else mc.set_color(255, 0, 0)
