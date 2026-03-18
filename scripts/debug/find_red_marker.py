"""Find the red marker using VLM and move the finger to point at it."""
from pymycobot import MyCobot280Socket
import httpx
import cv2
import numpy as np
import time
import base64
import json
import os
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# --- Connect to robot ---
print("Connecting to robot...")
mc = MyCobot280Socket('10.105.230.93', 9000)
time.sleep(1)

# --- Move to top-view position ---
print("Moving to top-view position...")
mc.send_angles([-62.13, 8.96, -87.71, -14.41, 2.54, -16.34], 15)
time.sleep(5)

# --- Capture overhead image ---
print("Capturing overhead image...")
resp = httpx.get("http://10.105.230.93:8080/snapshot", timeout=5.0)
img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
cv2.imwrite("temp/vl_now.jpg", img)
print(f"Image captured: {img.shape}")

# --- Send to GPT-4o to find the red marker ---
print("Asking GPT-4o to find the red marker...")

with open("temp/vl_now.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    azure_endpoint="https://bugtotest-resource.cognitiveservices.azure.com",
    azure_ad_token_provider=token_provider,
    api_version="2025-01-01-preview",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": """Look at this overhead camera image of a robot workspace. Find the red marker in the image.

Return ONLY a JSON object like this:
{
  "object": "red marker",
  "description": "brief description of what you see",
  "center_x": <pixel x coordinate of the center of the red marker, 0=left edge>,
  "center_y": <pixel y coordinate of the center of the red marker, 0=top edge>,
  "image_width": <total image width in pixels>,
  "image_height": <total image height in pixels>
}

Be precise with the pixel coordinates. The image is 640x480."""},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ]
    }],
    max_tokens=300,
)

raw = response.choices[0].message.content.strip()
print(f"GPT-4o response: {raw}")

# Parse JSON
cleaned = raw
if cleaned.startswith("```"):
    lines = cleaned.split("\n")
    lines = [l for l in lines if not l.strip().startswith("```")]
    cleaned = "\n".join(lines)
result = json.loads(cleaned)

cx = result["center_x"]
cy = result["center_y"]
print(f"Red marker at pixel ({cx}, {cy})")

# --- Draw detection on image ---
vis = img.copy()
cv2.circle(vis, (cx, cy), 15, (0, 255, 0), 3)
cv2.putText(vis, "RED MARKER", (cx - 50, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
cv2.imwrite("temp/vl_detected.jpg", vis)
print("Detection visualization saved to temp/vl_detected.jpg")

# --- Eye-to-hand: pixel -> robot coords ---
# Using the default 2-point linear interpolation from config
# This WILL need recalibration, but let's try it
from src.calibration.eye2hand import get_eye2hand
e2h = get_eye2hand()
robot_x, robot_y = e2h.pixel_to_robot(cx, cy)
print(f"Estimated robot coords: X={robot_x:.1f}, Y={robot_y:.1f}")

# --- Move to home first ---
print("\nMoving to home position...")
mc.send_angles([0, 0, 0, 0, 0, 0], 30)
time.sleep(4)

# --- Move above the red marker at safe height ---
print(f"Moving above red marker at ({robot_x:.1f}, {robot_y:.1f}, 230)...")
mc.send_coords([robot_x, robot_y, 230, 0, 180, 90], 20, 0)
time.sleep(4)

# --- Lower towards the marker ---
print(f"Lowering towards red marker...")
mc.send_coords([robot_x, robot_y, 150, 0, 180, 90], 15, 0)
time.sleep(4)

# Read final position
time.sleep(1)
for i in range(5):
    final_angles = mc.get_angles()
    time.sleep(0.3)
    if final_angles and final_angles != -1:
        break
print(f"\nFinal angles: {final_angles}")

for i in range(5):
    final_coords = mc.get_coords()
    time.sleep(0.3)
    if final_coords and final_coords != -1:
        break
print(f"Final coords: {final_coords}")

print("\nDone! The finger should be pointing at the red marker.")
print("NOTE: If it's off, we need to recalibrate the eye-to-hand transform.")
