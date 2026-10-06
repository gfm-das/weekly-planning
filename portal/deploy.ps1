<#
  portal/deploy.ps1: puts the portal's web pages into the running portal container.

  What it is: the portal (http://<server>:8070) is an nginx container, portal-ydpgd5zwrjrvz5aa188sa60u. It serves
  the files in its html volume. This script copies the files of this folder (portal/) into that volume and then
  reloads nginx, so people get the new pages at once.

  Who runs it: the Data Analyst after a change in portal/, and the updater (updater/gfm-updater.ps1) during an
  update that changes portal/.

  What it does, in this order:
    1. Checks that every Docker network and volume the portal compose files need exists. If one is missing it stops
       before copying anything; otherwise half of the new files would be live and nginx would never reload.
    2. Makes index.html from index.template.html by filling in the public Supabase "anon" key from supabase/.env, and
       writes site-config.js from GFM_PUBLIC_DOMAIN (portal/.env; empty: no public address).
       (That key is public by design: every browser gets it. It is still never printed here.)
    3. Puts index.html, the pages, scripts, styles, icons and the web manifest, the i18n folder (the 14 languages)
       and the whiteboard folder together in one folder (backups/.tmp-portal-deploy), copies that into the container
       in one go, and deletes the folder again.
    4. Removes what the portal no longer has (the list $RetiredPaths below).
    5. Makes sure the container runs with the current compose settings, checks nginx.conf and reloads nginx.

  Run it from the repository root (Windows PowerShell 5.1 or PowerShell 7):
      powershell -NoProfile -ExecutionPolicy Bypass -File portal/deploy.ps1
  Roll back: docs/README-start-here.md, "Roll back".
  Tests: ops-tests/test-deploy.ps1 (a stand-in for docker; nothing real is touched).
#>
[CmdletBinding()]
param(
    # Load the functions only, run nothing (ops-tests/test-deploy.ps1 uses this).
    [switch]$NoRun
)
$ErrorActionPreference = 'Stop'

# The container's name is a setting (GFM_PORTAL_CONTAINER, also read by portal/portal-compose.yml); the default is this server's.
$PortalContainer = if ($env:GFM_PORTAL_CONTAINER) { $env:GFM_PORTAL_CONTAINER } else { 'portal-ydpgd5zwrjrvz5aa188sa60u' }
$HtmlFolder = '/usr/share/nginx/html'
# The kinds of files in portal/ that browsers load. index.template.html is not one of them: it becomes index.html.
$PageExtensions = @('.html', '.css', '.js', '.svg', '.webmanifest')
# Folders copied as a whole, into the folder of the same name in the container. (An early deploy copied i18n into
# the existing i18n folder and made a nested copy: see i18n/i18n below.)
# portal/whiteboard-build (the files the Whiteboard bundle is built from) is never copied.
$CopiedFolders = @('i18n', 'whiteboard')
# What the portal no longer has. The html volume keeps whatever was ever copied into it, so these are removed there
# (a missing one is fine). Something that is back in portal/ (for example after a rollback) is kept.
$RetiredPaths = @(
    'grafana-session.html'   # round 6: Grafana's "Please open Dashboards again" page (Grafana is retired)
    'i18n/i18n'              # an early deploy copied the i18n folder into itself; nothing reads this copy
    'management.html'        # round 12: an old "Data & Administration" tile page, never linked from anywhere
)

# Windows PowerShell 5.1 turns anything a program (docker) writes to stderr into an error, and with 'Stop' that
# ends the script even when docker worked (docker prints progress such as "Container ... Running" to stderr).
# So programs run with 'Continue', their output is shown, and only the exit code decides.
function Invoke-Native {
    param([Parameter(Mandatory)][string]$Failure, [Parameter(Mandatory)][scriptblock]$Command)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        & $Command 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { Write-Host $_.Exception.Message } else { Write-Host $_ }
        }
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "$Failure (exit code $exitCode)" }
}

function Get-ComposeArguments([string]$PortalRoot) {
    return @('compose', '-p', 'portal',
        '-f', (Join-Path $PortalRoot 'portal-compose.yml'),
        '-f', (Join-Path $PortalRoot 'local-override.yml'))
}

