# Gambit — LLM Deployment & Operations Skill

## Last Updated: 2026-03-12

Gambit is a .NET 8 REST API server that runs on Surface DUTs, exposing device diagnostics, hardware info, and control via HTTP on **port 22133**. It uses a plugin architecture for extensibility.

**Source Repo:** `https://dev.azure.com/MSFTDEVICES/shared/_git/gambit`

---

## 1. How to Get Gambit

### Core Server
```
Package: Gambit.App
Feed:    Shared (https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json)
Type:    NuGet (self-contained .NET 8 app in content/ subfolder)
```

### Available Plugins (all on Shared NuGet feed)

| Package | Purpose |
|---------|---------|
| `Gambit.Plugin.Audio` | Audio subsystem testing |
| `Gambit.Plugin.Display` | Display testing |
| `Gambit.Plugin.Sensors` | Sensor testing |
| `Gambit.Plugin.ScreenCapture` | Screen capture |
| `Gambit.Plugin.Injection` | Input injection |
| `Gambit.Plugin.PowerStateTransition` | Power state testing |
| `Gambit.Plugin.Digitizer` | Digitizer/touch testing |
| `Gambit.Plugin.Digitizer.Firmware` | Digitizer firmware |
| `Gambit.Plugin.Streams.Raw` | Raw data streaming |

---

## 2. Deploy Gambit to a DUT

Uses **SDB** (see `Skill_SDB.md`) to bootstrap Gambit onto the DUT.

### Full Deployment Script

```powershell
param(
    [Parameter(Mandatory)][string]$DutIp,
    [string[]]$Plugins = @('Gambit.Plugin.Audio','Gambit.Plugin.Display','Gambit.Plugin.Sensors','Gambit.Plugin.ScreenCapture','Gambit.Plugin.Injection'),
    [string]$SdbPath  # Path to Sdb.Console.exe (auto-detected if not specified)
)

$nugetSource = "https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json"
$staging = "C:\Staging\GambitDeploy"
$dutPath = "C:\gambit"

# --- Find SDB ---
if (-not $SdbPath) {
    $SdbPath = @(
        "C:\sdb\Console\Sdb.Console.exe",
        "C:\STARK\Console\Sdb.Console.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $SdbPath) {
        # Install from NuGet
        nuget install Microsoft.Devices.SurfaceDeviceBridge.x64 -Source $nugetSource -OutputDirectory "$env:TEMP\sdb_install" -PreRelease 2>$null
        $SdbPath = Get-ChildItem "$env:TEMP\sdb_install" -Recurse -Filter "Sdb.Console.exe" | Select-Object -First 1 -ExpandProperty FullName
    }
}
Write-Host "SDB: $SdbPath"

# --- Stage Gambit ---
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item $staging -ItemType Directory -Force | Out-Null

# Download Gambit.App
Write-Host "Downloading Gambit.App..."
nuget install Gambit.App -Source $nugetSource -OutputDirectory "$env:TEMP\gambit_dl" -PreRelease 2>$null
$gambitPkg = Get-ChildItem "$env:TEMP\gambit_dl" -Directory -Filter "Gambit.App*" | Sort-Object Name -Descending | Select-Object -First 1
$contentDir = Join-Path $gambitPkg.FullName "content"
Copy-Item "$contentDir\*" -Destination $staging -Recurse
Write-Host "Gambit.App staged from $($gambitPkg.Name)"

# Download and stage plugins
$pluginsDir = Join-Path $staging "Plugins"
New-Item $pluginsDir -ItemType Directory -Force | Out-Null
foreach ($plugin in $Plugins) {
    Write-Host "Downloading $plugin..."
    nuget install $plugin -Source $nugetSource -OutputDirectory "$env:TEMP\gambit_plugins" -PreRelease 2>$null
    $pkgDir = Get-ChildItem "$env:TEMP\gambit_plugins" -Directory -Filter "$plugin*" | Sort-Object Name -Descending | Select-Object -First 1
    if ($pkgDir) {
        $targetDir = Join-Path $pluginsDir $plugin
        New-Item $targetDir -ItemType Directory -Force | Out-Null
        # Find the lib folder with DLLs
        $libDir = Get-ChildItem $pkgDir.FullName -Recurse -Directory -Filter "net8*" | Select-Object -First 1
        if (-not $libDir) { $libDir = Get-ChildItem $pkgDir.FullName -Recurse -Directory -Filter "lib" | Select-Object -First 1 }
        if ($libDir) {
            Copy-Item "$($libDir.FullName)\*" -Destination $targetDir -Recurse -Force
        } else {
            # Copy any DLLs found
            Get-ChildItem $pkgDir.FullName -Recurse -Filter "*.dll" | Copy-Item -Destination $targetDir -Force
        }
        Write-Host "  Staged $plugin"
    }
}

# --- Deploy to DUT via SDB ---
Write-Host "`nDeploying to DUT $DutIp..."

