"""Restart both TCP bridges and verify."""
import paramiko, time

for name, ip in [("right", "10.105.230.93"), ("left", "10.105.230.94")]:
    print(f"\n--- {name} arm ({ip}) ---")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(ip, username='er', password='Elephant', timeout=10)
    except Exception as e:
        print(f"  SSH failed: {e}")
        continue

    def run(cmd):
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
        return stdout.read().decode().strip()

    # Kill old bridge
    run("echo 'Elephant' | sudo -S fuser -k 9000/tcp 2>&1")
    time.sleep(2)

    # Start fresh
    run("nohup python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
    time.sleep(4)

    out = run("ss -tlnp | grep 9000")
    print(f"  Port 9000: {out if out else 'NOT LISTENING'}")
    out = run("tail -2 /tmp/bridge.log")
    if out: print(f"  Log: {out}")
    ssh.close()

# Test both
from pymycobot import MyCobot280Socket
for name, ip in [("right", "10.105.230.93"), ("left", "10.105.230.94")]:
    print(f"\n  Testing {name} ({ip})...")
    mc = MyCobot280Socket(ip, 9000)
    time.sleep(2)
    mc.power_on()
    time.sleep(2)
    print(f"    Power: {mc.is_power_on()}")
    time.sleep(0.3)
    for i in range(5):
        a = mc.get_angles()
        time.sleep(0.5)
        if a and a != -1:
            print(f"    Angles: {a}")
            break
    else:
        print(f"    Angles: failed after 5 retries")
    for i in range(5):
        c = mc.get_coords()
        time.sleep(0.5)
        if c and c != -1:
            print(f"    Coords: {c}")
            break
    else:
        print(f"    Coords: failed after 5 retries")

print("\nDone!")
