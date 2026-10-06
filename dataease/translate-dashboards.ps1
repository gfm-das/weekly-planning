<#
Makes the Dashboards copies in the portal's 13 other languages (dataease/translate-dashboards.mjs), in a short-lived
node:24-alpine container on DataEase's private network, with the values from dataease/.env. Nothing secret is printed
or put on a command line. Run it from the repository root (Windows PowerShell 5.1 or PowerShell 7):

  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/translate-dashboards.ps1            # make or update all
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/translate-dashboards.ps1 -Check     # only look
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/translate-dashboards.ps1 -Only de,ar
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/translate-dashboards.ps1 -Remove    # rollback: no copies

When to run it: after the first seeding (seed-dashboards.ps1), and every time someone changed an English dashboard
in DataEase (the copies are made again from the English ones; changes made to a copy itself are replaced).
It ends with "All copies are made and published." Words it lists as "no translation yet" stay English in the copies:
add them to the "gfm" part of dataease/i18n/<lang>.json (see dataease/i18n/README.md) and run it again.
-Project and -EnvFile are for a second, throw-away DataEase (tests).
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Remove,
    [string[]]$Only,
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

$arguments = @()
if ($Check) { $arguments += '--check' }
if ($Remove) { $arguments += '--remove' }
if ($Only) { $arguments += @('--only', (($Only -join ',') -replace '\s', '')) }

$docker = @('run', '--rm', '--name', "$Project-translate", '--memory', '256m', '--network', $network, '--env-file', $EnvFile,
    '-e', 'DE_BASE=http://dataease:8100', '-v', "${here}:/repo/dataease:ro", '-w', '/repo',
    'node:24-alpine', 'node', 'dataease/translate-dashboards.mjs') + $arguments
$ErrorActionPreference = 'Continue'
& docker @docker
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) { throw "translate-dashboards.mjs reported a problem (exit code $code); see the lines above." }
