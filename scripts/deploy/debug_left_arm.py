"""Debug left arm serial connection on the Pi."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.94', username='er', password='Elephant', timeout=10)
print("SSH to left arm Pi: OK")

def run(cmd, timeout=15):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(f"    {out}")
    if err: print(f"    ERR: {err[-200:]}")
    return out

# Check serial port
run("ls -la /dev/ttyAMA0")
run("groups")

# Test direct serial connection (kill bridge first)
run("echo 'Elephant' | sudo -S fuser -k 9000/tcp 2>&1")
time.sleep(2)

# Direct pymycobot serial test
test_cmd = 'python3 -c "from pymycobot.mycobot import MyCobot; import time; mc=MyCobot(chr(47)+chr(100)+chr(101)+chr(118)+chr(47)+chr(116)+chr(116)+chr(121)+chr(65)+chr(77)+chr(65)+chr(48), 1000000); time.sleep(1); print(chr(112)+chr(58), mc.is_power_on()); print(chr(97)+chr(58), mc.get_angles())"'
run(test_cmd, timeout=15)

# Restart bridge
run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(4)
run("ss -tlnp | grep 9000")
run("tail -3 /tmp/bridge.log")

ssh.close()
print("\nDone!")
