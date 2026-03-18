"""Fix: hitting 1 column to the right. Shift X by -1 column step."""
import json

with open("keyboard_taught.json", "r") as f:
    data = json.load(f)

# From model: X changes by 15.36 per column. Shift back by 1 column.
COL_OFFSET_X = -15.36
COL_OFFSET_Y = -0.57  # tiny Y per col

keys = data["keys"]
for key_data in keys.values():
    key_data["coords"][0] = round(key_data["coords"][0] + COL_OFFSET_X, 2)
    key_data["coords"][1] = round(key_data["coords"][1] + COL_OFFSET_Y, 2)

data["col_correction_applied"] = True

with open("keyboard_taught.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"Applied -1 column correction: X{COL_OFFSET_X:+.1f}mm, Y{COL_OFFSET_Y:+.1f}mm")
for k in ["q", "a", "d", "z", "1", "2", "3"]:
    c = keys[k]["coords"][:3]
    print(f"  '{k}': ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})")
