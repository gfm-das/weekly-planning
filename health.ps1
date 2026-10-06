<#
  health.ps1: checks that every part of the mission system is up, and prints one row per check.

  Who runs it: the Data Analyst (after a deploy, or when something seems wrong), and the updater
  (updater/gfm-updater.ps1) before and after an update. It only looks: it changes nothing.

  What it checks:
    1. Web addresses: each must answer with the expected status. 200 means "the page is there"; 401 or 403 on an
       address that needs a sign-in means "the door is locked", which is exactly what we want to see.
    2. Parts that exist only once they are deployed (Dashboards on DataEase, the Presentations deck address 8089):
       while they are not deployed their rows say SKIPPED, which is not a failure.
    3. The nightly backup: the newest Beta database dump must be less than 26 hours old and the last night must
       have worked (nightly-backup/, docs/handoff/round6/ops.md).
    4. No container may be restarting over and over, or be marked unhealthy.

  Run it from the repository root (Windows PowerShell 5.1 or PowerShell 7):
      powershell -NoProfile -ExecutionPolicy Bypass -File health.ps1
  Exit code 0: every row is OK (or SKIPPED/waiting). Exit code 1: at least one row says FAIL.
  Tests: ops-tests/test-health.ps1 (stand-ins for docker and the web; nothing real is asked).
#>
[CmdletBinding()]
param(
    # Load the functions only, run nothing (ops-tests/test-health.ps1 uses this).
    [switch]$NoRun
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------------------------------------------
# 1. Web addresses that must always answer. Expected: the status codes that count as OK. Body (optional): a pattern
#    the answer must contain, so that some other page answering 200 does not count.
# ---------------------------------------------------------------------------------------------------------------
$checks = @(
    @{ Name = 'Beta Studio'; Uri = 'http://127.0.0.1:13000'; Expected = @(200) }
    @{ Name = 'Beta Kong'; Uri = 'http://127.0.0.1:18000/auth/v1/settings'; Expected = @(200, 401) }
    @{ Name = 'Roster Importer'; Uri = 'http://127.0.0.1:8090/health'; Expected = @(200) }
    @{ Name = 'Slidev'; Uri = 'http://127.0.0.1:3030'; Expected = @(200) }
    @{ Name = 'Portal'; Uri = 'http://127.0.0.1:8070'; Expected = @(200) }
    @{ Name = 'Portal API'; Uri = 'http://127.0.0.1:8070/api/health'; Expected = @(200) }
    @{ Name = 'Portal Auth Boundary'; Uri = 'http://127.0.0.1:8070/api/overview'; Expected = @(401) }
)
# Appsmith (8080), Superset (8088, 8089) and Grafana were retired in round 6, and the older Supabase stack (Production,
# 3000/8000) on 3 Oct 2026; none of them has rows any more. Port 8088 is
# DataEase's since round 6 and port 8089 the Presentations deck address since round 8 (below).

# ---------------------------------------------------------------------------------------------------------------
# 2. Rows that exist only once their part is deployed.
# ---------------------------------------------------------------------------------------------------------------
# Dashboards (DataEase, dataease/compose.yml). /gfm-gate-health answers 200 only when DataEase answers and its
# sign-in gate holds a working DataEase sign-in. Without the portal's Dashboards cookie DataEase must answer 401.
$DataEaseContainer = 'gfm-dataease'
$DataEaseRows = @('Dashboards (DataEase)', 'DataEase Sign-in Boundary')
function Get-DataEaseChecks {
    return @(
        @{ Name = $DataEaseRows[0]; Uri = 'http://127.0.0.1:8088/gfm-gate-health'; Expected = @(200); Body = '"dataease"\s*:\s*"signed-in"' }
        @{ Name = $DataEaseRows[1]; Uri = 'http://127.0.0.1:8088/de2api/user/info'; Expected = @(401) }
    )
}

# Presentations on their own address (round 8, docs/handoff/round8/deckorigin.md): published decks and the deck
# editor answer on port 8089 once the Slidev container publishes it (slidev/local-override.yml).
#  - The deck address answers /health.
#  - A deck without a deck pass answers 401 (the manager's own sign-in never counts there).
#  - The manager (3030) refuses a data request without its X-GFM-Request header with 403, before anything else
#    (a deck page cannot send that header).
#  - On the deck address numbers are given only for the deck of the page that asks, so a request from no deck page
#    answers 403.
# A setting (GFM_SLIDEV_CONTAINER, also read by slidev/slidev-compose.yml); the default is this server's.
$SlidevContainer = if ($env:GFM_SLIDEV_CONTAINER) { $env:GFM_SLIDEV_CONTAINER } else { 'slidev-j5iyrpjbsssqlilqhw9axugx' }
$DeckAddressRows = @('Presentation Decks (8089)', 'Deck Pass Boundary', 'Presentations Request Guard', 'Deck Numbers Guard')
function Get-DeckAddressChecks {
    return @(
        @{ Name = $DeckAddressRows[0]; Uri = 'http://127.0.0.1:8089/health'; Expected = @(200); Body = '"deck-address"' }
        @{ Name = $DeckAddressRows[1]; Uri = 'http://127.0.0.1:8089/p/health-check/'; Expected = @(401) }
        @{ Name = $DeckAddressRows[2]; Uri = 'http://127.0.0.1:3030/api/presentations'; Expected = @(403) }
        @{ Name = $DeckAddressRows[3]; Uri = 'http://127.0.0.1:8089/api/deck-pass'; Expected = @(403) }
    )
}

# Windows PowerShell 5.1 turns a program's stderr into errors that stop the script under 'Stop', so docker runs
# with 'Continue' here and only its output and exit code are used.
function Invoke-Docker([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & docker @Arguments 2>$null
        return @{ Ok = ($LASTEXITCODE -eq 0); Output = @($output) }
    }
    finally { $ErrorActionPreference = $previous }
}

function Test-DataEaseDeployed {
    return (Invoke-Docker @('container', 'inspect', $DataEaseContainer, '--format', '{{.Name}}')).Ok
}

function Test-DeckAddressDeployed {
    $port = Invoke-Docker @('port', $SlidevContainer, '3041/tcp')
    return $port.Ok -and (($port.Output -join ' ') -match ':8089\b')
}

# ---------------------------------------------------------------------------------------------------------------
# 3. The nightly backup (nightly-backup/backup-compose.yml; docs/handoff/round6/ops.md). Skipped while the
#    gfm-backup container does not exist; "waiting" after its deploy until the first night (02:30).
# ---------------------------------------------------------------------------------------------------------------
$BackupContainer = 'gfm-backup'
$BackupMaxHours = 26

# What there is to look at: the container's state, the newest Beta dump and the result of the last night.
function Get-NightlyBackupFacts([string]$BackupDir) {
    $latest = Get-ChildItem -LiteralPath $BackupDir -Filter 'beta-*.dump' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^beta-\d{8}-\d{4}\.dump$' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return @{
        ContainerState = Invoke-Docker @('inspect', $BackupContainer, '--format', '{{.State.Running}}|{{.Created}}')
        LatestBackup   = $latest
        LastNight      = Get-Content -LiteralPath (Join-Path $BackupDir 'last-run.txt') -TotalCount 1 -ErrorAction SilentlyContinue
    }
}

