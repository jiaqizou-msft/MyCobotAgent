"""Compress the demo GIF for GitHub README (target < 5MB)."""
from PIL import Image
import os

gif_path = "demo_typing.gif"
out_path = "demo_typing_compressed.gif"

img = Image.open(gif_path)
frames = []
try:
    while True:
        # Resize to smaller dimensions
        frame = img.copy().resize((640, int(640 * img.height / img.width)), Image.LANCZOS)
        # Quantize to reduce colors
        frame = frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        frames.append(frame)
        img.seek(img.tell() + 1)
except EOFError:
    pass

# Skip frames to reduce count (every 2nd frame)
frames = frames[::2]

print(f"Frames: {len(frames)}")
frames[0].save(
    out_path,
    save_all=True,
    append_images=frames[1:],
    duration=200,  # 5fps
    loop=0,
    optimize=True,
)

size_kb = os.path.getsize(out_path) / 1024
print(f"Compressed GIF: {out_path} ({size_kb:.0f}KB, {len(frames)} frames)")

if size_kb > 5000:
    # Further reduce — skip more frames and shrink
    frames2 = frames[::2]
    smaller = []
    for f in frames2:
        rgb = f.convert("RGB")
        rgb = rgb.resize((480, int(480 * rgb.height / rgb.width)), Image.LANCZOS)
        smaller.append(rgb.quantize(colors=64))

    out2 = "demo_typing_small.gif"
    smaller[0].save(out2, save_all=True, append_images=smaller[1:],
                    duration=250, loop=0, optimize=True)
    size2 = os.path.getsize(out2) / 1024
    print(f"Smaller GIF: {out2} ({size2:.0f}KB, {len(smaller)} frames)")
