"""Fix left arm permanently: static IP + bridge auto-start on boot."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.105.230.94", username="er", password="Elephant", timeout=10)
print("SSH connected to left arm")

# 1. Make static IP permanent
print("\n1. Setting permanent static IP...")
# Check if already configured
stdin, stdout, stderr = ssh.exec_command("grep '10.105.230.94' /etc/dhcpcd.conf 2>/dev/null")
existing = stdout.read().decode().strip()
if existing:
    print("   Already configured in dhcpcd.conf")
else:
    ssh.exec_command('echo "\ninterface eth0\nstatic ip_address=10.105.230.94/24" | sudo tee -a /etc/dhcpcd.conf')
    time.sleep(1)
    print("   Added to /etc/dhcpcd.conf")

# 2. Start TCP bridge now
print("\n2. Starting TCP bridge...")
ssh.exec_command("sudo pkill -9 -f tcp_serial_bridge 2>/dev/null")
time.sleep(2)
ssh.exec_command("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(3)
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
bridge_status = stdout.read().decode().strip()
if "9000" in bridge_status:
    print("   Bridge running on port 9000")
else:
    print("   Bridge NOT running!")

# 3. Set bridge to auto-start on boot
print("\n3. Setting bridge auto-start on boot...")
stdin, stdout, stderr = ssh.exec_command("crontab -l 2>/dev/null")
cron = stdout.read().decode()
if "tcp_serial_bridge" in cron:
    print("   Crontab already configured")
else:
    ssh.exec_command('(crontab -l 2>/dev/null; echo "@reboot sleep 10 && python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &") | crontab -')
    time.sleep(1)
    print("   Added to crontab")

# 4. Open firewall
print("\n4. Clearing firewall...")
ssh.exec_command("sudo iptables -F")
ssh.exec_command("sudo iptables -P INPUT ACCEPT")
time.sleep(1)
print("   Firewall cleared")

# 5. Verify
print("\n5. Verification:")
stdin, stdout, stderr = ssh.exec_command("ip addr show eth0 | grep 'inet '")
print(f"   IP: {stdout.read().decode().strip()}")
stdin, stdout, stderr = ssh.exec_command("ss -tlnp | grep 9000")
print(f"   Bridge: {stdout.read().decode().strip()}")
stdin, stdout, stderr = ssh.exec_command("grep 'static ip_address' /etc/dhcpcd.conf")
print(f"   dhcpcd: {stdout.read().decode().strip()}")
stdin, stdout, stderr = ssh.exec_command("crontab -l 2>/dev/null | grep bridge")
print(f"   Crontab: {stdout.read().decode().strip()}")

ssh.close()
print("\nLeft arm permanently configured!")
