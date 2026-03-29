"""
Keyboard Annotator v4 — XML layout + anchor-based positioning.

The XML gives exact key positions in mm. You only need to:
1. Click on TWO keys in the camera image to set anchors
2. The system maps all 78 keys from the XML layout to pixel positions
3. Drag-teach the robot on one key -> all keys get robot coords

Features:
- Click a key in the image, then press a letter to assign it as anchor
- Two anchors define the full mapping (position + scale + rotation)
- All keys from XML overlay on the image with correct geometry
- Fine-tune by dragging anchor points
- Save with both pixel and robot coordinates
"""
import tkinter as tk
from tkinter import simpledialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import cv2
import numpy as np
import json
import os
import math

DATA_PATH = "data/keyboard_vision_detected.json"
LAYOUT_PATH = "data/keyboard_layout_parsed.json"
IMG_PATH = "temp/overhead_for_annotation.jpg"
USE_REALSENSE_OVERHEAD = False  # Use USB camera
CAM_INDEX = 1  # Overhead camera
FLIP_180 = True  # Camera mounted upside down


class AnchorAnnotator:
    def __init__(self, root):
        self.root = root
        self.root.title("Keyboard Annotator — XML Layout + Anchor")
        self.root.geometry("1600x950")

        # Load XML layout
        with open(LAYOUT_PATH) as f:
            self.layout = json.load(f)
        self.xml_keys = self.layout["keys"]
        self.touchpad = self.layout["touchpad"]

        # Anchors: {key_name: {"mm": (cx_mm, cy_mm), "pixel": (px, py)}}
        self.anchors = {}
        self.all_key_pixels = {}  # computed pixel positions for all keys

        # Image
        self.load_image()
        self.zoom = 0.75
        self.offset_x = 0
        self.offset_y = 0

        # Interaction
        self.selected_anchor = None
        self.dragging = False
        self.drag_anchor = None
        self.mode = "anchor"  # "anchor" or "view"

        self.build_ui()
        self.root.after(100, self.zoom_fit)

    def load_image(self):
        if os.path.exists(IMG_PATH):
            self.cv_img = cv2.imread(IMG_PATH)
        else:
            self.recapture()
        self.img_h, self.img_w = self.cv_img.shape[:2]

    def recapture(self):
        cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        for _ in range(15):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if ret:
            if FLIP_180:
                frame = cv2.flip(frame, -1)
            self.cv_img = frame
        cv2.imwrite(IMG_PATH, self.cv_img)
        self.img_h, self.img_w = self.cv_img.shape[:2]

    def build_ui(self):
        tb = tk.Frame(self.root, bg="#2b2b2b", height=50)
        tb.pack(side=tk.TOP, fill=tk.X)
        bs = {"bg": "#444", "fg": "white", "padx": 6, "pady": 3, "font": ("Segoe UI", 9)}

        tk.Button(tb, text="Recapture", command=self.on_recapture, **bs).pack(side=tk.LEFT, padx=2, pady=4)
        tk.Button(tb, text="Clear Anchors", command=self.clear_anchors, **bs).pack(side=tk.LEFT, padx=2, pady=4)
        tk.Button(tb, text="Zoom Fit", command=self.zoom_fit, **bs).pack(side=tk.LEFT, padx=2, pady=4)

        tk.Frame(tb, width=20, bg="#2b2b2b").pack(side=tk.LEFT)

        tk.Button(tb, text="SAVE", command=self.on_save, bg="#1a8", fg="white",
                  padx=14, pady=3, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=6, pady=4)
        tk.Button(tb, text="Save & Quit", command=self.on_save_quit, bg="#18a", fg="white",
                  padx=10, pady=3, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=2, pady=4)

        self.status = tk.StringVar(value="Click on a key, then type its name to set as anchor. Need 2 anchors.")
        tk.Label(tb, textvariable=self.status, bg="#2b2b2b", fg="#0f0",
                 font=("Consolas", 9), wraplength=500).pack(side=tk.RIGHT, padx=8)

        # Main layout
        main = tk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sb = tk.Frame(main, width=250, bg="#1e1e1e")
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sb.pack_propagate(False)

        tk.Label(sb, text="Anchors", bg="#1e1e1e", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(pady=4)

        self.anchor_text = tk.Text(sb, bg="#2a2a2a", fg="#ddd", font=("Consolas", 9),
                                    height=6, width=28, state=tk.DISABLED)
        self.anchor_text.pack(padx=4, pady=4)

        tk.Label(sb, text="Instructions", bg="#1e1e1e", fg="#aaa",
                 font=("Segoe UI", 10, "bold")).pack(pady=(10, 2))

        instructions = (
            "1. Click on a key in the image\n"
            "2. Type the key name in the popup\n"
            "   (e.g. 'q', 'enter', 'space')\n"
            "3. Repeat for 2nd key far apart\n"
            "   -> All 78 keys auto-populate!\n"
            "4. Add 3rd/4th anchor for accuracy\n"
            "   (3+ = affine, corrects skew)\n"
            "\n"
            "Tips:\n"
            "- Pick keys at corners/edges\n"
            "  e.g. esc, del, shift_l, right\n"
            "- Drag red dots to fine-tune\n"
            "- Mouse wheel: zoom\n"
            "- Right-drag: pan\n"
            "- 'C' = recapture from camera\n"
        )
        tk.Label(sb, text=instructions, bg="#1e1e1e", fg="#888",
                 font=("Consolas", 8), justify=tk.LEFT).pack(padx=6)

        # Key count
        self.key_count_var = tk.StringVar(value="Mapped: 0 / 78 keys")
        tk.Label(sb, textvariable=self.key_count_var, bg="#1e1e1e", fg="#0f0",
                 font=("Segoe UI", 10, "bold")).pack(pady=10)

        # Canvas
        self.canvas = tk.Canvas(main, bg="#111", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-3>", self.on_rpan_start)
        self.canvas.bind("<B3-Motion>", self.on_rpan)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.root.bind("<Escape>", lambda e: self.deselect())

    def img2canvas(self, ix, iy):
        return ix * self.zoom + self.offset_x, iy * self.zoom + self.offset_y

    def canvas2img(self, cx, cy):
        return (cx - self.offset_x) / self.zoom, (cy - self.offset_y) / self.zoom

    def zoom_fit(self):
        cw = max(self.canvas.winfo_width(), 800)
        ch = max(self.canvas.winfo_height(), 600)
        self.zoom = min(cw / self.img_w, ch / self.img_h) * 0.95
        self.offset_x = (cw - self.img_w * self.zoom) / 2
        self.offset_y = (ch - self.img_h * self.zoom) / 2
        self.redraw()

    def compute_all_keys(self):
        """From anchors, compute pixel position of all keys.
        2 anchors: scale + rotation + translation (rigid)
        3+ anchors: full affine transform (handles skew/perspective)
        """
        n = len(self.anchors)
        if n < 2:
            self.all_key_pixels = {}
            self.key_count_var.set(f"Mapped: 0 / {len(self.xml_keys)} keys (need 2+ anchors)")
            return

        names = list(self.anchors.keys())

        if n == 2:
            # 2-point: rigid transform (scale + rotation + translation)
            a1, a2 = self.anchors[names[0]], self.anchors[names[1]]
            mm1, mm2 = np.array(a1["mm"]), np.array(a2["mm"])
            px1, px2 = np.array(a1["pixel"]), np.array(a2["pixel"])
            dmm, dpx = mm2 - mm1, px2 - px1
            dist_mm = np.linalg.norm(dmm)
            dist_px = np.linalg.norm(dpx)
            if dist_mm < 1:
                return
            scale = dist_px / dist_mm
            theta = math.atan2(dpx[1], dpx[0]) - math.atan2(dmm[1], dmm[0])
            cos_t = math.cos(theta) * scale
            sin_t = math.sin(theta) * scale
            tx = px1[0] - (cos_t * mm1[0] - sin_t * mm1[1])
            ty = px1[1] - (sin_t * mm1[0] + cos_t * mm1[1])

            def mm_to_px(mx, my):
                return cos_t * mx - sin_t * my + tx, sin_t * mx + cos_t * my + ty

            avg_scale = scale

        else:
            # 3+ points: full affine transform via least squares
            # [mm_x, mm_y, 1] @ M = [px_x, px_y]
            A = np.array([[ad["mm"][0], ad["mm"][1], 1] for ad in self.anchors.values()])
            B = np.array([ad["pixel"] for ad in self.anchors.values()])
            M, _, _, _ = np.linalg.lstsq(A, B, rcond=None)

            def mm_to_px(mx, my):
                pt = np.array([mx, my, 1.0]) @ M
                return float(pt[0]), float(pt[1])

            # Estimate scale from the affine matrix
            avg_scale = (np.linalg.norm(M[:2, 0]) + np.linalg.norm(M[:2, 1])) / 2

        # Map all keys
        self.all_key_pixels = {}
        for name, kd in self.xml_keys.items():
            px_x, px_y = mm_to_px(kd["cx_mm"], kd["cy_mm"])
            self.all_key_pixels[name] = {
                "pixel": [int(round(px_x)), int(round(px_y))],
                "mm": [kd["cx_mm"], kd["cy_mm"]],
                "w_mm": kd["w_mm"],
                "h_mm": kd["h_mm"],
                "w_px": int(round(kd["w_mm"] * avg_scale)),
                "h_px": int(round(kd["h_mm"] * avg_scale)),
                "row": kd["row"],
            }

        # Touchpad
        tp = self.touchpad
        tp_cx = tp["x_mm"] + tp["w_mm"] / 2
        tp_cy = tp["y_mm"] + tp["h_mm"] / 2
        tp_px_x, tp_px_y = mm_to_px(tp_cx, tp_cy)
        self.all_key_pixels["__touchpad__"] = {
            "pixel": [int(round(tp_px_x)), int(round(tp_px_y))],
            "w_px": int(round(tp["w_mm"] * avg_scale)),
            "h_px": int(round(tp["h_mm"] * avg_scale)),
        }

        # Verify: compute error at anchor points
        errors = []
        for aname, ad in self.anchors.items():
            pred_x, pred_y = mm_to_px(ad["mm"][0], ad["mm"][1])
            err = math.sqrt((pred_x - ad["pixel"][0])**2 + (pred_y - ad["pixel"][1])**2)
            errors.append(err)

        err_str = f" (err: {np.mean(errors):.1f}px)" if errors else ""
        self.key_count_var.set(
            f"Mapped: {len(self.all_key_pixels)-1} / {len(self.xml_keys)} keys{err_str}\n"
            f"Anchors: {n} | {'Rigid' if n == 2 else 'Affine'} transform"
        )

    def redraw(self):
        rgb = cv2.cvtColor(self.cv_img, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        draw = ImageDraw.Draw(pil)

        try:
            font = ImageFont.truetype("arial.ttf", 12)
            font_big = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
            font_big = font

        # Draw all computed key positions
        for name, kd in self.all_key_pixels.items():
            if name == "__touchpad__":
                # Draw touchpad
                px, py = kd["pixel"]
                hw, hh = kd["w_px"] // 2, kd["h_px"] // 2
                draw.rectangle([px-hw, py-hh, px+hw, py+hh], outline=(255, 0, 255), width=2)
                draw.text((px-20, py-8), "TOUCHPAD", fill=(255, 0, 255), font=font)
                continue

            px, py = kd["pixel"]
            hw, hh = kd["w_px"] // 2, kd["h_px"] // 2

            is_anchor = name in self.anchors
            if is_anchor:
                color = (255, 255, 0)
                width = 3
            else:
                color = (0, 200, 0)
                width = 1

            draw.rectangle([px-hw, py-hh, px+hw, py+hh], outline=color, width=width)
            draw.text((px-hw+2, py-hh+1), name, fill=(255, 255, 100), font=font)

        # Draw anchor points as big circles
        for name, ad in self.anchors.items():
            px, py = ad["pixel"]
            draw.ellipse([px-8, py-8, px+8, py+8], fill=(255, 50, 50), outline=(255, 255, 0), width=2)
            draw.text((px+10, py-20), f"ANCHOR: {name}", fill=(255, 100, 100), font=font_big)

        # Scale
        new_w = max(1, int(self.img_w * self.zoom))
        new_h = max(1, int(self.img_h * self.zoom))
        pil = pil.resize((new_w, new_h), Image.LANCZOS)

        self.tk_img = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")
        self.canvas.create_image(self.offset_x, self.offset_y, anchor=tk.NW, image=self.tk_img)

    # --- Events ---
    def on_press(self, event):
        ix, iy = self.canvas2img(event.x, event.y)

        # Check if clicking near an anchor (to drag it)
        for name, ad in self.anchors.items():
            px, py = ad["pixel"]
            if abs(px - ix) < 15 and abs(py - iy) < 15:
                self.dragging = True
                self.drag_anchor = name
                return

        # Otherwise: set a new anchor
        name = simpledialog.askstring(
            "Set Anchor",
            f"Which key is at pixel ({int(ix)}, {int(iy)})?\n"
            f"(e.g. 'q', 'esc', 'enter', 'space', 'del', '/')\n"
            f"\nCurrent anchors: {list(self.anchors.keys())}",
            parent=self.root
        )

        if name and name.strip():
            name = name.strip().lower()
            if name not in self.xml_keys:
                messagebox.showerror("Error", f"Key '{name}' not found in XML layout!\n"
                                      f"Available: {', '.join(sorted(self.xml_keys.keys())[:20])}...")
                return

            kd = self.xml_keys[name]
            self.anchors[name] = {
                "mm": (kd["cx_mm"], kd["cy_mm"]),
                "pixel": (int(ix), int(iy)),
            }
            self.update_anchor_text()
            self.compute_all_keys()
            self.redraw()
            n = len(self.anchors)
            if n < 2:
                self.status.set(f"Anchor '{name}' set! Click one more key far away for 2nd anchor.")
            else:
                self.status.set(f"{len(self.all_key_pixels)-1} keys mapped! Drag anchors to fine-tune. Press SAVE.")

    def on_drag(self, event):
        if self.dragging and self.drag_anchor:
            ix, iy = self.canvas2img(event.x, event.y)
            self.anchors[self.drag_anchor]["pixel"] = (int(ix), int(iy))
            self.compute_all_keys()
            self.redraw()

    def on_release(self, event):
        self.dragging = False
        self.drag_anchor = None
        self.update_anchor_text()

    def on_rpan_start(self, event):
        self._rpan = (event.x - self.offset_x, event.y - self.offset_y)

    def on_rpan(self, event):
        if hasattr(self, '_rpan'):
            self.offset_x = event.x - self._rpan[0]
            self.offset_y = event.y - self._rpan[1]
            self.redraw()

    def on_wheel(self, event):
        old = self.zoom
        if event.delta > 0:
            self.zoom = min(4.0, self.zoom * 1.15)
        else:
            self.zoom = max(0.2, self.zoom / 1.15)
        f = self.zoom / old
        self.offset_x = event.x - (event.x - self.offset_x) * f
        self.offset_y = event.y - (event.y - self.offset_y) * f
        self.redraw()

    def update_anchor_text(self):
        self.anchor_text.config(state=tk.NORMAL)
        self.anchor_text.delete("1.0", tk.END)
        for name, ad in self.anchors.items():
            mm = ad["mm"]
            px = ad["pixel"]
            self.anchor_text.insert(tk.END, f"{name}: mm=({mm[0]:.1f},{mm[1]:.1f}) px=({px[0]},{px[1]})\n")
        self.anchor_text.config(state=tk.DISABLED)

    def deselect(self):
        self.selected_anchor = None
        self.redraw()

    def clear_anchors(self):
        self.anchors = {}
        self.all_key_pixels = {}
        self.update_anchor_text()
        self.key_count_var.set(f"Mapped: 0 / {len(self.xml_keys)} keys")
        self.redraw()
        self.status.set("Anchors cleared. Click a key to start.")

    def on_recapture(self):
        self.recapture()
        self.redraw()

    def on_save(self):
        if not self.all_key_pixels:
            messagebox.showwarning("No Data", "Set 2 anchors first!")
            return

        data = {
            "camera_index": 0,  # default camera index
            "anchors": {k: {"mm": list(v["mm"]), "pixel": list(v["pixel"])} for k, v in self.anchors.items()},
            "detected_keys": {},
            "touchpad": None,
            "num_keys": 0,
        }

        for name, kd in self.all_key_pixels.items():
            if name == "__touchpad__":
                data["touchpad"] = kd
                continue
            data["detected_keys"][name] = {
                "pixel": kd["pixel"],
                "mm": kd["mm"],
                "w_px": kd["w_px"],
                "h_px": kd["h_px"],
                "row": kd["row"],
            }

        data["num_keys"] = len(data["detected_keys"])

        with open(DATA_PATH, "w") as f:
            json.dump(data, f, indent=2)

        # Save annotated image
        vis = self.cv_img.copy()
        for name, kd in self.all_key_pixels.items():
            if name == "__touchpad__":
                px, py = kd["pixel"]
                hw, hh = kd["w_px"]//2, kd["h_px"]//2
                cv2.rectangle(vis, (px-hw, py-hh), (px+hw, py+hh), (255, 0, 255), 2)
                continue
            px, py = kd["pixel"]
            hw, hh = kd["w_px"]//2, kd["h_px"]//2
            cv2.rectangle(vis, (px-hw, py-hh), (px+hw, py+hh), (0, 255, 0), 1)
            cv2.putText(vis, name, (px-hw+2, py+hh-3), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1)
        cv2.imwrite("temp/keys_xml_annotated.jpg", vis)

        self.status.set(f"Saved {data['num_keys']} keys + touchpad!")

    def on_save_quit(self):
        self.on_save()
        self.root.quit()


if __name__ == "__main__":
    root = tk.Tk()
    app = AnchorAnnotator(root)
    root.mainloop()
