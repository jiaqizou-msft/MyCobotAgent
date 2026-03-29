"""Test Gambit keyboard stream by injecting keys."""
import requests
import time
import threading
import json

BASE = "http://192.168.0.4:22133"

events = []
stop = threading.Event()


def stream_keyboard():
    try:
        r = requests.get(f"{BASE}/streams/keyboard", stream=True, timeout=(30, 60))
        print(f"  Stream connected: {r.status_code} content-type={r.headers.get('content-type', '?')}")
        for line in r.iter_lines():
            if stop.is_set():
                break
            if line:
                text = line.decode("utf-8", errors="replace")
                events.append(text)
                print(f"  [KB] {text[:200]}")
    except Exception as e:
        print(f"  Stream error: {e}")


# Start stream
print("Starting keyboard stream...")
t = threading.Thread(target=stream_keyboard, daemon=True)
t.start()
time.sleep(3)

# Inject keys
print("\nInjecting key 'A'...")
requests.get(f"{BASE}/injection/keys/click", params={"key": "A"}, timeout=5)
time.sleep(2)

print("Injecting key 'B'...")
requests.get(f"{BASE}/injection/keys/click", params={"key": "B"}, timeout=5)
time.sleep(2)

print("Injecting key 'SPACE'...")
requests.get(f"{BASE}/injection/keys/click", params={"key": "SPACE"}, timeout=5)
time.sleep(2)

# Stop and report
stop.set()
time.sleep(1)
print(f"\nTotal events captured: {len(events)}")
for i, e in enumerate(events[:10]):
    print(f"  {i+1}: {e[:300]}")
