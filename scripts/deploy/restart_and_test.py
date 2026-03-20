"""Restart bridge and test robot."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    return stdout.read().decode().strip()

print("Killing old bridge...")
run("echo 'Elephant' | sudo -S kill -9 32425 2>&1")
time.sleep(2)
run("echo 'Elephant' | sudo -S fuser -k 9000/tcp 2>&1")
time.sleep(2)

print("Starting fresh bridge...")
run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
time.sleep(5)

out = run("ss -tlnp | grep 9000")
print(f"Port 9000: {out}")
out = run("tail -3 /tmp/bridge.log")
print(f"Log: {out}")

ssh.close()
print("\nNow testing robot...")

from pymycobot import MyCobot280Socket
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(2)

mc.power_on()
time.sleep(2)

print(f"Power: {mc.is_power_on()}")
time.sleep(0.5)

for i in range(3):
    a = mc.get_angles()
    time.sleep(0.5)
    if a and a != -1:
        print(f"Angles: {a}")
        break

mc.set_color(0, 255, 0)
time.sleep(1)
print("LED green!")
mc.set_color(255, 255, 255)
print("Robot OK!")
