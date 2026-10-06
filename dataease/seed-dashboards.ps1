<#
Sets up DataEase for the portal's Dashboards and checks it: runs dataease/seed-dashboards.mjs (or, with -ReaderCheck,
dataease/tests/reader-check.mjs) in a short-lived node:24-alpine container on DataEase's private network, with the
values from dataease/.env. Nothing secret is printed or put on a command line.

Run from the repository root (Windows PowerShell 5.1 or PowerShell 7), after DataEase has started (about a minute):
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1               # first start, updates
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1 -Check        # only read and check
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1 -Reset        # rebuild the three
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1 -Export       # save them as they are
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1 -ReaderCheck  # what the data source may read

-Reset replaces changes made in DataEase to the three dashboards (back up first: dataease/backup-dataease.ps1).
-Export writes dataease/dashboards/export/*.dataease.json (DataEase's own form of the dashboards, to keep in git).
-Project and -EnvFile are for a second, throw-away DataEase (tests).
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Reset,
    [switch]$Export,
    [switch]$ReaderCheck,
    [string]$Project = 'gfm-dataease',
    [string]$EnvFile
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
if (-not $EnvFile) { $EnvFile = Join-Path $here '.env' }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "$EnvFile is missing. Run dataease/init-env.ps1 first." }

$network = "$Project-internal"
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& docker network inspect $network --format '{{.Name}}' 2>$null | Out-Null
$exists = $LASTEXITCODE -eq 0
$ErrorActionPreference = $previous
if (-not $exists) { throw "Docker network $network is missing: start DataEase first (docker compose -p $Project -f dataease/compose.yml up -d)." }

$script = if ($ReaderCheck) { 'dataease/tests/reader-check.mjs' } else { 'dataease/seed-dashboards.mjs' }
$arguments = @()
if ($Check) { $arguments += '--check' }
if ($Reset) { $arguments += '--reset' }
if ($Export) { $arguments += '--export' }
$mount = if ($Export) { "${here}:/repo/dataease" } else { "${here}:/repo/dataease:ro" }

$docker = @('run', '--rm', '--name', "$Project-seed", '--memory', '256m', '--network', $network, '--env-file', $EnvFile,
    '-e', 'DE_BASE=http://dataease:8100', '-e', 'GFM_DATAEASE_DB_HOST=dbproxy', '-v', $mount, '-w', '/repo',
    'node:24-alpine', 'node', $script) + $arguments
$ErrorActionPreference = 'Continue'
& docker @docker
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) { throw "$script reported a problem (exit code $code); see the lines above." }
