<#
  GFM updater: brings the mission system on this computer up to date from GitHub, safely.

  In plain words:
    Check   Asks GitHub whether there are new changes ("git fetch") and writes what is new into the status file.
            Nothing on this computer changes.
    Update  Installs the new changes, but only when a person asked for it (DA Management > Updates, or
            -Mode Update in a terminal). It:
              1. only moves forward ("fast-forward"). It refuses when this computer has changes GitHub does not
                 have, or when files were changed by hand;
              2. runs the quick tests on a copy of the new version first (updater\quick-tests.ps1). If they
                 fail, nothing changes;
              3. checks that the system is healthy now (health.ps1). An update only starts from a healthy system;
              4. saves the way back before touching anything: a database backup, rollback tags of the images,
                 a copy of the portal's pages and the current commit (backups\updater\<time>\);
              5. installs: the new code, new database migrations in order (each followed by 019), rebuilds of
                 portal-api and DA Management, a Slidev restart and the portal pages (portal\deploy.ps1), each
                 only when the update changed it;
              6. runs health.ps1 again. If it does not pass, it puts the previous version back by itself.
    Watch   Keeps running (Task Scheduler starts it, see register-task.ps1). Every few seconds it looks for a
            request that DA Management's Updates page left in updater\requests, and every few hours it checks
            GitHub by itself. It never updates on its own.
    Status  Prints what the status file says.

  DA Management never runs git or a shell. It only leaves a small request file; this script reads a few fields
  from it (what to do, which version, who asked), checks each one, and ignores everything else. Programs are
  always started with a fixed list of arguments, never through a shell.

  Everything is written to updater\logs\updater-<year>-<month>.log. Passwords and tokens are never written: the
  script reads no .env file, and any address with a password in it is shown as ***.

  Setup, settings and rollback by hand: docs/handoff/round7/updater.md.
#>
[CmdletBinding()]
param(
    [ValidateSet('Check', 'Update', 'Watch', 'Status')]
    [string]$Mode = 'Check',
    # The folder of the mission system's code (the Git working tree), by default the folder above this one.
    [string]$RepoRoot = '',
    # -Mode Update without the typed question (for a person who already read the list of changes).
    [switch]$Confirmed,
    # Load the functions only (used by the tests).
    [switch]$NoRun
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------------------------------------------
# Fixed names. They are the live ones (docs/handoff/08_INFRASTRUCTURE_AND_DEPLOYMENT.md).
# ---------------------------------------------------------------------------------------------------------------
$script:DatabaseContainer = 'gfm-beta-supabase-db-1'
# Settings (GFM_PORTAL_CONTAINER, GFM_SLIDEV_CONTAINER, also read by the compose files); the defaults are this server's.
$script:PortalContainer = if ($env:GFM_PORTAL_CONTAINER) { $env:GFM_PORTAL_CONTAINER } else { 'portal-ydpgd5zwrjrvz5aa188sa60u' }
$script:SlidevContainer = if ($env:GFM_SLIDEV_CONTAINER) { $env:GFM_SLIDEV_CONTAINER } else { 'slidev-j5iyrpjbsssqlilqhw9axugx' }
# Every image a rebuild replaces, and the name its rollback copy gets (the same names the deploy logs use).
$script:Images = @(
    @{ Image = 'gfm-portal-portal-api'; Rollback = 'portal-api-rollback' },
    @{ Image = 'gfm-portal-portal-reminders'; Rollback = 'portal-reminders-rollback' },
    @{ Image = 'roster-importer-roster-importer'; Rollback = 'roster-importer-rollback' }
)
# The settings a person may change in updater\settings.json (see settings.example.json).
# Track 'branch' follows the newest commit of Remote/Branch (the Frankfurt way). Track 'tags' follows the newest release tag vX.Y.Z of Remote
# (the way new missions follow the public releases; updater/gfm-updater.sh uses the same rule).
$script:DefaultSettings = [ordered]@{ Remote = 'origin'; Branch = 'main'; Track = 'branch'; CheckEveryHours = 6 }
# A request from DA Management is a few lines. Anything bigger is not one of ours.
$script:MaxRequestBytes = 4096
# Roles that may ask for an update (the managers: AP, President, Data Analyst). Only used for the log.
$script:ManagerRoles = @('AP', 'PRESIDENT', 'DATA_ADMIN')
# The migration that removes public rights again; it runs after every migration (as every deploy did).
$script:RightsCheck = 'portal-api/migrations/019_restrict_public_functions.sql'
# A migration whose header says this is never installed by the updater: a person installs it.
$script:ByHandMarker = 'updater: install by hand'
# How long the health check may take to come back after an update (tries x seconds).
$script:HealthTries = 6
$script:HealthPause = 30

$script:Utf8 = New-Object System.Text.UTF8Encoding $false
$script:PowerShellExe = (Get-Process -Id $PID).Path
# git prints commit titles in UTF-8; read them as UTF-8 so umlauts survive (there may be no console at all).
try { [Console]::OutputEncoding = $script:Utf8 } catch { }

# ---------------------------------------------------------------------------------------------------------------
# Start-up: folders, settings, logging.
# ---------------------------------------------------------------------------------------------------------------
function Initialize-Updater([string]$Root) {
    $script:Repo = (Resolve-Path -LiteralPath $Root).Path
    $updaterDir = Join-Path $script:Repo 'updater'
    $script:Paths = @{
        Settings = Join-Path $updaterDir 'settings.json'
        Requests = Join-Path $updaterDir 'requests'   # DA Management writes here (and nowhere else)
        Status   = Join-Path $updaterDir 'status'     # only this script writes here; DA Management reads it
        Logs     = Join-Path $updaterDir 'logs'
        Backups  = Join-Path (Join-Path $script:Repo 'backups') 'updater'
    }
    foreach ($folder in 'Requests', 'Status', 'Logs', 'Backups') {
        New-Item -ItemType Directory -Force -Path $script:Paths[$folder] | Out-Null
    }
    $script:RequestFile = Join-Path $script:Paths.Requests 'request.json'
    $script:StatusFile = Join-Path $script:Paths.Status 'status.json'
    try { $script:Settings = Read-Settings }
    catch {
        # The scheduled task runs in a hidden window, so without these lines nobody could see why it stops: the log
        # says what is wrong, and the Updates page says that the settings need a look.
        Write-Log "The updater cannot start: $($_.Exception.Message)"
        Save-Status @{ settings_problem = $true }
        throw
    }
    $script:StatusData = Read-Status
    if ($script:StatusData['settings_problem']) { Save-Status @{ settings_problem = $false } }
    # Git must never stop and wait for a password: Task Scheduler has no window to type it in.
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'
}

function Read-Settings {
    $settings = [ordered]@{}
    foreach ($key in $script:DefaultSettings.Keys) { $settings[$key] = $script:DefaultSettings[$key] }
    if (Test-Path -LiteralPath $script:Paths.Settings) {
        $saved = [IO.File]::ReadAllText($script:Paths.Settings) | ConvertFrom-Json
        foreach ($key in @($settings.Keys)) {
            if ($saved.PSObject.Properties.Name -contains $key) { $settings[$key] = $saved.$key }
        }
    }
    # The remote and branch names become git arguments, so only plain names are accepted.
    if ("$($settings.Remote)" -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "updater\settings.json: Remote must be a plain name like origin (it is '$($settings.Remote)')."
    }
    if ("$($settings.Branch)" -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or "$($settings.Branch)" -match '\.\.|//|/$|\.lock$') {
        throw "updater\settings.json: Branch must be a plain branch name like main (it is '$($settings.Branch)')."
    }
    if ("$($settings.Track)" -cnotin @('branch', 'tags')) {
        throw "updater\settings.json: Track must be branch or tags (it is '$($settings.Track)')."
    }
    $settings.CheckEveryHours = [double]$settings.CheckEveryHours
    if ($settings.CheckEveryHours -lt 0.25) { $settings.CheckEveryHours = 0.25 }
    return $settings
}

# Hides passwords and tokens in any text before it reaches the log or the status file: a web address with a
# name and password in it (https://name:secret@github.com), GitHub tokens and signed web tokens become ***.
function Protect-Text([string]$Text) {
    $Text = $Text -replace '(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@', '$1***@'
    $Text = $Text -replace '\b(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})', '***'
    $Text = $Text -replace '\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '***'
    return $Text
}

function Get-Now { return (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz') }

function Write-Log([string]$Message) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), (Protect-Text $Message)
    $script:LogFile = Join-Path $script:Paths.Logs ('updater-{0}.log' -f (Get-Date -Format 'yyyy-MM'))
    [IO.File]::AppendAllText($script:LogFile, $line + [Environment]::NewLine, $script:Utf8)
    Write-Host $line
}

# ---------------------------------------------------------------------------------------------------------------
# Running programs (git, docker, powershell). Always a fixed list of arguments and never a shell, so no text
# from anywhere can turn into a command.
# ---------------------------------------------------------------------------------------------------------------
function Invoke-Native {
    param([string]$Program, [string[]]$Arguments, [switch]$Quiet)
    # Windows PowerShell 5.1 turns anything a program writes to stderr into an error; with 'Stop' that would end
    # the script even when the program worked. So: 'Continue' here, and success is only the exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        $output = @(& $Program @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if (-not $Quiet) {
        foreach ($line in $output) { if ($line.Trim()) { Write-Log "    $line" } }
    }
    return [pscustomobject]@{ Code = $code; Output = $output }
}

