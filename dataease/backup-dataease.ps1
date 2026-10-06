<#
Backs up what people build in Dashboards (DataEase): its metadata database (dashboards, charts, datasets, the data
source, DataEase's settings) and its two small file volumes (settings files, pictures uploaded into dashboards).
Nothing else is needed to bring Dashboards back: the numbers themselves stay in the mission database.

Run from the repository root (Windows PowerShell 5.1 or PowerShell 7). DataEase keeps running; the database dump
is one consistent snapshot (InnoDB, --single-transaction).
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/backup-dataease.ps1
    -> backups/dataease-metadata-<yyyyMMdd-HHmmss>.sql.gz and backups/dataease-files-<yyyyMMdd-HHmmss>.tgz
  powershell -NoProfile -ExecutionPolicy Bypass -File dataease/backup-dataease.ps1 -RestoreFrom backups/dataease-metadata-<date>.sql.gz
    -> takes a fresh backup first, stops DataEase and its gate, loads the dump, starts them again. Add
       -FilesFrom backups/dataease-files-<date>.tgz to put the file volumes back too.
Passwords stay inside the containers (MYSQL_ROOT_PASSWORD of gfm-dataease-mysql); nothing secret is printed.
-Name is for a second, throw-away DataEase (tests).
#>
[CmdletBinding()]
param(
    [string]$Name = 'gfm-dataease',
    [string]$OutDir,
    [string]$RestoreFrom,
    [string]$FilesFrom
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $repo 'backups' }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$mysql = "$Name-mysql"

function Invoke-Docker([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @Arguments
        if ($LASTEXITCODE -ne 0) { throw "docker $($Arguments[0]) $($Arguments[1]) failed (exit code $LASTEXITCODE)." }
    }
    finally { $ErrorActionPreference = $previous }
}

# Makes one backup (the metadata dump and the file volumes) and returns the dump's path.
function Save-DataEaseBackup {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $dump = Join-Path $OutDir "dataease-metadata-$stamp.sql.gz"
    $files = Join-Path $OutDir "dataease-files-$stamp.tgz"
    Invoke-Docker @('exec', $mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --databases dataease | gzip > /tmp/dataease-backup.sql.gz && test -s /tmp/dataease-backup.sql.gz')
    Invoke-Docker @('cp', "${mysql}:/tmp/dataease-backup.sql.gz", $dump)
    Invoke-Docker @('exec', $mysql, 'rm', '-f', '/tmp/dataease-backup.sql.gz')
    $dir = (Resolve-Path $OutDir).Path
    Invoke-Docker @('run', '--rm', '--name', "$Name-backup-files", '--memory', '128m', '--network', 'none',
        '-v', "${Name}-conf:/data/conf:ro", '-v', "${Name}-static:/data/static:ro", '-v', "${dir}:/out",
        'node:24-alpine', 'tar', 'czf', "/out/$(Split-Path -Leaf $files)", '-C', '/data', 'conf', 'static')
    foreach ($file in $dump, $files) {
        $size = (Get-Item -LiteralPath $file).Length
        if ($size -lt 100) { throw "$file is too small ($size bytes); the backup did not work." }
        Write-Host ("Saved {0} ({1:N0} KB)." -f $file, ($size / 1KB))
    }
    return $dump
}

if (-not $RestoreFrom) { [void](Save-DataEaseBackup); return }

$source = (Resolve-Path -LiteralPath $RestoreFrom).Path
if ($FilesFrom) { $filesSource = (Resolve-Path -LiteralPath $FilesFrom).Path }
Write-Host 'Taking a backup of the current state first.'
[void](Save-DataEaseBackup)
Write-Host 'Stopping DataEase and its gate (Dashboards show "starting" meanwhile).'
Invoke-Docker @('stop', $Name, "$Name-gate")
try {
    Invoke-Docker @('cp', $source, "${mysql}:/tmp/dataease-restore.sql.gz")
    Invoke-Docker @('exec', $mysql, 'sh', '-c', 'gunzip -c /tmp/dataease-restore.sql.gz | MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot && rm -f /tmp/dataease-restore.sql.gz')
    if ($FilesFrom) {
        $folder = Split-Path -Parent $filesSource
        Invoke-Docker @('run', '--rm', '--name', "$Name-restore-files", '--memory', '128m', '--network', 'none',
            '-v', "${Name}-conf:/data/conf", '-v', "${Name}-static:/data/static", '-v', "${folder}:/in:ro",
            'node:24-alpine', 'sh', '-c', "rm -rf /data/conf/* /data/static/* && tar xzf '/in/$(Split-Path -Leaf $filesSource)' -C /data")
    }
    Write-Host "Restored $source$(if ($FilesFrom) { " and $filesSource" })."
}
finally {
    Invoke-Docker @('start', $Name, "$Name-gate")
    Write-Host 'DataEase is starting again (about a minute).'
}
