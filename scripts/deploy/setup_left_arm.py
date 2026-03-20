"""Set up the new left arm: deploy TCP bridge + camera server."""
import paramiko
import time
import os

NEW_IP = "10.105.230.94"

# First check if we can even reach it
import socket
print(f"Pinging {NEW_IP}...")
s = socket.socket()
s.settimeout(5)
try:
    s.connect((NEW_IP, 22))
    print(f"  SSH port 22: OPEN")
    s.close()
except Exception as e:
    print(f"  SSH port 22: FAILED ({e})")
    print("  Cannot reach the new Pi. Check:")
    print("    1. Is the Ethernet cable connected to the switch?")
    print("    2. Does the Pi have IP 10.105.228.111?")
    print("    3. Run on the Pi: ip addr show eth0")
    exit(1)

# SSH in
print(f"\nSSH into {NEW_IP}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(NEW_IP, username='er', password='Elephant', timeout=10)
print("  SSH connected!")

def run(cmd, timeout=15):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(f"    {out}")
    if err and 'Warning' not in err: print(f"    ERR: {err[-200:]}")
    return out

# Check what's on this Pi
run("hostname")
run("whoami")
run("ls /dev/ttyAMA0")
run("ss -tlnp | grep -E '9000|8080'")
run("pip3 show pymycobot 2>/dev/null | grep Version || echo 'pymycobot not installed'")

# Upload TCP bridge
print("\nUploading TCP bridge...")
sftp = ssh.open_sftp()
bridge_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcp_serial_bridge.py")
sftp.put(bridge_path, "/home/er/tcp_serial_bridge.py")

# Upload camera server
cam_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_camera_server.py")
sftp.put(cam_path, "/home/er/pi_camera_server.py")
sftp.close()
print("  Files uploaded.")

# Install pymycobot if needed
out = run("pip3 show pymycobot 2>/dev/null | grep Version")
if not out:
    print("\nInstalling pymycobot...")
    run("pip3 install pymycobot", timeout=120)

# Install flask if needed
run("pip3 show flask 2>/dev/null | grep Version || pip3 install flask", timeout=60)

# Kill any existing servers
run("echo 'Elephant' | sudo -S fuser -k 9000/tcp 2>&1")
time.sleep(2)

# Start TCP bridge
print("\nStarting TCP bridge on port 9000...")
run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(5)
run("ss -tlnp | grep 9000")
run("tail -3 /tmp/bridge.log")

# Start camera server if there's a webcam
run("ls /dev/video0 2>/dev/null || echo 'no webcam'")
out = run("ls /dev/video0 2>/dev/null")
if out and "video0" in out:
    print("\nStarting camera server on port 8080...")
    run("echo 'Elephant' | sudo -S fuser -k 8080/tcp 2>&1")
    time.sleep(1)
    run("nohup python3 /home/er/pi_camera_server.py --port 8080 --camera 0 > /tmp/cam.log 2>&1 &")
    time.sleep(4)
    run("ss -tlnp | grep 8080")

ssh.close()

# Test connection
print(f"\n--- Testing left arm connection ---")
from pymycobot import MyCobot280Socket
try:
    mc = MyCobot280Socket(NEW_IP, 9000)
    time.sleep(2)
    mc.power_on()
    time.sleep(2)
    print(f"  Power: {mc.is_power_on()}")
    time.sleep(0.3)
    angles = mc.get_angles()
    print(f"  Angles: {angles}")
    mc.set_color(0, 0, 255)
    time.sleep(1)
    mc.set_color(255, 255, 255)
    print("  LEFT ARM: OK!")
except Exception as e:
    print(f"  LEFT ARM: FAILED ({e})")

print("\nDone!")