function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFail, [switch]$Quiet)
    $result = Invoke-Native -Program 'git' -Arguments (@('-C', $script:Repo) + $Arguments) -Quiet:$Quiet
    if ($result.Code -ne 0 -and -not $AllowFail) {
        $last = ($result.Output | Select-Object -Last 3) -join ' '
        throw (Protect-Text "git $($Arguments[0]) did not work (exit code $($result.Code)): $last")
    }
    return $result
}

# Runs a step that must work (docker, a script). Throws with a plain message when it does not.
function Invoke-Step {
    param([string]$What, [string]$Program, [string[]]$Arguments)
    Write-Log "  $What"
    $result = Invoke-Native -Program $Program -Arguments $Arguments
    if ($result.Code -ne 0) { throw "$What did not work (exit code $($result.Code))." }
}

function Invoke-Script([string]$What, [string]$Path, [string[]]$Arguments = @()) {
    Invoke-Step $What $script:PowerShellExe (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Path) + $Arguments)
}

# ---------------------------------------------------------------------------------------------------------------
# The status file: what DA Management's Updates page shows. Written whole, through a temporary file, so the page
# never reads half a file.
# ---------------------------------------------------------------------------------------------------------------
function Read-Status {
    $status = [ordered]@{}
    if (Test-Path -LiteralPath $script:StatusFile) {
        try {
            $saved = [IO.File]::ReadAllText($script:StatusFile) | ConvertFrom-Json
            foreach ($property in $saved.PSObject.Properties) { $status[$property.Name] = $property.Value }
        }
        catch { Write-Log 'The old status file could not be read; starting a new one.' }
    }
    return $status
}

function Save-Status([hashtable]$Changes = @{}) {
    # Start from what is on disk, not from an older copy in memory: a person may run the updater by hand while the
    # watcher runs, and neither may undo what the other wrote.
    $script:StatusData = Read-Status
    foreach ($key in $Changes.Keys) { $script:StatusData[$key] = $Changes[$key] }
    $script:StatusData['schema'] = 1
    $script:StatusData['updater_seen_at'] = Get-Now
    $json = Protect-Text ($script:StatusData | ConvertTo-Json -Depth 8)
    $temporary = "$($script:StatusFile).tmp"
    [IO.File]::WriteAllText($temporary, $json, $script:Utf8)
    Move-Item -LiteralPath $temporary -Destination $script:StatusFile -Force
}

function Set-State([string]$State, [string]$Step = '') {
    Save-Status @{ state = $State; step = $Step }
}

