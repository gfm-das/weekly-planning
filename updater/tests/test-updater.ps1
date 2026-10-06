<#
  Tests of the updater's decisions, with a local bare Git repository standing in for GitHub.
  No Docker, no database, no network: the steps that would touch the live system (quick tests, health check,
  backup, image tags, portal copy, SQL, rebuilds) are replaced by stand-ins that only write down that they ran.

  Each scenario builds three folders in a temporary folder:
    remote.git  the stand-in for GitHub
    dev         where new changes are made and pushed
    live        this computer (the one being updated)

  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File updater\tests\test-updater.ps1
  Exit code 0 means every check passed.
#>
$ErrorActionPreference = 'Stop'
$updaterScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'gfm-updater.ps1'
. $updaterScript -NoRun   # the updater's functions, without running it

$work = Join-Path ([IO.Path]::GetTempPath()) ('gfm-updater-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$script:Failures = 0
$script:Passes = 0

# The updater's own messages are not needed here; the results are printed with [Console] below.
function Write-Host { param([Parameter(ValueFromRemainingArguments = $true)]$Ignored) }

function Assert-That([bool]$Condition, [string]$Name) {
    if ($Condition) { $script:Passes++; [Console]::Out.WriteLine("PASS  $Name") }
    else { $script:Failures++; [Console]::Out.WriteLine("FAIL  $Name") }
}

# ---------------------------------------------------------------------------------------------------------------
# Stand-ins for the steps that would touch the live system. They only write down that they ran.
# ---------------------------------------------------------------------------------------------------------------
function Reset-StandIns {
    $script:Calls = New-Object System.Collections.ArrayList
    $script:TestsPass = $true
    $script:HealthAnswers = New-Object System.Collections.Queue   # empty = healthy
    $script:HealthTries = 2
    $script:HealthPause = 0
}
function Invoke-QuickTests { param($Commit, $Stamp) [void]$script:Calls.Add('quick tests'); return $script:TestsPass }
function Test-Health {
    [void]$script:Calls.Add('health')
    if ($script:HealthAnswers.Count) { return $script:HealthAnswers.Dequeue() }
    return $true
}
function Save-DatabaseBackup { param($Point) [void]$script:Calls.Add('backup') }
function Save-ImageTags { param($Point) [void]$script:Calls.Add('image tags') }
function Save-PortalPages { param($Point) [void]$script:Calls.Add('portal copy') }
function Invoke-SqlFile { param($File, $User) [void]$script:Calls.Add("sql $(Split-Path -Leaf $File) as $User"); return $true }
function Update-Parts {
    param($Point, $Parts)
    foreach ($part in $Parts) { [void]$Point.Renewed.Add($part) }
    [void]$script:Calls.Add("renew $(@($Parts) -join ',')")
}
function Undo-Parts { param($Point) [void]$script:Calls.Add("undo $(@($Point.Renewed) -join ',')") }

# ---------------------------------------------------------------------------------------------------------------
# Git helpers for the scenarios.
# ---------------------------------------------------------------------------------------------------------------
function Invoke-TestGit([string]$Folder, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& git -C $Folder -c user.name=Tester -c user.email=tester@example.invalid -c init.defaultBranch=main -c core.autocrlf=false @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "git $($Arguments -join ' ') in ${Folder}: $($output -join ' ')" }
    return $output
}

function Add-Commit([string]$Folder, [string]$Path, [string]$Content, [string]$Message) {
    $file = Join-Path $Folder $Path
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    [IO.File]::WriteAllText($file, $Content)
    Invoke-TestGit $Folder @('add', '--', $Path) | Out-Null
    Invoke-TestGit $Folder @('commit', '-q', '-m', $Message) | Out-Null
}

function Get-Head([string]$Folder) { return @(Invoke-TestGit $Folder @('rev-parse', 'HEAD'))[0].Trim() }

function New-Scenario([string]$Name) {
    $root = Join-Path $work $Name
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Invoke-TestGit $root @('init', '-q', '--bare', '-b', 'main', 'remote.git') | Out-Null
    Invoke-TestGit $root @('clone', '-q', 'remote.git', 'dev') | Out-Null
    $dev = Join-Path $root 'dev'
    Add-Commit $dev 'README.md' "Mission system`n" 'First version'
    Add-Commit $dev 'portal-api/migrations/019_restrict_public_functions.sql' "-- rights check`nBEGIN;`nCOMMIT;`n" 'Rights check'
    Invoke-TestGit $dev @('push', '-q', 'origin', 'main') | Out-Null
    Invoke-TestGit $root @('clone', '-q', 'remote.git', 'live') | Out-Null
    $live = Join-Path $root 'live'
    Initialize-Updater $live
    Reset-StandIns
    return @{ Root = $root; Dev = $dev; Live = $live }
}

