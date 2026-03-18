"""Test robot with longer delays between commands."""
from pymycobot import MyCobot280Socket
import time

print("Connecting...")
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(2)

print("Power on...")
mc.power_on()
time.sleep(3)

print(f"is_power_on: {mc.is_power_on()}")
time.sleep(1)

print(f"get_angles: {mc.get_angles()}")
time.sleep(1)

print(f"get_angles (2nd try): {mc.get_angles()}")
time.sleep(1)

print(f"get_coords: {mc.get_coords()}")
time.sleep(1)

print(f"get_coords (2nd try): {mc.get_coords()}")
time.sleep(1)

# Try setting LED to confirm communication
print("\nSetting LED to blue...")
mc.set_color(0, 0, 255)
time.sleep(1)

print("Setting LED to red...")
mc.set_color(255, 0, 0)
time.sleep(1)

print("\nTrying to read servo status...")
print(f"is_all_servo_enable: {mc.is_all_servo_enable()}")
time.sleep(1)

# Try sending a small angle command
print("\nSending home position [0,0,0,0,0,0] at speed 20...")
mc.send_angles([0, 0, 0, 0, 0, 0], 20)
time.sleep(5)

print(f"get_angles after home: {mc.get_angles()}")
time.sleep(1)
print(f"get_coords after home: {mc.get_coords()}")
