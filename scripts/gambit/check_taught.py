"""Quick check of taught keyboard data."""
import json

with open(r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\keyboard_taught.json") as f:
    d = json.load(f)
keys = d["keys"]
left = {k: v for k, v in keys.items() if v.get("arm") == "left"}
right = {k: v for k, v in keys.items() if v.get("arm") == "right"}
print(f"Total: {len(keys)} keys ({len(left)} left, {len(right)} right)")

# Single-char testable keys
left_chars = sorted([k for k in left if len(k) == 1 and -281.45 <= left[k]["coords"][0] <= 281.45])
right_chars = sorted([k for k in right if len(k) == 1 and -281.45 <= right[k]["coords"][0] <= 281.45])
print(f"\nTestable single-char keys:")
print(f"  Left arm ({len(left_chars)}): {left_chars}")
print(f"  Right arm ({len(right_chars)}): {right_chars}")
print(f"  Total: {len(left_chars) + len(right_chars)}")

print(f"\nRight arm sample positions:")
for k in ["8", "i", "k", "l", "p", ";", "0", "/"]:
    if k in right:
        c = right[k]["coords"][:3]
        print(f"  {k:5s} x={c[0]:7.1f} y={c[1]:7.1f} z={c[2]:7.1f}")

if "taught_reference_right" in d:
    print(f"\nReference keys: {list(d['taught_reference_right'].keys())}")
