"""Force kill old server and start bridge."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)
print("SSH connected!")

def run(cmd, timeout=15):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(f"STDERR: {err}")
    return out

# Force kill pid 5403 and anything on port 9000
run("echo 'Elephant' | sudo -S kill -9 5403 2>&1; sleep 1; echo done")
time.sleep(3)
run("echo 'Elephant' | sudo -S fuser -k 9000/tcp 2>&1; sleep 1; echo done")
time.sleep(3)

# Verify port is free
run("ss -tlnp | grep 9000 || echo 'PORT FREE'")

# Start bridge
run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(4)

# Check
run("ss -tlnp | grep 9000")
run("cat /tmp/bridge.log")

ssh.close()
print("\n--- Now testing robot connection ---")

from pymycobot import MyCobot280Socket
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(2)

mc.power_on()
time.sleep(2)

print(f"is_power_on: {mc.is_power_on()}")
time.sleep(0.5)
print(f"get_angles: {mc.get_angles()}")
time.sleep(0.5)
print(f"get_coords: {mc.get_coords()}")
time.sleep(0.5)

mc.set_color(0, 255, 0)
print("LED set to GREEN - check the robot!")
