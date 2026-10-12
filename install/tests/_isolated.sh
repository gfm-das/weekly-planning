#!/usr/bin/env bash
# _isolated.sh: shared by test-install.sh and test-dataease.sh (sourced, not run). Gives a test copy of the system names, a network,
# volumes and host ports of its own (prefix "gfmtest-", ports 28xxx and 23030), refuses to start when anything of it exists, and
# removes everything the test made when the test ends. A live system on the same computer is never touched.
INSTALL=$(cd "$HERE/.." && pwd)
REPO=$(cd "$INSTALL/.." && pwd)
WORK="$INSTALL/.work"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;; esac

export GFM_PROJECT_PREFIX=gfmtest- GFM_SUPA_PROJECT=gfmtest GFM_NETWORK=gfmtest-network GFM_OVERRIDE_DIR=install/tests/overrides
export GFM_VOLUMES="gfmtest-portal-data gfmtest-slidev-data"
export GFM_PORTAL_CONTAINER=gfmtest-portal GFM_PORTAL_VOLUME=gfmtest-portal-data GFM_SLIDEV_CONTAINER=gfmtest-slidev GFM_SLIDEV_VOLUME=gfmtest-slidev-data
export GFM_BACKUP_CONTAINER=gfmtest-backup GFM_CLOUDFLARED_CONTAINER=gfmtest-cloudflared GFM_DATAEASE_NAME=gfmtest-dataease GFM_DB_CONTAINER=gfmtest-supabase-db-1
export GFM_DATAEASE_PORT=28088 GFM_DATAEASE_DB_NETWORK=gfmtest-network
export GFM_PORT_KONG=28000 GFM_PORT_PORTAL=28070 GFM_PORT_DECKS=28089 GFM_PORT_IMPORTER=28090 GFM_PORT_SLIDEV=23030 GFM_PORT_DATAEASE=28088
export GFM_SKIP_UPDATER_TASK=yes   # (a test never makes a task in the computer's scheduler)
export GFM_HEALTH_SKIP="Beta Studio"
export GFM_BACKUP_DIR="$REPO/backups/nightly"

failed=0
check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=$((failed + 1)); fi; }
Q() { docker exec -i gfmtest-supabase-db-1 psql -U supabase_admin -d postgres -Atc "$1"; }
memory() { docker run --rm --network none alpine sh -c 'awk "/MemAvailable/ {printf \"%d MB\", \$2/1024}" /proc/meminfo'; }

isolated_guard() {
  local f port
  for f in supabase portal-api roster-importer slidev portal dataease nightly-backup cloudflared; do
    [ ! -e "$REPO/$f/.env" ] || { echo "Refusing: $f/.env exists (this test writes one and removes it)."; exit 2; }
  done
  [ ! -e "$REPO/nightly-backup/secrets/db-password" ] || { echo "Refusing: nightly-backup/secrets/db-password exists."; exit 2; }
  [ -z "$(docker ps -aq --filter name=gfmtest)" ] || { echo "Refusing: containers named gfmtest exist."; exit 2; }
  for port in 25432 28000 28070 28088 28089 28090 23030; do
    (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null && { echo "Refusing: port $port is in use."; exit 2; }
  done
  # Only the containers of the real system are compared (gfm-*, portal*, roster-importer*, slidev*): other containers on this computer,
  # such as gfm-test-* or short-lived ones with random names, come and go on their own.
  live_before=$(docker ps -a --format '{{.ID}} {{.Names}} {{.Image}}' | grep -E ' (gfm-|portal|roster-importer|slidev|supabase)' | grep -v ' gfmtest' | grep -v ' gfm-test-' | sort)
}

live_unchanged() {
  local live_after
  live_after=$(docker ps -a --format '{{.ID}} {{.Names}} {{.Image}}' | grep -E ' (gfm-|portal|roster-importer|slidev|supabase)' | grep -v ' gfmtest' | grep -v ' gfm-test-' | sort)
  [ "$live_before" = "$live_after" ]; check "the live containers are exactly the same as before the test" $?
  [ "$live_before" = "$live_after" ] || diff <(echo "$live_before") <(echo "$live_after") | sed 's/^/      /' | head -10
}

isolated_cleanup() {
  docker ps -aq --filter name=gfmtest | xargs -r docker rm -f >/dev/null 2>&1
  docker network ls --format '{{.Name}}' | grep '^gfmtest' | xargs -r docker network rm >/dev/null 2>&1
  docker volume ls -q --filter name=gfmtest | xargs -r docker volume rm >/dev/null 2>&1
  docker images -q 'gfmtest-*' | sort -u | xargs -r docker rmi >/dev/null 2>&1
  local f
  for f in supabase portal-api roster-importer slidev portal dataease nightly-backup cloudflared; do rm -f "$REPO/$f/.env"; done
  rm -f "$REPO/cloudflared/ROUTES.txt"
  rm -f "$REPO/nightly-backup/secrets/db-password"
  rm -rf "$WORK" "$REPO/backups/nightly" "$REPO/updater/requests" "$REPO/updater/status" "$REPO/updater/logs"
}

write_answers() {
  mkdir -p "$WORK" "$REPO/backups"
  cat > "$WORK/answers.json" <<'JSON'
{ "missionName": "Testland Example Mission", "missionCode": "TEM", "language": "de", "languageRequest": null,
  "admin": { "name": "Test Analyst", "email": "analyst@testland.example", "password": "Fake-Install-Test-2026" },
  "email": null, "publicDomain": "", "timeZone": "America/Denver", "cloudflareToken": "", "logo": null }
JSON
}