# The row, from those facts: Ok ($false turns the whole check to FAIL) and the text of the Result column.
function Get-NightlyBackupVerdict($ContainerState, $LatestBackup, $LastNight, [datetime]$Now) {
    $container = $BackupContainer
    if (-not $ContainerState.Ok) {
        # No container. Backup files without their container mean it was removed: that is a failure.
        if ($LatestBackup) { return @{ Ok = $false; Result = "FAIL: no $container container (docs/handoff/round6/ops.md)" } }
        return @{ Ok = $true; Result = "SKIPPED (not deployed: no $container container)" }
    }
    $state = $ContainerState.Output -join ''
    if ($state -notmatch '^true\|') { return @{ Ok = $false; Result = "FAIL: $container is not running" } }
    if ($LatestBackup) {
        $ageHours = ($Now - $LatestBackup.LastWriteTime).TotalHours
        if ($ageHours -ge $BackupMaxHours) {
            return @{ Ok = $false; Result = "FAIL: the newest backup $($LatestBackup.Name) is $([int]$ageHours) hours old" }
        }
    }
    if ($LastNight -match '^FAILED') {
        return @{ Ok = $false; Result = "FAIL: last night: $($LastNight -replace '^FAILED \S+: ', '') (backups\nightly\nightly.log)" }
    }
    if ($LatestBackup) {
        return @{ Ok = $true; Result = ('OK ({0}, {1:N1} MB, {2:N0} h old)' -f $LatestBackup.Name, ($LatestBackup.Length / 1MB), $ageHours) }
    }
    # Running, but no backup yet: fine during the first 26 hours after the deploy (the first night is at 02:30).
    $created = [DateTimeOffset]::Parse((($state -split '\|', 2)[1] -replace '\.\d+Z$', 'Z'))
    if (([DateTimeOffset]$Now - $created).TotalHours -lt $BackupMaxHours) {
        return @{ Ok = $true; Result = 'waiting (the first backup is made at 02:30)' }
    }
    return @{ Ok = $false; Result = 'FAIL: no backup yet, 26 hours after the deploy (backups\nightly\nightly.log)' }
}

