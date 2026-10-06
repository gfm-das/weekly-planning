<#
  Creates (or replaces) the scheduled task "GFM Updater", which keeps the updater watching for requests from
  DA Management > Updates.

  Run it once, in a normal (not administrator) PowerShell window of the Windows account that runs Docker Desktop:
      powershell -NoProfile -ExecutionPolicy Bypass -File /path/to/weekly-planning\updater\register-task.ps1

  What the task does:
    - it starts the updater (gfm-updater.ps1 -Mode Watch, hidden window) when this account signs in;
    - every 5 minutes it makes sure the updater is running (it never starts a second one). So after an update of
      the updater itself, or if it ever stops, it is back within 5 minutes;
    - it runs only while this account is signed in: Docker Desktop and the GitHub sign-in (Git Credential
      Manager) work only then.

  Stop it for a while:  Disable-ScheduledTask -TaskName 'GFM Updater'   (Enable-ScheduledTask to start again)
  Remove it:            Unregister-ScheduledTask -TaskName 'GFM Updater' -Confirm:$false
#>
[CmdletBinding()]
param([string]$TaskName = 'GFM Updater')

$ErrorActionPreference = 'Stop'
$updater = Join-Path $PSScriptRoot 'gfm-updater.ps1'
# Windows PowerShell is on every Windows computer; the updater works with it and with PowerShell 7.
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$updater`" -Mode Watch"
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $PSScriptRoot
$atSignIn = New-ScheduledTaskTrigger -AtLogOn -User $user
$everyFiveMinutes = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
# IgnoreNew: never a second updater. No time limit: the watcher runs until sign-out.
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atSignIn, $everyFiveMinutes) -Principal $principal `
    -Settings $settings -Force `
    -Description 'Answers DA Management > Updates and checks GitHub for updates (docs/handoff/round7/updater.md).' | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "The task '$TaskName' is created and started. The updater's log: $(Join-Path $PSScriptRoot 'logs')"
