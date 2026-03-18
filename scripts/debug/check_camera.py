"""Check camera on the Pi and deploy the streaming server."""
import paramiko
import time
import os

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

# Check for camera devices
run("ls -la /dev/video*")
run("v4l2-ctl --list-devices 2>/dev/null || echo 'v4l2-ctl not available'")

# Check if picamera is available (RPi camera module)
run("vcgencmd get_camera 2>/dev/null || echo 'vcgencmd not available'")

# Try a quick capture test with OpenCV
run("python3 -c \"import cv2; cap=cv2.VideoCapture(0); ret,f=cap.read(); print('capture ok, shape:', f.shape if ret else 'FAILED'); cap.release()\"")

# Check what's installed
run("pip3 list 2>/dev/null | grep -i -E 'flask|opencv|picamera'")

ssh.close()
print("\nDone!")
