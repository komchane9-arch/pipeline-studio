param([switch]$ListOnly)

$ErrorActionPreference = 'Stop'

function Close-StaleClaudeDialog {
    try {
        Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
public static class ClaudeErrorDialog {
    delegate bool WindowCallback(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback, IntPtr data);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr window, StringBuilder text, int length);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr window, StringBuilder text, int length);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    public static int Close() {
        int closed = 0;
        EnumWindows((window, data) => {
            var title = new StringBuilder(1024);
            var windowClass = new StringBuilder(128);
            GetWindowText(window, title, title.Capacity);
            GetClassName(window, windowClass, windowClass.Capacity);
            if (windowClass.ToString() != "#32770" ||
                !Regex.IsMatch(title.ToString(), @"^C:\\Program Files\\WindowsApps\\Claude_[^\\]+\\app\\Claude\.exe$", RegexOptions.IgnoreCase))
                return true;
            uint owner;
            GetWindowThreadProcessId(window, out owner);
            try {
                if (!Process.GetProcessById((int)owner).ProcessName.Equals("explorer", StringComparison.OrdinalIgnoreCase))
                    return true;
            } catch (ArgumentException) { return true; }
            if (PostMessage(window, 0x0010, IntPtr.Zero, IntPtr.Zero)) closed++;
            return true;
        }, IntPtr.Zero);
        return closed;
    }
}
'@ -ErrorAction Stop
        return [ClaudeErrorDialog]::Close()
    } catch {
        Write-Warning "Could not close the old Claude error dialog: $_"
        return 0
    }
}

# Match the actual Claude program name. Node is included only when its command
# line identifies the Claude Code package; unrelated Node jobs stay untouched.
$targets = @()
foreach ($process in (Get-Process -ErrorAction Stop)) {
    if ($process.ProcessName -in @('Claude', 'claude', 'claude-code')) {
        $targets += $process
        continue
    }
    try {
        $executable = $process.Path
        if ($executable -match '(?i)[\\/]Packages[\\/]Claude_[^\\/]+[\\/]' -or
            $executable -match '(?i)[\\/]Claude[\\/]ChromeNativeHost[\\/]') {
            $targets += $process
        }
    } catch {
        # Windows does not expose every process path to a standard user.
    }
}

$nodeInspectionFailed = $false
try {
    $nodeProcesses = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -match '(?i)(@anthropic-ai[\\/]claude-code|claude-code[\\/]cli\.js)' }
    foreach ($nodeProcess in $nodeProcesses) {
        $targets += Get-Process -Id $nodeProcess.ProcessId -ErrorAction SilentlyContinue
    }
} catch {
    $nodeInspectionFailed = $true
    Write-Warning 'Could not inspect Node command lines. Claude Code running through Node may be omitted.'
}

$targets = @($targets | Where-Object { $_ } | Sort-Object Id -Unique)
$claudeService = $null
try {
    $servicePath = (Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\CoworkVMService' -ErrorAction Stop).ImagePath
    if ($servicePath -match '(?i)[\\/]WindowsApps[\\/]Claude_[^\\/]+[\\/]') {
        $claudeService = Get-Service -Name 'CoworkVMService' -ErrorAction Stop
    }
} catch {
    Write-Warning 'Could not inspect the Claude background service.'
}

if ($targets.Count -eq 0 -and ($null -eq $claudeService -or $claudeService.Status -eq 'Stopped')) {
    Write-Host 'No Claude components identified as running right now.'
    if ($nodeInspectionFailed) {
        Write-Warning 'This is not a complete check: Node command lines could not be read.'
    }
    Write-Host 'An existing Windows error dialog can remain open after the process stops.'
    Write-Host 'Opening Claude again can start its background service again.'
    if (-not $ListOnly) {
        $dialogsClosed = Close-StaleClaudeDialog
        if ($dialogsClosed -gt 0) { Write-Host "Requested closing $dialogsClosed old Claude error dialog(s)." }
    }
    exit 0
}

if ($targets.Count -gt 0) {
    Write-Host 'Claude processes found:'
    $targets | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize
}
if ($null -ne $claudeService -and $claudeService.Status -ne 'Stopped') {
    Write-Host "Claude background service: $($claudeService.Name) ($($claudeService.Status))."
}

if ($ListOnly) {
    exit 0
}

$answer = Read-Host 'Close all listed Claude components? Type YES to confirm'
if ($answer -cne 'YES') {
    Write-Host 'Cancelled. Nothing was closed.'
    exit 0
}

$failed = 0
if ($null -ne $claudeService -and $claudeService.Status -ne 'Stopped') {
    try {
        Stop-Service -Name $claudeService.Name -ErrorAction Stop
        $claudeService.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
        Write-Host "Stopped Claude background service $($claudeService.Name)."
    } catch {
        Write-Warning "Could not stop Claude background service: $_"
        $failed++
    }
}

foreach ($process in $targets) {
    try {
        if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
            [void]$process.CloseMainWindow()
        }
    } catch {
        Write-Warning "Could not request a normal close for PID $($process.Id): $_"
    }
}

Start-Sleep -Seconds 3
foreach ($process in $targets) {
    if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        Write-Host "Closed PID $($process.Id)."
        continue
    }
    try {
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
        Write-Host "Stopped PID $($process.Id)."
    } catch {
        Write-Warning "Could not stop PID $($process.Id): $_"
        $failed++
    }
}

if ($failed -gt 0) {
    Write-Warning "$failed process(es) remain. Administrator permission may be required."
    exit 1
}
$dialogsClosed = Close-StaleClaudeDialog
if ($dialogsClosed -gt 0) { Write-Host "Requested closing $dialogsClosed old Claude error dialog(s)." }
Write-Host 'All listed Claude components are closed.'
