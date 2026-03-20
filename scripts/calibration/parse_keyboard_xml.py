"""
Parse the keyboard XML layout and build proper key position data.
The XML gives relative positions in mm. With one anchor key (pixel + robot coords),
we can compute every other key's position.
"""
import xml.etree.ElementTree as ET
import json
import os

XML_PATH = "data/keyboard_layout.xml"

tree = ET.parse(XML_PATH)
root = tree.getroot()
device = root.find("DEVICE")

# Parse rows
rows_data = {}
for row in device.find(".//ROWS"):
    num = int(row.get("number"))
    rows_data[num] = {
        "y_mm": float(row.get("Y")),
        "h_mm": float(row.get("H")),
    }

# Parse keys
keys_layout = {}
for key in device.find(".//KEYS"):
    text = key.get("text")
    w_mm = float(key.get("W"))
    x_mm = float(key.get("X"))
    row_num = int(key.get("Row"))
    row_info = rows_data[row_num]
    y_mm = row_info["y_mm"]
    h_mm = row_info["h_mm"]

    # Key center in mm from keyboard top-left
    cx_mm = x_mm + w_mm / 2
    cy_mm = y_mm + h_mm / 2

    # Normalize name
    name = text.lower().replace("-", "_")
    # Map to standard names
    name_map = {
        "tick": "`", "backspace": "backspace", "tab": "tab",
        "caplock": "caps", "enter": "enter",
        "l_shift": "shift_l", "r_shift": "shift_r",
        "l_ctrl": "ctrl_l", "function": "fn", "windows": "win",
        "l_alt": "alt_l", "spacebar": "space", "r_alt": "alt_r",
        "context": "copilot",
        "l_arrow": "left", "r_arrow": "right", "u_arrow": "up", "d_arrow": "down",
        "l_bracket": "[", "r_bracket": "]",
        "backslash": "\\", "semicolon": ";", "quote": "'",
        "comma": ",", "period": ".", "slash": "/",
    }
    std_name = name_map.get(name, name)

    keys_layout[std_name] = {
        "x_mm": round(x_mm, 2),
        "y_mm": round(y_mm, 2),
        "w_mm": round(w_mm, 2),
        "h_mm": round(h_mm, 2),
        "cx_mm": round(cx_mm, 2),
        "cy_mm": round(cy_mm, 2),
        "row": row_num,
        "original_name": text,
    }

# Parse touchpad
tp_offset = device.find(".//UPPERLEFTOFFSET/REGION[@Name='Touchpad']")
tp = device.find("TP")
touchpad_info = {
    "x_mm": float(tp_offset.get("X")),
    "y_mm": float(tp_offset.get("Y")),
    "w_mm": float(tp.get("W")),
    "h_mm": float(tp.get("H")),
}

# Save parsed layout
output = {
    "device": device.get("NAME"),
    "sku": device.get("SKU"),
    "type": device.get("TYPE"),
    "keyboard_offset_mm": {"x": 2, "y": 2},
    "touchpad": touchpad_info,
    "keys": keys_layout,
    "num_keys": len(keys_layout),
    "total_width_mm": max(k["x_mm"] + k["w_mm"] for k in keys_layout.values()),
    "total_height_mm": max(k["y_mm"] + k["h_mm"] for k in keys_layout.values()),
}

with open("data/keyboard_layout_parsed.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Parsed {len(keys_layout)} keys from {device.get('NAME')} layout")
print(f"Keyboard size: {output['total_width_mm']:.1f} x {output['total_height_mm']:.1f} mm")
print(f"Touchpad: ({touchpad_info['x_mm']}, {touchpad_info['y_mm']}) {touchpad_info['w_mm']}x{touchpad_info['h_mm']}mm")

print(f"\nSample keys:")
for k in ["esc", "q", "a", "z", "space", "enter", "backspace"]:
    if k in keys_layout:
        kd = keys_layout[k]
        print(f"  {k:12s}: center=({kd['cx_mm']:6.1f}, {kd['cy_mm']:5.1f})mm, size={kd['w_mm']:.0f}x{kd['h_mm']:.0f}")

print(f"\nRows:")
for rn in sorted(rows_data.keys()):
    rd = rows_data[rn]
    row_keys = [k for k, v in keys_layout.items() if v["row"] == rn]
    print(f"  Row {rn} (Y={rd['y_mm']:5.1f}, H={rd['h_mm']:4.1f}): {len(row_keys)} keys - {' '.join(row_keys[:8])}{'...' if len(row_keys)>8 else ''}")
