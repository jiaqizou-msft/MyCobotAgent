"""Analyze testable keys."""
import json

with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\keyboard_taught.json") as f:
    d = json.load(f)
keys = d["keys"]

typeable = {}
special = {}
out_of_reach = {}

for k, v in keys.items():
    coords = v["coords"][:3]
    arm = v.get("arm", "?")
    x = coords[0]
    in_reach = -281.45 <= x <= 281.45

    if not in_reach:
        out_of_reach[k] = {"coords": coords, "arm": arm}
    elif len(k) == 1:
        typeable[k] = {"coords": coords, "arm": arm}
    elif k in ("space", "enter", "tab", "backspace"):
        special[k] = {"coords": coords, "arm": arm}

print(f"Typeable single-char keys in reach: {len(typeable)}")
for k in sorted(typeable):
    c = typeable[k]
    print(f"  {k:5s}  arm={c['arm']:6s}  x={c['coords'][0]:7.1f}  y={c['coords'][1]:7.1f}  z={c['coords'][2]:7.1f}")

print(f"\nSpecial keys in reach: {len(special)}")
for k in sorted(special):
    c = special[k]
    print(f"  {k:10s}  arm={c['arm']:6s}  x={c['coords'][0]:7.1f}")

print(f"\nOut of reach: {len(out_of_reach)}")
for k in sorted(out_of_reach):
    c = out_of_reach[k]
    print(f"  {k:5s}  arm={c['arm']:6s}  x={c['coords'][0]:7.1f}")
