# Run in the interactive Windows session. Ctrl+C closes admission.
# Requires a dedicated WSL worker installed with the Linux node installer.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9._-]+$')][string]$Distribution,
    [ValidateRange(30,86400)][int]$IdleSeconds=300,
    [string[]]$GameProcesses=@(),
    [ValidateSet('Auto','Available','Gaming','Disabled')][string]$Mode='Auto'
)
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class SolomonIdle {
 [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
 [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO data);
 public static double Seconds() {
  var data = new LASTINPUTINFO(); data.cbSize=(uint)Marshal.SizeOf(data);
  if(!GetLastInputInfo(ref data)) return 0;
  return unchecked((uint)Environment.TickCount-data.dwTime)/1000.0;
 }
}
'@
function Set-WorkerMode([string]$State) {
    & wsl.exe -d $Distribution -u root -- /apps/solomonprime/app/scripts/worker-mode.sh $State
    if ($LASTEXITCODE -ne 0) { throw "Worker gate update failed ($LASTEXITCODE)" }
}
try {
    while ($true) {
        $state=$Mode.ToLowerInvariant()
        if ($Mode -eq 'Auto') {
            $gameRunning=@(Get-Process | Where-Object { $GameProcesses -contains $_.ProcessName }).Count -gt 0
            $state=if ($gameRunning -or [SolomonIdle]::Seconds() -lt $IdleSeconds) {'gaming'} else {'available'}
        }
        Set-WorkerMode $state
        Start-Sleep -Seconds 5
    }
} finally { Set-WorkerMode 'disabled' }
