# Writes one password file for the gfm-backup container (nightly-backup\secrets\<Name>, gitignored), taken from an
# .env file. The value is never printed. Run it again after a password change; no restart is needed, because the
# file is read at every backup.
#
#   powershell -ExecutionPolicy Bypass -File nightly-backup\set-db-password.ps1
#       postgres of the Beta stack (supabase\.env, SERVICE_PASSWORD_POSTGRES); the second stack uses the same one
#   powershell -ExecutionPolicy Bypass -File nightly-backup\set-db-password.ps1 -EnvFile <file> -Variable <NAME> -Name dataease-db-password
#       a password for a hook (hooks.d\README.md)
[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot '..\supabase\.env'),
    [string]$Variable = 'SERVICE_PASSWORD_POSTGRES',
    [ValidatePattern('^[a-z0-9-]+$')][string]$Name = 'db-password'
)

$ErrorActionPreference = 'Stop'

$line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match "^\s*$([regex]::Escape($Variable))\s*=" } | Select-Object -Last 1
if (-not $line) { throw "$Variable is not set in $EnvFile." }
$value = ($line -split '=', 2)[1].Trim()
if ($value.Length -ge 2 -and $value[0] -eq $value[$value.Length - 1] -and $value[0] -in @('"', "'")) {
    $value = $value.Substring(1, $value.Length - 2)
}
if (-not $value) { throw "$Variable is empty in $EnvFile." }

$dir = Join-Path $PSScriptRoot 'secrets'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$target = Join-Path $dir $Name
[System.IO.File]::WriteAllText($target, $value, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Wrote $target ($($value.Length) characters, not shown)."
