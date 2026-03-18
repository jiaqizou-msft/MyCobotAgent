"""
Restore working setup:
- Webcam on Pi (overhead) streaming via Flask
- RealSense on laptop USB for depth when needed
- Robot TCP on Pi port 9000
"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

def run(cmd, timeout=15):
    print(f"$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err and 'Warning' not in err: print(f"ERR: {err[-200:]}")

# Kill everything on port 8080
run("echo 'Elephant' | sudo -S fuser -k 8080/tcp 2>&1; sleep 2; echo freed")
time.sleep(2)

# Start the simple webcam-only pi_camera_server (already on the Pi)
run("nohup python3 /home/er/pi_camera_server.py --port 8080 --camera 0 > /tmp/cam.log 2>&1 &")
time.sleep(4)

run("ss -tlnp | grep 8080")
run("tail -5 /tmp/cam.log")

# Verify robot server
run("ss -tlnp | grep 9000")

ssh.close()

# Test from laptop
import httpx
try:
    r = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5)
    print(f"\nOverhead webcam: OK ({len(r.content)} bytes)")
except Exception as e:
    print(f"\nOverhead webcam: FAILED {e}")

import socket
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('10.105.230.93', 9000))
    print("Robot TCP: OK")
    s.close()
except:
    print("Robot TCP: FAILED")

print("\nSetup restored. Webcam=overhead on Pi, RealSense=laptop USB for depth.")
