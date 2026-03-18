"""Fix permissions and restart server on Pi."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

# Use sudo with password piped via stdin
stdin, stdout, stderr = ssh.exec_command("echo 'Elephant' | sudo -S chown er:er /home/er/pymycobot/demo/server.log 2>/dev/null && echo FIXED")
time.sleep(3)
print("chown:", stdout.read().decode().strip())

# Kill any leftover
stdin, stdout, stderr = ssh.exec_command("pkill -f 'python3 Server.py' 2>/dev/null; sleep 1; echo KILLED")
time.sleep(2)
print("kill:", stdout.read().decode().strip())

# Start the server in background
stdin, stdout, stderr = ssh.exec_command("cd /home/er/pymycobot/demo && nohup python3 Server.py > /tmp/server_out.log 2>&1 & echo STARTED")
time.sleep(1)
print("start:", stdout.read().decode().strip())

# Wait for server to initialize
time.sleep(4)

# Check status
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000; echo '---'; cat /tmp/server_out.log")
time.sleep(2)
print("status:")
print(stdout.read().decode().strip())

ssh.close()
