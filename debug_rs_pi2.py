"""Try RealSense on Pi with increased timeout and no other USB devices competing."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

def run(cmd, timeout=60):
    print(f"$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(f"ERR: {err[-300:]}")

# Kill anything using the cameras
run("pkill -f 'pi_camera_server' 2>/dev/null; pkill -f 'pi_dual_camera' 2>/dev/null; pkill -f 'python3.*capture' 2>/dev/null; sleep 2; echo killed")

test_script = r"""
import pyrealsense2 as rs
import numpy as np
import time
import sys

# Reset the device first
ctx = rs.context()
devs = ctx.query_devices()
print("Devices: {}".format(len(devs)))
if len(devs) > 0:
    print("Resetting device...")
    devs[0].hardware_reset()
    time.sleep(5)
    print("Reset done. Re-querying...")
    ctx2 = rs.context()
    devs2 = ctx2.query_devices()
    print("Devices after reset: {}".format(len(devs2)))

# Try with longer timeout
pipeline = rs.pipeline()
config = rs.config()
# Start with very low res
config.enable_stream(rs.stream.depth, 424, 240, rs.format.z16, 6)
config.enable_stream(rs.stream.color, 424, 240, rs.format.bgr8, 6)

print("\nStarting at 424x240 @6fps...")
try:
    profile = pipeline.start(config)
    print("Pipeline started. Waiting for frames with extended timeout...")
    
    # Manual frame wait with longer timeout
    for attempt in range(20):
        try:
            frames = pipeline.wait_for_frames(timeout_ms=10000)
            color = frames.get_color_frame()
            depth = frames.get_depth_frame()
            if color and depth:
                print("SUCCESS! Frame {}: color {}x{}, depth {}x{}".format(
                    attempt, color.get_width(), color.get_height(),
                    depth.get_width(), depth.get_height()))
                # Get intrinsics
                ci = color.get_profile().as_video_stream_profile().get_intrinsics()
                print("Intrinsics: fx={:.1f} fy={:.1f} ppx={:.1f} ppy={:.1f}".format(
                    ci.fx, ci.fy, ci.ppx, ci.ppy))
                break
        except Exception as e:
            print("Attempt {}: {}".format(attempt, e))
            time.sleep(1)
    
    # If we got here, try capturing a few more
    for i in range(3):
        frames = pipeline.wait_for_frames(timeout_ms=10000)
        d = np.asanyarray(frames.get_depth_frame().get_data())
        valid = d[d > 0]
        if len(valid) > 0:
            print("Frame {}: depth range {}-{}mm ({} valid pixels)".format(
                i, valid.min(), valid.max(), len(valid)))
    
    pipeline.stop()
    print("\nRealSense works on Pi!")
    
except Exception as e:
    print("FAILED: {}".format(e))
    import traceback
    traceback.print_exc()
    try:
        pipeline.stop()
    except:
        pass
"""

# Write and run
stdin, stdout, stderr = ssh.exec_command("cat > /tmp/test_rs2.py << 'PYEOF'\n" + test_script + "\nPYEOF")
time.sleep(1)
run("python3 /tmp/test_rs2.py", timeout=120)

ssh.close()