# Clear existing Gambit on DUT
& $SdbPath Dut $DutIp File RunOnDut "cmd.exe" "/c if exist $dutPath rmdir /s /q $dutPath" $false 30 2>$null
& $SdbPath Dut $DutIp File RunOnDut "cmd.exe" "/c mkdir $dutPath" $false 10 2>$null

# Push Gambit files
Write-Host "Pushing files to DUT..."
& $SdbPath Dut $DutIp File SendDirectory $staging $dutPath 300
Write-Host "Files pushed to $dutPath on DUT"

# Add firewall rule and start Gambit
Write-Host "Starting Gambit on DUT..."
& $SdbPath Dut $DutIp File RunOnDut "cmd.exe" "/c netsh advfirewall firewall add rule name=Gambit dir=in action=allow program=$dutPath\Gambit.exe protocol=tcp 2>nul" $false 15 2>$null
& $SdbPath Dut $DutIp File RunOnDut "$dutPath\Gambit.exe" '""' $true 5 2>$null

Write-Host "`nGambit deployed and starting on http://${DutIp}:22133"
Write-Host "Swagger UI: http://${DutIp}:22133/swagger"

# Clean up staging
Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\gambit_dl","$env:TEMP\gambit_plugins" -Recurse -Force -ErrorAction SilentlyContinue
```

### Quick Deploy (one-liner)
```powershell
# Minimal deploy — just Gambit core, no plugins
nuget install Gambit.App -Source "https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json" -OutputDirectory C:\Staging\g -PreRelease
$content = (Get-ChildItem C:\Staging\g -Directory -Filter "Gambit.App*" | Select -First 1).FullName + "\content"
C:\sdb\Console\Sdb.Console.exe Dut 192.168.0.59 File RunOnDut "cmd.exe" "/c if exist C:\gambit rmdir /s /q C:\gambit & mkdir C:\gambit" false 30
C:\sdb\Console\Sdb.Console.exe Dut 192.168.0.59 File SendDirectory $content "C:\gambit" 300
C:\sdb\Console\Sdb.Console.exe Dut 192.168.0.59 File RunOnDut "C:\gambit\Gambit.exe" '""' true 5
```

---

## 3. Architecture

```
Gambit.exe (self-contained .NET 8, runs as Administrator)
    │
    ├── Kestrel HTTP server on 0.0.0.0:22133
    ├── Auto-adds Windows Firewall rule
    ├── Swagger UI at /swagger (dev mode, always on)
    │
    ├── Built-in Endpoints:
    │   ├── GET  /battery/status       — Battery state
    │   ├── GET  /battery/percent      — Battery percentage
    │   ├── GET  /environment?name=X   — Read env variable
    │   ├── GET  /files?path=X         — Read file
    │   ├── POST /process/run          — Run command (sync)
    │   ├── POST /process/start        — Start process (async, returns job ID)
    │   ├── POST /process/stream       — Stream process output real-time
    │   ├── GET  /process/kill/id/{id} — Kill process
    │   ├── GET  /information          — Device info, driver versions
    │   ├── GET  /routes               — List all endpoints (plugin discovery)
    │   └── POST /installer            — Install drivers
    │
    └── Plugins/ (auto-discovered, DLL name must contain .Plugin.)
        ├── Gambit.Plugin.Audio/       → Audio endpoints
        ├── Gambit.Plugin.Display/     → Display endpoints
        ├── Gambit.Plugin.Sensors/     → Sensor endpoints
        └── ...
