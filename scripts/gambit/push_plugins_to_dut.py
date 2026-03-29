"""Push locally-downloaded plugin DLLs to the DUT via Gambit's file upload API."""
import httpx
import os
import time

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


def upload_file(local_path, remote_path, timeout=30):
    """Upload a file to the DUT via Gambit file upload API."""
    with open(local_path, "rb") as f:
        files = {"file": (os.path.basename(local_path), f)}
        r = httpx.post(
            f"{BASE}/file/upload",
            params={"destination": remote_path},
            files=files,
            timeout=timeout,
        )
    return r.status_code


def upload_directory(local_dir, remote_dir, timeout=60):
    """Upload a directory to the DUT via Gambit file uploaddirectory API."""
    # Create a zip of the directory and upload? Or use uploaddirectory
    # Let's try uploaddirectory first
    import zipfile
    import tempfile
    
    zip_path = os.path.join(tempfile.gettempdir(), "plugin_upload.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, local_dir)
                zf.write(filepath, arcname)
    
    with open(zip_path, "rb") as f:
        files = {"file": (os.path.basename(zip_path), f)}
        r = httpx.post(
            f"{BASE}/file/uploaddirectory",
            params={"destination": remote_dir},
            files=files,
            timeout=timeout,
        )
    os.remove(zip_path)
    return r.status_code, r.text[:300]


for plugin_name, local_path in LOCAL_PLUGINS.items():
    print(f"\n{'='*50}")
    print(f"Uploading {plugin_name}...")
    
    remote_dir = f"{DUT_PLUGIN_BASE}\\{plugin_name}"
    
    # Clean existing empty dir on DUT
    run(f'/c if exist "{remote_dir}" rmdir /s /q "{remote_dir}"')
    run(f'/c mkdir "{remote_dir}"')
    
    # Count local files
    local_files = []
    for root, dirs, files in os.walk(local_path):
        for f in files:
            local_files.append(os.path.join(root, f))
    print(f"  Local files: {len(local_files)}")
    
    # Try directory upload first
    status, text = upload_directory(local_path, remote_dir)
    print(f"  Upload directory response: {status}")
    if status != 200:
        print(f"  Response: {text}")
        # Fall back to individual file uploads
        print("  Falling back to individual file uploads...")
        for local_file in local_files:
            rel = os.path.relpath(local_file, local_path)
            remote_file = remote_dir + "\\" + rel
            # Create subdirs on DUT
            remote_subdir = "\\".join(remote_file.split("\\")[:-1])
            run(f'/c if not exist "{remote_subdir}" mkdir "{remote_subdir}"')
            status = upload_file(local_file, remote_file)
            fname = os.path.basename(local_file)
            if status == 200:
                pass  # print(f"    {fname}: OK")
            else:
                print(f"    {fname}: FAILED ({status})")
        print(f"  Individual uploads done")
    
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
for i in range(20):
    time.sleep(3)
    try:
        r = httpx.get(f"{BASE}/alive", timeout=3)
        if r.status_code == 200:
            print(f"  Gambit is back! (attempt {i+1})")
            break
    except:
        print(f"  waiting... ({i+1})")

time.sleep(2)
r = httpx.get(f"{BASE}/Routes", timeout=10)
routes = r.json()
print(f"\nTotal routes: {len(routes)}")

# Show interesting routes
for rt in routes:
    path = rt.get("Route", "")
    method = rt.get("Method", "ANY")
    lower = path.lower()
    if any(w in lower for w in ["inject", "screen", "stream", "keyboard", "mouse", "capture", "key"]):
        print(f"  {method:7s} {path}")
