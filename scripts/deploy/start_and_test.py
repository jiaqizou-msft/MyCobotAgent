"""Start server on Pi and test from Windows."""
import paramiko
import time
import socket

HOST = '10.105.230.93'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username='er', password='Elephant', timeout=10)

# Start the server in background (use bash -c to detach properly)
print("Starting server on Pi...")
ssh.exec_command("cd /home/er/pymycobot/demo && nohup python3 Server.py > /tmp/server_out.log 2>&1 &")
time.sleep(5)

# Check it's listening
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
result = stdout.read().decode().strip()
print(f"Port check: {result}")

stdin, stdout, stderr = ssh.exec_command("cat /tmp/server_out.log")
print(f"Server log: {stdout.read().decode().strip()}")

ssh.close()

# Now test TCP from Windows
print("\nTesting TCP connection from Windows...")
s = socket.socket()
s.settimeout(5)
try:
    s.connect((HOST, 9000))
    print("Port 9000 OPEN!")
    s.close()
except Exception as e:
    print(f"Connection failed: {e}")

# Now test with pymycobot using the OLD MyCobot class (matching Pi's v3.9.7 server)
print("\nTesting pymycobot connection...")
from pymycobot import MyCobot280Socket
mc = MyCobot280Socket(HOST, 9000)
time.sleep(2)

print(f"  is_power_on: {mc.is_power_on()}")
time.sleep(0.3)
print(f"  get_angles: {mc.get_angles()}")
time.sleep(0.3)
print(f"  get_coords: {mc.get_coords()}")

print("\nDone!")
