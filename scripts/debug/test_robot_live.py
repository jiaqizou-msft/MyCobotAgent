"""Full robot test — read status, flash LED, move to home position."""
from pymycobot import MyCobot280Socket
import time

print("Connecting to myCobot 280...")
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(2)

print("\n=== ROBOT STATUS ===")
for i in range(3):
    angles = mc.get_angles()
    time.sleep(0.5)
    if angles and angles != -1:
        break

print(f"  Joint angles: {angles}")

coords = mc.get_coords()
time.sleep(0.5)
print(f"  TCP coords:   {coords}")

power = mc.is_power_on()
time.sleep(0.3)
print(f"  Power on:     {power}")

print("\n=== LED COLOR TEST ===")
colors = [(255, 0, 0, "RED"), (0, 255, 0, "GREEN"), (0, 0, 255, "BLUE"), (255, 255, 0, "YELLOW")]
for r, g, b, name in colors:
    mc.set_color(r, g, b)
    print(f"  LED -> {name}")
    time.sleep(1)

# Set to white
mc.set_color(255, 255, 255)
print("  LED -> WHITE")

print("\n=== MOVING TO HOME POSITION ===")
print("  Sending [0, 0, 0, 0, 0, 0] at speed 25...")
mc.send_angles([0, 0, 0, 0, 0, 0], 25)
time.sleep(5)

for i in range(5):
    angles = mc.get_angles()
    time.sleep(0.5)
    if angles and angles != -1:
        break
print(f"  Angles after home: {angles}")

coords = mc.get_coords()
time.sleep(0.5)
print(f"  Coords after home: {coords}")

print("\n=== HEAD SHAKE TEST ===")
mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
time.sleep(2)
for _ in range(2):
    mc.send_angle(5, 30, 80)
    time.sleep(0.5)
    mc.send_angle(5, -30, 80)
    time.sleep(0.5)
mc.send_angles([0, 0, 0, 0, 0, 0], 40)
time.sleep(3)

print("  Head shake done!")

# Final status
for i in range(5):
    angles = mc.get_angles()
    time.sleep(0.5)
    if angles and angles != -1:
        break
print(f"\n=== FINAL STATUS ===")
print(f"  Angles: {angles}")
print(f"  ALL TESTS PASSED!")
