"""Check annotation and build cross-camera correspondence."""
import json
import numpy as np

# Check saved annotation
with open("data/keyboard_vision_detected.json") as f:
    anno = json.load(f)

print(f"Annotation: {anno['num_keys']} keys")
anchors = anno.get("anchors", {})
print(f"Anchors: {list(anchors.keys())}")

keys = anno["detected_keys"]
for k in ["esc", "q", "a", "z", "del", "enter", "space", "m", "shift_l", "right"]:
    if k in keys:
        px = keys[k]["pixel"]
        mm = keys[k].get("mm", [0,0])
        print(f"  {k:12s}: pixel=({px[0]:4d},{px[1]:4d}), mm=({mm[0]:6.1f},{mm[1]:5.1f})")

tp = anno.get("touchpad")
if tp:
    print(f"  touchpad   : pixel=({tp['pixel'][0]},{tp['pixel'][1]})")

print(f"\nTotal: {len(keys)} keys ready for cross-camera mapping")
