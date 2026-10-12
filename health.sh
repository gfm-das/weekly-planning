#!/usr/bin/env bash
# health.sh: checks that every part of the mission system is up, and prints one row per check (the shell twin of health.ps1,
# for Mac, Linux and Windows with Git Bash). It only looks: it changes nothing.
#   ./health.sh              one check; exit code 0 when no row says FAIL, 1 otherwise
#   ./health.sh --wait 180   keep checking for up to 180 seconds until everything is fine (right after a start or an install)
# Rows: web addresses with the answer they must give (200 = the page is there; 401 or 403 on a page that needs a sign-in = the
# door is locked, which is what we want); Dashboards and the Presentations deck address are SKIPPED while not installed; the
# nightly backup (the newest dump under 26 hours old); the Cloudflare tunnel (SKIPPED without one, a WARNING and never a failure when it
# is not connected: the office network works without it); no container restarting or unhealthy.
# Container names are settings, read from portal/.env and slidev/.env like the compose files do (the defaults are the
# Frankfurt server's, as in health.ps1).
# For tests only, so a test can check a copy that runs on other ports and names: GFM_PORT_STUDIO GFM_PORT_KONG GFM_PORT_IMPORTER
# GFM_PORT_SLIDEV GFM_PORT_PORTAL GFM_PORT_DATAEASE GFM_PORT_DECKS, GFM_DATAEASE_NAME, GFM_BACKUP_CONTAINER, and
# GFM_HEALTH_SKIP="Row name|Another row" (those rows say SKIPPED).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
WAIT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --wait) WAIT=${2:?--wait needs a number of seconds}; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

