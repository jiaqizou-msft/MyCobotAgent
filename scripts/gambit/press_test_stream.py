"""
Press a key and detect it via Gambit keyboard stream.
No Notepad needed — pure HID-level detection.

Usage:
  python press_test_stream.py i
  python press_test_stream.py a
"""
import sys
import json
import time
import threading
import httpx
from pymycobot import MyCobot280Socket

GAMBIT = "http://192.168.0.4:22133"
key = sys.argv[1] if len(sys.argv) > 1 else "i"

# Load position
with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\keyboard_taught.json") as f:
    taught = json.load(f)["keys"]
with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\learned_corrections.json") as f:
    corr = json.load(f)

if key not in taught:
    print(f"Key '{key}' not in taught positions")
    sys.exit(1)

coords = list(taught[key]["coords"][:3])
arm = taught[key].get("arm", "right")
if key in corr:
    coords[0] += corr[key]["dx"]
    coords[1] += corr[key]["dy"]

x, y, z = coords
ip = "10.105.230.93" if arm == "right" else "10.105.230.94"

print(f"╔════════════════════════════════════════╗")
print(f"║  KEY TEST (Stream Mode): '{key}'")
print(f"║  Arm: {arm}  ({ip})")
print(f"║  Position: ({x:.1f}, {y:.1f}, {z:.1f})")
print(f"╚════════════════════════════════════════╝")

# --- Keyboard stream listener ---
kb_events = []
stream_stop = threading.Event()
stream_ready = threading.Event()


def listen_keyboard():
    """Listen to /streams/keyboard in background."""
    try:
        with httpx.stream("GET", f"{GAMBIT}/streams/keyboard",
                          timeout=httpx.Timeout(connect=30, read=30, write=5, pool=5)) as resp:
            stream_ready.set()
            buffer = ""
            for chunk in resp.iter_text():
                if stream_stop.is_set():
                    break
                buffer += chunk
                # Try to parse JSON lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, list):
                            continue  # initial key list, skip
                        kb_events.append(obj)
                    except json.JSONDecodeError:
                        # Might be raw text event
                        if len(line) < 200:
                            kb_events.append({"raw": line})
    except Exception as e:
        stream_ready.set()  # unblock even on error
        if not stream_stop.is_set():
            print(f"  [Stream error: {e}]")


# --- Cursor stream (quick snapshot) ---
def get_cursor():
    try:
        r = httpx.get(f"{GAMBIT}/streams/cursor/current", timeout=5)
        return r.json()
    except:
        return None


# Start keyboard listener
print("  Starting keyboard stream...", end="", flush=True)
kb_thread = threading.Thread(target=listen_keyboard, daemon=True)
kb_thread.start()
# Wait up to 10s for stream to connect
stream_ready.wait(timeout=10)
time.sleep(0.5)
print(" OK")

# Get cursor before
cursor_before = get_cursor()
if cursor_before:
    print(f"  Cursor before: ({cursor_before.get('X')}, {cursor_before.get('Y')})")

# Connect robot
print(f"  Connecting {arm} arm...", end="", flush=True)
mc = MyCobot280Socket(ip, 9000)
time.sleep(1)
mc.power_on()
time.sleep(1)
print(" OK")
mc.set_color(255, 165, 0)

# Press key
hover_z = z + 15
press_z = z - 3
print(f"  Moving to hover...", end="", flush=True)
mc.send_coords([x, y, hover_z, 0, 180, 90], 15, 0)
time.sleep(3)
print(" OK")

print(f"  >>> PRESSING '{key}' <<<")
mc.send_coords([x, y, press_z, 0, 180, 90], 8, 0)
time.sleep(0.8)
mc.send_coords([x, y, hover_z, 0, 180, 90], 8, 0)
time.sleep(1.5)

# Get cursor after
cursor_after = get_cursor()
if cursor_after:
    print(f"  Cursor after: ({cursor_after.get('X')}, {cursor_after.get('Y')})")

# Stop stream and collect
time.sleep(1)
stream_stop.set()
time.sleep(0.5)

# Results
print()
print(f"  ╔══════════════════════════════════════╗")
print(f"  ║  KEY: '{key}'")
print(f"  ║  Keyboard events: {len(kb_events)}")
for i, evt in enumerate(kb_events[:10]):
    print(f"  ║    {i+1}: {evt}")
if not kb_events:
    print(f"  ║    (no events captured)")
print(f"  ╚══════════════════════════════════════╝")

mc.set_color(0, 255, 0) if kb_events else mc.set_color(255, 0, 0)
