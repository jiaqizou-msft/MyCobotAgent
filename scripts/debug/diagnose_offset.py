"""Diagnose the offset: s->x, a->z, d->c means shifted ~1 row down, ~1 col left."""
import json
import numpy as np

with open("keyboard_taught.json") as f:
    data = json.load(f)

keys = data["keys"]
# What was typed vs what should have been:
# Target: s(row2,col1) -> got x(row3,col1): 1 row too far
# Target: a(row2,col0) -> got z(row3,col0): 1 row too far  
# Target: d(row2,col3) -> got c(row3,col2): 1 row + 1 col off

# But s,a,d were TAUGHT directly, so their positions should be exact.
# Let's check what robot coords are being used:
for k in ['s', 'a', 'd', 'x', 'z', 'c']:
    if k in keys:
        c = keys[k]["coords"][:3]
        src = keys[k].get("source", "?")
        print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}) [{src}]")

# The taught 's' should go to s, but it goes to x
# That means the taught coordinate for 's' is actually at x's location on the real keyboard
# This means during teaching, get_coords() was returning WRONG values
# (like the stale reading problem from before)

# Let's look at the raw taught data
taught = data.get("taught_reference", {})
print("\nRaw taught data:")
for k, v in sorted(taught.items()):
    if "robot_coords" in v:
        rc = v["robot_coords"][:3]
        px = v.get("rs_pixel", "?")
        print(f"  '{k}': robot=({rc[0]:.1f},{rc[1]:.1f},{rc[2]:.1f}), pixel={px}")

# Check if the taught keys have very similar X values (stale reading)
print("\nX values of consecutive keys:")
for k in ['a','s','d','h']:
    if k in taught:
        print(f"  '{k}': X={taught[k]['robot_coords'][0]:.1f}")