env_value() {  # env_value FILE NAME DEFAULT
  local v=""
  [ -f "$1" ] && v=$(grep -E "^$2=" "$1" | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//')
  printf '%s' "${v:-$3}"
}
SLIDEV_CONTAINER=${GFM_SLIDEV_CONTAINER:-$(env_value "$HERE/slidev/.env" GFM_SLIDEV_CONTAINER slidev-j5iyrpjbsssqlilqhw9axugx)}
DATAEASE_CONTAINER=${GFM_DATAEASE_NAME:-gfm-dataease}
BACKUP_CONTAINER=${GFM_BACKUP_CONTAINER:-gfm-backup}
TUNNEL_CONTAINER=${GFM_CLOUDFLARED_CONTAINER:-gfm-cloudflared}
P_STUDIO=${GFM_PORT_STUDIO:-13000}; P_KONG=${GFM_PORT_KONG:-18000}; P_IMPORTER=${GFM_PORT_IMPORTER:-8090}; P_SLIDEV=${GFM_PORT_SLIDEV:-3030}
P_PORTAL=${GFM_PORT_PORTAL:-8070}; P_DATAEASE=${GFM_PORT_DATAEASE:-8088}; P_DECKS=${GFM_PORT_DECKS:-8089}
SKIP=${GFM_HEALTH_SKIP:-}
BACKUP_DIR=${GFM_BACKUP_DIR:-$HERE/backups/nightly}
BACKUP_MAX_MINUTES=$((26 * 60))

ROWS=()
FAILED=0
row() { ROWS+=("$1|$2|$3"); }   # service | status | result
fail() { FAILED=1; }

SLIDEV_ROWS="Slidev|Presentation Decks (8089)|Deck Pass Boundary|Presentations Request Guard|Deck Numbers Guard"
# Is the Presentations container running and younger than 20 minutes (since its last start)?
slidev_starting() {
  [ "$(docker inspect -f '{{.State.Running}}' "$SLIDEV_CONTAINER" 2>/dev/null)" = true ] || return 1
  local age; age=$(created_age_minutes "$SLIDEV_CONTAINER" .State.StartedAt)
  [ -n "$age" ] && [ "$age" -lt 20 ]
}

# web_check NAME URL "expected codes" [body pattern]
web_check() {
  local name=$1 url=$2 expected=$3 pattern=${4:-} answer code body
  if [ -n "$SKIP" ] && [[ "|$SKIP|" == *"|$name|"* ]]; then row "$name" "-" "SKIPPED (this check is switched off)"; return; fi
  # The answer and its status code in one piece (no temporary file); redirects are followed, as health.ps1 does.
  answer=$(curl -s -L -w $'
%{http_code}' --max-time 20 "$url" 2>/dev/null) || answer=$'
000'
  code=${answer##*$'
'}
  body=${answer%$'
'*}
  if [ "$code" = 000 ]; then
    # Presentations install their packages on a first start without them (the installer does it beforehand, but an update may need it
    # again): while the container is young, not answering yet is "waiting", not a failure.
    if [[ "|$SLIDEV_ROWS|" == *"|$name|"* ]] && slidev_starting; then row "$name" "-" "waiting (Presentations install their packages on the first start; docker logs $SLIDEV_CONTAINER)"; return; fi
    row "$name" "-" "FAIL: no answer"; fail; return
  fi
  if [[ " $expected " == *" $code "* ]]; then
    if [ -n "$pattern" ] && ! grep -Eq "$pattern" <<<"$body"; then row "$name" "$code" "FAIL (unexpected answer)"; fail
    else row "$name" "$code" "OK"; fi
  else
    row "$name" "$code" "FAIL"; fail
  fi
}

container_exists() { docker container inspect "$1" >/dev/null 2>&1; }

# Minutes since a container was created (or started: field StartedAt of .State); empty when this computer's date cannot read the time.
created_age_minutes() {
  local created now then field=${2:-.Created}
  created=$(docker inspect -f "{{$field}}" "$1" 2>/dev/null | sed -E 's/\.[0-9]+Z$/Z/') || return 0
  now=$(date +%s)
  then=$(date -d "$created" +%s 2>/dev/null || date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$created" +%s 2>/dev/null) || return 0
  [ -n "$then" ] && echo $(( (now - then) / 60 ))
}

backup_check() {
  local state latest last
  latest=$(ls -t "$BACKUP_DIR"/beta-[0-9]*-[0-9]*.dump 2>/dev/null | head -1)
  if ! container_exists "$BACKUP_CONTAINER"; then
    if [ -n "$latest" ]; then row "Nightly backup" "-" "FAIL: no $BACKUP_CONTAINER container"; fail
    else row "Nightly backup" "-" "SKIPPED (not deployed: no $BACKUP_CONTAINER container)"; fi
    return
  fi
  state=$(docker inspect -f '{{.State.Running}}' "$BACKUP_CONTAINER" 2>/dev/null)
  if [ "$state" != true ]; then row "Nightly backup" "-" "FAIL: $BACKUP_CONTAINER is not running"; fail; return; fi
  if [ -n "$latest" ] && [ -z "$(find "$latest" -mmin -"$BACKUP_MAX_MINUTES" 2>/dev/null)" ]; then
    row "Nightly backup" "-" "FAIL: the newest backup $(basename "$latest") is over 26 hours old"; fail; return
  fi
  last=$(head -1 "$BACKUP_DIR/last-run.txt" 2>/dev/null || true)
  if [[ "$last" == FAILED* ]]; then row "Nightly backup" "-" "FAIL: last night: ${last#FAILED * } (backups/nightly/nightly.log)"; fail; return; fi
  if [ -n "$latest" ]; then
    row "Nightly backup" "-" "OK ($(basename "$latest"), $(( $(wc -c < "$latest") / 1048576 )) MB)"; return
  fi
  local age; age=$(created_age_minutes "$BACKUP_CONTAINER")
  if [ -n "$age" ] && [ "$age" -ge "$BACKUP_MAX_MINUTES" ]; then
    row "Nightly backup" "-" "FAIL: no backup yet, 26 hours after the deploy (backups/nightly/nightly.log)"; fail
  else
    row "Nightly backup" "-" "waiting (the first backup is made at 02:30)"
  fi
}

# The Cloudflare tunnel container (cloudflared/): healthy while it is connected. Informational: a broken tunnel is a WARNING, not a FAIL.
tunnel_check() {
  local name="Cloudflare tunnel" state
  if ! container_exists "$TUNNEL_CONTAINER"; then row "$name" "-" "SKIPPED (no tunnel installed: the portal is on the local network only)"; return; fi
  state=$(docker inspect -f '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$TUNNEL_CONTAINER" 2>/dev/null)
  case "$state" in
    true\|healthy) row "$name" "-" "OK (connected)" ;;
    true\|starting) row "$name" "-" "waiting (connecting)" ;;
    true*) row "$name" "-" "WARNING: not connected (docker logs $TUNNEL_CONTAINER; check the token and the internet connection)" ;;
    *) row "$name" "-" "WARNING: not running (docker start $TUNNEL_CONTAINER)" ;;
  esac
}

# The updater (updater/gfm-updater.sh watch) writes the status file at least once a minute while it watches. Informational: never a FAIL.
updater_check() {
  local name="Updater" file="$HERE/updater/status/status.json"
  if [ ! -f "$file" ]; then row "$name" "-" "SKIPPED (not set up: this system does not update itself)"; return; fi
  if [ -n "$(find "$file" -mmin -15 2>/dev/null)" ]; then row "$name" "-" "OK (watching: the status file is fresh)"
  else row "$name" "-" "WARNING: not watching (updater/status/status.json is older than 15 minutes; bash updater/register-watcher.sh)"; fi
}

run_checks() {
  ROWS=(); FAILED=0
  backup_check
  updater_check
  tunnel_check
  web_check "Beta Studio" http://127.0.0.1:$P_STUDIO "200"
  web_check "Beta Kong" http://127.0.0.1:$P_KONG/auth/v1/settings "200 401"
  web_check "Roster Importer" http://127.0.0.1:$P_IMPORTER/health "200"
  web_check "Slidev" http://127.0.0.1:$P_SLIDEV "200"
  web_check "Portal" http://127.0.0.1:$P_PORTAL "200"
  web_check "Portal API" http://127.0.0.1:$P_PORTAL/api/health "200"
  web_check "Portal Auth Boundary" http://127.0.0.1:$P_PORTAL/api/overview "401"
  if container_exists "$DATAEASE_CONTAINER"; then
    web_check "Dashboards (DataEase)" http://127.0.0.1:$P_DATAEASE/gfm-gate-health "200" '"dataease"[[:space:]]*:[[:space:]]*"signed-in"'
    web_check "DataEase Sign-in Boundary" http://127.0.0.1:$P_DATAEASE/de2api/user/info "401"
  else
    row "Dashboards (DataEase)" "-" "SKIPPED (not deployed: no $DATAEASE_CONTAINER container)"
    row "DataEase Sign-in Boundary" "-" "SKIPPED (not deployed: no $DATAEASE_CONTAINER container)"
  fi
  if docker port "$SLIDEV_CONTAINER" 3041/tcp 2>/dev/null | grep -q ":$P_DECKS"; then
    web_check "Presentation Decks (8089)" http://127.0.0.1:$P_DECKS/health "200" '"deck-address"'
    web_check "Deck Pass Boundary" http://127.0.0.1:$P_DECKS/p/health-check/ "401"
    web_check "Presentations Request Guard" http://127.0.0.1:$P_SLIDEV/api/presentations "403"
    web_check "Deck Numbers Guard" http://127.0.0.1:$P_DECKS/api/deck-pass "403"
  else
    for n in "Presentation Decks (8089)" "Deck Pass Boundary" "Presentations Request Guard" "Deck Numbers Guard"; do
      row "$n" "-" "SKIPPED (not deployed: port 8089 not published yet)"
    done
  fi
}

print_rows() {
  printf '%-30s %-7s %s\n' Service Status Result
  printf '%-30s %-7s %s\n' ------- ------ ------
  local r
  for r in "${ROWS[@]}"; do IFS='|' read -r a b c <<<"$r"; printf '%-30s %-7s %s\n' "$a" "$b" "$c"; done
}

deadline=$(( $(date +%s) + WAIT ))
while :; do
  run_checks
  # (the tunnel container is judged in its own row)
  unstable=$(docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null | grep -E 'Restarting|unhealthy' | grep -v "^$TUNNEL_CONTAINER|" || true)
  [ -n "$unstable" ] && FAILED=1
  [ "$FAILED" = 0 ] && break
  [ "$(date +%s)" -ge "$deadline" ] && break
  sleep 10
done
print_rows
if [ -n "$unstable" ]; then echo; echo "Unstable containers:"; echo "$unstable"; fi
exit "$FAILED"
