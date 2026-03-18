"""Deploy the TCP-serial bridge to the Pi and start it."""
import paramiko
import time
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

# Upload the bridge script via SFTP
sftp = ssh.open_sftp()
local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcp_serial_bridge.py")
remote_path = "/home/er/tcp_serial_bridge.py"
sftp.put(local_path, remote_path)
sftp.close()
print(f"Uploaded {local_path} -> {remote_path}")

def run(cmd, timeout=15):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(f"STDERR: {err}")
    return out

# Kill any existing server on port 9000
run("pkill -f 'Server.py' 2>/dev/null; pkill -f 'tcp_serial_bridge' 2>/dev/null; sleep 1; echo 'Killed old servers'")

# Start the bridge in background
run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(3)

# Check it's running
run("ss -tlnp | grep 9000")
run("cat /tmp/bridge.log")

ssh.close()
print("\nBridge deployed! Testing connection...")

# Now test
from pymycobot import MyCobot280Socket
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(2)

mc.power_on()
time.sleep(2)

print(f"\nis_power_on: {mc.is_power_on()}")
time.sleep(0.5)
print(f"get_angles: {mc.get_angles()}")
time.sleep(0.5)
print(f"get_coords: {mc.get_coords()}")
time.sleep(0.5)

# LED test
print("\nSetting LED to GREEN...")
mc.set_color(0, 255, 0)
print("Check the robot end-effector for a green LED!")
