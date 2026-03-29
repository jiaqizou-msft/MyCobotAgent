"""Start TCP bridge on left arm via SSH."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.105.230.94", username="er", password="Elephant", timeout=10)
print("SSH connected to left arm")

# Check if bridge already running
stdin, stdout, stderr = ssh.exec_command("pgrep -f tcp_serial_bridge")
pids = stdout.read().decode().strip()
if pids:
    print(f"Bridge already running (PID: {pids})")
else:
    print("Starting bridge...")
    ssh.exec_command("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
    time.sleep(3)

# Verify
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
out = stdout.read().decode().strip()
if out:
    print(f"Port 9000 listening: {out}")
else:
    print("Port 9000 NOT listening — checking logs...")
    stdin, stdout, stderr = ssh.exec_command("cat /tmp/bridge.log 2>/dev/null | tail -5")
    print(stdout.read().decode())

ssh.close()
