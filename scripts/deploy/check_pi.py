"""Check Pi server status and restart if needed."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH OK")

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
    return stdout.read().decode().strip()

# Check port 9000
out = run("ss -tlnp | grep 9000")
print(f"Port 9000: {out if out else 'NOT LISTENING'}")

# Check processes
out = run("ps aux | grep tcp_serial | grep -v grep")
print(f"Bridge: {out if out else 'NOT RUNNING'}")

if "tcp_serial" not in (out or ""):
    print("\nRestarting TCP bridge...")
    run("echo 'Elephant' | sudo -S fuser -k 9000/tcp 2>&1")
    time.sleep(2)
    run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
    time.sleep(4)
    out = run("ss -tlnp | grep 9000")
    print(f"After restart: {out if out else 'STILL NOT LISTENING'}")
    out = run("tail -3 /tmp/bridge.log")
    print(f"Log: {out}")

# Check camera server
out = run("ss -tlnp | grep 8080")
print(f"\nPort 8080: {out if out else 'NOT LISTENING'}")

ssh.close()
print("\nDone!")