# ---------------------------------------------------------------------------------------------------------------
# Looking at the code: versions, what is new, what an update would do.
# ---------------------------------------------------------------------------------------------------------------
$script:Separator = [string][char]0x1f
$script:VersionFormat = '--format=%H%x1f%cI%x1f%s'

function ConvertTo-Version([string]$Line) {
    $parts = $Line -split $script:Separator
    return [ordered]@{ commit = $parts[0]; short = $parts[0].Substring(0, 7); date = $parts[1]; subject = $parts[2] }
}

function Get-Version([string]$Revision) {
    $result = Invoke-Git -Arguments @('log', '-1', $script:VersionFormat, $Revision) -Quiet
    return ConvertTo-Version ($result.Output -join '')
}

function Get-CurrentBranch {
    $result = Invoke-Git -Arguments @('symbolic-ref', '--quiet', '--short', 'HEAD') -AllowFail -Quiet
    if ($result.Code -ne 0) { return '' }
    return ($result.Output -join '').Trim()
}

function Get-CommitCount([string]$Range) {
    return [int]((Invoke-Git -Arguments @('rev-list', '--count', $Range) -Quiet).Output -join '').Trim()
}

function Get-NewChanges([string]$From, [string]$To) {
    $result = Invoke-Git -Arguments @('log', '--max-count=100', $script:VersionFormat, "$From..$To") -Quiet
    foreach ($line in $result.Output) { if ($line.Trim()) { ConvertTo-Version $line } }
}

function Get-ChangedFiles([string]$From, [string]$To, [string]$Filter) {
    return @((Invoke-Git -Arguments @('diff', '--name-only', "--diff-filter=$Filter", $From, $To) -Quiet).Output |
        Where-Object { $_.Trim() })
}

# Files changed by hand and not saved in Git (new files that Git does not know are fine: an update never
# touches them, and git refuses by itself if an update would overwrite one).
function Test-TreeClean {
    $result = Invoke-Git -Arguments @('status', '--porcelain', '--untracked-files=no') -Quiet
    return -not ($result.Output | Where-Object { $_.Trim() })
}

# New migrations of an update, in the order they must run. Rollback files are not migrations.
function Get-NewMigrations([string]$From, [string]$To) {
    return @(Get-ChangedFiles $From $To 'A' |
        Where-Object { $_ -match '^portal-api/migrations/\d{3}_[A-Za-z0-9_]+\.sql$' -and $_ -notmatch '_rollback\.sql$' } |
        Sort-Object)
}

# The header of a migration is its comment lines before BEGIN. It names who runs it ("psql -U postgres" or
# "psql -U supabase_admin", supabase_admin when it says nothing) and may say that a person installs it by hand.
function Get-MigrationHeader([string]$Text) {
    $header = @()
    foreach ($line in ($Text -split "`n")) {
        if ($line -match '^\s*BEGIN\b') { break }
        if ($line -match '^\s*--') { $header += $line }
    }
    return $header -join "`n"
}

function Get-MigrationUser([string]$Header) {
    if ($Header -match 'psql -U (postgres|supabase_admin)\b') { return $Matches[1] }
    return 'supabase_admin'
}

function Get-FileAt([string]$Commit, [string]$Path) {
    return ((Invoke-Git -Arguments @('show', "${Commit}:$Path") -Quiet).Output -join "`n")
}

# Which running parts an update renews, from the folders it changes (tests and docs need nothing).
function Get-PartsToRenew([string[]]$ChangedFiles) {
    $parts = @()
    $code = @($ChangedFiles | Where-Object { $_ -notmatch '^[^/]+/tests/' })
    if ($code | Where-Object { $_ -match '^portal-api/' -and $_ -notmatch '^portal-api/migrations/' }) { $parts += 'portal-api' }
    if ($code | Where-Object { $_ -match '^roster-importer/' }) { $parts += 'da-management' }
    if ($code | Where-Object { $_ -match '^slidev/' }) { $parts += 'slidev' }
    if ($code | Where-Object { $_ -match '^portal/' }) { $parts += 'portal' }
    return $parts
}

# Folders an update changes that the updater does not install (for example supabase or nightly-backup): a
# person reads the update's notes and installs them. The page lists them. (docs and ops-tests need no install.)
function Get-OtherParts([string[]]$ChangedFiles) {
    $handled = @('docs', 'ops-tests', 'updater', 'portal', 'portal-api', 'roster-importer', 'slidev')
    $folders = $ChangedFiles | Where-Object { $_ -match '/' } | ForEach-Object { ($_ -split '/')[0] } |
        Where-Object { $handled -notcontains $_ } | Sort-Object -Unique
    return @($folders)
}

