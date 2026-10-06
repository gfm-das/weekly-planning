<#
  The quick tests the updater runs on a copy of a new version before it installs anything (about a minute).
  They need no database and no network: each runs in a throw-away container started with --network none, on the
  copy only (never on the live files).

    1. Presentations (Slidev): node --test tests/*.test.mjs
    2. Portal page checks: node portal/tests/*.cjs and *.test.mjs
    3. Python files of portal-api and DA Management compile
    4. DA Management's Updates page (tests/test_updates_page.py, in DA Management's own image)
    5. The updater's own tests (updater/tests/test-updater.ps1) and every PowerShell script parses

  Usage (the updater does this):  quick-tests.ps1 -Root <folder with a copy of the version>
  Exit code 0 means everything passed.
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Root)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $Root).Path
$PowerShellExe = (Get-Process -Id $PID).Path

# Runs one test program and says whether it passed. Output is shown so the updater's log keeps it.
function Test-Part([string]$Name, [string]$Program, [string[]]$Arguments) {
    Write-Host "--- $Name"
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1: stderr of a program is not an error here
    try {
        $global:LASTEXITCODE = 0
        & $Program @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -eq 0) { Write-Host "--- $($Name): passed" } else { Write-Host "--- $($Name): DID NOT PASS (exit code $code)" }
    return ($code -eq 0)
}

function Invoke-InContainer([string]$Name, [string]$Image, [string]$WorkDir, [string[]]$Command) {
    $arguments = @('run', '--rm', '--network', 'none', '-v', "${Root}:/repo", '-w', $WorkDir, $Image) + $Command
    return (Test-Part $Name 'docker' $arguments)
}

# 1. Presentations. One of these tests measures time; a busy computer can make it fail once, so it gets a second try.
function Test-Presentations {
    $slidev = @('sh', '-c', 'node --test tests/*.test.mjs')
    if (Invoke-InContainer 'Presentations (Slidev) tests' 'node:24-alpine' '/repo/slidev' $slidev) { return $true }
    return (Invoke-InContainer 'Presentations (Slidev) tests, second try' 'node:24-alpine' '/repo/slidev' $slidev)
}

# 2. Portal page checks.
function Test-Portal {
    $portal = @('sh', '-c', 'for f in portal/tests/*.cjs; do echo "$f"; node "$f" || exit 1; done; node --test portal/tests/*.test.mjs')
    return (Invoke-InContainer 'Portal page checks' 'node:24-alpine' '/repo' $portal)
}

# 3. Python compiles.
function Test-PythonCompiles {
    return (Invoke-InContainer 'Python files compile' 'python:3.12-alpine' '/repo' @('python', '-m', 'compileall', '-q', 'portal-api', 'roster-importer'))
}

# The lines of a text, trimmed, without empty ones (to compare two requirements.txt files).
function Get-Lines([string[]]$Text) { return (@($Text | ForEach-Object { "$_".Trim() } | Where-Object { $_ }) -join "`n") }

# 4. DA Management's Updates page, in DA Management's own image (it has Flask). DATABASE_URL is a stand-in: the
#    test never opens a database. The image has today's packages: when the new version changes them
#    (roster-importer/requirements.txt), they only arrive with the rebuild, so this test waits for the next update.
function Test-UpdatesPage {
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'roster-importer\tests\test_updates_page.py'))) { return $true }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1: a line on stderr is not an error here
    try { $inImage = Get-Lines (& docker run --rm --network none roster-importer-roster-importer cat /app/requirements.txt 2>$null) }
    finally { $ErrorActionPreference = $previous }
    $inVersion = Get-Lines (Get-Content -LiteralPath (Join-Path $Root 'roster-importer\requirements.txt'))
    if ($inImage -ne $inVersion) {
        Write-Host '--- DA Management Updates page: skipped (this version changes its packages; they arrive with the rebuild)'
        return $true
    }
    $page = @('run', '--rm', '--network', 'none', '-v', "${Root}:/repo", '-w', '/repo/roster-importer',
        '-e', 'DATABASE_URL=postgresql://nobody@127.0.0.1:1/none', '-e', 'PYTHONDONTWRITEBYTECODE=1',
        'roster-importer-roster-importer', 'python', '-m', 'unittest', 'tests.test_updates_page')
    return (Test-Part 'DA Management Updates page' 'docker' $page)
}

# 5a. The updater's own tests.
function Test-Updater {
    $updaterTests = Join-Path $Root 'updater\tests\test-updater.ps1'
    if (-not (Test-Path -LiteralPath $updaterTests)) { return $true }
    return (Test-Part 'Updater tests' $PowerShellExe @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $updaterTests))
}

# 5b. Every PowerShell script parses (a typo would stop a deploy half-way). Returns the names of those that do not.
function Get-ScriptsThatDoNotParse {
    Write-Host '--- PowerShell scripts parse'
    $broken = @()
    $scripts = Get-ChildItem -LiteralPath $Root -Recurse -Filter '*.ps1' -File |
        Where-Object { $_.FullName -notmatch '\\(node_modules|legacy|backups)\\' }
    foreach ($file in $scripts) {
        $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$null, [ref]$errors)
        if ($errors) {
            Write-Host "$($file.FullName.Substring($Root.Length)): $($errors[0].Message)"
            $broken += "PowerShell $($file.Name)"
        }
    }
    return $broken
}

$failed = @()
if (-not (Test-Presentations)) { $failed += 'Presentations' }
if (-not (Test-Portal)) { $failed += 'Portal' }
if (-not (Test-PythonCompiles)) { $failed += 'Python' }
if (-not (Test-UpdatesPage)) { $failed += 'Updates page' }
if (-not (Test-Updater)) { $failed += 'Updater' }
$failed += @(Get-ScriptsThatDoNotParse)

if ($failed) {
    Write-Host "Quick tests that did not pass: $($failed -join ', ')"
    exit 1
}
Write-Host 'All quick tests passed.'
exit 0
