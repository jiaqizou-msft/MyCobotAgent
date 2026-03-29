"""
Type text with concurrent dual-arm motion.
While one arm presses a key, the other arm pre-positions to its next key.
Higher hover for safe clearance between adjacent keys.
"""
import json, time, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.cobot.cached_robot import CachedRobot

RIGHT_IP = "192.168.0.5"
LEFT_IP = "192.168.0.6"
PORT = 9000
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

with open(os.path.join(DATA_DIR, "keyboard_taught.json")) as f:
    TAUGHT = json.load(f)["keys"]

HOVER_Z_OFFSET = 20  # mm above key — lower for faster tap
PRESS_Z_OFFSET = 3   # mm below key center
TAP_Z_OFFSET = 8     # mm above key — low hover for fast tap approach


def get_pos(ch):
    k = ch.lower()
    if k == " ":
        k = "space"
    if k not in TAUGHT:
        return None, None
    data = TAUGHT[k]
    return list(data["coords"][:3]), data.get("arm", "right")


def wait_until_still(mc, timeout=2.0):
    """Wait until the arm stops moving."""
    deadline = time.time() + timeout
    time.sleep(0.2)
    while time.time() < deadline:
        try:
            if not mc.is_moving():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def type_text(text, mc_r, mc_l):
    """Type with concurrent arms — other arm pre-moves while one presses."""
    # Build action list
    actions = []
    for ch in text:
        coords, arm = get_pos(ch)
        if coords is None:
            display = ch if ch != " " else "SPACE"
            print(f"  {display} - no position, skip")
            continue
        actions.append((ch, coords, arm))

    if not actions:
        return

    # Find next key index for a given arm starting from position i
    def next_for_arm(start, arm_name):
        for j in range(start, len(actions)):
            if actions[j][2] == arm_name:
                return j
        return -1

    # Center keys where arms might collide
    CENTER_KEYS = set("6 7 y u g h b n t j".split())
    # Nudge distance: move other arm ~30mm sideways instead of full retract
    NUDGE_DIST = 30

    for i, (ch, coords, arm) in enumerate(actions):
        mc = mc_l if arm == "left" else mc_r
        other_mc = mc_r if arm == "left" else mc_l
        other_arm = "right" if arm == "left" else "left"
        x, y, z = coords
        hover_z = z + HOVER_Z_OFFSET
        press_z = z - PRESS_Z_OFFSET
        display = ch.upper() if ch != " " else "SPACE"
        key_name = ch.lower() if ch != " " else "space"

        # If pressing a center key, nudge the other arm sideways
        if key_name in CENTER_KEYS:
            try:
                other_coords = other_mc.get_coords()
                if other_coords and other_coords != -1 and len(other_coords) >= 6:
                    ox, oy, oz = other_coords[0], other_coords[1], other_coords[2]
                    # Move other arm away: left arm moves +Y, right arm moves -Y
                    nudge_y = NUDGE_DIST if other_arm == "left" else -NUDGE_DIST
                    safe_z = max(oz, z + HOVER_Z_OFFSET)
                    other_mc.send_coords([ox, oy + nudge_y, safe_z, 0, 180, 90], 40, 0)
            except Exception:
                pass
            time.sleep(0.3)

        # Move active arm to hover position
        print(f"  {display} ({arm})", end="", flush=True)
        mc.send_coords([x, y, hover_z, 0, 180, 90], 40, 0)

        # For non-center keys, pre-position other arm to its next key
        if key_name not in CENTER_KEYS:
            next_idx = next_for_arm(i + 1, other_arm)
            if next_idx >= 0:
                nch, ncoords, _ = actions[next_idx]
                nkey = nch.lower() if nch != " " else "space"
                if nkey not in CENTER_KEYS:
                    nx, ny, nz = ncoords
                    other_mc.send_coords([nx, ny, nz + HOVER_Z_OFFSET, 0, 180, 90], 40, 0)

        # Wait for active arm to reach hover
        wait_until_still(mc, timeout=1.5)

        # Two-stage tap for ~100ms contact:
        # 1. Drop to low hover (close to key surface)
        tap_z = z + TAP_Z_OFFSET
        mc.send_coords([x, y, tap_z, 0, 180, 90], 50, 0)
        wait_until_still(mc, timeout=1.0)

        # 2. Quick strike: press and immediately lift
        mc.send_coords([x, y, press_z, 0, 180, 90], 80, 0)
        time.sleep(0.1)  # ~100ms contact
        mc.send_coords([x, y, hover_z, 0, 180, 90], 50, 0)
        time.sleep(0.1)
        wait_until_still(mc, timeout=1.0)
        print(" ok")


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Paven"

    mc_r = CachedRobot(RIGHT_IP, PORT)
    mc_l = CachedRobot(LEFT_IP, PORT)
    mc_r.power_on()
    mc_l.power_on()
    time.sleep(1)

    print(f"Typing: {text}")
    type_text(text, mc_r, mc_l)

    mc_r.send_angles([0, 0, 0, 0, 0, 0], 25)
    mc_l.send_angles([0, 0, 0, 0, 0, 0], 25)
    time.sleep(2)
    print("Done!")
