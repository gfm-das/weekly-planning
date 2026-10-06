<#
Writes dataease/.env with generated values, once, and (with -SyncPortalApi) gives portal-api the same Dashboards
sign-in secret. Nothing secret is printed.

- DE_MYSQL_ROOT_PASSWORD, DE_MYSQL_PASSWORD: 32 letters and digits (DataEase's own MySQL).
- DE_ADMIN_PASSWORD: 20 characters with a-z, A-Z, 0-9 and one of @-_.+ (DataEase's password rule). Used only by the
  gate container and seed-dashboards.ps1; people never type it.
- GFM_DATAEASE_PROXY_SECRET: 48 letters and digits. Signs the portal's Dashboards cookie; portal-api/.env must hold
  the same value as DATAEASE_PROXY_SECRET (-SyncPortalApi writes it there).
- GFM_DASHBOARD_READER_PASSWORD: generated, and then set on the database with dataease/set-reader-password.ps1.

Run from the repository root (Windows PowerShell 5.1 or PowerShell 7):
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/init-env.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/init-env.ps1 -SyncPortalApi
The first form refuses to overwrite an existing dataease/.env. The second (with an existing dataease/.env) only adds
DATAEASE_PROXY_SECRET to portal-api/.env, or checks that the value there is the same; it never prints either value.
#>
[CmdletBinding()]
param(
    [string]$Target,
    [switch]$SyncPortalApi,
    [string]$PortalApiEnv
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Target) { $Target = Join-Path $PSScriptRoot '.env' }
if (-not $PortalApiEnv) { $PortalApiEnv = Join-Path $repo 'portal-api\.env' }
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-EnvValue([string]$File, [string]$Name) {
    if (-not (Test-Path -LiteralPath $File)) { return $null }
    $line = Get-Content -LiteralPath $File | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if (-not $line) { return $null }
    $value = ($line -replace "^$Name=", '').Trim().Trim('"').Trim("'")
    if (-not $value -or $value -match 'REPLACE') { return $null }
    return $value
}

if ($SyncPortalApi) {
    $secret = Read-EnvValue $Target 'GFM_DATAEASE_PROXY_SECRET'
    if (-not $secret) { throw "GFM_DATAEASE_PROXY_SECRET is missing in $Target. Run this script without -SyncPortalApi first." }
    if (-not (Test-Path -LiteralPath $PortalApiEnv)) { throw "$PortalApiEnv does not exist." }
    $current = Read-EnvValue $PortalApiEnv 'DATAEASE_PROXY_SECRET'
    if ($current -ceq $secret) { Write-Host 'portal-api/.env already has the Dashboards sign-in secret (the same value).'; return }
    if ($current) { throw "portal-api/.env has a different DATAEASE_PROXY_SECRET. Remove that line by hand (without printing it), then run this again." }
    $text = [System.IO.File]::ReadAllText($PortalApiEnv)
    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += $newline }
    $text += "# Dashboards (DataEase) sign-in: the same value as GFM_DATAEASE_PROXY_SECRET in dataease/.env.$newline"
    $text += "DATAEASE_PROXY_SECRET=$secret$newline"
    [System.IO.File]::WriteAllText($PortalApiEnv, $text, $utf8)
    Write-Host 'Added DATAEASE_PROXY_SECRET to portal-api/.env. Recreate portal-api so it reads it.'
    return
}

if (Test-Path -LiteralPath $Target) { throw "$Target exists already; it is kept as it is. Delete it only if DataEase has never been started with it." }

$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
function New-Secret([int]$Length, [string]$Alphabet) {
    $bytes = New-Object byte[] ($Length * 2)
    $rng.GetBytes($bytes)
    $chars = for ($i = 0; $i -lt $Length; $i++) { $Alphabet[([int]$bytes[2 * $i] * 256 + $bytes[2 * $i + 1]) % $Alphabet.Length] }
    -join $chars
}
$letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
do {
    $admin = (New-Secret 19 $letters) + (New-Secret 1 '@-_.+')
} until ($admin -cmatch '[a-z]' -and $admin -cmatch '[A-Z]' -and $admin -match '[0-9]')

$reader = New-Secret 32 $letters
$readerNote = 'generated: set it on the database with dataease/set-reader-password.ps1 before seeding'

$content = @(
    '# Written by dataease/init-env.ps1. Secret: never commit, copy into chats or print.'
    "DE_MYSQL_ROOT_PASSWORD=$(New-Secret 32 $letters)"
    "DE_MYSQL_PASSWORD=$(New-Secret 32 $letters)"
    "DE_ADMIN_PASSWORD=$admin"
    "GFM_DATAEASE_PROXY_SECRET=$(New-Secret 48 $letters)"
    "GFM_DASHBOARD_READER_PASSWORD=$reader"
) -join "`n"
# UTF-8 without BOM and LF line ends, so docker compose reads it the same from Windows PowerShell 5.1 and 7.
[System.IO.File]::WriteAllText($Target, $content + "`n", $utf8)
Write-Host "$Target written. Reader password: $readerNote."
