"""Small Y offset to center on keys (currently hitting bottom rim)."""
import json

with open("keyboard_taught.json", "r") as f:
    data = json.load(f)

# Hitting bottom rim → need to shift +Y by ~5mm to center on key
Y_NUDGE = 5.0

keys = data["keys"]
for key_data in keys.values():
    key_data["coords"][1] = round(key_data["coords"][1] + Y_NUDGE, 2)

data["y_nudge_applied"] = Y_NUDGE

with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"Applied Y nudge: +{Y_NUDGE}mm")
for k in ["q", "d", "a", "s", "z"]:
    c = keys[k]["coords"][:3]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")
