"""Touchpad swipe using taught reference points."""
from pymycobot import MyCobot280Socket
import time

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000

mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
time.sleep(1)
mc.set_color(255, 0, 255)  # purple = touchpad mode

# Taught touchpad positions:
# lower left corner: (232.1, -77.0, 131.6)
# center: (282.1, -41.1, 132.0)
# The touchpad is roughly a rectangle. Estimate bounds from these two points.
# Lower-left to center gives us half the touchpad diagonal.

# Touchpad approximate bounds in robot frame:
# Left edge X ~ 220, Right edge X ~ 280 (limited by reach)
# Bottom Y ~ -80, Top Y ~ -10
# Z surface ~ 131.5

TP_Z = 131.5
HOVER_Z = 145
PRESS_DEPTH = 2
SLOW = 8
APPROACH = 10

# Swipe: scroll down (drag from top to bottom of touchpad)
# Start near top of touchpad, end near bottom
swipe_start = (245, -25, TP_Z)  # top area of reachable touchpad
swipe_end = (245, -70, TP_Z)    # bottom area

print("=== TOUCHPAD SWIPE (scroll down) ===")
print(f"  Start: {swipe_start}")
print(f"  End:   {swipe_end}")

sx, sy, sz = swipe_start
ex, ey, ez = swipe_end
press_z = sz - PRESS_DEPTH

# Move above start
print("  Moving above start...")
mc.send_coords([sx, sy, HOVER_Z, 0, 180, 90], APPROACH, 0)
time.sleep(4)

# Lower to hover
mc.send_coords([sx, sy, sz + 10, 0, 180, 90], APPROACH, 0)
time.sleep(2)

# Touch down at start
print("  Touching down...")
mc.send_coords([sx, sy, press_z, 0, 180, 90], SLOW, 0)
time.sleep(1.5)

# Swipe to end (stay pressed)
print("  Swiping...")
mc.send_coords([ex, ey, press_z, 0, 180, 90], SLOW, 0)
time.sleep(3)

# Lift up
print("  Lifting...")
mc.send_coords([ex, ey, HOVER_Z, 0, 180, 90], APPROACH, 0)
time.sleep(2)

# Return home
mc.send_angles([0, 0, 0, 0, 0, 0], 12)
time.sleep(3)
mc.set_color(255, 255, 255)

print("\nSwipe complete!")
