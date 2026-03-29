"""Debug: check Notepad state on DUT and test read."""
import httpx

BASE = "http://192.168.0.4:22133"

def run(args, timeout=20):
    r = httpx.post(f"{BASE}/Process/run", json={"Binary": "cmd.exe", "Args": args}, timeout=timeout)
    return r.json().get("Output", "").strip()

# Check Notepad process
print("Notepad process:")
print(run('/c tasklist /fi "imagename eq notepad.exe" 2>nul')[:200])

# Get foreground window title
print("\nForeground window:")
print(run('/c powershell -NoProfile -Command "Add-Type -Name W -Namespace U -MemberDefinition \'[DllImport(\\\"user32.dll\\\")]public static extern IntPtr GetForegroundWindow();[DllImport(\\\"user32.dll\\\")]public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);\'; $h=[U.W]::GetForegroundWindow(); $s=New-Object System.Text.StringBuilder 256; [U.W]::GetWindowText($h,$s,256)|Out-Null; $s.ToString()"'))

# Test the full read sequence with proper delays
print("\nFull read test:")
text = run(
    '/c powershell -NoProfile -Command "'
    'Add-Type -AssemblyName System.Windows.Forms; '
    'Add-Type -AssemblyName Microsoft.VisualBasic; '
    '$p = Get-Process notepad -EA SilentlyContinue | Select -First 1; '
    'if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) }; '
    'Start-Sleep -Milliseconds 500; '
    '[System.Windows.Forms.SendKeys]::SendWait(\'^a\'); '
    'Start-Sleep -Milliseconds 500; '
    '[System.Windows.Forms.SendKeys]::SendWait(\'^c\'); '
    'Start-Sleep -Milliseconds 500; '
    'Get-Clipboard"',
    timeout=20
)
print(f"Read: [{text[:80]}] (len={len(text)})")
