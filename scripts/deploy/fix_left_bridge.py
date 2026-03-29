"""Check and fix firewall/connectivity on left arm."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.105.230.94", username="er", password="Elephant", timeout=10)
print("SSH connected")

# Check iptables
stdin, stdout, stderr = ssh.exec_command("sudo iptables -L -n 2>/dev/null | head -20")
print("iptables:")
print(stdout.read().decode())

# Check if bridge is really listening on all interfaces
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
print("Port 9000:", stdout.read().decode().strip())

# Try to open the firewall for port 9000
print("Opening firewall for port 9000...")
ssh.exec_command("sudo iptables -I INPUT -p tcp --dport 9000 -j ACCEPT 2>/dev/null")
time.sleep(1)

# Restart the bridge to be safe
print("Restarting bridge...")
ssh.exec_command("pkill -f tcp_serial_bridge")
time.sleep(2)
ssh.exec_command("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(3)

stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
out = stdout.read().decode().strip()
print(f"After restart: {out}")

ssh.close()
print("Done")
