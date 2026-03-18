"""Debug RealSense on Pi - try different resolutions and configs."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

def run(cmd, timeout=30):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out[-500:] if len(out) > 500 else out)
    if err: print(f"ERR: {err[-300:]}")
    return out

# Check USB speed
run("lsusb -t | head -20")

# Check dmesg for USB errors
run("dmesg | grep -i -E 'usb|realsense' | tail -10")

# Try basic RealSense test with lower resolution
test_script = """
import pyrealsense2 as rs
import time

pipeline = rs.pipeline()
config = rs.config()

# Try 424x240 which is lighter on USB bandwidth
config.enable_stream(rs.stream.color, 424, 240, rs.format.bgr8, 15)
config.enable_stream(rs.stream.depth, 424, 240, rs.format.z16, 15)

print("Starting pipeline at 424x240@15fps...")
try:
    profile = pipeline.start(config)
    print("Started!")
    
    dev = profile.get_device()
    print("Device:", dev.get_info(rs.camera_info.name))
    print("USB type:", dev.get_info(rs.camera_info.usb_type_descriptor))
    
    for i in range(5):
        frames = pipeline.wait_for_frames()
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        print("Frame {}: color={} depth={}".format(i, color.get_width(), depth.get_width()))
    
    pipeline.stop()
    print("Success at 424x240!")
except Exception as e:
    print("Failed at 424x240: {}".format(e))
    try:
        pipeline.stop()
    except:
        pass

# Try 640x480 color only (no depth)
pipeline2 = rs.pipeline()
config2 = rs.config()
config2.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)

print("\\nTrying 640x480 color only @15fps...")
try:
    profile2 = pipeline2.start(config2)
    for i in range(3):
        frames2 = pipeline2.wait_for_frames()
        print("Frame {}: ok".format(i))
    pipeline2.stop()
    print("Success color-only!")
except Exception as e:
    print("Failed: {}".format(e))

# Try 640x480 with depth at 15fps
pipeline3 = rs.pipeline()
config3 = rs.config()
config3.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
config3.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)

print("\\nTrying 640x480 RGBD @15fps...")
try:
    profile3 = pipeline3.start(config3)
    for i in range(3):
        frames3 = pipeline3.wait_for_frames()
        print("Frame {}: ok".format(i))
    pipeline3.stop()
    print("Success 640x480 @15fps!")
except Exception as e:
    print("Failed: {}".format(e))
"""

# Write and run on Pi
stdin, stdout, stderr = ssh.exec_command("cat > /tmp/test_rs.py << 'PYEOF'\n" + test_script + "\nPYEOF")
time.sleep(1)
run("python3 /tmp/test_rs.py", timeout=60)

ssh.close()
print("\nDone!")
