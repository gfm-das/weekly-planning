<#
  Tests of dataease/backup-dataease.ps1 (the Dashboards backup and restore), with a stand-in for docker. Nothing real
  is touched: no container is stopped, no database is read. The stand-in writes down every docker command and
  makes the files a real "docker cp" or "tar" would make, in a temporary folder.

  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File ops-tests\test-dataease-backup.ps1
  Exit code 0 means every check passed. Works in Windows PowerShell 5.1 and PowerShell 7.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$backupScript = Join-Path $repo 'dataease\backup-dataease.ps1'

$script:Passes = 0
$script:Failures = 0
function Assert-That([bool]$Condition, [string]$Name) {
    if ($Condition) { $script:Passes++; [Console]::Out.WriteLine("PASS  $Name") }
    else { $script:Failures++; [Console]::Out.WriteLine("FAIL  $Name") }
}
# ---------------------------------------------------------------------------------------------------------------
# The stand-in for docker. "docker cp <container>:<file> <here>" and the tar container make a file of
# $StandIn.FileSize bytes; a command that contains $StandIn.FailOn fails.
# The stand-ins keep what they saw in one shared table, $StandIn: the backup script runs as its own script, where
# "$script:" would mean the backup script's variables, not these.
# ---------------------------------------------------------------------------------------------------------------
$StandIn = @{}
function Reset-StandIn {
    $StandIn.Calls = New-Object System.Collections.ArrayList
    $StandIn.Messages = New-Object System.Collections.ArrayList
    $StandIn.FileSize = 500
    $StandIn.FailOn = ''
}
# The script's own messages are kept, so the tests can look at them.
function Write-Host { param([Parameter(ValueFromRemainingArguments = $true)]$Text) [void]$StandIn.Messages.Add("$Text") }
function New-FileOfSize([string]$Path) { [IO.File]::WriteAllBytes($Path, (New-Object byte[] $StandIn.FileSize)) }
function docker {
    $line = ($args | ForEach-Object { "$_" }) -join ' '
    [void]$StandIn.Calls.Add($line)
    $global:LASTEXITCODE = 0
    if ($StandIn.FailOn -and $line -like "*$($StandIn.FailOn)*") { $global:LASTEXITCODE = 1; return }
    if ($args[0] -eq 'cp' -and "$($args[1])" -like '*:/tmp/dataease-backup.sql.gz') { New-FileOfSize $args[2] }
    if ($args[0] -eq 'run' -and $args -contains 'czf') {
        $out = ($args | Where-Object { "$_" -like '*:/out' } | Select-Object -First 1) -replace ':/out$', ''
        $leaf = Split-Path -Leaf ($args | Where-Object { "$_" -like '/out/*' } | Select-Object -First 1)
        New-FileOfSize (Join-Path $out $leaf)
    }
}

