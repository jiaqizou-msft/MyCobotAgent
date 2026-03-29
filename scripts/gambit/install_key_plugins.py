"""Download and install Gambit plugin DLLs on the DUT via NuGet."""
import httpx
import time

BASE = "http://192.168.0.4:22133"
NUGET_SOURCE = "https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json"
GAMBIT_PATH = "C:\\gambit"
STAGING = "C:\\staging_plugins"

PLUGINS = [
    "Gambit.Plugin.Injection",
    "Gambit.Plugin.ScreenCapture",
    "Gambit.Plugin.Streams.Raw",
]

def run(args, timeout=120):
    r = httpx.post(f"{BASE}/Process/run",
                   json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    data = r.json()
    return data.get("Output", ""), data.get("Error", ""), data.get("ExitCode", -1)

# Step 0: check nuget
print("Checking nuget...")
out, _, _ = run("/c where nuget 2>nul")
if "nuget" not in out.lower():
    print("Downloading nuget.exe...")
    run('/c curl -sLo C:\\nuget.exe https://dist.nuget.org/win-x86-commandline/latest/nuget.exe', timeout=60)
    nuget = "C:\\nuget.exe"
else:
    nuget = out.strip().split("\n")[0].strip()
print(f"Using nuget: {nuget}")

# Step 1: Clean staging
run(f'/c if exist {STAGING} rmdir /s /q {STAGING}')
run(f'/c mkdir {STAGING}')

for plugin in PLUGINS:
    print(f"\n{'='*50}")
    print(f"Installing {plugin}...")
    
    # Download via nuget
    out, err, code = run(
        f'/c "{nuget}" install {plugin} -Source "{NUGET_SOURCE}" '
        f'-OutputDirectory {STAGING} -PreRelease -NonInteractive 2>&1',
        timeout=180
    )
    print(f"  Download exit: {code}")
    if code != 0:
        print(f"  Output: {(out+err)[:300]}")
        continue
    
    # Find the package folder
    out_dir, _, _ = run(f'/c dir {STAGING}\\{plugin}* /b /ad /o-n 2>nul')
    pkg = out_dir.strip().split("\n")[0].strip() if out_dir.strip() else ""
    if not pkg:
        print(f"  Package dir not found!")
        continue
    print(f"  Package: {pkg}")
    
    # Find DLLs in the package
    dll_out, _, _ = run(f'/c dir "{STAGING}\\{pkg}" /s /b *.dll 2>nul')
    if not dll_out.strip():
        print(f"  No DLLs found in package!")
        # Show contents
        contents, _, _ = run(f'/c dir "{STAGING}\\{pkg}" /s /b 2>nul')
        print(f"  Contents: {contents[:500]}")
        continue
    
    dlls = [d.strip() for d in dll_out.strip().split("\n") if d.strip()]
    print(f"  Found {len(dlls)} DLLs")
    
    # Find the net8 lib folder (or any lib folder with DLLs)
    lib_out, _, _ = run(f'/c dir "{STAGING}\\{pkg}" /s /b /ad 2>nul')
    lib_folders = [f.strip() for f in lib_out.strip().split("\n") if f.strip()]
    
    # Look for net8.0 or net8.0-windows folder
    target_folder = None
    for f in lib_folders:
        if "net8" in f.lower():
            target_folder = f
            break
    if not target_folder:
        # Use parent of first DLL
        first_dll = dlls[0]
        target_folder = "\\".join(first_dll.split("\\")[:-1])
    
    print(f"  Source folder: {target_folder}")
    
    # Create plugin dir and copy
    dest = f"{GAMBIT_PATH}\\Plugins\\{plugin}"
    run(f'/c if exist "{dest}" rmdir /s /q "{dest}"')
    run(f'/c mkdir "{dest}"')
    out, _, code = run(f'/c xcopy "{target_folder}\\*" "{dest}\\" /s /e /y 2>nul')
    print(f"  Copy to {dest}: exit={code}")
    
    # Verify
    verify, _, _ = run(f'/c dir "{dest}" /b *.dll 2>nul')
    dll_count = len([x for x in verify.strip().split("\n") if x.strip()]) if verify.strip() else 0
    print(f"  Installed: {dll_count} DLLs")

# Cleanup staging
run(f'/c if exist {STAGING} rmdir /s /q {STAGING}')

# Restart Gambit to load plugins
print(f"\n{'='*50}")
print("Restarting Gambit to load plugins...")
try:
    httpx.get(f"{BASE}/installer/restart", timeout=5)
except:
    pass

# Wait for Gambit to come back
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

# Check routes
r = httpx.get(f"{BASE}/Routes", timeout=10)
routes = r.json()
print(f"\nTotal routes after restart: {len(routes)}")

# Show new plugin routes
for rt in routes:
    path = rt.get("Route", "")
    method = rt.get("Method", "ANY")
    lower = path.lower()
    if any(w in lower for w in ["inject", "screen", "stream", "keyboard", "mouse", "capture"]):
        print(f"  >>> {method:7s} {path}")