```

---

## 4. Using Gambit APIs

### From PowerShell (once deployed)
```powershell
$base = "http://192.168.0.59:22133"

# Health check — list all available routes
Invoke-RestMethod "$base/routes"

# Battery
Invoke-RestMethod "$base/battery/status"
Invoke-RestMethod "$base/battery/percent"

# Run a command on the DUT
$body = @{ command = "cmd.exe"; args = "/c dir C:\" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/process/run" -Body $body -ContentType "application/json"

# Start process (async — returns immediately)
$body = @{ command = "notepad.exe"; args = "" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/process/start" -Body $body -ContentType "application/json"

# Get environment variable
Invoke-RestMethod "$base/environment?name=COMPUTERNAME"

# Get OS version
Invoke-RestMethod "$base/information"
```

### From curl
```bash
curl http://192.168.0.59:22133/battery/percent
curl http://192.168.0.59:22133/routes
curl -X POST http://192.168.0.59:22133/process/run -H "Content-Type: application/json" -d '{"command":"cmd.exe","args":"/c systeminfo"}'
```

---

## 5. Plugin System

### Plugin Requirements
- .NET 8 class library
- Assembly name **must contain `.Plugin.`** (e.g., `MyCompany.Plugin.MyTool.dll`)
- Implements `IPlugin` interface from `Microsoft.Surface.Gambit.Plugins`
- Uses `ExtensionCore` for dependency injection via `IExtensionInstaller`
- Placed in `Plugins/<AssemblyName>/` subfolder

### Adding a Plugin Post-Deploy
```powershell
# Via SDB — push a plugin DLL to existing Gambit installation
$sdb = "C:\sdb\Console\Sdb.Console.exe"
$ip = "192.168.0.59"

# Create plugin folder on DUT
& $sdb Dut $ip File RunOnDut "cmd.exe" "/c mkdir C:\gambit\Plugins\MyCompany.Plugin.MyTool" false 10

# Push plugin DLL
& $sdb Dut $ip File SendDirectory "C:\local\MyPlugin" "C:\gambit\Plugins\MyCompany.Plugin.MyTool" 60

# Restart Gambit to pick up the new plugin
& $sdb Dut $ip File RunOnDut "cmd.exe" "/c taskkill /f /im Gambit.exe 2>nul & timeout /t 2 & C:\gambit\Gambit.exe" true 10
```

---

## 6. Key Details

| Item | Value |
|------|-------|
| **Default Port** | 22133 |
| **Admin Required** | Yes (enforced via app.manifest) |
| **Swagger URL** | `http://{IP}:22133/swagger` |
| **Self-Contained** | Yes — no .NET runtime needed on DUT |
| **Config** | `appsettings.json` + per-plugin `.config.json` |
| **Firewall** | Auto-adds rule on startup |
| **Plugin Discovery** | `Plugins/` subfolder, `.Plugin.` in DLL name |
| **Request Size Limit** | None (unlimited, for large file uploads) |
| **Version Format** | `2.{YY}.{MMDD}.{HH}00` |
| **Streaming** | Channels with async enumerables or Rx Observables |

---

## 7. Troubleshooting

| Issue | Fix |
|-------|-----|
| **Can't connect** | Check firewall: `netsh advfirewall firewall show rule name=Gambit` |
| **Won't start** | Must run as Administrator. Check if port 22133 is in use: `netstat -an | findstr 22133` |
| **Plugin not loading** | DLL name must contain `.Plugin.` — verify with `/routes` endpoint |
| **Config not applied** | Plugin config must be in same subfolder as the plugin DLL |
| **Gambit already running** | Kill first: `taskkill /f /im Gambit.exe` then restart |
| **SDB RunOnDut returns immediately** | Gambit starts async — use `showUI=true` and short timeout, then verify via HTTP |

---

## 8. Deployment Learnings (March 2026)

### Gambit May Already Be Deployed
The DUT at 192.168.0.59 already had Gambit + all plugins installed. Before deploying, check first:
```powershell
try { Invoke-RestMethod "http://${dutIp}:22133/alive" -TimeoutSec 5; Write-Host "Already running" } catch { Write-Host "Not running" }
```

### Legacy SDB (`C:\sdb\Console\`) Doesn't Support `--task-verbose`
The legacy SDB binary at `C:\sdb\Console\` crashes with `--task-verbose`. Use it without that flag:
```powershell
& C:\sdb\Console\Sdb.Console.exe Dut 192.168.0.59 File RunOnDut "cmd.exe" "/c dir C:\gambit" false 30
```

### NuGet Download May Require ConfigFile
The NuGet feed can time out without the credential provider. Use the Gambit repo's `nuget.config`:
```powershell
nuget install Gambit.App -Source "https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json" -OutputDirectory C:\Staging -PreRelease -NonInteractive -ConfigFile C:\Yoda4\Gambit\nuget.config
```

### Content Subfolder
`Gambit.App` NuGet installs to `Gambit.App.{version}/content/` — the self-contained binary is inside `content/`, not at the package root.

### Verified Plugin Versions (on DUT 192.168.0.59)

| Plugin | Version |
|--------|---------|
| Gambit (core) | 2.26.227.1200 |
| Gambit.Audio.Plugin | 2.25.1121.100 |
| Digitizer.Gambit.Plugin | 1.0.2602.1008 |
| Digitizer.Firmware.Gambit.Plugin | 1.0.2602.1008 |
| Gambit.Plugin.Display | 2.26.227.1200 |
| Imaging.Gambit.Plugin | 0.25.1112.1100 |
| Gambit.Plugin.Injection | 1.25.1112.700 |
| PowerStateTransition.Plugin | 2.25.813.1200 |
| Gambit.Plugin.ScreenCapture | 3.26.207.400 |
| Gambit.Plugin.Sensors | 1.26.112.700 |
| Gambit.Plugin.Streams.Raw | 2.25.1215.800 |
| Uefi.Gambit.Plugin | 0.25.1113.500 |

### Full Endpoint Count by Category (183 total)

| Category | Endpoints | Highlights |
|----------|-----------|------------|
| `/digitizer` | 43 | Firmware, touch sim, pen pressure, GPIO, heat streams |
| `/display` | 28 | HDR, EDID, refresh, resolution, brightness, test patterns |
| `/sensors` | 23 | Hall effect, light, temp, fan, accelerometer, lid |
| `/injection` | 13 | Mouse move/click, keyboard type/press/release |
| `/Process` | 11 | Run/start/kill/stream, job results |
| `/uefi` | 9 | Runtime mode, signing, policy blob, events, logs |
| `/streams` | 9 | Cursor, keyboard, mouse, pen, PTP, touch, USB raw |
| `/audio` | 8 | Volume, play file/tone/noise, stop, pause |
| `/power` | 6 | State, button, lid, sleep/wake events |
| `/screen` | 5 | Capture screenshot, stream, record start/stop |
| `/file` | 4 | Upload/download files and directories |
| `/environment` | 3 | Get/set/delete env vars |
| `/version` | 3 | Gambit version, drivers, firmware |
| `/imaging` | 3 | Direct/file image processing |
| `/battery` | 2 | Status, percentage |
| `/installer` | 3 | Driver install, startup, restart |
| Other | 4 | /alive, /routes, /info, /logs |
