"""Deploy a compatible TCP server on the Pi and test the robot."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

def run(cmd, timeout=15):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print(f"STDERR: {err}")
    return out

# Kill any existing server
run("pkill -f Server.py 2>/dev/null; sleep 1; echo 'old server killed'")

# Check pymycobot version on Pi — it's 3.9.7 which uses the old MyCobot class
# The old Server.py protocol should work with the old MyCobot client class
# Let's try using MyCobot (not MyCobot280Socket) from our side
# But first, let's restart the server
run("cd /home/er/pymycobot/demo && nohup python3 Server.py > /tmp/server_out.log 2>&1 &")
time.sleep(3)
run("ss -tlnp | grep 9000")
run("cat /tmp/server_out.log")

ssh.close()
print("\nServer restarted. Testing connection from Windows side...")