# Step 1. Returns the Docker networks and volumes the compose files name as "external" that do not exist, for
# example 'network gfm-network'. Throws when the compose files cannot be read.
function Get-MissingDockerResources([string]$PortalRoot) {
    $compose = Get-ComposeArguments $PortalRoot
    $missing = @()
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $configJson = (& docker @compose config --format json 2>$null) -join "`n"
        $configExitCode = $LASTEXITCODE
        if ($configExitCode -eq 0 -and $configJson) {
            $config = $configJson | ConvertFrom-Json
            foreach ($kind in 'network', 'volume') {
                $entries = $config.($kind + 's')
                if (-not $entries) { continue }
                foreach ($entry in $entries.PSObject.Properties.Value) {
                    if (-not $entry.external) { continue }
                    & docker $kind inspect $entry.name *> $null
                    if ($LASTEXITCODE -ne 0) { $missing += "$kind $($entry.name)" }
                }
            }
        }
    }
    finally { $ErrorActionPreference = $previous }
    if ($configExitCode -ne 0 -or -not $configJson) { throw 'Reading the portal compose files failed. Nothing was deployed.' }
    return $missing
}

function Assert-DockerResourcesExist([string]$PortalRoot) {
    $missing = @(Get-MissingDockerResources $PortalRoot)
    if ($missing.Count) {
        throw ("Nothing was deployed: Docker $($missing -join ', ') is missing. Check the portal compose files " +
            "(portal/portal-compose.yml, portal/local-override.yml) and docs/handoff/08_INFRASTRUCTURE_AND_DEPLOYMENT.md.")
    }
}

# Step 2. The public anon key from supabase/.env (SERVICE_SUPABASEANON_KEY, or ANON_KEY in an older .env).
function Get-PublicAnonKey([string]$EnvFile) {
    $settings = @{}
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') { $settings[$Matches[1]] = $Matches[2].Trim('"').Trim("'") }
    }
    $anonKey = $settings['SERVICE_SUPABASEANON_KEY']
    if (-not $anonKey) { $anonKey = $settings['ANON_KEY'] }
    # A Supabase key is a signed web token, and those always start with "eyJ".
    if (-not $anonKey -or $anonKey -notmatch '^eyJ') { throw 'Public Supabase anon key missing.' }
    return $anonKey
}

# The mission's public web name (GFM_PUBLIC_DOMAIN in portal/.env, or in the environment), for example example.org.
# Empty when the mission has no public address. Letters, digits, dots and hyphens only (it ends up in a script file).
function Get-PublicDomain([string]$PortalRoot) {
    $domain = "$env:GFM_PUBLIC_DOMAIN"
    $file = Join-Path $PortalRoot '.env'
    if (-not $domain -and (Test-Path -LiteralPath $file)) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if ($line -match '^GFM_PUBLIC_DOMAIN=(.*)$') { $domain = $Matches[1].Trim().Trim('"').Trim("'") }
        }
    }
    $domain = $domain.Trim().Trim('.').ToLowerInvariant()
    if ($domain -and $domain -notmatch '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$') { throw "GFM_PUBLIC_DOMAIN is not a domain name: $domain" }
    return $domain
}

# The mission's time zone (GFM_TIME_ZONE in portal/.env, or in the environment); Europe/Berlin when nothing says otherwise.
function Get-MissionTimeZone([string]$PortalRoot) {
    $zone = "$env:GFM_TIME_ZONE"
    $file = Join-Path $PortalRoot '.env'
    if (-not $zone -and (Test-Path -LiteralPath $file)) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if ($line -match '^GFM_TIME_ZONE=(.*)$') { $zone = $Matches[1].Trim().Trim('"').Trim("'") }
        }
    }
    if (-not $zone) { $zone = 'Europe/Berlin' }
    if ($zone -notmatch '^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$') { throw "GFM_TIME_ZONE is not a time zone name: $zone" }
    return $zone
}

