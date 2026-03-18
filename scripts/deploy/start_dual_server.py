"""Kill old servers and start the new dual camera server on the Pi."""
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
    if err and 'Warning' not in err: print(f"STDERR: {err[-200:]}")
    return out

# Kill old camera server
run("pkill -f 'pi_camera_server' 2>/dev/null; pkill -f 'pi_dual_camera' 2>/dev/null; sleep 1; echo 'killed old'")

# Free port 8080
run("echo 'Elephant' | sudo -S fuser -k 8080/tcp 2>&1; sleep 1; echo 'port freed'")
time.sleep(2)

# Start dual camera server
run("nohup python3 /home/er/pi_dual_camera_server.py --port 8080 --webcam 0 > /tmp/dual_cam.log 2>&1 &")
time.sleep(8)  # Give RealSense time to initialize

# Check it's running
run("ss -tlnp | grep 8080")
run("tail -20 /tmp/dual_cam.log")

ssh.close()
print("\n--- Testing from Windows ---")

# Test endpoints
import httpx
base = "http://10.105.230.93:8080"

# Status
try:
    r = httpx.get(f"{base}/", timeout=5)
    print(f"\nStatus: {r.status_code}")
    print(r.json())
except Exception as e:
    print(f"Status failed: {e}")

# RealSense color
try:
    r = httpx.get(f"{base}/realsense/color", timeout=5)
    print(f"\nRS color: {r.status_code}, {len(r.content)} bytes")
except Exception as e:
    print(f"RS color failed: {e}")

# RealSense depth
try:
    r = httpx.get(f"{base}/realsense/depth", timeout=5)
    print(f"RS depth: {r.status_code}, {len(r.content)} bytes")
except Exception as e:
    print(f"RS depth failed: {e}")

# Webcam
try:
    r = httpx.get(f"{base}/webcam/snapshot", timeout=5)
    print(f"Webcam: {r.status_code}, {len(r.content)} bytes")
except Exception as e:
    print(f"Webcam failed: {e}")

# RealSense intrinsics
try:
    r = httpx.get(f"{base}/realsense/intrinsics", timeout=5)
    print(f"Intrinsics: {r.json()}")
except Exception as e:
    print(f"Intrinsics failed: {e}")

# Save test images
import cv2
import numpy as np
import os
os.makedirs("temp", exist_ok=True)

try:
    r = httpx.get(f"{base}/realsense/color", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/overhead_color.jpg", img)
    print(f"\nOverhead color saved: {img.shape}")
except: pass

try:
    r = httpx.get(f"{base}/realsense/depth_colormap", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/overhead_depth.jpg", img)
    print(f"Overhead depth saved: {img.shape}")
except: pass

try:
    r = httpx.get(f"{base}/webcam/snapshot", timeout=5)
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite("temp/side_color.jpg", img)
    print(f"Side view saved: {img.shape}")
except: pass

print("\nDone! Check temp/overhead_*.jpg and temp/side_color.jpg")
