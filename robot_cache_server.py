#!/usr/bin/env python3
"""
Smart Robot Server with Angle Caching
======================================
Replaces tcp_serial_bridge.py on the Raspberry Pi.
Uses pymycobot directly, caches angles in background,
and serves commands via a simple JSON-over-TCP protocol.

Deploy on the Raspberry Pi:
    python3 robot_cache_server.py

Listens on 0.0.0.0:9000. Supports multiple simultaneous clients.
"""
import socket
import json
import threading
import time
import sys

SERIAL_PORT = "/dev/ttyAMA0"
SERIAL_BAUD = 1000000
TCP_HOST = "0.0.0.0"
TCP_PORT = 9000
POLL_INTERVAL = 0.1  # 10 Hz angle polling

mc = None
serial_lock = threading.Lock()

# Cached values with timestamps
cache = {
    "angles": None,
    "coords": None,
    "angles_ts": 0,
    "coords_ts": 0,
}
cache_lock = threading.Lock()


def init_robot():
    global mc
    from pymycobot import MyCobot280
    print(f"Opening serial {SERIAL_PORT} @ {SERIAL_BAUD}...")
    mc = MyCobot280(SERIAL_PORT, SERIAL_BAUD)
    time.sleep(1)
    print("Robot initialized")


def cache_poller():
    """Background thread: continuously read angles and cache them."""
    while True:
        try:
            with serial_lock:
                a = mc.get_angles()
            if a and a != -1 and isinstance(a, list) and len(a) == 6:
                with cache_lock:
                    cache["angles"] = [round(v, 2) for v in a]
                    cache["angles_ts"] = time.time()
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)


def handle_command(cmd_data):
    """Execute a command and return a result dict."""
    cmd = cmd_data.get("cmd", "")

    if cmd == "get_angles":
        with cache_lock:
            return {"r": cache["angles"], "ts": cache["angles_ts"]}

    elif cmd == "get_coords":
        with serial_lock:
            c = mc.get_coords()
        if c and c != -1 and isinstance(c, list) and len(c) >= 6:
            return {"r": [round(v, 2) for v in c]}
        return {"r": None}

    elif cmd == "send_angles":
        with serial_lock:
            mc.send_angles(cmd_data["a"], cmd_data["s"])
        return {"r": "ok"}

    elif cmd == "send_coords":
        with serial_lock:
            mc.send_coords(cmd_data["c"], cmd_data["s"], cmd_data.get("m", 0))
        return {"r": "ok"}

    elif cmd == "release":
        with serial_lock:
            mc.release_all_servos()
        return {"r": "ok"}

    elif cmd == "focus":
        with serial_lock:
            mc.focus_all_servos()
        return {"r": "ok"}

    elif cmd == "power_on":
        with serial_lock:
            mc.power_on()
        return {"r": "ok"}

    elif cmd == "power_off":
        with serial_lock:
            mc.power_off()
        return {"r": "ok"}

    elif cmd == "color":
        with serial_lock:
            mc.set_color(cmd_data["r"], cmd_data["g"], cmd_data["b"])
        return {"r": "ok"}

    elif cmd == "get_encoders":
        with serial_lock:
            e = mc.get_encoders()
        if e and e != -1:
            return {"r": e}
        return {"r": None}

    elif cmd == "is_moving":
        with serial_lock:
            m = mc.is_moving()
        return {"r": m}

    elif cmd == "ping":
        return {"r": "pong"}

    else:
        return {"e": f"unknown: {cmd}"}


def handle_client(conn, addr):
    """Handle one TCP client — newline-delimited JSON."""
    print(f"Client connected: {addr}")
    buf = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    cmd_data = json.loads(line.decode("utf-8"))
                    result = handle_command(cmd_data)
                    resp = json.dumps(result).encode("utf-8") + b"\n"
                    conn.sendall(resp)
                except json.JSONDecodeError:
                    conn.sendall(b'{"e":"bad json"}\n')
                except Exception as ex:
                    conn.sendall(json.dumps({"e": str(ex)}).encode("utf-8") + b"\n")
    except (ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        print(f"Client error: {e}")
    finally:
        conn.close()
        print(f"Client disconnected: {addr}")


def main():
    init_robot()

    # Start cache poller
    t = threading.Thread(target=cache_poller, daemon=True)
    t.start()
    print(f"Angle cache poller running at {1/POLL_INTERVAL:.0f} Hz")

    # TCP server (supports multiple clients)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((TCP_HOST, TCP_PORT))
    srv.listen(5)
    print(f"Listening on {TCP_HOST}:{TCP_PORT}")

    while True:
        conn, addr = srv.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
