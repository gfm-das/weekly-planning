<#
Sets the password of gfm_dashboard_reader (the read-only login DataEase uses) from dataease/.env.

Needed once after dataease/init-env.ps1 has generated the reader password (a new install).
(portal-api's charts and Archetypal Health use this role without a password, through SET LOCAL ROLE.)

Only a SCRAM-SHA-256 hash of the password is sent to Postgres, through psql's standard input and a psql variable,
so the password never appears on a command line, in the process list or in the database log.

Run from the repository root:
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/set-reader-password.ps1
#>
[CmdletBinding()]
param(
    [string]$EnvFile,
    [string]$Container = 'gfm-beta-supabase-db-1',
    [string]$Database = 'postgres'
)
$ErrorActionPreference = 'Stop'
if (-not $EnvFile) { $EnvFile = Join-Path $PSScriptRoot '.env' }

$line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^GFM_DASHBOARD_READER_PASSWORD=' } | Select-Object -First 1
if (-not $line) { throw "GFM_DASHBOARD_READER_PASSWORD is missing in $EnvFile." }
$password = ($line -replace '^GFM_DASHBOARD_READER_PASSWORD=', '').Trim().Trim('"').Trim("'")
if ($password.Length -lt 20 -or $password -notmatch '^[A-Za-z0-9_-]+$') {
    throw 'GFM_DASHBOARD_READER_PASSWORD must be a generated value of at least 20 letters, digits, - or _.'
}

# SCRAM-SHA-256 verifier as PostgreSQL stores it (RFC 5802 / RFC 7677, 4096 iterations).
$iterations = 4096
$salt = New-Object byte[] 16
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)
$derive = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
    [Text.Encoding]::UTF8.GetBytes($password), $salt, $iterations, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
$salted = $derive.GetBytes(32)
$hmac = [System.Security.Cryptography.HMACSHA256]::new($salted)
$clientKey = $hmac.ComputeHash([Text.Encoding]::ASCII.GetBytes('Client Key'))
$serverKey = $hmac.ComputeHash([Text.Encoding]::ASCII.GetBytes('Server Key'))
$storedKey = [System.Security.Cryptography.SHA256]::Create().ComputeHash($clientKey)
$verifier = 'SCRAM-SHA-256$' + $iterations + ':' + [Convert]::ToBase64String($salt) + '$' +
    [Convert]::ToBase64String($storedKey) + ':' + [Convert]::ToBase64String($serverKey)

$sql = "\set verifier '" + $verifier + "'`nALTER ROLE gfm_dashboard_reader PASSWORD :'verifier';`n"
$sql | docker exec -i $Container psql -U postgres -d $Database -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) { throw "Setting the password failed (psql exit code $LASTEXITCODE)." }
Write-Host 'The password of gfm_dashboard_reader is set.'
