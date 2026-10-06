<#
  Tests of health.ps1, with stand-ins for docker and for the web. Nothing real is asked: no container, no address.

  What is checked: the "Nightly backup" row in every state it can be in, one web check (OK, a wrong status, a
  wrong answer, no answer), when the DataEase and deck-address rows are checked or SKIPPED, and the order of all
  rows together.

  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File ops-tests\test-health.ps1
  Exit code 0 means every check passed. Works in Windows PowerShell 5.1 and PowerShell 7.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $repo 'health.ps1') -NoRun   # the health check's functions, without running it

$script:Passes = 0
$script:Failures = 0
function Assert-That([bool]$Condition, [string]$Name) {
    if ($Condition) { $script:Passes++; [Console]::Out.WriteLine("PASS  $Name") }
    else { $script:Failures++; [Console]::Out.WriteLine("FAIL  $Name") }
}

# ---------------------------------------------------------------------------------------------------------------
# 1. The nightly backup row.
# ---------------------------------------------------------------------------------------------------------------
$now = Get-Date '2026-09-29T10:00:00'
$running = @{ Ok = $true; Output = @('true|2026-09-28T08:00:00.123456789Z') }
$runningNew = @{ Ok = $true; Output = @(('true|' + $now.ToUniversalTime().AddHours(-2).ToString('yyyy-MM-ddTHH:mm:ss') + '.5Z')) }
$runningOld = @{ Ok = $true; Output = @(('true|' + $now.ToUniversalTime().AddHours(-30).ToString('yyyy-MM-ddTHH:mm:ss') + 'Z')) }
$stopped = @{ Ok = $true; Output = @('false|2026-09-28T08:00:00Z') }
$noContainer = @{ Ok = $false; Output = @() }
function New-Dump([double]$HoursOld) {
    return [pscustomobject]@{ Name = 'beta-20260929-0230.dump'; LastWriteTime = $now.AddHours(-$HoursOld); Length = 4.5MB }
}

$verdict = Get-NightlyBackupVerdict $noContainer $null $null $now
Assert-That ($verdict.Ok -and $verdict.Result -eq 'SKIPPED (not deployed: no gfm-backup container)') 'no container, no files: SKIPPED, not a failure'
$verdict = Get-NightlyBackupVerdict $noContainer (New-Dump 3) $null $now
Assert-That (-not $verdict.Ok -and $verdict.Result -eq 'FAIL: no gfm-backup container (docs/handoff/round6/ops.md)') 'files without their container: FAIL'
$verdict = Get-NightlyBackupVerdict $stopped (New-Dump 3) 'OK 2026-09-29T02:30:05+02:00' $now
Assert-That (-not $verdict.Ok -and $verdict.Result -eq 'FAIL: gfm-backup is not running') 'a stopped container: FAIL'
$verdict = Get-NightlyBackupVerdict $running (New-Dump 27.4) 'OK 2026-09-28T02:30:05+02:00' $now
Assert-That (-not $verdict.Ok -and $verdict.Result -eq 'FAIL: the newest backup beta-20260929-0230.dump is 27 hours old') 'a backup 27 hours old: FAIL with its age'
$verdict = Get-NightlyBackupVerdict $running (New-Dump 3) 'FAILED 2026-09-29T02:31:00+02:00: production, hook dataease' $now
Assert-That (-not $verdict.Ok -and $verdict.Result -eq 'FAIL: last night: production, hook dataease (backups\nightly\nightly.log)') 'a failed night: FAIL with the parts that failed'
$verdict = Get-NightlyBackupVerdict $running (New-Dump 7.6) 'OK 2026-09-29T02:30:05+02:00' $now
$expected = 'OK (beta-20260929-0230.dump, {0:N1} MB, {1:N0} h old)' -f 4.5, 7.6
Assert-That ($verdict.Ok -and $verdict.Result -eq $expected) "a fresh backup and a good night: $expected"
$verdict = Get-NightlyBackupVerdict $runningNew $null $null $now
Assert-That ($verdict.Ok -and $verdict.Result -eq 'waiting (the first backup is made at 02:30)') 'deployed 2 hours ago, no backup yet: waiting, not a failure'
$verdict = Get-NightlyBackupVerdict $runningOld $null $null $now
Assert-That (-not $verdict.Ok -and $verdict.Result -eq 'FAIL: no backup yet, 26 hours after the deploy (backups\nightly\nightly.log)') 'deployed 30 hours ago, still no backup: FAIL'

