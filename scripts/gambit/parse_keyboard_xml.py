"""
Parse the Ortler keyboard layout XML and compute exact physical key centers in mm.
Maps key names from the XML to the lowercase key names used in taught positions.
"""
import xml.etree.ElementTree as ET
import json

XML_PATH = r"c:\Users\jiaqizou\SurfaceLaptopRobot\Ortler[DV][English].xml"

# Parse XML
tree = ET.parse(XML_PATH)
root = tree.getroot()

device = root.find("DEVICE")
keyset = device.find("KEYSET")

# Parse rows: row_number -> {Y, H}
rows_el = keyset.find("ROWS")
rows = {}
for row in rows_el.findall("ROW"):
    num = int(row.get("number"))
    y = float(row.get("Y"))
    h = float(row.get("H"))
    rows[num] = {"y": y, "h": h}

print("Rows:")
for num in sorted(rows):
    r = rows[num]
    print(f"  Row {num}: Y={r['y']:.2f}  H={r['h']:.2f}  center_y={r['y'] + r['h']/2:.2f}")

# XML key name -> lowercase key name mapping
KEY_NAME_MAP = {
    "ESC": "esc", "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
    "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8", "F9": "f9",
    "F10": "f10", "F11": "f11", "F12": "f12", "DEL": "del",
    "Tick": "`", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9", "0": "0",
    "-": "_", "=": "=", "Backspace": "backspace",
    "Tab": "tab", "Q": "q", "W": "w", "E": "e", "R": "r", "T": "t",
    "Y": "y", "U": "u", "I": "i", "O": "o", "P": "p",
    "L-Bracket": "[", "R-Bracket": "]", "Backslash": "\\",
    "Caplock": "caps", "A": "a", "S": "s", "D": "d", "F": "f",
    "G": "g", "H": "h", "J": "j", "K": "k", "L": "l",
    "Semicolon": ";", "Quote": "'", "Enter": "enter",
    "L-Shift": "shift_l", "Z": "z", "X": "x", "C": "c", "V": "v",
    "B": "b", "N": "n", "M": "m", "Comma": ",", "Period": ".",
    "Slash": "/", "R-Shift": "shift_r",
    "L-Ctrl": "ctrl_l", "Function": "fn", "Windows": "win",
    "L-Alt": "alt_l", "Spacebar": "space", "R-Alt": "alt_r",
    "Context": "copilot",  # context/copilot key
    "L-Arrow": "left", "U-Arrow": "up", "R-Arrow": "right", "D-Arrow": "down",
}

# Also map the output char that appears in Notepad -> key name
# For single chars, the char IS the key name
# For special keys, we need the reverse mapping
CHAR_TO_KEY = {}
for xml_name, key_name in KEY_NAME_MAP.items():
    if len(key_name) == 1:
        CHAR_TO_KEY[key_name] = key_name

# Parse keys: compute center position in mm
keys_el = keyset.find("KEYS")
key_positions = {}  # key_name -> {x_mm, y_mm, w_mm, h_mm, center_x_mm, center_y_mm}

for key in keys_el.findall("KEY"):
    text = key.get("text")
    w = float(key.get("W"))
    x = float(key.get("X"))
    row_num = int(key.get("Row"))

    row = rows[row_num]
    key_name = KEY_NAME_MAP.get(text, text.lower())

    center_x = x + w / 2
    center_y = row["y"] + row["h"] / 2

    key_positions[key_name] = {
        "xml_name": text,
        "row": row_num,
        "x_mm": x,
        "y_mm": row["y"],
        "w_mm": w,
        "h_mm": row["h"],
        "center_x_mm": round(center_x, 2),
        "center_y_mm": round(center_y, 2),
    }

print(f"\nParsed {len(key_positions)} keys")
print(f"\nKey positions (center in mm from keyboard top-left):")
for k in sorted(key_positions, key=lambda k: (key_positions[k]["center_y_mm"], key_positions[k]["center_x_mm"])):
    p = key_positions[k]
    print(f"  {k:12s}  center=({p['center_x_mm']:6.1f}, {p['center_y_mm']:5.1f})  "
          f"row={p['row']}  size=({p['w_mm']:.0f}x{p['h_mm']:.0f})")

# Save as JSON for the test script
output = {
    "keyboard_offset": {"x": 2, "y": 2},  # from XML UPPERLEFTOFFSET
    "touchpad_offset": {"x": 84, "y": 110},
    "touchpad_size": {"w": 111, "h": 90},
    "rows": rows,
    "keys": key_positions,
}
out_path = r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\keyboard_layout_xml.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"\nSaved to {out_path}")

# Show key pitch (distance between adjacent keys)
print("\n=== Key Pitch Analysis ===")
# Row 4 (home row): A through Enter
home_keys = [(k, key_positions[k]) for k in ["a","s","d","f","g","h","j","k","l",";","'"]
             if k in key_positions]
for i in range(1, len(home_keys)):
    prev_name, prev = home_keys[i-1]
    curr_name, curr = home_keys[i]
    dx = curr["center_x_mm"] - prev["center_x_mm"]
    print(f"  {prev_name} -> {curr_name}: dx={dx:.2f}mm")

# Row pitch (Y distance between rows)
print("\nRow pitch:")
row_centers = {num: rows[num]["y"] + rows[num]["h"]/2 for num in sorted(rows) if num <= 6}
for r in range(2, 7):
    if r in row_centers and r-1 in row_centers:
        dy = row_centers[r] - row_centers[r-1]
        print(f"  Row {r-1} -> Row {r}: dy={dy:.2f}mm")
