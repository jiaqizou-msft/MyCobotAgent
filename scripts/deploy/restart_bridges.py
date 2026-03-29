"""Restart TCP bridge on robot arm Pis."""
import paramiko
import time
import sys

ARMS = {
    "right": "10.105.230.93",
    "left": "10.105.230.94",
}
USER = "er"
PASS = "Elephant"

for name, ip in ARMS.items():
    print(f"\n--- {name.upper()} ARM ({ip}) ---")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(ip, username=USER, password=PASS, timeout=10)
        print("  SSH connected")
    except Exception as e:
        print(f"  SSH failed: {e}")
        continue

    def run(cmd):
        _, out, err = ssh.exec_command(cmd, timeout=15)
        return out.read().decode().strip()

    # Kill old
    run("sudo pkill -f tcp_serial_bridge 2>/dev/null")
    run("sudo pkill -f Server.py 2>/dev/null")
    time.sleep(1)

    # Start
    run("nohup sudo python3 /home/er/tcp_serial_bridge.py > /tmp/bridge.log 2>&1 &")
    time.sleep(3)

    # Check
    port = run("ss -tlnp | grep 9000")
    if port:
        print(f"  Port 9000: LISTENING")
    else:
        print(f"  Port 9000: NOT LISTENING")
        log = run("cat /tmp/bridge.log 2>/dev/null")
        if log:
            print(f"  Log: {log[:300]}")

    ssh.close()

# Test robot connections
print("\n--- TESTING ROBOT CONNECTIONS ---")
from pymycobot import MyCobot280Socket
for name, ip in ARMS.items():
    try:
        mc = MyCobot280Socket(ip, 9000)
        time.sleep(1)
        for _ in range(10):
            a = mc.get_angles()
            if a and a != -1:
                print(f"  {name}: OK angles={[round(x,1) for x in a]}")
                mc.set_color(0, 255, 0)
                break
            time.sleep(0.3)
        else:
            print(f"  {name}: connected, angles pending")
    except Exception as e:
        print(f"  {name}: FAILED ({e})")
