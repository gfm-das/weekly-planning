#!/usr/bin/env bash
# test-cloudflared.sh: checks the Cloudflare tunnel step of the installer for real, with everything under names of its own (see
# _isolated.sh), in two runs:
#   1. no tunnel token: the step says it is skipped, nothing is written, no container exists, the health row says SKIPPED;
#   2. a token of the right form but made up (so the tunnel cannot connect; a real connection needs a real tunnel): the settings file
#      and the routes list are written, the container is started with the token in it, the token is never printed, the health row says
#      WARNING (not OK, and never FAIL: the office network works without a tunnel).
# It starts only the tunnel container (cloudflare/cloudflared, about 30 MB) and removes everything it made.
#   bash install/tests/test-cloudflared.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$HERE/_isolated.sh"

isolated_guard
trap isolated_cleanup EXIT
# shellcheck disable=SC1091
. "$INSTALL/run-install.sh"
set +e

answers() {  # answers TOKEN: the answers file, with a public web name (a tunnel needs one)
  mkdir -p "$WORK" "$REPO/backups"
  cat > "$WORK/answers.json" <<JSON
{ "missionName": "Testland Example Mission", "missionCode": "TEM", "language": "de", "languageRequest": null,
  "admin": { "name": "Test Analyst", "email": "analyst@testland.example", "password": "Fake-Install-Test-2026" },
  "email": null, "publicDomain": "testland.example", "timeZone": "Europe/Berlin", "cloudflareToken": "$1", "logo": null }
JSON
}
clear_settings() {
  local f
  for f in supabase portal-api roster-importer slidev portal dataease nightly-backup cloudflared; do rm -f "$REPO/$f/.env"; done
  rm -f "$REPO/nightly-backup/secrets/db-password" "$REPO/cloudflared/ROUTES.txt"
}
row() { GFM_BACKUP_DIR=/nonexistent bash "$REPO/health.sh" 2>/dev/null | grep "^Cloudflare tunnel" | sed 's/  */ /g'; }

echo "---- run 1: no token"
answers ""
step_generate >/dev/null 2>&1; check "the settings were written" $?
[ ! -e "$REPO/cloudflared/.env" ]; check "no cloudflared/.env without a token" $?
OUT=$(step_cloudflare 2>&1)
echo "$OUT" | grep -q "Skipped: no tunnel token"; check "the step says it is skipped" $?
[ -z "$(docker ps -aq --filter name=gfmtest-cloudflared)" ]; check "no tunnel container exists" $?
[ ! -e "$REPO/cloudflared/ROUTES.txt" ]; check "no routes list is written" $?
row | grep -q "SKIPPED"; check "the health row says SKIPPED ($(row))" $?
clear_settings

echo; echo "---- run 2: a made-up token"
TOKEN=$(printf '{"a":"%s","t":"6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10","s":"%s"}' "$(printf 'a%.0s' $(seq 1 32))" "c2VjcmV0c2VjcmV0c2VjcmV0" | base64 | tr -d '\n=')
answers "$TOKEN"
step_generate >/dev/null 2>&1; check "the settings were written" $?
[ "$(grep -c '^TUNNEL_TOKEN=' "$REPO/cloudflared/.env")" = 1 ]; check "cloudflared/.env holds the token" $?
OUT=$(step_cloudflare 2>&1)
echo "$OUT" | sed 's/^/    /'
[ -n "$(docker ps -aq --filter name=gfmtest-cloudflared)" ]; check "the tunnel container was made" $?
docker inspect gfmtest-cloudflared --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^TUNNEL_TOKEN=.'; check "the token reached the container as TUNNEL_TOKEN" $?
[ "$(docker inspect gfmtest-cloudflared --format '{{.HostConfig.RestartPolicy.Name}}')" = unless-stopped ]; check "it restarts by itself (unless-stopped)" $?
echo "$OUT" | grep -qF "$TOKEN"; [ $? -ne 0 ]; check "the installer did not print the token" $?
# (the test copy listens on other ports than 8070 and 8088: the list names the ports of the install it was written for)
[ -f "$REPO/cloudflared/ROUTES.txt" ] && grep -q "^dashboards.testland.example *http://host.docker.internal:$GFM_PORT_DATAEASE " "$REPO/cloudflared/ROUTES.txt" && grep -q "^testland.example *http://host.docker.internal:$GFM_PORT_PORTAL " "$REPO/cloudflared/ROUTES.txt" && [ "$(grep -c host.docker.internal "$REPO/cloudflared/ROUTES.txt")" = 6 ]; check "ROUTES.txt lists the portal and Dashboards (and the other four) with the public name" $?
grep -qF "$TOKEN" "$REPO/cloudflared/ROUTES.txt"; [ $? -ne 0 ]; check "ROUTES.txt holds no token" $?
echo "$OUT" | grep -q "add these routes"; check "the routes are printed for the person to enter in Cloudflare" $?
echo "health row: $(row)"
# (a tunnel that cannot connect keeps restarting, so the row changes between "waiting" and WARNING: look at what was seen when the loop stopped)
seen=""
for _ in $(seq 1 60); do seen=$(row); echo "$seen" | grep -q "WARNING" && break; sleep 4; done
echo "health row later: $seen"
echo "$seen" | grep -q "WARNING"; check "the health row becomes a WARNING (never OK) for a tunnel that cannot connect" $?
echo "$seen" | grep -q "OK"; [ $? -ne 0 ]; check "and it is never OK" $?
echo "$seen" | grep -q "FAIL"; [ $? -ne 0 ]; check "and it is never a FAIL" $?
docker logs gfmtest-cloudflared 2>&1 | grep -qF "$TOKEN"; [ $? -ne 0 ]; check "the token is not in the container's log" $?
live_unchanged

echo; [ "$failed" = 0 ] && echo "All checks passed." || echo "$failed check(s) failed."
exit "$failed"
