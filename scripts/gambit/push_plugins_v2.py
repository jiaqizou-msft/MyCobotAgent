"""Push plugin DLLs to DUT via Gambit file upload API (fixed params)."""
import httpx
import os
import time
import zipfile
import tempfile

BASE = "http://192.168.0.4:22133"

LOCAL_PLUGINS = {
    "Gambit.Plugin.Injection": r"C:\Staging\gambit_plugins\Gambit.Plugin.Injection.1.25.1112.700\content\Plugins\Gambit.Plugin.Injection",
    "Gambit.Plugin.ScreenCapture": r"C:\Staging\gambit_plugins\Gambit.Plugin.ScreenCapture.3.26.207.400\content\Plugins\Gambit.Plugin.ScreenCapture",
    "Gambit.Plugin.Streams.Raw": r"C:\Staging\gambit_plugins\Gambit.Plugin.Streams.Raw.2.25.1215.800\content\Plugins\Gambit.Plugin.Streams.Raw",
}

DUT_PLUGIN_BASE = r"C:\gambit\Plugins"


def run(args, timeout=30):
    r = httpx.post(f"{BASE}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", ""), r.json().get("ExitCode", -1)


for plugin_name, local_path in LOCAL_PLUGINS.items():
    print(f"\n{'='*50}")
    print(f"Uploading {plugin_name}...")

    remote_dir = f"{DUT_PLUGIN_BASE}\\{plugin_name}"

    # Clean existing dir on DUT
    run(f'/c if exist "{remote_dir}" rmdir /s /q "{remote_dir}"')
    time.sleep(0.5)

    # Create zip
    zip_path = os.path.join(tempfile.gettempdir(), f"{plugin_name}.zip")
    file_count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(local_path):
            for f in files:
                filepath = os.path.join(root, f)
                arcname = os.path.relpath(filepath, local_path)
                zf.write(filepath, arcname)
                file_count += 1
    zip_size = os.path.getsize(zip_path)
    print(f"  Zip: {file_count} files, {zip_size/1024:.0f} KB")

    # Upload via uploaddirectory with correct params
    with open(zip_path, "rb") as f:
        r = httpx.post(
            f"{BASE}/file/uploaddirectory",
            params={"destinationFolder": remote_dir},
            files={"zipFile": (f"{plugin_name}.zip", f, "application/zip")},
            timeout=120,
        )
    os.remove(zip_path)
    print(f"  Upload: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.text[:300]}")

    # Verify
    out, _ = run(f'/c dir "{remote_dir}" /b *.dll 2>nul')
    dll_count = len([x for x in out.strip().split("\n") if x.strip()]) if out.strip() else 0
    print(f"  Verified: {dll_count} DLLs on DUT")

# Restart Gambit
print(f"\n{'='*50}")
print("Restarting Gambit to load plugins...")
try:
    httpx.get(f"{BASE}/installer/restart", timeout=5)
except:
    pass

print("Waiting for Gambit...")
for i in range(25):
    time.sleep(3)
    try:
        r = httpx.get(f"{BASE}/alive", timeout=3)
        if r.status_code == 200:
            print(f"  Gambit is back! (attempt {i+1})")
            break
    except:
        print(f"  waiting... ({i+1})")

time.sleep(3)
r = httpx.get(f"{BASE}/Routes", timeout=10)
routes = r.json()
print(f"\nTotal routes: {len(routes)}")

# Show all routes
from collections import defaultdict
groups = defaultdict(list)
for rt in routes:
    path = rt.get("Route", "")
    method = rt.get("Method", "ANY")
    prefix = "/" + path.strip("/").split("/")[0] if path.strip("/") else "/"
    groups[prefix].append(f"{method:7s} {path}")

for prefix in sorted(groups):
    if len(groups[prefix]) > 0:
        print(f"\n  {prefix} ({len(groups[prefix])})")
        for ep in groups[prefix]:
            print(f"    {ep}")