# Two new changes on "GitHub": a migration (run as postgres, with its rollback file) and page code.
function Add-RemoteChanges($Scenario) {
    $migration = "-- Test migration. Apply:`n--   psql -U postgres -d postgres`nBEGIN;`nCREATE TABLE t(id int);`nCOMMIT;`n"
    Add-Commit $Scenario.Dev 'portal-api/migrations/090_test_table.sql' $migration 'Add the test table'
    Add-Commit $Scenario.Dev 'portal-api/migrations/090_test_table_rollback.sql' "BEGIN;`nDROP TABLE t;`nCOMMIT;`n" 'Its rollback'
    Add-Commit $Scenario.Dev 'slidev/manager/new.mjs' "export const x = 1`n" 'Presentations: a new file'
    Add-Commit $Scenario.Dev 'portal/page.html' "<p>Hello</p>`n" "Portal: a page with a Gr$([char]0xFC)$([char]0xDF)e"
    Invoke-TestGit $Scenario.Dev @('push', '-q', 'origin', 'main') | Out-Null
    return Get-Head $Scenario.Dev
}

function Send-Request([hashtable]$Fields) {
    [IO.File]::WriteAllText($script:RequestFile, ($Fields | ConvertTo-Json))
}

function Invoke-NextRequest {
    $request = Read-Request
    if ($request) { Invoke-Request $request }
    return $request
}

function Read-TestStatus { return ([IO.File]::ReadAllText($script:StatusFile) | ConvertFrom-Json) }

# Stands in for a person running the updater in a terminal: another thread holds the work lock until Stop-LockHolder.
function Start-LockHolder {
    $held = New-Object System.Threading.ManualResetEvent $false
    $done = New-Object System.Threading.ManualResetEvent $false
    $shell = [powershell]::Create()
    [void]$shell.AddScript({
        param($Name, $Held, $Done)
        $mutex = New-Object System.Threading.Mutex($false, $Name)
        [void]$mutex.WaitOne()
        [void]$Held.Set()
        [void]$Done.WaitOne(20000)
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }).AddArgument((Get-LockName 'Work')).AddArgument($held).AddArgument($done)
    $async = $shell.BeginInvoke()
    [void]$held.WaitOne(10000)
    return @{ Shell = $shell; Async = $async; Done = $done }
}

function Stop-LockHolder($Holder) {
    [void]$Holder.Done.Set()
    [void]$Holder.Shell.EndInvoke($Holder.Async)
    $Holder.Shell.Dispose()
}

$uuid = '11111111-2222-3333-4444-555555555555'

