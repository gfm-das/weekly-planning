<#
  Starts the whole mission system after Windows or Docker Desktop stopped badly: starts Docker Desktop if it is not running,
  waits until it answers, then waits until every part of the system answers (health.ps1 is the full check afterwards).
  Run it from the repository root:  powershell -NoProfile -ExecutionPolicy Bypass -File start-gfm.ps1
#>
[CmdletBinding()]
param(
    [int]$WaitSeconds = 90,
    [int]$ServiceWaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
$taskLocalRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA)
$taskDesktop = Join-Path $taskLocalRoot 'Programs\DockerDesktop\Docker Desktop.exe'

if (-not (Test-Path -LiteralPath $taskDesktop)) {
    throw "Docker Desktop was not found at $taskDesktop"
}

docker version --format '{{.Server.Version}}' *> $null
if ($LASTEXITCODE -ne 0) {
    if (Get-Process -Name 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue) {
        Write-Host 'Docker Desktop is already starting.'
    }
    else {
        # Docker Desktop can leave Windows AF_UNIX reparse points behind after an
        # unclean exit. Preserve the small runtime directories, then let Docker
        # recreate them. Application containers, images, and volumes live elsewhere.
        $taskTargets = @(
            (Join-Path $taskLocalRoot 'Docker\run'),
            (Join-Path $taskLocalRoot 'docker-secrets-engine')
        )
        foreach ($taskTarget in $taskTargets) {
            if (-not (Test-Path -LiteralPath $taskTarget)) { continue }
            $taskResolved = (Get-Item -LiteralPath $taskTarget).FullName
            if ($taskResolved -ne $taskTarget -or
                -not $taskResolved.StartsWith($taskLocalRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing unexpected runtime path: $taskResolved"
            }
            $taskName = (Split-Path -Leaf $taskTarget) + '-stale-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
            Rename-Item -LiteralPath $taskResolved -NewName $taskName
            Write-Host "Preserved stale Docker runtime directory as $taskName"
        }
        Start-Process -FilePath $taskDesktop -WindowStyle Hidden
    }

    $taskDeadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        Start-Sleep -Seconds 2
        docker version --format '{{.Server.Version}}' *> $null
        if ($LASTEXITCODE -eq 0) { break }
    } while ((Get-Date) -lt $taskDeadline)
}

if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop did not become ready in time.' }
Write-Host "Docker engine $(docker version --format '{{.Server.Version}}') is ready."
$taskHealth = Join-Path $PSScriptRoot 'health.ps1'
$taskServiceDeadline = (Get-Date).AddSeconds($ServiceWaitSeconds)
do {
    $taskHealthOutput = & $taskHealth | Out-String
    $taskHealthCode = $LASTEXITCODE
    if ($taskHealthCode -eq 0) {
        Write-Host $taskHealthOutput.TrimEnd()
        exit 0
    }
    Start-Sleep -Seconds 10
} while ((Get-Date) -lt $taskServiceDeadline)

Write-Host $taskHealthOutput.TrimEnd()
throw 'One or more GFM services did not become healthy in time.'