# Which file counts: the newest beta-YYYYMMDD-HHMM.dump; not the roles file, not a half-written or other file.
$folder = Join-Path ([IO.Path]::GetTempPath()) ('gfm-health-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$files = [ordered]@{
    'beta-20260927-0230.dump' = -50; 'beta-20260928-0230.dump' = -30; 'beta-by-hand.dump' = -1
    'beta-20260929-0230.dump.partial' = -1; 'production-20260929-0230.dump' = -2; 'beta-roles-20260929-0230.sql.gz' = -2
}
foreach ($name in $files.Keys) {
    $path = Join-Path $folder $name
    [IO.File]::WriteAllText($path, 'x')
    (Get-Item -LiteralPath $path).LastWriteTime = (Get-Date).AddHours($files[$name])
}
[IO.File]::WriteAllText((Join-Path $folder 'last-run.txt'), "FAILED 2026-09-29T02:31:00+02:00: beta`nsecond line")
function Invoke-Docker([string[]]$Arguments) { $script:DockerAsked += , ($Arguments -join ' '); return $script:DockerAnswers[$Arguments[0] + ' ' + $Arguments[1]] }
$script:DockerAsked = @()
$script:DockerAnswers = @{ "inspect gfm-backup" = $running }
$facts = Get-NightlyBackupFacts $folder
Assert-That ($facts.LatestBackup.Name -eq 'beta-20260928-0230.dump') 'the newest beta-YYYYMMDD-HHMM.dump counts; other files do not'
Assert-That ($facts.LastNight -eq 'FAILED 2026-09-29T02:31:00+02:00: beta') 'the first line of last-run.txt is read'
Assert-That ($script:DockerAsked -contains 'inspect gfm-backup --format {{.State.Running}}|{{.Created}}') 'the container is asked for its state and start time'

# ---------------------------------------------------------------------------------------------------------------
# 2. One web check.
# ---------------------------------------------------------------------------------------------------------------
function Get-HttpResult([string]$Uri) {
    $answer = $script:WebAnswers[$Uri]
    if ($answer -is [string]) { throw $answer }
    return $answer
}
$script:WebAnswers = @{
    'http://ok' = @{ Status = 200; Content = '{"dataease":"signed-in"}' }
    'http://locked' = @{ Status = 401; Content = '' }
    'http://other-page' = @{ Status = 200; Content = '<html>the portal</html>' }
    'http://down' = 'Unable to connect to the remote server'
}
$answer = Invoke-WebCheck @{ Name = 'A'; Uri = 'http://ok'; Expected = @(200); Body = '"dataease"\s*:\s*"signed-in"' }
Assert-That ($answer.Ok -and $answer.Row.Result -eq 'OK' -and $answer.Row.Status -eq 200) 'the expected status and answer: OK'
$answer = Invoke-WebCheck @{ Name = 'B'; Uri = 'http://locked'; Expected = @(200) }
Assert-That (-not $answer.Ok -and $answer.Row.Result -eq 'FAIL' -and $answer.Row.Status -eq 401) 'another status: FAIL with the status'
$answer = Invoke-WebCheck @{ Name = 'C'; Uri = 'http://locked'; Expected = @(200, 401) }
Assert-That ($answer.Ok) 'a locked door counts when it is expected'
$answer = Invoke-WebCheck @{ Name = 'D'; Uri = 'http://other-page'; Expected = @(200); Body = '"deck-address"' }
Assert-That (-not $answer.Ok -and $answer.Row.Result -eq 'FAIL (unexpected answer)') 'the right status with the wrong page: FAIL (unexpected answer)'
$answer = Invoke-WebCheck @{ Name = 'E'; Uri = 'http://down'; Expected = @(200) }
Assert-That (-not $answer.Ok -and $answer.Row.Result -eq 'FAIL: Unable to connect to the remote server' -and $answer.Row.Status -eq '-') 'no answer: FAIL with the reason'
Assert-That ((@($answer.Row.PSObject.Properties.Name) -join ',') -eq 'Service,Status,Result') 'a row has exactly the three columns Service, Status, Result'

