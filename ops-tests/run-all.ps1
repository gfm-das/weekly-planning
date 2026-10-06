<#
  Runs every test of the operations parts in one go: the portal deploy, the health check, the updater, the nightly
  backup and the Dashboards (DataEase) scripts and backup. Nothing real is touched: the tests use stand-ins, and the ones that
  need Linux run in throw-away containers without network (local images postgres:15-alpine and node:24-alpine).

  Run it from anywhere (Windows PowerShell 5.1 or PowerShell 7):
      powershell -NoProfile -ExecutionPolicy Bypass -File ops-tests\run-all.ps1
  It prints one line per part and ends with exit code 0 when every part passed.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$powershell = (Get-Process -Id $PID).Path

# Runs one part and returns whether it passed. Its own output is shown only when it did not pass.
function Test-Part([string]$Name, [string]$Program, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1: stderr of a program is not an error here
    try {
        $global:LASTEXITCODE = 0
        $output = @(& $Program @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    # The summary lines: "... tests: 36 passed, 0 did not pass." (PowerShell and bash) or "tests 42", "pass 42", "fail 0" (Node).
    $summary = @($output | Where-Object { $_ -match 'tests: \d+ passed|(tests|pass|fail) \d+$' } | ForEach-Object { $_ -replace '^\S+ (tests|pass|fail) ', '$1 ' })
    if ($code -eq 0) { Write-Host ("PASS  {0}  ({1})" -f $Name, ($summary -join '; ')) }
    else {
        Write-Host "FAIL  $Name (exit code $code)"
        $output | Select-Object -Last 40 | ForEach-Object { Write-Host "      $_" }
    }
    return ($code -eq 0)
}

function Invoke-PowerShellTest([string]$Name, [string]$Script) {
    return (Test-Part $Name $powershell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $repo $Script)))
}

function Invoke-ContainerTest([string]$Name, [string]$Folder, [string]$Mount, [string]$Image, [string[]]$Command) {
    $arguments = @('run', '--rm', '--network', 'none', '-v', ((Join-Path $repo $Folder) + ":${Mount}:ro"), '-w', $Mount, $Image) + $Command
    return (Test-Part $Name 'docker' $arguments)
}

$results = @(
    Invoke-PowerShellTest 'portal/deploy.ps1' 'ops-tests\test-deploy.ps1'
    Invoke-PowerShellTest 'health.ps1' 'ops-tests\test-health.ps1'
    Invoke-PowerShellTest 'updater' 'updater\tests\test-updater.ps1'
    Invoke-ContainerTest 'nightly backup' 'nightly-backup' '/backup' 'postgres:15-alpine' @('bash', '/backup/tests/test-nightly.sh')
    Invoke-ContainerTest 'Dashboards (DataEase) scripts' 'dataease' '/d' 'node:24-alpine' @('sh', '-c', 'node --test tests/*.test.mjs')
    Invoke-PowerShellTest 'Dashboards (DataEase) backup' 'ops-tests\test-dataease-backup.ps1'
)
$failed = @($results | Where-Object { -not $_ }).Count
Write-Host ''
Write-Host "Operations tests: $($results.Count - $failed) of $($results.Count) parts passed."
if ($failed) { exit 1 }
exit 0
