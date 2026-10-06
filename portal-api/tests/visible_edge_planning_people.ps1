# Visible Edge walkthrough of the planning people tabs + add-person pop-ups.
# Drives a normal (headed) Edge window over the DevTools protocol, with a pause per step.
# Test target only: temporary portal/API on port 18070 backed by a throwaway DB copy.
param([string]$Base = 'http://localhost:18070', [string]$Gate, [string]$UserId,
      [string]$Out = "$PSScriptRoot\shots", [int]$Pause = 1600)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Out | Out-Null
$edge = @('C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe') + (Get-ChildItem 'C:\Program Files (x86)\Microsoft\EdgeCore\*\msedge.exe' -ErrorAction SilentlyContinue | ForEach-Object FullName) | Where-Object { Test-Path $_ } | Select-Object -First 1
$profile = Join-Path $env:TEMP ('gfm-visible-test-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$port = 9339
$proc = Start-Process $edge -PassThru -ArgumentList @("--remote-debugging-port=$port", "--user-data-dir=`"$profile`"", '--no-first-run', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--no-default-browser-check', '--window-size=1250,1000', '--window-position=40,20', '--new-window', 'about:blank')
$targets = $null
for ($i = 0; $i -lt 40 -and -not $targets; $i++) { Start-Sleep -Milliseconds 500; try { $targets = Invoke-RestMethod "http://127.0.0.1:$port/json" } catch {} }
$page = $targets | Where-Object { $_.type -eq 'page' } | Select-Object -First 1
$ws = New-Object System.Net.WebSockets.ClientWebSocket
$ws.Options.KeepAliveInterval = [TimeSpan]::FromSeconds(20)
$ws.ConnectAsync([Uri]$page.webSocketDebuggerUrl, [Threading.CancellationToken]::None).Wait()
$script:msgId = 0
$results = New-Object System.Collections.ArrayList
function Send-Cdp($method, $params = @{}) {
  $script:msgId++; $id = $script:msgId
  $json = @{ id = $id; method = $method; params = $params } | ConvertTo-Json -Depth 20 -Compress
  $bytes = [Text.Encoding]::UTF8.GetBytes($json)
  $ws.SendAsync([ArraySegment[byte]]::new($bytes), 'Text', $true, [Threading.CancellationToken]::None).Wait()
  while ($true) {
    $ms = New-Object IO.MemoryStream; $buf = New-Object byte[] 65536
    do { $cts = New-Object Threading.CancellationTokenSource 45000; $r = $ws.ReceiveAsync([ArraySegment[byte]]::new($buf), $cts.Token).Result; $ms.Write($buf, 0, $r.Count) } while (-not $r.EndOfMessage)
    $msg = [Text.Encoding]::UTF8.GetString($ms.ToArray()) | ConvertFrom-Json
    if ($msg.id -eq $id) { if ($msg.error) { throw "CDP $method failed: $($msg.error.message)" }; return $msg.result }
  }
}
function JS($code) {
  $r = Send-Cdp 'Runtime.evaluate' @{ expression = "(async()=>{ $code })()"; awaitPromise = $true; returnByValue = $true }
  if ($r.exceptionDetails) { throw "JS error: $($r.exceptionDetails.exception.description)" }
  return $r.result.value
}
function Banner($text) { JS "let b=document.getElementById('__steps');if(!b){b=document.createElement('div');b.id='__steps';b.style.cssText='position:fixed;z-index:99999;top:8px;left:50%;transform:translateX(-50%);background:#173644ee;color:#fff;padding:8px 16px;border-radius:10px;font:600 14px system-ui;box-shadow:0 6px 20px #0005;pointer-events:none';document.body.append(b)}b.style.display='block';b.textContent=$(ConvertTo-Json $text);" | Out-Null }
function Step($text) { Write-Output "STEP  $text"; Banner $text; Start-Sleep -Milliseconds $Pause }
function Check($name, $ok, $detail = '') { [void]$results.Add([pscustomobject]@{ ok = [bool]$ok; name = $name; detail = "$detail" }); Write-Output ($(if ($ok) { 'PASS  ' } else { 'FAIL  ' }) + $name + $(if ($detail) { " -- $detail" } else { '' })) }
function Shot($name, $selector) {
  JS "const b=document.getElementById('__steps');if(b)b.style.display='none';" | Out-Null
  Start-Sleep -Milliseconds 250
  $params = @{ format = 'png' }
  if ($selector) {
    $rect = JS "const e=document.querySelector($(ConvertTo-Json $selector));e.scrollIntoView({block:'start'});await new Promise(r=>setTimeout(r,300));const r=e.getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height}"
    $params = @{ format = 'png'; captureBeyondViewport = $true; clip = @{ x = $rect.x; y = $rect.y; width = $rect.w; height = $rect.h; scale = 1 } }
  }
  $img = Send-Cdp 'Page.captureScreenshot' $params
  [IO.File]::WriteAllBytes((Join-Path $Out "$name.png"), [Convert]::FromBase64String($img.data))
  JS "const b=document.getElementById('__steps');if(b)b.style.display='block';" | Out-Null
}
function Theme($t) { JS "window.postMessage({type:'portal-theme',theme:'$t'},'*');await new Promise(r=>setTimeout(r,250));" | Out-Null }
function ShotBoth($name, $selector) { Theme 'mission'; Shot "$name-light" $selector; Theme 'dark'; Start-Sleep -Milliseconds 700; Shot "$name-dark" $selector; Theme 'mission' }
function Go($url) { Send-Cdp 'Page.navigate' @{ url = $url } | Out-Null; Start-Sleep -Milliseconds 800; for ($i = 0; $i -lt 60; $i++) { try { if (JS "return location.href.startsWith('http') && document.readyState==='complete'") { break } } catch {}; Start-Sleep -Milliseconds 250 }; Write-Output "      at $(JS 'return location.href')" }
function WaitFor($cond, $ms = 10000) { JS "for(let i=0;i<$($ms/100);i++){ if($cond) return true; await new Promise(r=>setTimeout(r,100)) } return false" }
$fill = "const fill=(sel,v)=>{const e=document.querySelector(sel);e.focus();const proto=e.tagName==='SELECT'?HTMLSelectElement:(e.tagName==='TEXTAREA'?HTMLTextAreaElement:HTMLInputElement);Object.getOwnPropertyDescriptor(proto.prototype,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))};"

try {
  Send-Cdp 'Page.enable' | Out-Null
  Send-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 1200; height = 900; deviceScaleFactor = 1; mobile = $false } | Out-Null
  Go "$Base/__enter?k=$Gate"
  $tok = JS "const enc=o=>btoa(JSON.stringify(o)).replace(/=+$/,'').replace(/\+/g,'-').replace(/\//g,'_');return enc({alg:'HS256',typ:'JWT'})+'.'+enc({sub:'$UserId',role:'authenticated',aud:'authenticated',exp:1990000000})+'.fixture'"
  JS "localStorage.setItem('mission_access_token','$tok')" | Out-Null

  # ---------- BEFORE: current main page against the same test API ----------
  Go "$Base/planning-before.html"
  WaitFor "document.querySelector('#section-new-members')" | Out-Null
  Step 'BEFORE (main): New members are carousel cards, only "Add from database"'
  ShotBoth 'before-new-members' '#section-new-members'
  ShotBoth 'before-baptismal' '#section-baptismal-friends'
  Check 'before: no per-person tabs / no create button' ((JS "return document.querySelectorAll('[role=tab],[data-create]').length") -eq 0)

  # ---------- AFTER: branch page ----------
  Go "$Base/planning.html"
  WaitFor "document.querySelector('#section-new-members [data-create]')" | Out-Null
  Step 'AFTER (branch): each person now has a tab; "+ New member" opens a pop-up'
  JS "document.querySelector('#section-new-members').scrollIntoView({block:'start'})" | Out-Null
  $nmTabs = JS "return [...document.querySelectorAll('#section-new-members [role=tab]')].map(t=>t.textContent)"
  Check 'after: New Member tabs rendered' ($nmTabs.Count -ge 1) ($nmTabs -join ', ')
  ShotBoth 'after-new-members' '#section-new-members'
  ShotBoth 'after-baptismal' '#section-baptismal-friends'

  Step 'Open "+ New member" and press "Create and add" with everything empty'
  JS "document.querySelector('#section-new-members [data-create]').click()" | Out-Null
  Start-Sleep -Milliseconds $Pause
  JS "document.getElementById('createSave').click()" | Out-Null
  Start-Sleep -Milliseconds 600
  $errs = JS "return [...document.querySelectorAll('#createFields .invalid')].map(e=>e.dataset.createField).sort()"
  Check 'empty form: 6 fields marked (first name + 5 required choices)' ($errs.Count -eq 6) ($errs -join ', ')
  Step 'Errors appear under each input (light and dark)'
  ShotBoth 'after-modal-errors' '#createDialog'

  Step 'Fill in a birth date in the future to see the date check'
  JS ($fill + "fill('#create-first_name','Zz Visible');fill('#create-date_of_birth','2030-01-01');document.getElementById('createSave').click();") | Out-Null
  Start-Sleep -Milliseconds 700
  $dob = JS "return document.querySelector('[data-create-field=date_of_birth] .field-error')?.textContent||''"
  Check 'future birth date rejected under its input' ($dob -eq 'Birth date cannot be in the future.') $dob
  Start-Sleep -Milliseconds $Pause

  Step 'Fill in the form correctly and create the new member'
  JS ($fill + "fill('#create-last_name','Browsertest');fill('#create-date_of_birth','1998-02-03');fill('#create-baptism_date','2026-09-20');fill('#create-age_range','18-30');fill('#create-gender','Male');fill('#create-living_situation','Student');fill('#create-marital_status','Single');fill('#create-mission_language_competency','Conversational/complex');fill('#create-finding_source','Missionary/English Class');fill('#create-native_language','Spanish');fill('#create-child_dependents','0');fill('#create-conversion_success_notes','Visible Edge test');fill('#create-baptismal_date_extended','2026-09-01');fill('#create-country_of_origin','Spain');document.getElementById('create-not_confirmed').click();") | Out-Null
  Start-Sleep -Milliseconds $Pause
  Shot 'after-modal-filled-light' '#createDialog'
  JS "document.getElementById('createSave').click()" | Out-Null
  $closed = WaitFor "!document.getElementById('createDialog').open && document.querySelector('#section-new-members [role=tab][aria-selected=true]')?.textContent==='Zz Visible Browsertest'"
  Check 'new member created, gets its own selected tab' $closed (JS "return document.querySelector('#section-new-members [role=tab][aria-selected=true]')?.textContent+' | '+document.getElementById('message').textContent")
  Step 'New member saved in the database and shown in a new tab'
  JS "document.querySelector('#section-new-members').scrollIntoView({block:'start'})" | Out-Null
  ShotBoth 'after-new-member-created' '#section-new-members'

  Step 'Type lessons for the new person (autosave)'
  JS ($fill + "fill('#section-new-members [role=tabpanel]:not([hidden]) [data-field=lessons_actual]','2')") | Out-Null
  Start-Sleep -Milliseconds 2500
  $saved = JS "return document.getElementById('saveState').textContent"
  Check 'autosave after editing the new tab' ($saved -match 'Saved|saved') $saved

  Step 'Switch between person tabs'
  $switch = JS "const tabs=[...document.querySelectorAll('#section-new-members [role=tab]')];if(tabs.length<2)return 'only one tab';tabs[0].click();await new Promise(r=>setTimeout(r,900));const ok=!document.getElementById(tabs[0].getAttribute('aria-controls')).hidden;tabs[tabs.length-1].click();return ok?'ok':'bad'"
  Check 'clicking tabs switches the visible person' ($switch -eq 'ok' -or $switch -eq 'only one tab') $switch
  Start-Sleep -Milliseconds $Pause

  Step 'Open "+ Add person on date" (Baptismal Date) and create a friend'
  JS "document.querySelector('#section-baptismal-friends').scrollIntoView({block:'start'});document.querySelector('#section-baptismal-friends [data-create]').click()" | Out-Null
  Start-Sleep -Milliseconds $Pause
  JS "document.getElementById('createSave').click()" | Out-Null
  Start-Sleep -Milliseconds 500
  Check 'baptismal pop-up: only first name required' ((JS "return document.querySelectorAll('#createFields .invalid').length") -eq 1)
  ShotBoth 'after-modal-baptismal-errors' '#createDialog'
  JS ($fill + "fill('#create-first_name','Zz Visible');fill('#create-last_name','Datefriend');fill('#create-finding_source','Media/Referral');") | Out-Null
  Start-Sleep -Milliseconds $Pause
  JS "document.getElementById('createSave').click()" | Out-Null
  $bd = WaitFor "document.querySelector('#section-baptismal-friends [role=tab][aria-selected=true]')?.textContent==='Zz Visible Datefriend'"
  Check 'baptismal-date friend created with its own tab' $bd
  JS "document.querySelector('#section-baptismal-friends').scrollIntoView({block:'start'})" | Out-Null
  Step 'Baptismal-date friend added'
  ShotBoth 'after-baptismal-created' '#section-baptismal-friends'
  $api = JS "const r=await portalAPI('planning/form');return {nm:r.people.new_members.map(p=>p.display_name),bd:r.people.baptismal_friends.map(p=>p.display_name)}"
  Check 'API confirms both people on this week''s plan' (($api.nm -contains 'Zz Visible Browsertest') -and ($api.bd -contains 'Zz Visible Datefriend')) ("NM: " + ($api.nm -join ', ') + " | BD: " + ($api.bd -join ', '))
  Step 'Done - all steps finished'
  Start-Sleep -Milliseconds 2500
} catch {
  Check 'walkthrough ran without script errors' $false $_.Exception.Message
} finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue; Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object { $_.CommandLine -like "*$profile*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } catch {}
  Start-Sleep 2; Remove-Item -Recurse -Force $profile -ErrorAction SilentlyContinue
  $pass = @($results | Where-Object ok).Count
  Write-Output "`n$pass/$($results.Count) passed"
  $results | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Out 'results.json')
}
