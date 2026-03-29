"""Test Gambit streams with raw socket and physical key press."""
import socket
import time
import threading
import json

HOST = "192.168.0.4"
PORT = 22133

events = []

def raw_stream(path, label, duration=8):
    """Connect via raw HTTP and read whatever comes."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(duration + 5)
    s.connect((HOST, PORT))
    req = f"GET {path} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nAccept: */*\r\n\r\n"
    s.sendall(req.encode())
    
    data = b""
    start = time.time()
    s.settimeout(2)
    while time.time() - start < duration:
        try:
            chunk = s.recv(4096)
            if chunk:
                data += chunk
                # Print new data as it arrives
                text = chunk.decode("utf-8", errors="replace")
                if len(data) < 2000:  # only print initial data
                    for line in text.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("HTTP") and not line.startswith("Content") and not line.startswith("Transfer") and not line.startswith("Date") and not line.startswith("Server"):
                            events.append(line)
            else:
                break
        except socket.timeout:
            pass
    s.close()
    return data


print("=== /streams/keyboard (8s, press a key physically!) ===")
data = raw_stream("/streams/keyboard", "keyboard", 8)
print(f"Total received: {len(data)} bytes")
if data:
    text = data.decode("utf-8", errors="replace")
    # Find the body (after \r\n\r\n)
    parts = text.split("\r\n\r\n", 1)
    if len(parts) > 1:
        body = parts[1]
        print(f"Headers: {parts[0][:200]}")
        print(f"Body ({len(body)} chars): {body[:500]}")
    else:
        print(f"Raw: {text[:500]}")

print(f"\nEvents captured: {len(events)}")
for e in events[:20]:
    print(f"  {e[:200]}")

print("\n=== /streams/cursor/current ===")
data2 = raw_stream("/streams/cursor/current", "cursor", 3)
text2 = data2.decode("utf-8", errors="replace")
parts2 = text2.split("\r\n\r\n", 1)
if len(parts2) > 1:
    print(f"Cursor: {parts2[1][:200]}")
