"""Debug: keep keyboard stream open and print ALL data received."""
import socket
import time
import re

HOST = "192.168.0.4"
PORT = 22133

print("Connecting to keyboard stream...")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(120)
s.connect((HOST, PORT))
req = f"GET /streams/keyboard HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nAccept: */*\r\n\r\n"
s.sendall(req.encode())
print("Connected. Press keys on the DUT...")
print("(Will run for 60 seconds)\n")

s.settimeout(2)
start = time.time()
total_bytes = 0
key_count = 0
last_key_time = None

while time.time() - start < 60:
    try:
        data = s.recv(8192)
        if data:
            total_bytes += len(data)
            text = data.decode("utf-8", errors="replace")

            # Extract key names
            for m in re.finditer(r'"Key"\s*:\s*"([A-Za-z][A-Za-z0-9_]*)"', text):
                vk = m.group(1)
                now = time.time() - start
                if last_key_time is None or now - last_key_time > 0.5:
                    key_count += 1
                    print(f"  [{now:.1f}s] KEY #{key_count}: {vk}")
                last_key_time = now

            # Check for errors
            if "Unable to add consumer" in text:
                print("  ⚠ STREAM BUSY — another consumer connected!")
                break
        else:
            print(f"  [{time.time()-start:.1f}s] Connection closed by server")
            break
    except socket.timeout:
        # Print a dot every 2s to show we're alive
        pass

s.close()
print(f"\nTotal: {total_bytes} bytes, {key_count} key events in {time.time()-start:.0f}s")
