"""Deploy pi_camera_server.py to the Pi and start it."""
import paramiko
import time
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

# Upload the camera server via SFTP
sftp = ssh.open_sftp()
local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_camera_server.py")
remote_path = "/home/er/pi_camera_server.py"
sftp.put(local_path, remote_path)
sftp.close()
print(f"Uploaded pi_camera_server.py to Pi")

def run(cmd, timeout=15):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(f"STDERR: {err}")
    return out

# Kill any existing camera server
run("pkill -f 'pi_camera_server' 2>/dev/null; sleep 1; echo 'killed old'")

# Start camera server on port 8080
run("nohup python3 /home/er/pi_camera_server.py --port 8080 --camera 0 > /tmp/camera.log 2>&1 &")
time.sleep(4)

# Check it's running
run("ss -tlnp | grep 8080")
run("cat /tmp/camera.log")

ssh.close()
print("\nCamera server deployed! Testing from Windows...")

# Test snapshot endpoint
import httpx
try:
    resp = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5.0)
    print(f"Snapshot response: {resp.status_code}, size: {len(resp.content)} bytes")
    
    # Save the snapshot
    import cv2
    import numpy as np
    img_array = np.frombuffer(resp.content, dtype=np.uint8)
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if frame is not None:
        os.makedirs("temp", exist_ok=True)
        cv2.imwrite("temp/test_snapshot.jpg", frame)
        print(f"Snapshot saved to temp/test_snapshot.jpg — shape: {frame.shape}")
    else:
        print("Failed to decode image")
except Exception as e:
    print(f"Snapshot test failed: {e}")

# Test stream endpoint
try:
    cap = cv2.VideoCapture("http://10.105.230.93:8080/video")
    ret, frame = cap.read()
    if ret:
        print(f"Stream working! Frame shape: {frame.shape}")
    else:
        print("Stream failed to grab frame")
    cap.release()
except Exception as e:
    print(f"Stream test failed: {e}")

print("\nAll camera tests done!")
