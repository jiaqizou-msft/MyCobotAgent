"""
Voice Control System for myCobot 280.

Listens to your microphone, transcribes speech, and executes robot commands.

Supports:
  - Direct commands: "press key A", "type hello", "go home", "dance"
  - Natural language: "move the finger to the D key and press it"
  - LLM-powered: complex instructions parsed by GPT-4o agent planner

Usage:
  python voice_control.py              # continuous listening mode
  python voice_control.py --once       # listen for one command and execute
  python voice_control.py --push-to-talk  # hold Enter to talk
"""
import speech_recognition as sr
import time
import json
import sys
import os
import re
import threading
from pymycobot import MyCobot280Socket

ROBOT_IP = '10.105.230.93'
ROBOT_PORT = 9000


class VoiceController:
    def __init__(self):
        self.mc = None
        self.recognizer = sr.Recognizer()
        self.mic = None
        self.keyboard_keys = {}
        self.kbd_z = 130.3
        self.running = True

        # Motion params
        self.hover_z = 145
        self.press_z_offset = 3
        self.slide_speed = 12
        self.press_speed = 6
        self.travel_speed = 15

    def setup(self):
        """Connect to robot, load keyboard layout, test microphone."""
        # Connect robot
        print("Connecting to robot...")
        self.mc = MyCobot280Socket(ROBOT_IP, ROBOT_PORT)
        time.sleep(1)
        self.mc.set_color(0, 200, 255)  # cyan = voice mode

        # Load keyboard layout
        try:
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            with open(os.path.join(data_dir, "keyboard_taught.json")) as f:
                data = json.load(f)
            self.keyboard_keys = data.get("keys", {})
            self.kbd_z = data.get("keyboard_z", 130.3)
            print(f"  Keyboard loaded: {len(self.keyboard_keys)} keys")
        except FileNotFoundError:
            print("  WARNING: No keyboard layout. Key pressing won't work.")

        # Test microphone
        print("  Testing microphone...")
        self.mic = sr.Microphone()
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        print("  Microphone ready.")
        print()

    def listen(self, timeout=5, phrase_time_limit=10):
        """Listen for speech and return transcribed text."""
        with self.mic as source:
            print("  Listening...")
            try:
                audio = self.recognizer.listen(source, timeout=timeout,
                                                phrase_time_limit=phrase_time_limit)
                print("  Transcribing...")
                text = self.recognizer.recognize_google(audio)
                return text.lower().strip()
            except sr.WaitTimeoutError:
                return None
            except sr.UnknownValueError:
                print("  Could not understand audio.")
                return None
            except sr.RequestError as e:
                print(f"  Speech API error: {e}")
                return None

    # ── Command Parsing ──────────────────────────────────────────────────

    def parse_and_execute(self, text):
        """Parse a voice command and execute it."""
        if not text:
            return

        print(f'\n  Command: "{text}"')
        self.mc.set_color(255, 165, 0)  # orange = executing

        # Match patterns
        executed = False

        # "press [key]" or "press key [key]"
        m = re.match(r"(?:press|hit|tap)\s+(?:key\s+)?(.+)", text)
        if m:
            key = m.group(1).strip()
            if len(key) == 1 or key in ('space', 'enter', 'tab', 'esc', 'backspace'):
                self.press_key(key)
                executed = True

        # "type [text]"
        if not executed:
            m = re.match(r"(?:type|write|spell)\s+(.+)", text)
            if m:
                self.type_text(m.group(1).strip())
                executed = True

        # "go home" / "home"
        if not executed and re.match(r"(?:go\s+)?home|reset|zero", text):
            self.go_home()
            executed = True

        # "dance"
        if not executed and "dance" in text:
            self.dance()
            executed = True

        # "shake" / "shake head" / "no"
        if not executed and re.match(r"shake|no\b", text):
            self.head_shake()
            executed = True

        # "nod" / "yes"
        if not executed and re.match(r"nod|yes\b", text):
            self.head_nod()
            executed = True

        # "release" / "free" / "relax"
        if not executed and re.match(r"release|free|relax", text):
            self.mc.release_all_servos()
            print("  Servos released.")
            executed = True

        # "lock" / "hold"
        if not executed and re.match(r"lock|hold|freeze", text):
            self.mc.focus_all_servos()
            print("  Servos locked.")
            executed = True

        # "led [color]" / "color [color]"
        if not executed:
            m = re.match(r"(?:led|color|light)\s+(.+)", text)
            if m:
                self.set_led_by_name(m.group(1).strip())
                executed = True

        # "stop"
        if not executed and "stop" in text:
            self.mc.stop()
            print("  Motion stopped.")
            executed = True

        # "status"
        if not executed and "status" in text:
            self.print_status()
            executed = True

        # "can you type ..." / "please type ..." / "type in ..."
        if not executed:
            m = re.search(r"(?:can you |please |go ahead and )?(?:type|write|spell)(?:\s+in)?\s+(.+)", text)
            if m:
                self.type_text(m.group(1).strip())
                executed = True

        # Fallback: try as typing if it's short
        if not executed:
            if len(text) <= 8 and text.replace(' ', '').isalpha():
                print(f'  Interpreting as type command: "{text}"')
                self.type_text(text)
                executed = True
            else:
                print(f'  Unknown command: "{text}"')
                print("  Try: press A, type hello, go home, dance, led red, stop")

        self.mc.set_color(0, 200, 255)  # back to cyan

    # ── Robot Actions ────────────────────────────────────────────────────

    def press_key(self, key_name):
        """Press a single key."""
        key = key_name.lower()
        if key not in self.keyboard_keys:
            print(f"  Key '{key}' not in keyboard layout!")
            return

        coords = self.keyboard_keys[key]["coords"][:3]
        x, y, z = coords
        press_z = z - self.press_z_offset

        print(f"  Pressing '{key}'...")
        self.mc.send_coords([x, y, self.hover_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)
        self.mc.send_coords([x, y, press_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1.2)
        self.mc.send_coords([x, y, self.hover_z, 0, 180, 90], self.press_speed, 0)
        time.sleep(1)
        print(f"  Pressed '{key}'.")

    def type_text(self, text):
        """Type a string of characters."""
        keys = []
        for ch in text:
            k = 'space' if ch == ' ' else ch.lower()
            if k not in self.keyboard_keys:
                print(f"  Skipping '{k}' (not in layout)")
                continue
            coords = self.keyboard_keys[k]["coords"][:3]
            x, y = coords[0], coords[1]
            # Reachability check
            if not (-281 <= x <= 281 and -281 <= y <= 281):
                print(f"  Skipping '{k}' (out of reach: X={x:.0f})")
                continue
            keys.append((k, coords))

        if not keys:
            return

        # Move to first key
        x, y, z = keys[0][1]
        self.mc.send_coords([x, y, self.hover_z, 0, 180, 90], self.travel_speed, 0)
        time.sleep(3)

        for key, (x, y, z) in keys:
            press_z = z - self.press_z_offset
            self.mc.send_coords([x, y, self.hover_z, 0, 180, 90], self.slide_speed, 0)
            time.sleep(1.5)
            self.mc.send_coords([x, y, press_z, 0, 180, 90], self.press_speed, 0)
            time.sleep(1.2)
            self.mc.send_coords([x, y, self.hover_z, 0, 180, 90], self.press_speed, 0)
            time.sleep(1.0)
            print(f"  '{key}'", end=" ", flush=True)

        # Retreat
        self.mc.send_coords([x, y, 200, 0, 180, 90], self.travel_speed, 0)
        time.sleep(2)
        print(f"\n  Typed: '{text}'")

    def go_home(self):
        print("  Going home...")
        self.mc.send_angles([0, 0, 0, 0, 0, 0], 15)
        time.sleep(4)
        print("  Home.")

    def dance(self):
        print("  Dancing...")
        mc = self.mc
        mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
        time.sleep(1)
        mc.send_angles([-0.17, -94.3, 118.91, -39.9, 59.32, -0.52], 80)
        time.sleep(1.2)
        mc.send_angles([67.85, -3.42, -116.98, 106.52, 23.11, -0.52], 80)
        time.sleep(1.7)
        mc.send_angles([-38.14, -115.04, 116.63, 69.69, 3.25, -11.6], 80)
        time.sleep(1.7)
        mc.send_angles([0, 0, 0, 0, 0, 0], 80)
        time.sleep(2)
        print("  Dance complete!")

    def head_shake(self):
        print("  Shaking head...")
        mc = self.mc
        mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
        time.sleep(1)
        for _ in range(2):
            mc.send_angle(5, 30, 80)
            time.sleep(0.5)
            mc.send_angle(5, -30, 80)
            time.sleep(0.5)
        mc.send_angles([0, 0, 0, 0, 0, 0], 40)
        time.sleep(2)

    def head_nod(self):
        print("  Nodding...")
        mc = self.mc
        mc.send_angles([0.87, -50.44, 47.28, 0.35, -0.43, -0.26], 70)
        time.sleep(1)
        for _ in range(2):
            mc.send_angle(4, 13, 70)
            time.sleep(0.5)
            mc.send_angle(4, -20, 70)
            time.sleep(1)
        mc.send_angles([0, 0, 0, 0, 0, 0], 40)
        time.sleep(2)

    def set_led_by_name(self, color_name):
        colors = {
            "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
            "white": (255, 255, 255), "off": (0, 0, 0),
            "yellow": (255, 255, 0), "purple": (128, 0, 255),
            "orange": (255, 165, 0), "pink": (255, 100, 150),
            "cyan": (0, 255, 255),
        }
        rgb = colors.get(color_name, None)
        if rgb:
            self.mc.set_color(*rgb)
            print(f"  LED set to {color_name}.")
        else:
            print(f"  Unknown color '{color_name}'. Try: red, green, blue, white, off")

    def print_status(self):
        mc = self.mc
        angles = mc.get_angles()
        time.sleep(0.3)
        coords = mc.get_coords()
        time.sleep(0.3)
        power = mc.is_power_on()
        print(f"  Power: {power}")
        print(f"  Angles: {angles}")
        print(f"  Coords: {coords}")

    # ── Main Loops ───────────────────────────────────────────────────────

    def run_continuous(self):
        """Continuously listen and execute commands."""
        print("=" * 55)
        print("  VOICE CONTROL - Continuous Mode")
        print("=" * 55)
        print("  Say commands like:")
        print('    "press A"')
        print('    "type hello"')
        print('    "go home"')
        print('    "dance"')
        print('    "shake"')
        print('    "led red"')
        print('    "stop"')
        print("  Say 'quit' or 'exit' to stop.")
        print("=" * 55)
        print()

        while self.running:
            text = self.listen(timeout=None, phrase_time_limit=10)
            if text:
                if text in ("quit", "exit", "stop listening"):
                    print("  Exiting voice control.")
                    break
                self.parse_and_execute(text)

    def run_push_to_talk(self):
        """Press Enter to start listening, then speak."""
        print("=" * 55)
        print("  VOICE CONTROL - Push to Talk")
        print("=" * 55)
        print("  Press ENTER to start listening, then speak.")
        print("  Type 'quit' to exit.")
        print("=" * 55)
        print()

        while self.running:
            cmd = input("  [Press ENTER to talk, or type command] ").strip()
            if cmd.lower() in ("quit", "exit"):
                break
            if cmd:
                # Typed command
                self.parse_and_execute(cmd)
            else:
                # Voice input
                text = self.listen(timeout=5, phrase_time_limit=10)
                if text:
                    self.parse_and_execute(text)

    def run_hybrid(self):
        """Accept both voice and typed commands."""
        print("=" * 55)
        print("  VOICE CONTROL - Hybrid Mode")
        print("=" * 55)
        print("  Type commands directly OR press ENTER to speak.")
        print("  Commands: press <key>, type <text>, home, dance,")
        print("            shake, nod, led <color>, status, quit")
        print("=" * 55)
        print()

        while self.running:
            try:
                cmd = input("\n  Command (or ENTER to speak): ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if cmd.lower() in ("quit", "exit", "q"):
                break

            if cmd:
                self.parse_and_execute(cmd)
            else:
                text = self.listen(timeout=8, phrase_time_limit=10)
                if text:
                    self.parse_and_execute(text)


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    vc = VoiceController()
    vc.setup()

    if "--continuous" in sys.argv:
        vc.run_continuous()
    elif "--push-to-talk" in sys.argv or "--ptt" in sys.argv:
        vc.run_push_to_talk()
    else:
        vc.run_hybrid()

    # Cleanup
    vc.go_home()
    vc.mc.set_color(255, 255, 255)
    print("\nVoice control ended.")