# Asks GitHub for news (git fetch) and works out what an update would do. Changes nothing in the code.
function Get-UpdatePlan {
    $remote = $script:Settings.Remote
    $branch = $script:Settings.Branch
    $plan = [ordered]@{
        result = ''; blocked = ''; can_update = $false; follows = "$remote/$branch"
        current = $null; remote = $null; new_changes = @(); migrations = @(); parts = @(); other_parts = @()
    }
    $plan.current = Get-Version 'HEAD'
    $plan.current['branch'] = Get-CurrentBranch
    $remotes = @((Invoke-Git -Arguments @('remote') -Quiet).Output | ForEach-Object { $_.Trim() })
    if ($remotes -notcontains $remote) {
        Write-Log "This computer has no Git remote called '$remote' yet (one-time setup: docs/handoff/round7/updater.md)."
        $plan.result = 'no_remote'
        return $plan
    }
    $byTags = ($script:Settings.Track -ceq 'tags')
    if ($byTags) { $plan.follows = "$remote (release tags)" }
    Write-Log "Asking GitHub for new changes ($($plan.follows))."
    if ($byTags) { $fetchArgs = @('fetch', '--tags', '--force', $remote) }
    else { $fetchArgs = @('fetch', '--no-tags', $remote, "+refs/heads/${branch}:refs/remotes/$remote/$branch") }
    $fetch = Invoke-Git -Arguments $fetchArgs -AllowFail
    if ($fetch.Code -ne 0) {
        Write-Log 'GitHub could not be reached, or this computer is not signed in to GitHub.'
        $plan.result = 'fetch_failed'
        return $plan
    }
    if ($byTags) {
        # The newest release: a tag exactly like v1.2.3, newest by version number. Other tags are not releases.
        $tag = @((Invoke-Git -Arguments @('tag', '--list', 'v[0-9]*', '--sort=-v:refname') -Quiet).Output |
            ForEach-Object { $_.Trim() } | Where-Object { $_ -cmatch '^v\d+\.\d+\.\d+$' }) | Select-Object -First 1
        if (-not $tag) {
            Write-Log 'There is no release yet.'
            $plan.result = 'up_to_date'
            return $plan
        }
        $plan.follows = "$remote ($tag)"
        $target = ((Invoke-Git -Arguments @('rev-parse', '--verify', "refs/tags/$tag^{commit}") -Quiet).Output -join '').Trim()
    }
    else {
        $target = ((Invoke-Git -Arguments @('rev-parse', '--verify', "refs/remotes/$remote/$branch^{commit}") -Quiet).Output -join '').Trim()
    }
    $plan.remote = Get-Version $target
    $head = $plan.current.commit
    $behind = Get-CommitCount "$head..$target"   # changes GitHub has and this computer not
    $ahead = Get-CommitCount "$target..$head"    # changes this computer has and GitHub not
    if ($behind -eq 0 -and $ahead -eq 0) { $plan.result = 'up_to_date' }
    elseif ($behind -gt 0 -and $ahead -gt 0) { $plan.result = 'diverged' }
    elseif ($ahead -gt 0) { $plan.result = 'local_ahead' }
    else { $plan.result = 'updates' }
    if ($behind -gt 0) {
        $plan.new_changes = @(Get-NewChanges $head $target)
        $plan.migrations = @(Get-NewMigrations $head $target)
        $changed = Get-ChangedFiles $head $target 'ACDMRT'
        $plan.parts = @(Get-PartsToRenew $changed)
        $plan.other_parts = @(Get-OtherParts $changed)
        foreach ($edited in (Get-ChangedFiles $head $target 'M' | Where-Object { $_ -match '^portal-api/migrations/' })) {
            Write-Log "Note: the update edits $edited, which is not run again (a person decides)."
        }
    }
    $plan.blocked = Get-BlockedReason $plan
    $plan.can_update = ($plan.result -eq 'updates' -and -not $plan.blocked)
    Write-Log ("Result: {0}; {1} new change(s){2}." -f $plan.result, @($plan.new_changes).Count, $(if ($plan.blocked) { "; cannot update: $($plan.blocked)" } else { '' }))
    return $plan
}

# Why an update cannot happen now (empty when it can). The page explains each reason in plain words.
function Get-BlockedReason($Plan) {
    if ($Plan.result -eq 'local_ahead' -or $Plan.result -eq 'diverged') { return $Plan.result }
    if ($Plan.result -ne 'updates') { return '' }
    if (-not $Plan.current.branch) { return 'not_on_branch' }
    if (-not (Test-TreeClean)) { return 'changed_by_hand' }
    foreach ($migration in $Plan.migrations) {
        if ((Get-MigrationHeader (Get-FileAt $Plan.remote.commit $migration)) -match [regex]::Escape($script:ByHandMarker)) {
            Write-Log "$migration says it is installed by hand."
            return 'by_hand'
        }
    }
    return ''
}

function Save-CheckResult($Plan) {
    Save-Status @{
        state = 'idle'; step = ''; checked_at = Get-Now; checked_head = $Plan.current.commit
        follows = $Plan.follows; current = $Plan.current; remote = $Plan.remote
        check_result = $Plan.result; blocked = $Plan.blocked; can_update = $Plan.can_update
        new_changes = @($Plan.new_changes); migrations = @($Plan.migrations); other_parts = @($Plan.other_parts)
    }
}

# ---------------------------------------------------------------------------------------------------------------
# Requests from DA Management (updater\requests\request.json). Untrusted: read once, checked field by field.
# ---------------------------------------------------------------------------------------------------------------
function Read-Request {
    if (-not (Test-Path -LiteralPath $script:RequestFile)) { return $null }
    $item = Get-Item -LiteralPath $script:RequestFile -Force
    $text = $null
    $plainFile = -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and -not $item.PSIsContainer
    if ($plainFile -and $item.Length -le $script:MaxRequestBytes) { $text = [IO.File]::ReadAllText($item.FullName) }
    # A request is read once, even a wrong one, so it can never be run twice.
    Remove-Item -LiteralPath $item.FullName -Force -Recurse
    if ($null -eq $text) {
        Write-Log 'A request was ignored: it was not a small plain file.'
        return $null
    }
    return ConvertTo-Request $text
}

function ConvertTo-Request([string]$Text) {
    try { $raw = $Text | ConvertFrom-Json }
    catch { Write-Log 'A request was ignored: it was not readable.'; return $null }
    if ($raw -isnot [System.Management.Automation.PSCustomObject]) {
        Write-Log 'A request was ignored: it was not readable.'
        return $null
    }
    $action = "$($raw.action)"
    if ($action -cne 'check' -and $action -cne 'update') {
        Write-Log 'A request was ignored: it asked for something the updater does not do.'
        return $null
    }
    $role = "$($raw.role)"
    $user = "$($raw.user_id)"
    $askedBy = 'someone'
    if ($script:ManagerRoles -ccontains $role) { $askedBy = $role }
    if ($user -match '^[0-9a-fA-F-]{36}$') { $askedBy = "$askedBy (user $user)" }
    $request = @{ Action = $action; Target = ''; AskedBy = "DA Management, $askedBy" }
    if ($action -ceq 'update') {
        $confirmed = ($raw.confirmed -is [bool]) -and $raw.confirmed
        if ("$($raw.target)" -cnotmatch '^[0-9a-f]{40}$' -or -not $confirmed) {
            Write-Log 'An update request was ignored: it did not name one version, or it was not confirmed.'
            return $null
        }
        $request.Target = "$($raw.target)"
    }
    return $request
}

