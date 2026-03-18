"""Small nudge: D hitting top-left of key, shift all keys +3mm X, -3mm Y to center."""
import json

with open("keyboard_taught.json") as f:
    data = json.load(f)

X_NUDGE = 3.0   # shift right
Y_NUDGE = -3.0  # shift down (toward front of keyboard)

for key_data in data["keys"].values():
    key_data["coords"][0] = round(key_data["coords"][0] + X_NUDGE, 2)
    key_data["coords"][1] = round(key_data["coords"][1] + Y_NUDGE, 2)

with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2, default=str)

k = data["keys"]
print(f"Applied nudge: X+{X_NUDGE}, Y{Y_NUDGE}")
for n in ["s", "a", "d"]:
    c = k[n]["coords"][:3]
    print(f"  '{n}': ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")
