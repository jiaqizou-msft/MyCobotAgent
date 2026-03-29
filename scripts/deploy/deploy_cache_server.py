"""
Deploy robot_cache_server.py to both Pis.
Kills old bridge/server, uploads new server, starts it.
"""
import paramiko
import time
import os
import sys

ARMS = {
    "right": "10.105.230.93",
    "left": "10.105.230.94",
}
USER = "er"
PASS = "Elephant"

LOCAL_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "robot_cache_server.py")
REMOTE_PATH = "/home/er/robot_cache_server.py"

for name, ip in ARMS.items():
    print(f"\n{'='*50}")
    print(f"  {name.upper()} ARM ({ip})")
    print(f"{'='*50}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(ip, username=USER, password=PASS, timeout=10)
        print("  SSH connected")
    except Exception as e:
        print(f"  SSH FAILED: {e}")
        continue

    def run(cmd, t=15):
        _, out, err = ssh.exec_command(cmd, timeout=t)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        if o:
            print(f"  {o}")
        if e and "warning" not in e.lower():
            print(f"  ERR: {e[:200]}")
        return o

    # Upload
    sftp = ssh.open_sftp()
    sftp.put(LOCAL_SERVER, REMOTE_PATH)
    sftp.close()
    print(f"  Uploaded robot_cache_server.py")

    # Ensure pymycobot 4.x is installed system-wide (sudo runs from /usr/local)
    run("sudo pip3 install --upgrade pymycobot 2>&1 | tail -2", t=60)

    # Kill old servers
    run("sudo pkill -f tcp_serial_bridge 2>/dev/null; sudo pkill -f robot_cache_server 2>/dev/null; sudo pkill -f Server.py 2>/dev/null; sleep 1")
    print("  Killed old processes")

    # Start new server
    run(f"nohup sudo python3 {REMOTE_PATH} > /tmp/cache_server.log 2>&1 &")
    time.sleep(4)

    # Check
    port = run("ss -tlnp | grep 9000")
    if "9000" in (port or ""):
        print("  Port 9000: LISTENING ✓")
    else:
        print("  Port 9000: NOT LISTENING ✗")
        run("cat /tmp/cache_server.log")

    log = run("head -5 /tmp/cache_server.log")

    ssh.close()

# Test connections
print(f"\n{'='*50}")
print("  TESTING CONNECTIONS")
print(f"{'='*50}")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

for name, ip in ARMS.items():
    try:
        mc = CachedRobot(ip, 9000)
        if mc.ping():
            print(f"  {name}: ping OK")
        mc.power_on()
        time.sleep(2)
        # Try reading angles a few times
        for i in range(5):
            a = mc.get_angles()
            if a and a != -1:
                print(f"  {name}: angles={[round(x,1) for x in a]} ✓")
                mc.set_color(0, 255, 0)
                break
            time.sleep(0.5)
        else:
            print(f"  {name}: angles pending (cache warming up)")
        mc.close()
    except Exception as e:
        print(f"  {name}: FAILED ({e})")

print("\nDone!")
