"""Inspect detected key layout."""
import json
with open("device_layout.json") as f:
    d = json.load(f)

print("Keyboard bounds:", d.get("keyboard_bounds_px"))
print()
for k in ["a", "s", "d", "q", "w", "z", "1", "2", "g", "`"]:
    if k in d["keyboard"]:
        info = d["keyboard"][k]
        px = info["pixel"]
        rb = info["robot"]
        dm = info.get("depth_m", 0)
        print(f"  '{k}': pixel=({px[0]},{px[1]}), robot=({rb[0]:.1f},{rb[1]:.1f},{rb[2]:.1f}), depth={dm*1000:.0f}mm")

# Check Z range
zvals = [v["robot"][2] for v in d["keyboard"].values() if "robot" in v]
print(f"\nZ range: {min(zvals):.1f} to {max(zvals):.1f}mm")
print(f"Z mean:  {sum(zvals)/len(zvals):.1f}mm")
