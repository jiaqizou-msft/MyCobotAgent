"""Upload and start the dual camera server on Pi."""
import paramiko
import time
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

# Upload
sftp = ssh.open_sftp()
sftp.put(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_dual_camera_server.py"),
         "/home/er/pi_dual_camera_server.py")
sftp.close()
print("Uploaded pi_dual_camera_server.py")

def run(cmd, timeout=15):
    print(f"$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err and 'Warning' not in err and 'Deprecation' not in err: print(f"ERR: {err[-200:]}")

# Kill old, free port
run("echo 'Elephant' | sudo -S fuser -k 8080/tcp 2>&1; sleep 2; echo freed")
time.sleep(2)

# Start
run("nohup python3 /home/er/pi_dual_camera_server.py --port 8080 --webcam 0 > /tmp/dual_cam.log 2>&1 &")
time.sleep(10)

run("ss -tlnp | grep 8080")
run("tail -5 /tmp/dual_cam.log")
ssh.close()

# Test
import httpx, cv2, numpy as np
base = "http://10.105.230.93:8080"
os.makedirs("temp", exist_ok=True)

for name, url in [("overhead_color", "/realsense/color"), ("overhead_depth", "/realsense/depth_colormap"), ("side_view", "/webcam/snapshot")]:
    try:
        r = httpx.get(f"{base}{url}", timeout=5)
        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        cv2.imwrite(f"temp/{name}.jpg", img)
        print(f"{name}: OK {img.shape}")
    except Exception as e:
        print(f"{name}: FAILED {e}")

try:
    r = httpx.get(f"{base}/realsense/intrinsics", timeout=5)
    print(f"Intrinsics: {r.json()}")
except Exception as e:
    print(f"Intrinsics: {e}")

print("\nDone!")
