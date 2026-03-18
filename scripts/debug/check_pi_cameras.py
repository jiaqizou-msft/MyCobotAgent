"""Check what cameras are now available on the Pi after remounting."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

def run(cmd, timeout=15):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(f"STDERR: {err}")
    return out

# Check USB devices
run("lsusb")

# Check video devices
run("ls -la /dev/video*")
run("v4l2-ctl --list-devices 2>/dev/null || echo 'v4l2-ctl not found'")

# Check if pyrealsense2 is installed on Pi
run("pip3 list 2>/dev/null | grep -i realsense || echo 'pyrealsense2 NOT installed'")
run("python3 -c 'import pyrealsense2 as rs; ctx=rs.context(); print(f\"RealSense devices: {len(ctx.query_devices())}\")' 2>&1")

# Check if the webcam still works
run("python3 -c 'import cv2; cap=cv2.VideoCapture(0); ret,f=cap.read(); print(f\"Webcam capture: {f.shape if ret else \"FAILED\"}\"); cap.release()' 2>&1")

# Check what's currently running
run("ss -tlnp | grep -E '8080|9000'")

ssh.close()
print("\nDone!")