# Writes site-config.js (the settings the pages read first) to $OutFile, as UTF-8 without a byte order mark.
function Write-SiteConfig([string]$PublicDomain, [string]$TimeZone, [string]$OutFile) {
    $text = "// Written by portal/deploy.ps1 from GFM_PUBLIC_DOMAIN and GFM_TIME_ZONE. Do not edit.`nwindow.GFM_SITE = { publicDomain: `"$PublicDomain`", timeZone: `"$TimeZone`" };`n"
    [IO.File]::WriteAllText($OutFile, $text, [Text.UTF8Encoding]::new($false))
}

# Writes index.html (the template with the key filled in) to $OutFile, as UTF-8 without a byte order mark.
function Write-IndexHtml([string]$PortalRoot, [string]$AnonKey, [string]$OutFile) {
    $html = [IO.File]::ReadAllText((Join-Path $PortalRoot 'index.template.html'))
    [IO.File]::WriteAllText($OutFile, $html.Replace('__ANON_KEY__', $AnonKey), [Text.UTF8Encoding]::new($false))
}

# Step 3a. Puts everything that goes live into one folder, laid out exactly as in the container: index.html, the
# pages, and the folders of $CopiedFolders. A folder left over from an earlier deploy that stopped is emptied first.
function New-PortalStaging([string]$PortalRoot, [string]$AnonKey, [string]$Staging) {
    Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Staging | Out-Null
    Write-IndexHtml $PortalRoot $AnonKey (Join-Path $Staging 'index.html')
    Get-ChildItem -LiteralPath $PortalRoot -File |
        Where-Object { $_.Extension -in $PageExtensions -and $_.Name -ne 'index.template.html' } |
        Copy-Item -Destination $Staging
    # The real site-config.js replaces the safe default that was just copied.
    Write-SiteConfig (Get-PublicDomain $PortalRoot) (Get-MissionTimeZone $PortalRoot) (Join-Path $Staging 'site-config.js')
    foreach ($folder in $CopiedFolders) {
        $source = Join-Path $PortalRoot $folder
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $Staging -Recurse }
    }
}

# Step 3b. One copy of that folder's contents into the html folder ("<folder>/." adds to what is there and replaces
# files of the same name). With one docker cp per file this step took about 4 seconds; now about 2.
function Copy-PortalFiles([string]$Staging) {
    Invoke-Native 'Copying the portal pages failed.' { docker cp ($Staging + '/.') "${PortalContainer}:$HtmlFolder" }
}

# Step 4.
function Remove-RetiredPaths([string]$PortalRoot) {
    foreach ($retired in $RetiredPaths) {
        if (Test-Path -LiteralPath (Join-Path $PortalRoot $retired)) { continue }
        Invoke-Native "Removing the retired $retired failed." { docker exec $PortalContainer rm -rf "$HtmlFolder/$retired" }
    }
}

# Step 5. compose recreates the container only when its settings changed, so nginx is always reloaded as well
# (nginx.conf is mounted from portal/, and an edited nginx.conf must take effect).
function Restart-PortalNginx([string]$PortalRoot) {
    $compose = Get-ComposeArguments $PortalRoot
    Invoke-Native 'Portal nginx recreate failed.' { docker @compose up -d --no-deps portal }
    Invoke-Native 'Portal nginx configuration failed.' { docker exec $PortalContainer nginx -t }
    Invoke-Native 'Portal nginx reload failed.' { docker exec $PortalContainer nginx -s reload }
}

function Invoke-PortalDeploy([string]$PortalRoot) {
    $projectRoot = Split-Path -Parent $PortalRoot
    Assert-DockerResourcesExist $PortalRoot
    $anonKey = Get-PublicAnonKey (Join-Path $projectRoot 'supabase/.env')
    $staging = Join-Path $projectRoot 'backups/.tmp-portal-deploy'
    try {
        New-PortalStaging $PortalRoot $anonKey $staging
        Copy-PortalFiles $staging
        Remove-RetiredPaths $PortalRoot
        Restart-PortalNginx $PortalRoot
        Write-Host 'Portal assets and API proxy deployed.'
    }
    finally { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
}

if ($NoRun) { return }
Invoke-PortalDeploy $PSScriptRoot
