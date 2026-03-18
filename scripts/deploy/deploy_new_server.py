"""Find server script and create a new one if needed."""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.105.230.93', username='er', password='Elephant', timeout=10)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
    time.sleep(2)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(f"$ {cmd}")
    if out: print(out)
    if err: print(f"ERR: {err}")
    return out

run("pip3 show pymycobot | grep Location")
run("ls /home/er/.local/lib/python3.8/site-packages/pymycobot/*.py | head -20")

# The new pymycobot 4.0.4 has a built-in socket server class.
# Let's just create a simple server that works with MyCobot280Socket
server_script = r'''#!/usr/bin/env python3
"""TCP Socket server for myCobot 280 Pi - compatible with pymycobot 4.0.4 MyCobot280Socket client."""
import socket
import serial
import time
import struct
import fcntl
import sys

HOST = "0.0.0.0"
PORT = 9000
SERIAL_PORT = "/dev/ttyAMA0"
SERIAL_BAUD = 1000000

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ip = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', b'wlan0' + b'\x00'*251))[20:24])
        return ip
    except:
        return "0.0.0.0"

class SimpleServer:
    def __init__(self):
        self.ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.1)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, PORT))
        self.sock.listen(1)
        print(f"Server listening on {get_ip()}:{PORT}")
        print("Binding succeeded and waiting connect")

    def run(self):
        while True:
            print("Waiting for client connection...")
            conn, addr = self.sock.accept()
            print(f"Client connected: {addr}")
            try:
                self.handle_client(conn)
            except Exception as e:
                print(f"Client error: {e}")
            finally:
                conn.close()
                print("Client disconnected")

    def handle_client(self, conn):
        while True:
            data = b""
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                data += chunk
                if len(chunk) < 1024:
                    break

            if not data:
                return

            # Forward to serial
            self.ser.write(data)
            self.ser.flush()
            time.sleep(0.05)

            # Read response
            response = b""
            time.sleep(0.02)
            while self.ser.in_waiting:
                response += self.ser.read(self.ser.in_waiting)
                time.sleep(0.01)

            if response:
                conn.sendall(response)
            else:
                conn.sendall(b"\x00")

if __name__ == "__main__":
    print("myCobot 280 TCP Server (pymycobot 4.x compatible)")
    server = SimpleServer()
    server.run()
'''

# Write the server to Pi
sftp = ssh.open_sftp()
with sftp.open('/home/er/mycobot_server.py', 'w') as f:
    f.write(server_script)
sftp.close()
print("\nServer script deployed to /home/er/mycobot_server.py")

# Start the new server
ssh.exec_command('nohup python3 /home/er/mycobot_server.py > /tmp/server_out.log 2>&1 &')
time.sleep(4)

run("ss -tlnp | grep 9000")
run("cat /tmp/server_out.log")

ssh.close()
print("\nDone!")
