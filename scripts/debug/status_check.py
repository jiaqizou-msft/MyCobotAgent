"""Quick status check — robot + camera."""
from pymycobot import MyCobot280Socket
import httpx
import time

print("=== Robot Status ===")
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(1)

for i in range(3):
    angles = mc.get_angles()
    time.sleep(0.5)
    if angles and angles != -1:
        break
print(f"  Angles: {angles}")

for i in range(3):
    coords = mc.get_coords()
    time.sleep(0.5)
    if coords and coords != -1:
        break
print(f"  Coords: {coords}")
print(f"  Power:  {mc.is_power_on()}")

print("\n=== Camera Status ===")
try:
    resp = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5.0)
    print(f"  Snapshot: {resp.status_code} OK, {len(resp.content)} bytes")
except Exception as e:
    print(f"  Snapshot: FAILED - {e}")

print("\nAll systems operational!")
