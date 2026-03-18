"""Check which keys are reachable by the robot and mark unreachable ones."""
import json
import numpy as np

with open("keyboard_taught.json", "r") as f:
    data = json.load(f)

# myCobot 280 approximate reachable workspace (Cartesian, pointing down)
# X: roughly 80-280mm (forward from base)
# Y: roughly -200 to 200mm (left-right)
# These are conservative estimates
MAX_REACH_X = 270
MIN_REACH_X = 80
MAX_REACH_Y = 200
MIN_REACH_Y = -200

# Also the combined XY distance from base must be within arm reach
MAX_RADIUS = 280  # mm from base center

keys = data["keys"]

reachable = []
unreachable = []

for key_name, key_data in sorted(keys.items()):
    coords = key_data["coords"]
    x, y, z = coords[0], coords[1], coords[2]
    radius = np.sqrt(x**2 + y**2)
    
    in_range = (MIN_REACH_X <= x <= MAX_REACH_X and 
                MIN_REACH_Y <= y <= MAX_REACH_Y and
                radius <= MAX_RADIUS)
    
    if in_range:
        reachable.append(key_name)
    else:
        unreachable.append(key_name)
        key_data["reachable"] = False
    
    if not in_range:
        reason = []
        if x > MAX_REACH_X:
            reason.append(f"X={x:.0f}>{MAX_REACH_X}")
        if x < MIN_REACH_X:
            reason.append(f"X={x:.0f}<{MIN_REACH_X}")
        if radius > MAX_RADIUS:
            reason.append(f"R={radius:.0f}>{MAX_RADIUS}")
        print(f"  OUT OF RANGE: '{key_name}' at ({x:.1f}, {y:.1f}) - {', '.join(reason)}")
    else:
        key_data["reachable"] = True

print(f"\nReachable: {len(reachable)} keys")
print(f"  {', '.join(reachable)}")
print(f"\nUnreachable: {len(unreachable)} keys")
print(f"  {', '.join(unreachable)}")

# Save updated
with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"\nUpdated keyboard_taught.json with reachability flags.")

# Print the reachable key map
print("\n  Reachable key map:")
QWERTY = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
]
for row in QWERTY:
    line = "    "
    for k in row:
        if k in keys and keys[k].get("reachable", True):
            line += f"[{k}] "
        else:
            line += f" {k}  "
    print(line)