# ---------------------------------------------------------------------------------------------------------------
# 3. All rows: which are checked, which are SKIPPED, and their order.
# ---------------------------------------------------------------------------------------------------------------
$script:WebAnswers = @{}
foreach ($check in ($checks + (Get-DataEaseChecks) + (Get-DeckAddressChecks))) {
    $script:WebAnswers[$check.Uri] = @{ Status = $check.Expected[0]; Content = '"dataease":"signed-in" "deck-address"' }
}
$emptyFolder = Join-Path $folder 'empty'
New-Item -ItemType Directory -Force -Path $emptyFolder | Out-Null

$script:DockerAnswers = @{ 'inspect gfm-backup' = $noContainer; 'container inspect' = @{ Ok = $false; Output = @() }; 'port slidev-j5iyrpjbsssqlilqhw9axugx' = @{ Ok = $true; Output = @('0.0.0.0:3041') } }
$health = Get-HealthRows $emptyFolder
$names = @($health.Rows | ForEach-Object { $_.Service })
Assert-That (-not $health.Failed) 'nothing deployed yet and every address answering: no failure'
Assert-That ($names[0] -eq 'Nightly backup' -and $names[1] -eq 'Beta Studio' -and $names[7] -eq 'Portal Auth Boundary') 'the backup row first, then the addresses in their order'
Assert-That (($names[8..13] -join ',') -eq 'Dashboards (DataEase),DataEase Sign-in Boundary,Presentation Decks (8089),Deck Pass Boundary,Presentations Request Guard,Deck Numbers Guard') 'then the rows of parts not deployed yet'
Assert-That ((@($health.Rows | Select-Object -Skip 8 | Where-Object { $_.Result -like 'SKIPPED (not deployed:*' }).Count) -eq 6) 'which say SKIPPED'
Assert-That (-not (Test-DeckAddressDeployed)) 'Slidev without port 8089 published: the deck address is not deployed yet'

$script:DockerAnswers = @{ 'inspect gfm-backup' = $noContainer; 'container inspect' = @{ Ok = $true; Output = @('/gfm-dataease') }; 'port slidev-j5iyrpjbsssqlilqhw9axugx' = @{ Ok = $true; Output = @('0.0.0.0:8089', '[::]:8089') } }
$health = Get-HealthRows $emptyFolder
$rows = @($health.Rows)
Assert-That ($rows.Count -eq 14 -and -not ($rows | Where-Object { $_.Result -like 'SKIPPED*' -and $_.Service -ne 'Nightly backup' })) 'once deployed, the DataEase and deck rows are checked (14 rows)'
Assert-That (($rows[8].Service -eq 'Dashboards (DataEase)') -and ($rows[10].Service -eq 'Presentation Decks (8089)') -and ($rows[13].Result -eq 'OK')) 'in the order DataEase, then the deck address'

$script:WebAnswers['http://127.0.0.1:8088/gfm-gate-health'] = @{ Status = 503; Content = '{"dataease":"not-signed-in"}' }
$health = Get-HealthRows $emptyFolder
Assert-That ($health.Failed -and (@($health.Rows)[8].Result -eq 'FAIL')) 'one failing address turns the whole check to FAIL'

$script:WebAnswers['http://127.0.0.1:8088/gfm-gate-health'] = @{ Status = 200; Content = '"dataease":"signed-in"' }
$script:DockerAnswers['inspect gfm-backup'] = $stopped
$health = Get-HealthRows $emptyFolder
Assert-That ($health.Failed -and (@($health.Rows)[0].Result -eq 'FAIL: gfm-backup is not running')) 'a failing backup row turns the whole check to FAIL'

Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
[Console]::Out.WriteLine("Health tests: $script:Passes passed, $script:Failures did not pass.")
if ($script:Failures) { exit 1 }
exit 0