try {
    # --- Hiding secrets -----------------------------------------------------------------------------------------
    Assert-That ((Protect-Text 'https://name:pw123@github.com/gfm-das/x.git') -eq 'https://***@github.com/gfm-das/x.git') 'a password in a web address is hidden'
    Assert-That ((Protect-Text 'token ghp_abcdefghijklmnop1234') -notmatch 'ghp_') 'a GitHub token is hidden'
    Assert-That ((Protect-Text 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl') -eq '***') 'a signed web token is hidden'

    # --- Which parts an update renews, and which a person installs ----------------------------------------------
    $changed = @('portal-api/app.py', 'portal-api/migrations/090_x.sql', 'portal-api/tests/test_x.py', 'roster-importer/app.py',
        'slidev/manager/server.mjs', 'portal/home.html', 'docs/README-start-here.md', 'ops-tests/test-deploy.ps1',
        'updater/gfm-updater.ps1', 'health.ps1', 'supabase/config/kong/kong.yml', 'nightly-backup/nightly.sh')
    Assert-That (((Get-PartsToRenew $changed) -join ',') -eq 'portal-api,da-management,slidev,portal') 'renewed: portal-api, DA Management, Slidev and the portal pages'
    Assert-That (@(Get-PartsToRenew @('portal-api/migrations/090_x.sql', 'portal-api/tests/test_x.py')).Count -eq 0) 'a migration or a test alone renews no service'
    Assert-That (((Get-OtherParts $changed) -join ',') -eq 'nightly-backup,supabase') 'installed by a person: only the folders the updater does not handle (not docs, tests or root files)'

    # --- Up to date ---------------------------------------------------------------------------------------------
    $s = New-Scenario 'uptodate'
    $plan = Invoke-Check
    $status = Read-TestStatus
    Assert-That ($plan.result -eq 'up_to_date' -and -not $plan.can_update) 'up to date: nothing to install'
    Assert-That ($status.current.commit -eq (Get-Head $s.Live) -and $status.check_result -eq 'up_to_date' -and $status.follows -eq 'origin/main') 'up to date: the status file names this version and origin/main'

    # --- New changes: the check lists them and changes nothing --------------------------------------------------
    $before = Get-Head $s.Live
    $target = Add-RemoteChanges $s
    $plan = Invoke-Check
    $status = Read-TestStatus
    Assert-That ($plan.result -eq 'updates' -and $plan.can_update) 'new changes: an update is possible'
    Assert-That (@($status.new_changes).Count -eq 4 -and $status.new_changes[0].subject -eq "Portal: a page with a Gr$([char]0xFC)$([char]0xDF)e") 'new changes: the status lists all four, newest first, umlauts kept'
    Assert-That ((@($status.migrations) -join ',') -eq 'portal-api/migrations/090_test_table.sql') 'new changes: the new migration is found (its rollback file is not a migration)'
    Assert-That ((Get-Head $s.Live) -eq $before) 'a check never changes the code'

    # --- An update request from DA Management: fast-forward, every step in order --------------------------------
    Send-Request @{ action = 'update'; target = $target; confirmed = $true; role = 'AP'; user_id = $uuid }
    $request = Invoke-NextRequest
    $status = Read-TestStatus
    Assert-That ($null -ne $request -and -not (Test-Path -LiteralPath $script:RequestFile)) 'update request: read once and removed'
    Assert-That ((Get-Head $s.Live) -eq $target) 'update: the code is now the new version (fast-forward)'
    Assert-That ($status.last_update.result -eq 'done' -and $status.last_update.to -eq $target -and $status.last_update.from -eq $before) 'update: the status says done, from and to'
    Assert-That ($status.last_update.asked_by -eq "DA Management, AP (user $uuid)") 'update: the status says who asked'
    $expected = @('quick tests', 'health', 'backup', 'image tags', 'portal copy', 'sql 090_test_table.sql as postgres',
        'sql 019_restrict_public_functions.sql as supabase_admin', 'renew slidev,portal', 'health')
    Assert-That ((@($script:Calls) -join ' | ') -eq ($expected -join ' | ')) "update: tests, health, way back saved, then migration + 019, renew, health (got: $(@($script:Calls) -join ' | '))"
    $point = Get-ChildItem -LiteralPath $script:Paths.Backups -Directory | Select-Object -First 1
    Assert-That (Test-Path -LiteralPath (Join-Path $point.FullName 'rollback-sql\090_test_table_rollback.sql')) 'update: the rollback file of the new migration is kept for the way back'
    Assert-That (([IO.File]::ReadAllText((Join-Path $point.FullName 'repo-head.txt'))).Trim() -eq $before) 'update: the previous commit is kept for the way back'
    Assert-That ($status.check_result -eq 'up_to_date' -and $status.current.commit -eq $target) 'after the update the page shows the new version, up to date'

    # --- The watcher and a person in a terminal: neither undoes what the other wrote ----------------------------
    $script:StatusData = [ordered]@{ state = 'idle'; can_update = $true }   # an old copy in memory, as a watcher had it
    Update-Heartbeat
    $status = Read-TestStatus
    Assert-That ($status.last_update.result -eq 'done' -and -not $status.can_update) 'a write from an old copy in memory keeps the last update and offers no update'

    # --- This computer has a change GitHub does not have: refused ------------------------------------------------
    Add-Commit $s.Live 'notes.txt' "local`n" 'A change made on this computer'
    $localHead = Get-Head $s.Live
    Reset-StandIns
    $plan = Invoke-Check
    Assert-That ($plan.result -eq 'local_ahead' -and $plan.blocked -eq 'local_ahead' -and -not $plan.can_update) 'local change: the check says this computer is ahead, no update'

    # --- Both have their own changes (diverged): refused ---------------------------------------------------------
    Add-Commit $s.Dev 'docs/news.md' "news`n" 'News on GitHub'
    Invoke-TestGit $s.Dev @('push', '-q', 'origin', 'main') | Out-Null
    $remoteHead = Get-Head $s.Dev
    Send-Request @{ action = 'update'; target = $remoteHead; confirmed = $true; role = 'DATA_ADMIN' }
    Invoke-NextRequest | Out-Null
    $status = Read-TestStatus
    Assert-That ($status.check_result -eq 'diverged' -and $status.last_update.result -eq 'refused' -and $status.last_update.reason -eq 'diverged') 'diverged: the update is refused and the reason saved'
    Assert-That ((Get-Head $s.Live) -eq $localHead -and $script:Calls.Count -eq 0) 'diverged: the code is unchanged and no step ran'

    # --- Files changed by hand: refused, the file keeps its content ----------------------------------------------
    $s = New-Scenario 'dirty'
    $before = Get-Head $s.Live
    $target = Add-RemoteChanges $s
    [IO.File]::WriteAllText((Join-Path $s.Live 'README.md'), "changed by hand`n")
    Send-Request @{ action = 'update'; target = $target; confirmed = $true; role = 'PRESIDENT' }
    Invoke-NextRequest | Out-Null
    $status = Read-TestStatus
    Assert-That ($status.blocked -eq 'changed_by_hand' -and $status.last_update.result -eq 'refused' -and $status.last_update.reason -eq 'changed_by_hand') 'changed by hand: the update is refused'
    Assert-That ((Get-Head $s.Live) -eq $before -and ([IO.File]::ReadAllText((Join-Path $s.Live 'README.md'))) -eq "changed by hand`n") 'changed by hand: code and the changed file are untouched'
    # A new file Git does not know is not a change by hand.
    Invoke-TestGit $s.Live @('checkout', '--', 'README.md') | Out-Null
    [IO.File]::WriteAllText((Join-Path $s.Live 'scratch.txt'), "untracked`n")
    Assert-That ((Invoke-Check).can_update) 'an untracked file does not block an update'

    # --- Quick tests fail: nothing installed ---------------------------------------------------------------------
    Reset-StandIns
    $script:TestsPass = $false
    Send-Request @{ action = 'update'; target = $target; confirmed = $true; role = 'AP' }
    Invoke-NextRequest | Out-Null
    $status = Read-TestStatus
    Assert-That ($status.last_update.result -eq 'tests_failed' -and (Get-Head $s.Live) -eq $before) 'tests fail: nothing installed'
    Assert-That (-not ($script:Calls -contains 'backup')) 'tests fail: not even the backup ran'

    # --- Not healthy before: nothing installed -------------------------------------------------------------------
    Reset-StandIns
    $script:HealthAnswers.Enqueue($false)
    Send-Request @{ action = 'update'; target = $target; confirmed = $true; role = 'AP' }
    Invoke-NextRequest | Out-Null
    $status = Read-TestStatus
    Assert-That ($status.last_update.result -eq 'refused' -and $status.last_update.reason -eq 'not_healthy' -and (Get-Head $s.Live) -eq $before) 'not healthy before: the update waits'

    # --- Not healthy after: everything goes back by itself -------------------------------------------------------
    Reset-StandIns
    foreach ($answer in @($true, $false, $false, $true)) { $script:HealthAnswers.Enqueue($answer) }   # before, 2 tries after, after the way back
    Send-Request @{ action = 'update'; target = $target; confirmed = $true; role = 'AP' }
    Invoke-NextRequest | Out-Null
    $status = Read-TestStatus
    Assert-That ($status.last_update.result -eq 'rolled_back') 'not healthy after: the status says the previous version is back'
    Assert-That ((Get-Head $s.Live) -eq $before -and @(Invoke-TestGit $s.Live @('status', '--porcelain', '--untracked-files=no')).Count -eq 0) 'not healthy after: the code is back at the previous commit, clean'
    Assert-That ($script:Calls -contains 'undo slidev,portal') 'not healthy after: the renewed services go back'
    $undo = [array]::IndexOf(@($script:Calls), 'sql 090_test_table_rollback.sql as supabase_admin')
    Assert-That ($undo -gt 0 -and @($script:Calls)[$undo + 1] -eq 'sql 019_restrict_public_functions.sql as supabase_admin') 'not healthy after: the new migration is rolled back, then 019'

    # --- The list changed after it was shown: refused ------------------------------------------------------------
    Reset-StandIns
    Send-Request @{ action = 'update'; target = $before; confirmed = $true; role = 'AP' }
    Invoke-NextRequest | Out-Null
    $status = Read-TestStatus
    Assert-That ($status.last_update.reason -eq 'list_changed' -and (Get-Head $s.Live) -eq $before -and $script:Calls.Count -eq 0) 'another version than the one shown: refused'

    # --- Requests that are not ours are ignored and removed ------------------------------------------------------
    $bad = @(
        @{ Text = 'not json at all'; Name = 'unreadable text' },
        @{ Text = '[1, 2, 3]'; Name = 'a list' },
        @{ Text = (@{ action = 'powershell'; target = $target; confirmed = $true } | ConvertTo-Json); Name = 'an unknown action' },
        @{ Text = (@{ action = 'update'; target = $target } | ConvertTo-Json); Name = 'an update without confirmation' },
        @{ Text = (@{ action = 'update'; target = $target; confirmed = 'true' } | ConvertTo-Json); Name = 'confirmation as text' },
        @{ Text = (@{ action = 'update'; target = 'HEAD; Remove-Item -Recurse C:\'; confirmed = $true } | ConvertTo-Json); Name = 'a target that is not a version' },
        @{ Text = (@{ action = 'update'; target = $target.ToUpper(); confirmed = $true } | ConvertTo-Json); Name = 'a target in capitals' },
        @{ Text = ('{"action":"check","pad":"' + ('x' * 5000) + '"}'); Name = 'a file that is too big' }
    )
    foreach ($case in $bad) {
        Reset-StandIns
        [IO.File]::WriteAllText($script:RequestFile, $case.Text)
        $request = Invoke-NextRequest
        Assert-That ($null -eq $request -and -not (Test-Path -LiteralPath $script:RequestFile) -and (Get-Head $s.Live) -eq $before -and $script:Calls.Count -eq 0) "ignored and removed: $($case.Name)"
    }
    Send-Request @{ action = 'check'; role = 'AP' }
    Assert-That ((Invoke-NextRequest).Action -eq 'check' -and (Read-TestStatus).check_result -eq 'updates') 'a check request runs a check'

    # --- A migration that says it is installed by hand -----------------------------------------------------------
    Add-Commit $s.Dev 'portal-api/migrations/091_big_change.sql' "-- Big change. updater: install by hand`nBEGIN;`nCOMMIT;`n" 'A migration for a person'
    Invoke-TestGit $s.Dev @('push', '-q', 'origin', 'main') | Out-Null
    $plan = Invoke-Check
    Assert-That ($plan.blocked -eq 'by_hand' -and -not $plan.can_update) 'a migration marked "install by hand" blocks the automatic update'

    # --- The branch to follow is a setting -----------------------------------------------------------------------
    $s = New-Scenario 'branch'
    Invoke-TestGit $s.Dev @('checkout', '-q', '-b', 'release') | Out-Null
    Add-Commit $s.Dev 'docs/release.md' "release`n" 'On the release branch'
    Invoke-TestGit $s.Dev @('push', '-q', 'origin', 'release') | Out-Null
    [IO.File]::WriteAllText($script:Paths.Settings, '{ "Branch": "release" }')
    Initialize-Updater $s.Live
    $plan = Invoke-Check
    Assert-That ($plan.follows -eq 'origin/release' -and $plan.result -eq 'updates' -and @($plan.new_changes).Count -eq 1) 'Branch setting: follows origin/release'
    [IO.File]::WriteAllText($script:Paths.Settings, '{ "Branch": "main; rm -rf /" }')
    $refused = $false
    try { Initialize-Updater $s.Live } catch { $refused = $true }
    Assert-That $refused 'a branch setting that is not a plain name is refused'
    Assert-That (([IO.File]::ReadAllText($script:LogFile)) -match 'The updater cannot start: .*Branch' -and (Read-TestStatus).settings_problem -eq $true) 'wrong settings: the log says why, the status says the settings need a look'
    [IO.File]::WriteAllText($script:Paths.Settings, '{ "Branch": ')
    $refused = $false
    try { Initialize-Updater $s.Live } catch { $refused = $true }
    Assert-That ($refused -and (Read-TestStatus).settings_problem -eq $true) 'a settings file that is not readable is refused and reported'
    Remove-Item -LiteralPath $script:Paths.Settings
    Initialize-Updater $s.Live
    Assert-That ((Read-TestStatus).settings_problem -eq $false) 'good settings again: the settings notice goes away'
    [IO.File]::WriteAllText($script:Paths.Settings, '{ "Remote": "github" }')
    Initialize-Updater $s.Live
    Assert-That ((Invoke-Check).result -eq 'no_remote') 'no remote of that name yet: the check says so'
    Remove-Item -LiteralPath $script:Paths.Settings
    Initialize-Updater $s.Live

    # --- No password or token reaches the log or the status file -------------------------------------------------
    $fake = 'ghp_' + 'FAKE0123456789abcdefFAKE'
    Invoke-TestGit $s.Live @('remote', 'set-url', 'origin', "https://gfm-tester:$fake@127.0.0.1:9/gfm-platform.git") | Out-Null
    $plan = Invoke-Check
    $log = [IO.File]::ReadAllText($script:LogFile)
    $statusText = [IO.File]::ReadAllText($script:StatusFile)
    Assert-That ($plan.result -eq 'fetch_failed') 'GitHub not reachable: the check says so'
    Assert-That ($log -notmatch 'FAKE0123' -and $statusText -notmatch 'FAKE0123' -and $log -notmatch 'gfm-tester:') 'no token or password in the log or the status file'

    # --- An update that is still running in a terminal is left alone; one that was interrupted is reported --------
    Save-Status @{ state = 'updating'; step = 'migrations'; last_update = $null }
    $holder = Start-LockHolder
    try { Invoke-Heartbeat } finally { Stop-LockHolder $holder }
    $status = Read-TestStatus
    Assert-That ($status.state -eq 'updating' -and $null -eq $status.last_update) 'while someone else updates, the watcher leaves the status alone'
    Invoke-Heartbeat
    $status = Read-TestStatus
    Assert-That ($status.state -eq 'idle' -and $status.last_update.result -eq 'needs_person' -and $status.last_update.reason -eq 'interrupted') 'an interrupted update is reported for a person'
    Save-Status @{ state = 'checking' }
    Invoke-Heartbeat
    $status = Read-TestStatus
    Assert-That ($status.state -eq 'idle' -and $status.check_result -eq 'check_failed') 'an interrupted check is reported, not left "checking"'

    # --- Following release tags (Track "tags", the way new missions follow the public releases) ------------------
    $s = New-Scenario 'tagged'
    [IO.File]::WriteAllText($script:Paths.Settings, '{ "Track": "tags" }')
    Initialize-Updater $s.Live
    $plan = Invoke-Check
    Assert-That ($plan.result -eq 'up_to_date') 'tags: no release tag yet means up to date'
    Invoke-TestGit $s.Dev @('tag', 'v1.0.0') | Out-Null
    Invoke-TestGit $s.Dev @('push', '-q', 'origin', 'v1.0.0') | Out-Null
    Invoke-TestGit $s.Live @('fetch', '-q', '--tags') | Out-Null
    $plan = Invoke-Check
    Assert-That ($plan.result -eq 'up_to_date') 'tags: on the newest release means up to date'
    $target = Add-RemoteChanges $s
    Invoke-TestGit $s.Dev @('tag', 'v1.0.1') | Out-Null
    Invoke-TestGit $s.Dev @('tag', 'v1.10.0') | Out-Null
    Invoke-TestGit $s.Dev @('tag', 'v2-beta') | Out-Null
    Invoke-TestGit $s.Dev @('push', '-q', 'origin', 'v1.0.1', 'v1.10.0', 'v2-beta') | Out-Null
    $plan = Invoke-Check
    $status = Read-TestStatus
    Assert-That ($plan.result -eq 'updates' -and $plan.can_update -and $plan.remote.commit -eq $target) 'tags: a newer release tag offers an update to its commit'
    Assert-That ($status.follows -eq 'origin (v1.10.0)') "tags: the newest by version number wins (v1.10.0 after v1.0.1) and a tag like v2-beta is ignored (got: $($status.follows))"
    [IO.File]::WriteAllText($script:Paths.Settings, '{ "Track": "sideways" }')
    $refused = $false
    try { Initialize-Updater $s.Live } catch { $refused = $true }
    Assert-That $refused 'tags: an unknown Track in the settings is refused'
    Remove-Item -LiteralPath $script:Paths.Settings
    Initialize-Updater $s.Live
    Assert-That ($script:Settings.Track -eq 'branch') 'without a setting the updater follows the branch, as before'

    # --- The live steps name the right containers, images and files. Nothing runs: in this block the real steps
    #     are loaded again and every program they would start is only written down.
    $s = New-Scenario 'commands'
    Add-RemoteChanges $s | Out-Null
    Invoke-TestGit $s.Live @('pull', '-q', '--ff-only') | Out-Null   # the new files on disk, as after the new code
    $written = & {
        . $updaterScript -NoRun
        $script:Written = New-Object System.Collections.ArrayList
        function Invoke-Native {
            param([string]$Program, [string[]]$Arguments, [switch]$Quiet)
            [void]$script:Written.Add(((@(Split-Path -Leaf $Program) + $Arguments) -join ' '))
            return [pscustomobject]@{ Code = 0; Output = @() }
        }
        $point = @{ Stamp = 'T'; Folder = 'F'; Dump = 'D'; Migrations = @('portal-api/migrations/090_test_table.sql')
            Applied = New-Object System.Collections.ArrayList; Renewed = New-Object System.Collections.ArrayList }
        Save-DatabaseBackup $point; Save-ImageTags $point; Save-PortalPages $point
        Install-Migrations $point
        Update-Parts $point @('portal-api', 'da-management', 'slidev', 'portal')
        Undo-Parts $point
        Test-Health | Out-Null
        $script:Written
    }
    $live = $s.Live
    $expected = @(
        'docker exec gfm-beta-supabase-db-1 pg_dump -U postgres -Fc -d postgres -f /tmp/gfm-updater-T.dump',
        'docker cp gfm-beta-supabase-db-1:/tmp/gfm-updater-T.dump D',
        'docker tag gfm-portal-portal-api:latest portal-api-rollback:upd-T',
        'docker tag gfm-portal-portal-reminders:latest portal-reminders-rollback:upd-T',
        'docker tag roster-importer-roster-importer:latest roster-importer-rollback:upd-T',
        'docker cp portal-ydpgd5zwrjrvz5aa188sa60u:/usr/share/nginx/html F\portal-html',
        "docker cp $live\portal-api\migrations\090_test_table.sql gfm-beta-supabase-db-1:/tmp/gfm-updater-090_test_table.sql",
        'docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f /tmp/gfm-updater-090_test_table.sql',
        'docker exec gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -f /tmp/gfm-updater-019_restrict_public_functions.sql',
        "docker compose -p gfm-portal -f $live\portal-api\compose.yml up -d --build",
        "docker compose -p roster-importer -f $live\roster-importer\docker-compose.yml up -d --build --no-deps roster-importer",
        'docker restart slidev-j5iyrpjbsssqlilqhw9axugx',
        'docker tag portal-api-rollback:upd-T gfm-portal-portal-api:latest',
        "docker compose -p gfm-portal -f $live\portal-api\compose.yml up -d --no-build --no-deps --force-recreate portal-api portal-reminders",
        'docker tag roster-importer-rollback:upd-T roster-importer-roster-importer:latest',
        "docker compose -p roster-importer -f $live\roster-importer\docker-compose.yml up -d --no-build --no-deps --force-recreate roster-importer",
        'docker cp F\portal-html/. portal-ydpgd5zwrjrvz5aa188sa60u:/usr/share/nginx/html',
        'docker exec portal-ydpgd5zwrjrvz5aa188sa60u nginx -s reload'
    )
    $missing = @($expected | Where-Object { @($written) -notcontains $_ })
    Assert-That ($missing.Count -eq 0) "the live steps: backup, tags, portal copy, SQL, rebuilds, Slidev and the way back (missing: $($missing -join ' | '))"
    Assert-That (@($written | Where-Object { $_ -like "*-File $live\portal\deploy.ps1" }).Count -eq 1 -and @($written | Where-Object { $_ -like "*-File $live\health.ps1" }).Count -eq 1) 'the live steps: deploy.ps1 and health.ps1 of this code folder'
}
catch {
    $script:Failures++
    [Console]::Out.WriteLine("FAIL  the tests stopped: $($_.Exception.Message) (line $($_.InvocationInfo.ScriptLineNumber))")
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

[Console]::Out.WriteLine("Updater tests: $($script:Passes) passed, $($script:Failures) did not pass.")
if ($script:Failures) { exit 1 }
exit 0
