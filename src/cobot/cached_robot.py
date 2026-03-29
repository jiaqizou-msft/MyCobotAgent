"""
CachedRobot — Drop-in replacement for MyCobot280Socket.
Talks to robot_cache_server.py running on the Pi.
Angles are served from a 10Hz cache on the Pi, so reads are
instant and work even with released servos.
"""
import socket
import json


class CachedRobot:
    def __init__(self, ip, port=9000):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((ip, port))
        self.buf = b""

    def _cmd(self, d):
        self.sock.sendall(json.dumps(d).encode() + b"\n")
        while b"\n" not in self.buf:
            self.buf += self.sock.recv(4096)
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    # --- Read ---
    def get_angles(self):
        r = self._cmd({"cmd": "get_angles"})
        return r.get("r") or -1

    def get_coords(self):
        r = self._cmd({"cmd": "get_coords"})
        return r.get("r") or -1

    def get_encoders(self):
        r = self._cmd({"cmd": "get_encoders"})
        return r.get("r") or -1

    def is_moving(self):
        return self._cmd({"cmd": "is_moving"}).get("r")

    # --- Move ---
    def send_angles(self, angles, speed):
        self._cmd({"cmd": "send_angles", "a": angles, "s": speed})

    def send_coords(self, coords, speed, mode=0):
        self._cmd({"cmd": "send_coords", "c": coords, "s": speed, "m": mode})

    # --- Servo control ---
    def release_all_servos(self):
        self._cmd({"cmd": "release"})

    def focus_all_servos(self):
        self._cmd({"cmd": "focus"})

    def power_on(self):
        self._cmd({"cmd": "power_on"})

    def power_off(self):
        self._cmd({"cmd": "power_off"})

    # --- LED ---
    def set_color(self, r, g, b):
        self._cmd({"cmd": "color", "r": r, "g": g, "b": b})

    # --- Utility ---
    def ping(self):
        return self._cmd({"cmd": "ping"}).get("r") == "pong"

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