# Only one check or update at a time, even when a person runs the script by hand while the watcher runs. The lock
# belongs to this code folder (the tests use their own folders, so they never wait for the real updater).
function Get-LockName([string]$Name) {
    $sha = New-Object System.Security.Cryptography.SHA256Managed
    $folder = [BitConverter]::ToString($sha.ComputeHash($script:Utf8.GetBytes($script:Repo.ToLowerInvariant()))).Replace('-', '').Substring(0, 16)
    return "Global\GfmUpdater-$Name-$folder"
}

function Enter-Lock([string]$Name) {
    $mutex = New-Object System.Threading.Mutex($false, (Get-LockName $Name))
    try { $mine = $mutex.WaitOne(0) }
    catch {
        # The last holder stopped without letting go (the computer or the updater stopped): the lock is ours now.
        if ($_.Exception.GetBaseException() -isnot [System.Threading.AbandonedMutexException]) { throw }
        $mine = $true
    }
    if ($mine) { return $mutex }
    $mutex.Dispose()
    return $null
}

function Exit-Lock($Mutex) {
    if ($Mutex) { $Mutex.ReleaseMutex(); $Mutex.Dispose() }
}

function Invoke-Check {
    $lock = Enter-Lock 'Work'
    if (-not $lock) { Write-Log 'The updater is busy with something else; the check waits.'; return $null }
    try {
        Set-State 'checking'
        $plan = Get-UpdatePlan
        Save-CheckResult $plan
        return $plan
    }
    catch {
        Write-Log "The check stopped: $($_.Exception.Message)"
        Save-Status @{ state = 'idle'; step = ''; checked_at = Get-Now; check_result = 'check_failed'; can_update = $false }
        return $null
    }
    finally { Exit-Lock $lock }
}

# ---------------------------------------------------------------------------------------------------------------
# The update itself.
# ---------------------------------------------------------------------------------------------------------------
function Invoke-Update([string]$Target, [string]$AskedBy) {
    $lock = Enter-Lock 'Work'
    if (-not $lock) { Write-Log 'The updater is busy with something else; this update request is not run.'; return }
    $started = Get-Now
    $from = ''
    try {
        Write-Log "=== Update asked for by $AskedBy ==="
        Set-State 'checking'
        $plan = Get-UpdatePlan
        Save-CheckResult $plan
        $from = $plan.current.commit
        if (-not $plan.can_update) {
            $reason = $plan.blocked
            if (-not $reason) { $reason = $plan.result }
            Complete-Update 'refused' $reason $from '' $AskedBy $started
            return
        }
        if ($Target -and $Target -ne $plan.remote.commit) {
            Write-Log 'New changes arrived after the list was shown; nothing is installed. Please look at the list again.'
            Complete-Update 'refused' 'list_changed' $from '' $AskedBy $started
            return
        }
        Install-Update $plan $AskedBy $started
    }
    catch {
        Write-Log "The update stopped before anything was changed: $($_.Exception.Message)"
        Complete-Update 'refused' 'stopped' $from '' $AskedBy $started
    }
    finally { Exit-Lock $lock }
}

function Install-Update($Plan, [string]$AskedBy, [string]$Started) {
    $from = $Plan.current.commit
    $to = $Plan.remote.commit
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Write-Log ("Updating from {0} to {1} ({2} change(s)); new migrations: {3}; renews: {4}." -f $Plan.current.short,
        $Plan.remote.short, @($Plan.new_changes).Count, (Get-ListText $Plan.migrations), (Get-ListText $Plan.parts))

    Set-State 'testing' 'quick_tests'
    if (-not (Invoke-QuickTests $to $stamp)) {
        Complete-Update 'tests_failed' '' $from $to $AskedBy $Started
        return
    }
    Set-State 'updating' 'health_before'
    if (-not (Test-Health)) {
        Write-Log 'The system is not fully healthy now, so the update waits (health.ps1 above says what).'
        Complete-Update 'refused' 'not_healthy' $from $to $AskedBy $Started
        return
    }
    Set-State 'updating' 'rollback_point'
    try { $point = Save-RollbackPoint $Plan $stamp }
    catch {
        Write-Log "The way back could not be saved, so nothing is installed: $($_.Exception.Message)"
        Complete-Update 'refused' 'rollback_point_failed' $from $to $AskedBy $Started
        return
    }
    try {
        Set-State 'updating' 'code'
        Update-Code $point $to
        Set-State 'updating' 'migrations'
        Install-Migrations $point
        Set-State 'updating' 'services'
        Update-Parts $point $Plan.parts
        Set-State 'updating' 'health_after'
        if (-not (Wait-ForHealth)) { throw 'The health check did not pass after the update.' }
    }
    catch {
        Write-Log "The update did not work: $($_.Exception.Message) Putting the previous version back."
        Set-State 'rolling_back' ''
        $back = Undo-Update $point
        if ($back) { Complete-Update 'rolled_back' '' $from $to $AskedBy $Started $point }
        else { Complete-Update 'needs_person' '' $from $to $AskedBy $Started $point }
        return
    }
    Write-Log "Update finished well. The way back stays in $($point.Folder)."
    Complete-Update 'done' '' $from $to $AskedBy $Started $point
}

function Get-ListText($Items) {
    $list = @($Items)
    if ($list.Count -eq 0) { return 'none' }
    return $list -join ', '
}