function New-TempFolder {
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('gfm-dataease-backup-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    return $folder
}

# Runs the script with these arguments; returns '' when it worked, else its error message.
function Invoke-BackupScript([hashtable]$Arguments) {
    try { & $backupScript @Arguments | Out-Null; return '' }
    catch { return $_.Exception.Message }
}

# The position of the first docker command that matches a pattern (-1 when there is none).
function Get-CallIndex([string]$Pattern) {
    for ($i = 0; $i -lt $StandIn.Calls.Count; $i++) { if ($StandIn.Calls[$i] -like $Pattern) { return $i } }
    return -1
}

$name = 'gfm-test-standin'
$out = New-TempFolder

# 1. A backup ---------------------------------------------------------------------------------------------------
Reset-StandIn
$problem = Invoke-BackupScript @{ Name = $name; OutDir = $out }
Assert-That ($problem -eq '') "a backup runs to the end ($problem)"
$dumps = @(Get-ChildItem -LiteralPath $out -Filter 'dataease-metadata-*.sql.gz')
$archives = @(Get-ChildItem -LiteralPath $out -Filter 'dataease-files-*.tgz')
Assert-That (($dumps.Count -eq 1) -and ($archives.Count -eq 1)) 'it saves one metadata dump and one files archive'
Assert-That ((Get-CallIndex "exec $name-mysql sh -c *mysqldump*--single-transaction*") -eq 0) 'first it dumps the metadata database in one consistent snapshot'
Assert-That ((Get-CallIndex "cp ${name}-mysql:/tmp/dataease-backup.sql.gz *") -eq 1) 'then it copies the dump out'
Assert-That ((Get-CallIndex "exec $name-mysql rm -f /tmp/dataease-backup.sql.gz") -eq 2) 'and deletes the copy inside the container'
Assert-That ((Get-CallIndex "run --rm * --network none -v ${name}-conf:/data/conf:ro -v ${name}-static:/data/static:ro *") -eq 3) 'the file volumes are read only, without network'
Assert-That (-not ($StandIn.Calls -like 'stop *')) 'a backup stops nothing'
Assert-That (@($StandIn.Messages | Where-Object { $_ -like 'Saved *' }).Count -eq 2) 'it says what it saved'

# 2. A dump that is too small ------------------------------------------------------------------------------------
Reset-StandIn
$StandIn.FileSize = 10
$problem = Invoke-BackupScript @{ Name = $name; OutDir = $out }
Assert-That ($problem -like '*is too small (10 bytes); the backup did not work.') 'an almost empty backup is an error'

# 3. A dump that fails ---------------------------------------------------------------------------------------------
Reset-StandIn
$StandIn.FailOn = 'mysqldump'
$problem = Invoke-BackupScript @{ Name = $name; OutDir = $out }
Assert-That ($problem -eq 'docker exec gfm-test-standin-mysql failed (exit code 1).') 'a failed dump stops it and says which command'
Assert-That ($StandIn.Calls.Count -eq 1) 'and nothing after it runs'

# 4. A restore ----------------------------------------------------------------------------------------------------
$source = Join-Path $out 'dataease-metadata-old.sql.gz'
$files = Join-Path $out 'dataease-files-old.tgz'
[IO.File]::WriteAllText($source, 'old dump')
[IO.File]::WriteAllText($files, 'old files')
Reset-StandIn
$problem = Invoke-BackupScript @{ Name = $name; OutDir = $out; RestoreFrom = $source }
Assert-That ($problem -eq '') "a restore runs to the end ($problem)"
$dumped = Get-CallIndex '*mysqldump*'
$stopped = Get-CallIndex "stop $name $name-gate"
$loaded = Get-CallIndex "exec $name-mysql sh -c gunzip -c /tmp/dataease-restore.sql.gz*"
$started = Get-CallIndex "start $name $name-gate"
Assert-That (($dumped -ge 0) -and ($dumped -lt $stopped)) 'a restore takes a backup of the current state first'
Assert-That (($stopped -lt $loaded) -and ($loaded -lt $started)) 'then stops DataEase and its gate, loads the dump, starts them again'
Assert-That ($started -eq $StandIn.Calls.Count - 1) 'starting them again is the last step'
Assert-That (-not ($StandIn.Calls -like '*restore-files*')) 'without -FilesFrom the file volumes are left alone'

# 5. A restore with the files --------------------------------------------------------------------------------------
Reset-StandIn
$problem = Invoke-BackupScript @{ Name = $name; OutDir = $out; RestoreFrom = $source; FilesFrom = $files }
Assert-That ($problem -eq '') "a restore with -FilesFrom runs to the end ($problem)"
Assert-That ((Get-CallIndex "run --rm --name $name-restore-files * --network none -v ${name}-conf:/data/conf -v ${name}-static:/data/static *") -gt 0) 'with -FilesFrom the file volumes are put back too'
Assert-That ((Get-CallIndex '*restore-files*') -lt (Get-CallIndex "start $name $name-gate")) 'before DataEase starts again'

# 6. A restore that fails -----------------------------------------------------------------------------------------
Reset-StandIn
$StandIn.FailOn = 'gunzip'
$problem = Invoke-BackupScript @{ Name = $name; OutDir = $out; RestoreFrom = $source }
Assert-That ($problem -eq 'docker exec gfm-test-standin-mysql failed (exit code 1).') 'a failed restore is an error'
Assert-That ($StandIn.Calls[$StandIn.Calls.Count - 1] -eq "start $name $name-gate") 'DataEase and its gate are started again even then'

Remove-Item -LiteralPath $out -Recurse -Force -ErrorAction SilentlyContinue
[Console]::Out.WriteLine("DataEase backup tests: $script:Passes passed, $script:Failures did not pass.")
if ($script:Failures) { exit 1 }
exit 0
