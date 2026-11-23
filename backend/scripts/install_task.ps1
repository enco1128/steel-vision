# Register SteelVision as a Windows scheduled task (start at boot, auto-restart on crash).
# Usage (PowerShell, admin recommended for system-level registration):
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -AlsoWatchdog
# Uninstall:
#   Unregister-ScheduledTask -TaskName "SteelVisionBackend" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "SteelVisionWatchdog" -Confirm:$false
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less .ps1
# files using the system ANSI codepage; non-ASCII text breaks parsing.
param(
  [string]$Python = "",
  [int]$Port = 8000,
  [switch]$AlsoWatchdog
)

$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
  $cand = Get-Command py -ErrorAction SilentlyContinue
  if ($cand) { $Python = "py -3.12" } else {
    $Python = (Get-Command python -ErrorAction Stop).Source
  }
}

$uvicorn = "$Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port"
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
  -Argument "/c cd /d `"$backend`" && $uvicorn" `
  -WorkingDirectory $backend
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

# Try system-level (AtStartup) first; fall back to per-user AtLogOn when not admin.
function Register-SvTask([string]$name, $taskAction, [string]$desc) {
  try {
    $t = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName $name -Action $taskAction `
      -Trigger $t -Settings $settings -Force -Description $desc | Out-Null
    Write-Host "[OK] $name registered (AtStartup, system-level)"
    return
  } catch [Microsoft.Management.Infrastructure.CimException] {
    if ($_.Exception.HResult -ne -2147024891) { throw }  # only fall back on ACCESS_DENIED
  }
  $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  Register-ScheduledTask -TaskName $name -Action $taskAction `
    -Trigger $t -Settings $settings -Force -Description $desc | Out-Null
  Write-Host "[OK] $name registered (AtLogOn for $env:USERNAME, no admin required)"
}

Register-SvTask "SteelVisionBackend" $action `
  "SteelVision backend: start at boot/logon, restart on crash"

if ($AlsoWatchdog) {
  $wd = "$Python scripts\watchdog.py --port $Port --no-start"
  $wdAction = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c cd /d `"$backend`" && $wd" -WorkingDirectory $backend
  Register-SvTask "SteelVisionWatchdog" $wdAction `
    "SteelVision health watchdog (probe /api/health every 10s)"
}

Write-Host ""
Write-Host "Start manually now: Start-ScheduledTask -TaskName SteelVisionBackend"
Write-Host "Check health      : Invoke-RestMethod http://127.0.0.1:$Port/api/health"