function Complete-Update([string]$Result, [string]$Reason, [string]$From, [string]$To, [string]$AskedBy, [string]$Started, $Point = $null) {
    $folder = ''
    if ($Point) { $folder = $Point.Folder.Substring($script:Repo.Length).TrimStart('\', '/') }
    $log = ''
    if ($script:LogFile) { $log = $script:LogFile.Substring($script:Repo.Length).TrimStart('\', '/') }
    Write-Log "=== Update result: $Result $Reason ==="
    Save-Status @{
        state = 'idle'; step = ''
        last_update = [ordered]@{
            result = $Result; reason = $Reason; from = $From; to = $To; asked_by = $AskedBy
            started_at = $Started; finished_at = Get-Now; rollback_folder = $folder; log = $log
        }
    }
    # When the code may have changed, show the new state at once (current version, anything newer).
    if ($Point) {
        try { Save-CheckResult (Get-UpdatePlan) } catch { Write-Log "The check after the update stopped: $($_.Exception.Message)" }
    }
}

# The quick tests run on a copy of the new version (never on the live files), with that version's own list of
# tests (updater\quick-tests.ps1). Nothing is installed when they fail.
function Invoke-QuickTests([string]$Commit, [string]$Stamp) {
    $folder = Join-Path $script:Paths.Backups "$Stamp-tests"
    $archive = "$folder.tar"
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    try {
        Write-Log 'Running the quick tests on a copy of the new version.'
        Invoke-Git -Arguments @('archive', '--format=tar', '-o', $archive, $Commit) -Quiet | Out-Null
        Invoke-Step 'Unpacking the copy' (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xf', $archive, '-C', $folder)
        $tests = Join-Path $folder 'updater\quick-tests.ps1'
        if (-not (Test-Path -LiteralPath $tests)) { $tests = Join-Path $script:Repo 'updater\quick-tests.ps1' }
        Invoke-Script 'Quick tests' $tests @('-Root', $folder)
        Write-Log 'The quick tests passed.'
        return $true
    }
    catch {
        Write-Log "The quick tests did not pass, so nothing is installed: $($_.Exception.Message)"
        return $false
    }
    finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
}

function Test-Health {
    Write-Log 'Health check (health.ps1):'
    $result = Invoke-Native -Program $script:PowerShellExe -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $script:Repo 'health.ps1'))
    return ($result.Code -eq 0)
}

# Services need a moment after a restart, so the health check gets a few tries.
function Wait-ForHealth {
    for ($try = 1; $try -le $script:HealthTries; $try++) {
        if (Test-Health) { return $true }
        if ($try -lt $script:HealthTries) {
            Write-Log "Not healthy yet (try $try of $($script:HealthTries)); trying again in $($script:HealthPause) s."
            Start-Sleep -Seconds $script:HealthPause
        }
    }
    return $false
}

# ---------------------------------------------------------------------------------------------------------------
# The way back, saved before anything changes: current commit, database backup, image tags, portal pages.
# ---------------------------------------------------------------------------------------------------------------
function Save-RollbackPoint($Plan, [string]$Stamp) {
    $folder = Join-Path $script:Paths.Backups $Stamp
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $point = @{
        Stamp = $Stamp; Folder = $folder; Head = $Plan.current.commit; Branch = $Plan.current.branch
        Dump = Join-Path (Join-Path $script:Repo 'backups') "beta-pre-update-$Stamp.dump"
        Migrations = @($Plan.migrations); Applied = New-Object System.Collections.ArrayList
        Renewed = New-Object System.Collections.ArrayList; CodeChanged = $false
    }
    Write-Log "Saving the way back in $folder."
    [IO.File]::WriteAllText((Join-Path $folder 'repo-head.txt'), "$($point.Head)`n", $script:Utf8)
    Save-DatabaseBackup $point
    Save-ImageTags $point
    Save-PortalPages $point
    return $point
}

function Save-DatabaseBackup($Point) {
    $inside = "/tmp/gfm-updater-$($Point.Stamp).dump"
    Invoke-Step 'Database backup (pg_dump)' 'docker' @('exec', $script:DatabaseContainer, 'pg_dump', '-U', 'postgres', '-Fc', '-d', 'postgres', '-f', $inside)
    Invoke-Step 'Copying the backup out' 'docker' @('cp', "$($script:DatabaseContainer):$inside", $Point.Dump)
    Invoke-Native -Program 'docker' -Arguments @('exec', $script:DatabaseContainer, 'rm', '-f', $inside) | Out-Null
}

function Save-ImageTags($Point) {
    foreach ($image in $script:Images) {
        Invoke-Step "Rollback tag $($image.Rollback):upd-$($Point.Stamp)" 'docker' @('tag', "$($image.Image):latest", "$($image.Rollback):upd-$($Point.Stamp)")
    }
}

function Save-PortalPages($Point) {
    Invoke-Step 'Copy of the portal pages' 'docker' @('cp', "$($script:PortalContainer):/usr/share/nginx/html", (Join-Path $Point.Folder 'portal-html'))
}

# ---------------------------------------------------------------------------------------------------------------
# Installing.
# ---------------------------------------------------------------------------------------------------------------
function Update-Code($Point, [string]$Target) {
    Write-Log "  New code (git merge --ff-only $Target)"
    $Point.CodeChanged = $true
    Invoke-Git -Arguments @('merge', '--ff-only', $Target) | Out-Null
    $head = ((Invoke-Git -Arguments @('rev-parse', 'HEAD') -Quiet).Output -join '').Trim()
    if ($head -ne $Target) { throw "After the update the code is at $head, not at $Target." }
    # The rollback files of the new migrations exist only in the new version: keep a copy for the way back.
    $rollbackFolder = Join-Path $Point.Folder 'rollback-sql'
    New-Item -ItemType Directory -Force -Path $rollbackFolder | Out-Null
    foreach ($migration in $Point.Migrations) {
        $rollback = Join-Path $script:Repo (($migration -replace '\.sql$', '_rollback.sql') -replace '/', '\')
        if (Test-Path -LiteralPath $rollback) { Copy-Item -LiteralPath $rollback -Destination $rollbackFolder }
    }
}

function Install-Migrations($Point) {
    foreach ($migration in $Point.Migrations) {
        $file = Join-Path $script:Repo ($migration -replace '/', '\')
        $user = Get-MigrationUser (Get-MigrationHeader ([IO.File]::ReadAllText($file)))
        if (-not (Invoke-SqlFile $file $user)) {
            # A migration waits at most 10 s for a lock and then stops, having changed nothing. Once more.
            Write-Log "  $migration did not finish; trying once more in 15 s."
            Start-Sleep -Seconds 15
            if (-not (Invoke-SqlFile $file $user)) { throw "Migration $migration did not work." }
        }
        [void]$Point.Applied.Add($migration)
        Invoke-RightsCheck
    }
}

function Invoke-RightsCheck {
    $rights = Join-Path $script:Repo ($script:RightsCheck -replace '/', '\')
    if (-not (Invoke-SqlFile $rights 'supabase_admin')) { throw 'Migration 019 (the rights check) did not work.' }
}

# Runs one SQL file in the Beta database. The file is copied into the container first (no text through a pipe,
# so umlauts arrive as written), and psql stops at the first error; each migration is one transaction.
function Invoke-SqlFile([string]$File, [string]$User) {
    $name = Split-Path -Leaf $File
    $inside = "/tmp/gfm-updater-$name"
    Write-Log "  Database: $name (as $User)"
    $copy = Invoke-Native -Program 'docker' -Arguments @('cp', $File, "$($script:DatabaseContainer):$inside")
    if ($copy.Code -ne 0) { return $false }
    $run = Invoke-Native -Program 'docker' -Arguments @('exec', $script:DatabaseContainer, 'psql', '-U', $User, '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-f', $inside)
    Invoke-Native -Program 'docker' -Arguments @('exec', $script:DatabaseContainer, 'rm', '-f', $inside) -Quiet | Out-Null
    return ($run.Code -eq 0)
}

function Update-Parts($Point, $Parts) {
    $portalApiCompose = Join-Path $script:Repo 'portal-api\compose.yml'
    $managementCompose = Join-Path $script:Repo 'roster-importer\docker-compose.yml'
    if ($Parts -contains 'portal-api') {
        [void]$Point.Renewed.Add('portal-api')
        Invoke-Step 'Rebuilding portal-api and portal-reminders' 'docker' @('compose', '-p', 'gfm-portal', '-f', $portalApiCompose, 'up', '-d', '--build')
    }
    if ($Parts -contains 'da-management') {
        [void]$Point.Renewed.Add('da-management')
        Invoke-Step 'Rebuilding DA Management' 'docker' @('compose', '-p', 'roster-importer', '-f', $managementCompose, 'up', '-d', '--build', '--no-deps', 'roster-importer')
    }
    if ($Parts -contains 'slidev') {
        [void]$Point.Renewed.Add('slidev')
        Invoke-Step 'Restarting Presentations (Slidev)' 'docker' @('restart', $script:SlidevContainer)
    }
    if ($Parts -contains 'portal') {
        [void]$Point.Renewed.Add('portal')
        Invoke-Script 'Portal pages (portal\deploy.ps1)' (Join-Path $script:Repo 'portal\deploy.ps1')
    }
}

# ---------------------------------------------------------------------------------------------------------------
# Putting the previous version back (after a failed update). Code first, then the database, then health.
# Every step is tried even when one before it did not work; the result says whether all worked.
# ---------------------------------------------------------------------------------------------------------------
function Undo-Update($Point) {
    $allWell = $true
    if ($Point.CodeChanged) {
        $allWell = (Invoke-UndoStep 'Code back to the previous commit' { Invoke-Git -Arguments @('reset', '--hard', $Point.Head) | Out-Null }) -and $allWell
    }
    $allWell = (Invoke-UndoStep 'Services back to the previous images' { Undo-Parts $Point }) -and $allWell
    $allWell = (Invoke-UndoStep 'Database back (rollback files of the new migrations)' { Undo-Migrations $Point }) -and $allWell
    if (-not (Wait-ForHealth)) {
        Write-Log 'After putting the previous version back, the health check still does not pass.'
        $allWell = $false
    }
    if ($allWell) { Write-Log 'The previous version is back and healthy.' }
    else { Write-Log "A person needs to look at this. Everything to go back by hand is in $($Point.Folder) and $($Point.Dump)." }
    return $allWell
}

function Invoke-UndoStep([string]$What, [scriptblock]$Action) {
    Write-Log "Way back: $What"
    try { & $Action | Out-Null; return $true }
    catch { Write-Log "  did not work: $($_.Exception.Message)"; return $false }
}

function Undo-Parts($Point) {
    $stamp = "upd-$($Point.Stamp)"
    if ($Point.Renewed -contains 'portal-api') {
        Invoke-Step 'portal-api image back' 'docker' @('tag', "portal-api-rollback:$stamp", 'gfm-portal-portal-api:latest')
        Invoke-Step 'portal-reminders image back' 'docker' @('tag', "portal-reminders-rollback:$stamp", 'gfm-portal-portal-reminders:latest')
        Invoke-Step 'Starting the previous portal-api' 'docker' @('compose', '-p', 'gfm-portal', '-f', (Join-Path $script:Repo 'portal-api\compose.yml'),
            'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'portal-api', 'portal-reminders')
    }
    if ($Point.Renewed -contains 'da-management') {
        Invoke-Step 'DA Management image back' 'docker' @('tag', "roster-importer-rollback:$stamp", 'roster-importer-roster-importer:latest')
        Invoke-Step 'Starting the previous DA Management' 'docker' @('compose', '-p', 'roster-importer', '-f', (Join-Path $script:Repo 'roster-importer\docker-compose.yml'),
            'up', '-d', '--no-build', '--no-deps', '--force-recreate', 'roster-importer')
    }
    if ($Point.Renewed -contains 'slidev') {
        Invoke-Step 'Restarting Presentations with the previous code' 'docker' @('restart', $script:SlidevContainer)
    }
    if ($Point.Renewed -contains 'portal') {
        Invoke-Step 'Portal pages back' 'docker' @('cp', ((Join-Path $Point.Folder 'portal-html') + '/.'), "$($script:PortalContainer):/usr/share/nginx/html")
        Invoke-Step 'Portal reload' 'docker' @('exec', $script:PortalContainer, 'nginx', '-s', 'reload')
    }
}

# The migrations this update applied are undone newest first, each with its own rollback file, then 019.
# They ran minutes ago, so their rollback only takes back what they added.
function Undo-Migrations($Point) {
    $applied = @($Point.Applied)
    [array]::Reverse($applied)
    foreach ($migration in $applied) {
        $name = (Split-Path -Leaf $migration) -replace '\.sql$', '_rollback.sql'
        $file = Join-Path (Join-Path $Point.Folder 'rollback-sql') $name
        if (-not (Test-Path -LiteralPath $file)) { throw "$migration has no rollback file; the database stays as it is." }
        $user = Get-MigrationUser (Get-MigrationHeader ([IO.File]::ReadAllText($file)))
        if (-not (Invoke-SqlFile $file $user)) { throw "The rollback of $migration did not work." }
        Invoke-RightsCheck
    }
}

# ---------------------------------------------------------------------------------------------------------------
# Watching (what Task Scheduler runs).
# ---------------------------------------------------------------------------------------------------------------
function Invoke-Request($Request) {
    if ($Request.Action -eq 'check') {
        Write-Log "Check asked for by $($Request.AskedBy)."
        Invoke-Check | Out-Null
    }
    else { Invoke-Update $Request.Target $Request.AskedBy }
}

# After a restart of the computer in the middle of an update (or a check) the status would say "updating" for
# ever. Only called while nobody holds the work lock (Invoke-Heartbeat), so a busy state here really was stopped.
function Repair-InterruptedState {
    $state = (Read-Status)['state']
    if ($state -in @('testing', 'updating', 'rolling_back')) {
        Write-Log 'The last update was interrupted (the computer or the updater stopped). A person should look at the log.'
        Save-Status @{
            state = 'idle'; step = ''
            last_update = [ordered]@{ result = 'needs_person'; reason = 'interrupted'; finished_at = Get-Now; log = '' }
        }
    }
    elseif ($state -eq 'checking') {
        Save-Status @{ state = 'idle'; step = ''; check_result = 'check_failed'; can_update = $false }
    }
}

# The version on this computer can change without the updater (a person deploying by hand). Then the last
# check no longer fits: it is cleared, and the page asks for a new check.
function Update-Heartbeat {
    $current = Get-Version 'HEAD'
    $current['branch'] = Get-CurrentBranch
    $changes = @{ current = $current }
    $checkedHead = (Read-Status)['checked_head']
    if ($checkedHead -and $checkedHead -ne $current.commit) {
        $changes += @{ check_result = ''; can_update = $false; new_changes = @(); checked_head = '' }
    }
    Save-Status $changes
}

# Once a minute the watcher writes that it is alive (and repairs a state left by a stopped update). It does this
# only while no check or update runs, here or in a terminal: the one at work owns the status file until it is done.
function Invoke-Heartbeat {
    $lock = Enter-Lock 'Work'
    if (-not $lock) { return }
    try {
        Repair-InterruptedState
        Update-Heartbeat
    }
    finally { Exit-Lock $lock }
}

function Start-Watching {
    $watch = Enter-Lock 'Watch'
    if (-not $watch) { Write-Host 'The updater is already watching (another window or the scheduled task).'; return }
    try {
        Write-Log "The updater watches $($script:Paths.Requests) (follows $($script:Settings.Remote)/$($script:Settings.Branch), checks every $($script:Settings.CheckEveryHours) h)."
        Invoke-Heartbeat
        $nextCheck = Get-Date
        $nextBeat = (Get-Date).AddMinutes(1)
        while ($true) {
            try {
                $request = Read-Request
                if ($request) {
                    Invoke-Request $request
                    # A finished update may have brought a new version of this script. Stop, so Task Scheduler
                    # starts the new one (within 5 minutes; register-task.ps1).
                    if ($request.Action -eq 'update' -and $script:StatusData['last_update'].result -eq 'done') {
                        Write-Log 'Stopping so that the new version of the updater starts.'
                        return
                    }
                    $nextBeat = (Get-Date).AddMinutes(1)
                }
                elseif ((Get-Date) -ge $nextCheck) {
                    Invoke-Check | Out-Null
                    $nextCheck = (Get-Date).AddHours($script:Settings.CheckEveryHours)
                    $nextBeat = (Get-Date).AddMinutes(1)
                }
                elseif ((Get-Date) -ge $nextBeat) {
                    Invoke-Heartbeat
                    $nextBeat = (Get-Date).AddMinutes(1)
                }
            }
            catch { Write-Log "Something went wrong ($($_.Exception.Message)); the updater keeps watching." }
            Start-Sleep -Seconds 5
        }
    }
    finally { Exit-Lock $watch }
}

# ---------------------------------------------------------------------------------------------------------------
# By hand in a terminal.
# ---------------------------------------------------------------------------------------------------------------
function Show-Plan($Plan) {
    Write-Host ''
    Write-Host ("This computer: {0}  {1}  {2}" -f $Plan.current.short, $Plan.current.date, $Plan.current.subject)
    Write-Host ("Follows: {0}   Result: {1}" -f $Plan.follows, $Plan.result)
    foreach ($change in $Plan.new_changes) { Write-Host ("  new: {0}  {1}  {2}" -f $change.short, $change.date, $change.subject) }
    if ($Plan.blocked) { Write-Host "Cannot update now: $($Plan.blocked) (docs/handoff/round7/updater.md explains each reason)." }
    Write-Host ''
}

function Start-UpdateByHand {
    $plan = Invoke-Check
    if (-not $plan) { return }
    Show-Plan $plan
    if (-not $plan.can_update) { return }
    if (-not $Confirmed) {
        $answer = Read-Host 'Type UPDATE to install these changes'
        if ($answer.Trim() -cne 'UPDATE') { Write-Host 'Nothing was installed.'; return }
    }
    Invoke-Update $plan.remote.commit 'a person in a terminal'
}

function Show-Status {
    if (-not (Test-Path -LiteralPath $script:StatusFile)) { Write-Host 'No status yet: run -Mode Check.'; return }
    Write-Host ([IO.File]::ReadAllText($script:StatusFile))
}

if ($NoRun) { return }
# (Worked out here and not in param(): Windows PowerShell 5.1 does not always know $PSScriptRoot there.)
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
Initialize-Updater $RepoRoot
switch ($Mode) {
    'Check' { $plan = Invoke-Check; if ($plan) { Show-Plan $plan } }
    'Update' { Start-UpdateByHand }
    'Watch' { Start-Watching }
    'Status' { Show-Status }
}
