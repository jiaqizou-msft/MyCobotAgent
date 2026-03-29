"""Restart right arm bridge."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.105.230.93", username="er", password="Elephant", timeout=10)
print("SSH connected to right arm")

ssh.exec_command("sudo pkill -9 -f python3")
time.sleep(2)
ssh.exec_command("sudo iptables -F")
ssh.exec_command("sudo iptables -P INPUT ACCEPT")
time.sleep(1)
ssh.exec_command("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(4)

stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
out = stdout.read().decode().strip()
print(f"Port 9000: {out if out else 'NOT LISTENING'}")
ssh.close()
