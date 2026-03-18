"""Upgrade pymycobot on Pi and deploy new server."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

def run(cmd, timeout=30):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(f"STDERR: {err}")
    return out

# Check current pymycobot version
run("python3 -c 'import pymycobot; print(pymycobot.__version__)'")

# Kill existing server
run("pkill -f 'Server.py' 2>/dev/null; sleep 1; echo 'Server killed'")

# Upgrade pymycobot
run("pip3 install --upgrade pymycobot", timeout=120)

# Check new version
run("python3 -c 'import pymycobot; print(pymycobot.__version__)'")

# Find the new server script
run("find /home/er -name '*.py' -path '*/demo/*' 2>/dev/null | head -20")
run("pip3 show pymycobot | grep Location")

ssh.close()
print("\nDone!")
