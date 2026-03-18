"""Check Pi server status and start if needed, then test robot connection."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

# Check if server is running
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
time.sleep(2)
out = stdout.read().decode().strip()
print(f"Server status: {out if out else 'NOT RUNNING'}")

if not out:
    print("Fixing log permission...")
    stdin, stdout, stderr = ssh.exec_command("echo 'Elephant' | sudo -S rm -f /home/er/pymycobot/demo/server.log 2>&1")
    time.sleep(3)
    print(stdout.read().decode().strip())

    print("Starting Server.py...")
    ssh.exec_command("cd /home/er/pymycobot/demo && nohup python3 Server.py > /tmp/server_out.log 2>&1 &")
    time.sleep(5)

    stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
    time.sleep(2)
    out = stdout.read().decode().strip()
    print(f"Server after start: {out if out else 'STILL NOT RUNNING'}")

    stdin, stdout, stderr = ssh.exec_command("cat /tmp/server_out.log")
    time.sleep(2)
    print(f"Server log: {stdout.read().decode().strip()}")

ssh.close()
print("\nNow testing robot TCP connection from Windows...")

# Test TCP connection
import socket
s = socket.socket()
s.settimeout(5)
try:
    s.connect(('10.105.230.93', 9000))
    print("Port 9000: OPEN!")
    s.close()
except Exception as e:
    print(f"Port 9000: FAILED - {e}")

# Test pymycobot connection
print("\nTesting pymycobot connection...")
from pymycobot import MyCobot280Socket
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(1)

mc.power_on()
time.sleep(2)

print(f"  is_power_on: {mc.is_power_on()}")
time.sleep(0.3)
print(f"  get_angles: {mc.get_angles()}")
time.sleep(0.3)
print(f"  get_coords: {mc.get_coords()}")
