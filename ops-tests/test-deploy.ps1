<#
  Tests of portal/deploy.ps1, with a stand-in for docker. Nothing real is touched: no container, no volume, no
  network. The stand-in only writes down every docker command the script would run.

  Each test builds a small fake repository in a temporary folder (portal/ with a few pages, i18n/ and whiteboard/,
  supabase/.env with a made-up key, backups/) and runs the deploy on it.

  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File ops-tests\test-deploy.ps1
  Exit code 0 means every check passed. Works in Windows PowerShell 5.1 and PowerShell 7.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $repo 'portal\deploy.ps1') -NoRun   # the deploy's functions, without running it

$script:Passes = 0
$script:Failures = 0
function Assert-That([bool]$Condition, [string]$Name) {
    if ($Condition) { $script:Passes++; [Console]::Out.WriteLine("PASS  $Name") }
    else { $script:Failures++; [Console]::Out.WriteLine("FAIL  $Name") }
}
# The deploy's own messages are not needed here; the results are printed with [Console] above.
function Write-Host { param([Parameter(ValueFromRemainingArguments = $true)]$Ignored) }

# ---------------------------------------------------------------------------------------------------------------
# The stand-in for docker. It answers "compose config" with a small compose file, "inspect" with success unless
# the resource is in $script:MissingResources, and fails a command that contains $script:FailOn.
# ---------------------------------------------------------------------------------------------------------------
$FakeKey = 'eyJmYWtl.test.key'
function Reset-StandIn {
    $script:DockerCalls = New-Object System.Collections.ArrayList
    $script:MissingResources = @()
    $script:ConfigFails = $false
    $script:FailOn = ''
    $script:CopiedIndex = $null
    $script:CopiedFiles = @()
}
# The deploy copies one folder (backups\.tmp-portal-deploy) into the container. When the stand-in is asked to copy
# it, it writes down what is in it at that moment: index.html's text and every file, as a path like 'i18n/en.json'.
function docker {
    $line = ($args | ForEach-Object { "$_" }) -join ' '
    [void]$script:DockerCalls.Add($line)
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'compose' -and $args -contains 'config') {
        if ($script:ConfigFails) { $global:LASTEXITCODE = 1; return }
        return '{"networks":{"gfm":{"name":"gfm-network","external":true},"own":{"name":"portal_default"}},"volumes":{"data":{"name":"portal-data","external":true}}}'
    }
    if ($args[1] -eq 'inspect' -and $script:MissingResources -contains "$($args[0]) $($args[2])") { $global:LASTEXITCODE = 1; return }
    if ($script:FailOn -and $line -like "*$script:FailOn*") { $global:LASTEXITCODE = 1; return }
    if ($args[0] -eq 'cp' -and "$($args[1])" -like '*.tmp-portal-deploy/.') {
        $folder = "$($args[1])".Substring(0, "$($args[1])".Length - 2)
        $script:CopiedIndex = [IO.File]::ReadAllText((Join-Path $folder 'index.html'))
        $script:CopiedFiles = @(Get-ChildItem -LiteralPath $folder -Recurse -File |
            ForEach-Object { $_.FullName.Substring($folder.Length + 1).Replace('\', '/') })
    }
}

# A fake repository: portal/ with pages of every kind, a file that is not copied, the two folders, and the
# build folder of the Whiteboard (never copied).
function New-FakeRepository([string]$EnvText = "SERVICE_SUPABASEANON_KEY=`"$FakeKey`"") {
    $root = Join-Path ([IO.Path]::GetTempPath()) ('gfm-deploy-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $portal = Join-Path $root 'portal'
    foreach ($folder in 'portal\i18n', 'portal\whiteboard', 'portal\whiteboard-build', 'supabase', 'backups') {
        New-Item -ItemType Directory -Force -Path (Join-Path $root $folder) | Out-Null
    }
    $files = @{
        'portal\index.template.html' = '<html><script>window.KEY="__ANON_KEY__"</script></html>'
        'portal\home.html' = 'home'; 'portal\portal.js' = 'js'; 'portal\portal.css' = 'css'; 'portal\icon.svg' = 'svg'
        'portal\manifest.webmanifest' = '{}'; 'portal\notes.md' = 'not a page'; 'portal\nginx.conf' = 'not a page'
        'portal\i18n\en.json' = '{}'; 'portal\whiteboard\index.html' = 'wb'; 'portal\whiteboard-build\build.mjs' = 'build'
        'supabase\.env' = $EnvText
    }
    foreach ($name in $files.Keys) { [IO.File]::WriteAllText((Join-Path $root $name), $files[$name]) }
    return $portal
}

function Invoke-TestDeploy([string]$Portal) {
    try { Invoke-PortalDeploy $Portal; return '' }
    catch { return $_.Exception.Message }
}

$cleanUp = @()
$html = '/usr/share/nginx/html'
$container = 'portal-ydpgd5zwrjrvz5aa188sa60u'
function Get-Staging([string]$Portal) { return Join-Path (Split-Path -Parent $Portal) 'backups\.tmp-portal-deploy' }

# 1. A normal deploy -------------------------------------------------------------------------------------------
Reset-StandIn
$portal = New-FakeRepository
$cleanUp += Split-Path -Parent $portal
# A folder left by an earlier deploy that stopped half-way: its old file must not go live.
New-Item -ItemType Directory -Force -Path (Get-Staging $portal) | Out-Null
[IO.File]::WriteAllText((Join-Path (Get-Staging $portal) 'stale.html'), 'old')
$problem = Invoke-TestDeploy $portal
$calls = @($script:DockerCalls)
$copied = @($script:CopiedFiles)
Assert-That ($problem -eq '') "a normal deploy runs to the end ($problem)"
Assert-That ($calls[0] -like 'compose -p portal -f *portal-compose.yml -f *local-override.yml config --format json') 'first it reads the compose files'
Assert-That (($calls -contains 'network inspect gfm-network') -and ($calls -contains 'volume inspect portal-data')) 'it checks the external network and volume'
Assert-That (-not ($calls -like '*inspect portal_default*')) 'a network the compose file makes itself is not checked'
Assert-That ($script:CopiedIndex -eq "<html><script>window.KEY=`"$FakeKey`"</script></html>") 'index.html is the template with the key filled in'
Assert-That ($calls -contains "cp $(Get-Staging $portal)/. ${container}:$html") 'everything goes into the html folder in one copy'
Assert-That (@($calls -like 'cp *').Count -eq 1) 'there is only that one copy'
foreach ($page in 'index.html', 'home.html', 'portal.js', 'portal.css', 'icon.svg', 'manifest.webmanifest') {
    Assert-That ($copied -contains $page) "the page $page is copied"
}
foreach ($other in 'index.template.html', 'notes.md', 'nginx.conf', 'whiteboard-build/build.mjs', 'stale.html') {
    Assert-That (-not ($copied -contains $other)) "$other is not copied"
}
Assert-That (($copied -contains 'i18n/en.json') -and -not ($copied -like 'i18n/i18n/*')) 'the contents of i18n go into i18n (no nested copy)'
Assert-That ($copied -contains 'whiteboard/index.html') 'the contents of whiteboard go into whiteboard'
Assert-That ($copied -contains 'site-config.js') 'site-config.js (written from GFM_PUBLIC_DOMAIN) is copied'
Assert-That ($copied.Count -eq 9) "nothing else is copied ($($copied -join ', '))"
Assert-That ($calls -contains "exec $container rm -rf $html/grafana-session.html") 'the retired Grafana page is removed'
Assert-That ($calls -contains "exec $container rm -rf $html/i18n/i18n") 'the old nested i18n/i18n folder is removed'
$last = $calls[($calls.Count - 3)..($calls.Count - 1)]
Assert-That ($last[0] -like 'compose -p portal -f *portal-compose.yml -f *local-override.yml up -d --no-deps portal') 'then the container is brought up to date'
Assert-That (($last[1] -eq "exec $container nginx -t") -and ($last[2] -eq "exec $container nginx -s reload")) 'and nginx is checked and reloaded, last'
Assert-That (-not (Test-Path -LiteralPath (Get-Staging $portal))) 'the temporary folder is deleted'

# 2. Something missing: nothing is copied ----------------------------------------------------------------------
Reset-StandIn
$script:MissingResources = @('network gfm-network')
$problem = Invoke-TestDeploy $portal
Assert-That ($problem -like 'Nothing was deployed: Docker network gfm-network is missing*') 'a missing network stops the deploy with its name'
Assert-That (-not ($script:DockerCalls -like 'cp *')) 'and nothing is copied'

Reset-StandIn
$script:ConfigFails = $true
$problem = Invoke-TestDeploy $portal
Assert-That ($problem -eq 'Reading the portal compose files failed. Nothing was deployed.') 'unreadable compose files stop the deploy'
Assert-That (-not ($script:DockerCalls -like 'cp *')) 'and nothing is copied'

# 3. A page that is back in portal/ (a rollback) is kept ---------------------------------------------------------
Reset-StandIn
[IO.File]::WriteAllText((Join-Path $portal 'grafana-session.html'), 'back')
$problem = Invoke-TestDeploy $portal
Assert-That ($problem -eq '') "the deploy with a page that is back runs to the end ($problem)"
Assert-That (@($script:CopiedFiles) -contains 'grafana-session.html') 'the page that is back is copied'
Assert-That (-not ($script:DockerCalls -like '*rm -rf*grafana-session.html')) 'and not removed'
Assert-That ($script:DockerCalls -contains "exec $container rm -rf $html/i18n/i18n") 'the other retired paths are still removed'
Remove-Item -LiteralPath (Join-Path $portal 'grafana-session.html')

# 4. The key -------------------------------------------------------------------------------------------------
Reset-StandIn
$portalOld = New-FakeRepository "# older .env`nANON_KEY='$FakeKey'"
$cleanUp += Split-Path -Parent $portalOld
$problem = Invoke-TestDeploy $portalOld
Assert-That (($problem -eq '') -and $script:CopiedIndex -like "*$FakeKey*") 'an older .env with ANON_KEY works too'

Reset-StandIn
$portalNoKey = New-FakeRepository 'SERVICE_SUPABASEANON_KEY=REPLACE_ME'
$cleanUp += Split-Path -Parent $portalNoKey
$problem = Invoke-TestDeploy $portalNoKey
Assert-That ($problem -eq 'Public Supabase anon key missing.') 'without a real key it stops'
Assert-That (-not ($script:DockerCalls -like 'cp *')) 'and nothing is copied'

# 5. A copy that fails ---------------------------------------------------------------------------------------
Reset-StandIn
$script:FailOn = '.tmp-portal-deploy'
$problem = Invoke-TestDeploy $portal
Assert-That ($problem -eq 'Copying the portal pages failed. (exit code 1)') 'a failed copy stops the deploy'
Assert-That (-not ($script:DockerCalls -like '*rm -rf*') -and -not ($script:DockerCalls -like '*nginx -s reload*')) 'nothing is removed and nginx is not reloaded after a failed copy'
Assert-That (-not (Test-Path -LiteralPath (Get-Staging $portal))) 'the temporary folder is deleted after a failure too'

foreach ($folder in $cleanUp) { Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue }
[Console]::Out.WriteLine("Deploy tests: $script:Passes passed, $script:Failures did not pass.")
if ($script:Failures) { exit 1 }
exit 0
