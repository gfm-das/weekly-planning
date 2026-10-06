<#
  Proves that portal-api/baseline/000_baseline.sql builds the same database as the live one.

  What it does (nothing live is changed; the live database is only read):
    1. starts a throw-away database container of the same image as the live one (an empty Supabase database);
    2. applies the baseline, then migration 019 (the rights check), then every newer migration (041 and up) each followed by
       019, as supabase_admin;
    3. lists everything that makes up the schema (columns, constraints, indexes, functions, views, policies, triggers,
       row-level security, rights, default rights, sequences; compare.sql) in the new and in the live database;
    4. compares the two lists, ignoring the few known harmless differences below;
    5. checks the starting rows (mission, planning questions) and removes the container.
  It is for a person with Docker, from the repository root:
      powershell -NoProfile -ExecutionPolicy Bypass -File portal-api/baseline/check-baseline.ps1
  Ends with "Baseline check: OK" (exit code 0) or lists the differences (exit code 1).

  Known harmless differences (the live database is not changed to remove them):
    - the retired grafana_readonly role on the public schema (the baseline leaves it out);
    - one check constraint and three views that PostgreSQL writes with an extra bracket or an explicit "AS text"
      after a reload (the same meaning and the same columns).
#>
[CmdletBinding()]
param([string]$LiveContainer = 'gfm-beta-supabase-db-1')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$name = 'gfm-test-baseline'
$image = (docker inspect $LiveContainer --format '{{.Config.Image}}').Trim()
if (-not $image) { throw "Live container $LiveContainer not found." }

function Run-Sql($container, $file, [switch]$Quiet, [string]$User = 'supabase_admin', [string[]]$Extra = @()) {
    $out = docker exec $container psql -U $User -h 127.0.0.1 -d postgres -At -v ON_ERROR_STOP=1 @Extra -f $file 2>&1
    if ($LASTEXITCODE -ne 0) { throw "psql failed in ${container}: $($out | Select-Object -Last 3)" }
    return $out
}

docker rm -f $name 2>&1 | Out-Null
docker run -d --name $name -e POSTGRES_PASSWORD=baseline-check $image | Out-Null
try {
    for ($i = 0; $i -lt 60; $i++) {
        docker exec $name pg_isready -U supabase_admin -h 127.0.0.1 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Start-Sleep 3; break }
        Start-Sleep 2
    }
    docker cp (Join-Path $PSScriptRoot '000_baseline.sql') "${name}:/tmp/base.sql"
    docker cp (Join-Path $repo 'portal-api/migrations/019_restrict_public_functions.sql') "${name}:/tmp/m019.sql"
    docker cp (Join-Path $PSScriptRoot 'compare.sql') "${name}:/tmp/compare.sql"
    docker cp (Join-Path $PSScriptRoot 'compare.sql') "${LiveContainer}:/tmp/gfm-compare.sql"
    Run-Sql $name '/tmp/base.sql' -Extra @('--single-transaction') | Out-Null
    $rights = Run-Sql $name '/tmp/m019.sql'
    if (-not ($rights | Select-String 'COMMIT')) { throw 'The rights check (019) did not end with COMMIT.' }
    # Every migration newer than the baseline (041 and up) is applied in order, each followed by the rights check, like a new install.
    $newer = Get-ChildItem (Join-Path $repo 'portal-api/migrations') -Filter '*.sql' | Where-Object { $_.Name -match '^(\d{3})_' -and [int]$Matches[1] -gt 40 -and $_.Name -notmatch '_rollback\.sql$' } | Sort-Object Name
    foreach ($file in $newer) {
        docker cp $file.FullName "${name}:/tmp/newer.sql"
        Run-Sql $name '/tmp/newer.sql' | Out-Null
        Run-Sql $name '/tmp/m019.sql' | Out-Null
        "Applied after the baseline: $($file.Name)"
    }

    $fresh = Run-Sql $name '/tmp/compare.sql'
    $live = Run-Sql $LiveContainer '/tmp/gfm-compare.sql'
    docker exec $LiveContainer sh -c 'rm -f /tmp/gfm-compare.sql' | Out-Null

    $known = @('^acl schema public ', '^constraint portal\.whiteboards whiteboards_name_length ',
               '^view dashboards\.findechristus_referrals_week ', '^view dashboards\.zone_history_week ', '^view public\.data_upload_week_batches ')
    $isKnown = { param($line) foreach ($pattern in $known) { if ($line -match $pattern) { return $true } } return $false }
    $a = @($live | Where-Object { -not (& $isKnown $_) })
    $b = @($fresh | Where-Object { -not (& $isKnown $_) })
    $diff = Compare-Object -ReferenceObject $a -DifferenceObject $b
    "Lines compared: live $($live.Count), new $($fresh.Count) (ignoring $($known.Count) known harmless kinds)"
    if ($diff) {
        $diff | Select-Object -First 30 | ForEach-Object { '{0} {1}' -f $_.SideIndicator, $_.InputObject }
        throw "The baseline differs from the live database in $(@($diff).Count) line(s)."
    }
} catch {
    Write-Host "Baseline check: FAILED. $($_.Exception.Message)"
    docker rm -f $name 2>&1 | Out-Null
    exit 1
}
$counts = docker exec $name psql -U supabase_admin -h 127.0.0.1 -d postgres -At -c "select (select count(*) from public.missions), (select count(*) from public.planning_questions), (select count(*) from public.planning_question_sections)"
docker rm -f $name 2>&1 | Out-Null
if ($counts -ne '1|46|6') { Write-Host "Baseline check: FAILED. Starting rows are $counts (expected 1|46|6)."; exit 1 }
Write-Host 'Baseline check: OK (same schema and rights as live, starting rows 1 mission, 46 questions, 6 sections).'
exit 0
