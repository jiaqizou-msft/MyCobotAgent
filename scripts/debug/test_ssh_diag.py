"""Quick SSH diagnostic script for the Pi."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

def run(cmd):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print(f"STDERR: {err}")

# Check available server scripts
run("ls -la /home/er/pymycobot/demo/")

# Read the running Server.py
run("head -60 /home/er/pymycobot/demo/Server.py")

# Test direct serial connection on the Pi (while the server is NOT using the port,
# this will fail if server holds serial — that's expected)
run("python3 /home/er/pymycobot/demo/test_serial.py 2>/dev/null || echo 'no test script'")

# Check pymycobot version on Pi
run("pip3 show pymycobot 2>/dev/null | grep -i version || python3 -c 'import pymycobot; print(pymycobot.__version__)'")

# Kill existing server and test serial directly
run("kill -9 3693 2>/dev/null; sleep 1; echo killed")

# Now test local serial access
run('python3 -c "from pymycobot.mycobot import MyCobot; import time; mc=MyCobot(chr(47)+chr(100)+chr(101)+chr(118)+chr(47)+chr(116)+chr(116)+chr(121)+chr(65)+chr(77)+chr(65)+chr(48), 1000000); time.sleep(1); print(chr(112)+chr(111)+chr(119)+chr(101)+chr(114)+chr(58), mc.is_power_on()); print(chr(97)+chr(110)+chr(103)+chr(108)+chr(101)+chr(115)+chr(58), mc.get_angles())"')

ssh.close()
