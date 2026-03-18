"""Check key spacing and adjust if needed."""
import json

with open("keyboard_taught.json", "r") as f:
    d = json.load(f)

k = d["keys"]
for n in ["a", "s", "d", "f", "g"]:
    c = k[n]["coords"][:2]
    print(f"  {n}: X={c[0]:.1f} Y={c[1]:.1f}")

a_x = k["a"]["coords"][0]
s_x = k["s"]["coords"][0]
d_x = k["d"]["coords"][0]
f_x = k["f"]["coords"][0]

print(f"\n  a→s: {s_x - a_x:.1f}mm")
print(f"  s→d: {d_x - s_x:.1f}mm")
print(f"  d→f: {f_x - d_x:.1f}mm")

# 'd' hit 's' → d needs more X. The step is 15.4mm per key.
# A typical laptop key is ~19mm wide. Our 15.4mm per key is too tight.
# Let's check: taught 'a' was at 206.3, taught '5' was at 265.9
# '5' is at row=0,col=5 and 'a' is at row=2,col=0
# X_5 - X_a = 265.9 - 206.3 = 59.6 over 5 columns and -2 rows
# 59.6 = 5*col_step + (-2)*row_step → 5*col_step - 2*7.55 = 59.6 → col_step = (59.6+15.1)/5 = 14.9mm
# But actual key pitch is ~19mm. So our col_step is ~4mm too small.
print(f"\n  Current col step: ~15.4mm")
print(f"  Typical laptop key pitch: ~19mm")
print(f"  Need to increase col step by ~3.5mm")
