"""Find and start the new Server_280.py on the Pi."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(f"$ {cmd}")
    if out: print(out)
    if err: print(f"ERR: {err}")
    return out

# Find Server_280.py
run("find / -name 'Server_280*' 2>/dev/null")
run("pip3 show pymycobot | grep Location")
run("ls /home/er/.local/lib/python3.8/site-packages/pymycobot/ | head -20")

# Check if there's a demo dir in the new package
run("find /home/er/.local -path '*/pymycobot/demo*' 2>/dev/null")
run("find /home/er/.local -path '*/pymycobot/*server*' -o -path '*/pymycobot/*Server*' 2>/dev/null")

ssh.close()
