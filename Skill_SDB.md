# SDB (Surface Device Bridge) — LLM Skill

## Last Updated: 2026-03-12

SDB is the transport layer between a host/agent machine and a Surface DUT (Device Under Test). All remote operations — file transfer, command execution, reboots, firmware queries — go through SDB.

---

## 1. How to Get SDB

### NuGet Package
```
Package: Microsoft.Devices.SurfaceDeviceBridge.x64  (or .arm64 for ARM hosts)
Feed:    https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json
Version: 1.81.137+ (latest)
```

### Install Methods

**From NuGet CLI:**
```powershell
nuget install Microsoft.Devices.SurfaceDeviceBridge.x64 -Source "https://pkgs.dev.azure.com/MSFTDEVICES/_packaging/Shared/nuget/v3/index.json" -OutputDirectory C:\SDB -PreRelease
# Binary at: C:\SDB\Microsoft.Devices.SurfaceDeviceBridge.x64.1.xxx\contentFiles\any\any\x64\Sdb\Sdb.Console.exe
```

**From CTEF manifest:**
```json
{ "InstallPackage": [{"type":"nuget"},{"feed":"Shared"},{"name":"Microsoft.Devices.SurfaceDeviceBridge.x64"},{"version":"*"},{"destination":"${TSRootPath}\\SDB"}] }
```

**Known locations on agents:**
- `C:\sdb\Console\Sdb.Console.exe` (legacy)
- `C:\STARK\Console\Sdb.Console.exe` (legacy)
- `C:\agent3\_work\1\s\Microsoft.Devices.SurfaceDeviceBridge.x64\contentFiles\any\any\x64\Sdb\Sdb.Console.exe` (pipeline)

---

## 2. Command Reference

All commands follow: `Sdb.Console.exe <target> <IP> <category> <command> <args...>`

### File Operations (most common)

| Command | Signature | Purpose |
|---------|-----------|---------|
| **RunOnDut** | `Dut <IP> File RunOnDut <exePath> <args> <showUI:bool> <timeoutSec> [exeTimeoutMs]` | Execute a binary on the DUT. Blocks until exit. |
| **RunPs1OnDut** | `Dut <IP> File RunPs1OnDut <ps1Path> <args> <showUI:bool> <timeoutSec> [ps1TimeoutMs]` | Execute a PowerShell script on the DUT. |
| **SendDirectory** | `Dut <IP> File SendDirectory <localDir> <remoteDir> <timeoutSec>` | Push a folder from host to DUT. |
| **SendFile** | `Dut <IP> File SendFile <destPath> <data> <timeoutSec>` | Push a single file to DUT. |
| **GetRemoteFile** | `Dut <IP> File GetRemoteFile <remotePath> <localDir> <timeoutSec>` | Pull a file from DUT to host. |

### Power & State

| Command | Signature | Purpose |
|---------|-----------|---------|
| **Reboot** | `Dut <IP> Reboot <timeoutSec>` | Reboot the DUT. |
| **Shutdown** | `Dut <IP> Shutdown <timeoutSec>` | Shut down the DUT. |
| **Hibernate** | `Dut <IP> Hibernate <timeoutSec>` | Hibernate the DUT. |
| **GetState** | `Dut <IP> GetState <timeoutSec>` | Returns `On` or `Off`. |
| **EnsureState** | `Dut <IP> EnsureState <isOnline:bool> <timeoutSec>` | Poll until DUT reaches expected state. |

### Software/Firmware Info

| Command | Signature | Purpose |
|---------|-----------|---------|
| **GetOsImageVersion** | `Dut <IP> Software GetOsImageVersion <timeoutSec>` | OS build version. |
| **GetUefiVersion** | `Dut <IP> Software GetUefiVersion <timeoutSec>` | UEFI firmware version. |
| **GetSamVersion** | `Dut <IP> Software GetSamVersion <timeoutSec>` | SAM controller version. |

### Date/Time

| Command | Signature | Purpose |
|---------|-----------|---------|
| **GetDateTimeUtc** | `Dut <IP> GetDateTimeUtc <timeoutSec>` | Get DUT's UTC time. |
| **SetDateTimeUtc** | `Dut <IP> SetDateTimeUtc <datetime> <timeoutSec>` | Set DUT's UTC time. |

### Host Commands (run on agent machine)