# ---------------------------------------------------------------------------------------------------------------
# Asking a web address.
# ---------------------------------------------------------------------------------------------------------------
# Works in Windows PowerShell 5.1 and PowerShell 7: 4xx/5xx answers throw in both, so the status code is read from
# the exception's response instead of relying on -SkipHttpErrorCheck (PowerShell 7 only).
function Get-HttpResult([string]$Uri) {
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 20
        return @{ Status = [int]$response.StatusCode; Content = [string]$response.Content }
    }
    catch {
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) { return @{ Status = [int]$response.StatusCode; Content = '' } }
        throw
    }
}

function New-Row([string]$Service, $Status, [string]$Result) {
    return [pscustomobject]@{ Service = $Service; Status = $Status; Result = $Result }
}

# One web check: @{ Ok; Row }.
function Invoke-WebCheck($Check) {
    try {
        $answer = Get-HttpResult $Check.Uri
    }
    catch {
        return @{ Ok = $false; Row = New-Row $Check.Name '-' "FAIL: $($_.Exception.Message)" }
    }
    $ok = $answer.Status -in $Check.Expected
    $note = ''
    if ($ok -and $Check.Body -and $answer.Content -notmatch $Check.Body) {
        $ok = $false
        $note = ' (unexpected answer)'
    }
    $result = if ($ok) { 'OK' } else { "FAIL$note" }
    return @{ Ok = $ok; Row = New-Row $Check.Name $answer.Status $result }
}

# ---------------------------------------------------------------------------------------------------------------
# All rows, in the order they are printed: the nightly backup, the web checks, then the rows that were skipped.
# ---------------------------------------------------------------------------------------------------------------
function Get-HealthRows([string]$BackupDir) {
    $failed = $false
    $rows = @()

    $facts = Get-NightlyBackupFacts $BackupDir
    $backup = Get-NightlyBackupVerdict $facts.ContainerState $facts.LatestBackup $facts.LastNight (Get-Date)
    $failed = $failed -or -not $backup.Ok
    $rows += New-Row 'Nightly backup' '-' $backup.Result

    $dataEaseDeployed = Test-DataEaseDeployed
    $deckAddressDeployed = Test-DeckAddressDeployed
    $webChecks = $checks
    if ($dataEaseDeployed) { $webChecks += Get-DataEaseChecks }
    if ($deckAddressDeployed) { $webChecks += Get-DeckAddressChecks }
    foreach ($check in $webChecks) {
        $answer = Invoke-WebCheck $check
        $failed = $failed -or -not $answer.Ok
        $rows += $answer.Row
    }

    if (-not $dataEaseDeployed) {
        foreach ($name in $DataEaseRows) { $rows += New-Row $name '-' "SKIPPED (not deployed: no $DataEaseContainer container)" }
    }
    if (-not $deckAddressDeployed) {
        foreach ($name in $DeckAddressRows) { $rows += New-Row $name '-' 'SKIPPED (not deployed: port 8089 not published yet)' }
    }
    return @{ Rows = $rows; Failed = $failed }
}

# 4. Containers that keep restarting or are marked unhealthy (one line each: name|status).
function Get-UnstableContainers {
    $lines = docker ps -a --format '{{.Names}}|{{.Status}}' | Select-String -Pattern 'Restarting|unhealthy'
    return @($lines | ForEach-Object { $_.Line })
}

if ($NoRun) { return }

$health = Get-HealthRows (Join-Path $PSScriptRoot 'backups\nightly')
$failed = $health.Failed
# Printed explicitly, so the table is not lost when the script ends with 'exit'.
$health.Rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Host

$unstable = Get-UnstableContainers
if ($unstable) {
    $failed = $true
    Write-Host "`nUnstable containers:" -ForegroundColor Red
    $unstable | ForEach-Object { Write-Host $_ }
}

if ($failed) {
    exit 1
}