| Command | Signature | Purpose |
|---------|-----------|---------|
| **DetectDut** | `Host DetectDut <IP> <timeoutSec>` | Detect if DUT is reachable. |
| **HIDController** | `Host HIDController <subcommand>` | Mouse/keyboard simulation via Arduino. |
| **MachineVision** | `Host MachineVision Ocr <cameraIndex> <timeoutSec>` | OCR from camera feed. |

> **Note:** All `Dut` commands also work as `Arm64Dut` for ARM64 Surface devices.

---

## 3. Common Patterns

### Health check
```powershell
$sdb = "C:\sdb\Console\Sdb.Console.exe"
& $sdb Dut 192.168.0.59 GetState 60
# Returns: Success||...||True (online) or times out
```

### Push files + run test + pull results
```powershell
$sdb = "C:\sdb\Console\Sdb.Console.exe"
$ip = "192.168.0.59"

# Push test files
& $sdb Dut $ip File SendDirectory "C:\MyTests" "C:\TestOnDut" 300

# Run test
& $sdb Dut $ip File RunOnDut "C:\TestOnDut\test.exe" '""' $false 600

# Pull results
& $sdb Dut $ip File GetRemoteFile "C:\TestOnDut\results.xml" "C:\LocalResults" 120
```

### Reboot and wait for DUT to come back
```powershell
& $sdb Dut $ip Reboot 60
& $sdb Dut $ip EnsureState $true 600  # Wait up to 10 min for DUT to come back online
```

### Run PowerShell on DUT (safe pattern)
```powershell
# Use cmd.exe wrapper with 2>nul to suppress stderr (CRITICAL for SDB)
& $sdb Dut $ip File RunOnDut "cmd.exe" "/c `"C:\Program Files\PowerShell\7\pwsh.exe`" -ExecutionPolicy Bypass -File C:\TestOnDut\script.ps1 2>nul" $true 300
```

---

## 4. SDB Output Format

SDB returns results in this format:
```
Success||<logPath>||<stdout>
NonZeroExitCode||<logPath>||<stdout>
ErrorOutput||<logPath>||<stdout>
Fail||<logPath>||<errorMessage>
```

- **Success** — command completed, exit code 0, no stderr
- **NonZeroExitCode** — command completed but exit code != 0 OR stderr was detected
- **ErrorOutput** — command produced stderr (even if exit code was 0)
- **Fail** — SDB-level failure (timeout, connection lost, etc.)

---

## 5. Critical Gotchas

1. **stderr = failure**: ANY stderr output causes SDB to report `NonZeroExitCode` even with exit code 0. Always suppress: `2>nul` (cmd.exe) or `Start-Process -RedirectStandardError` (PowerShell wrapper).

2. **Empty args**: Pass `""` (literal double-quotes). In PowerShell use `'""'` because PS may consume empty strings.

3. **Synchronous blocking**: `RunOnDut` blocks until the process exits. If DUT reboots mid-execution, SDB returns `Fail`. For reboot tests, use scheduled task + polling pattern.

4. **pwsh wrapping in CTEF**: Ruacana's `ExecuteOnDut` wraps through `pwsh.exe -command "..."`. This means `&&` operators don't work, `.cmd` files aren't recognized, and `$()` expressions get parsed as CTEF variables.

5. **One session at a time**: Only one SDB connection to a DUT at a time. Pipeline holds the session — can't SDB from workstation simultaneously.

6. **Write-Host -ForegroundColor**: ANSI escape codes route through stderr in the pwsh→SDB chain, causing failure. Don't use color parameters in SDB-wrapped scripts.

7. **Connection via IP only**: SDB connects by IP address, not hostname. Use `dutIp` parameter or agent capabilities for `DUTIP`.

---

## 6. SDB in CTEF Manifests

CTEF provides these commands that use SDB under the hood:

| CTEF Command | SDB Equivalent | Notes |
|-------------|----------------|-------|
| `ExecuteOnDut` | `RunOnDut` via pwsh | Inline PowerShell wrapped through `pwsh -command` |
| `ExecuteTestOnDut` | `RunOnDut` via cmd.exe | Test case Path + Args executed directly |
| `PushFiles` | `SendDirectory` | source → destination |
| `GetFiles` | `GetRemoteFile` | source → destination |
| `RebootDut` | `Reboot` + `EnsureState` | Reboots then waits for DUT to return |
| `EnsureDutState` | `EnsureState` | Polls until DUT online/offline |
| `CheckAndPrepareDut` | `EnsureState` + health check | Verifies DUT is ready |
