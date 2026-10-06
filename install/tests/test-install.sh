#!/usr/bin/env bash
# test-install.sh: runs the whole installer (run-install.sh) for real on a computer that may already run a live system, with
# everything the test makes under other names (see _isolated.sh). It starts the database, Auth, the REST layer and Kong, then
# portal-api, DA Management, Presentations, the portal and the backup (about 2 GB), skips Dashboards (DataEase: test-dataease.sh
# checks it on its own), checks the result, and removes everything it made. It also checks that the live containers are exactly
# the same before and after.        bash install/tests/test-install.sh     (the first run builds images: several minutes)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$HERE/_isolated.sh"
export GFM_SUPA_SERVICES="supabase-db supabase-auth supabase-rest supabase-kong" GFM_SKIP_DATAEASE=yes

isolated_guard
trap isolated_cleanup EXIT
write_answers

echo "free memory in Docker before: $(memory)"
bash "$INSTALL/run-install.sh" 2>&1 | tee "$REPO/backups/last-install-test.log" | sed -e 's/^/    /'
check "the installer ran to the end" "${PIPESTATUS[0]}"
echo "free memory in Docker after: $(memory)"

echo; echo "---- checks"
[ "$(Q "select id||'|'||name||'|'||default_language||'|'||time_zone from public.missions order by id")" = "1|Testland Example Mission|de|America/Denver" ]; check "mission 1 with the typed name, language and time zone" $?
[ "$(Q "select app_role||'|'||home_mission_id from public.user_profiles")" = "DATA_ADMIN|1" ]; check "the first Data Analyst has a profile" $?
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28070/)" = 200 ]; check "the portal opens" $?
curl -s http://127.0.0.1:28070/site-config.js | grep -q 'defaultLanguage: "de"'; check "the portal's site-config.js carries the mission's language (de)" $?
curl -s http://127.0.0.1:28070/ | grep -q 'eyJ'; check "the portal page carries the public Supabase key" $?
curl -s http://127.0.0.1:28070/site-config.js | grep -q 'missionName: "Testland Example Mission"'; check "the portal's site-config.js carries the mission's name (the pages show it, not the Frankfurt name)" $?
curl -s http://127.0.0.1:28070/site-config.js | grep -q 'timeZone: "America/Denver"'; check "the portal's site-config.js carries the mission's time zone" $?
[ "$(docker exec gfmtest-portal-api python -c "import mission_time; print(mission_time.NAME)")" = America/Denver ]; check "portal-api counts in the mission's time zone" $?
[ "$(docker exec gfmtest-roster-importer-roster-importer-1 python -c "import settings; print(settings.TIME_ZONE_NAME)" 2>/dev/null)" = America/Denver ]; check "DA Management counts in the mission's time zone" $?
[ "$(Q "select public.gfm_time_zone()")" = America/Denver ]; check "the database counts in the mission's time zone (gfm_time_zone())" $?
[ "$(docker exec gfmtest-backup printenv TZ)" = America/Denver ]; check "the nightly backup runs in the mission's time zone" $?
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28090/health)" = 200 ]; check "DA Management answers" $?
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:23030/)" = 200 ]; check "Presentations answer" $?

ANON=$(grep '^SERVICE_SUPABASEANON_KEY=' "$REPO/supabase/.env" | cut -d= -f2)
TOKEN=$(curl -s -X POST "http://127.0.0.1:28070/auth/v1/token?grant_type=password" -H "apikey: $ANON" -H 'Content-Type: application/json' \
  -d '{"email":"analyst@testland.example","password":"Fake-Install-Test-2026"}' | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
[ -n "$TOKEN" ]; check "signing in through the portal's own address works (nginx, Kong, Auth)" $?
OVERVIEW=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28070/api/overview -H "Authorization: Bearer $TOKEN")
[ "$OVERVIEW" = 200 ]; check "portal-api accepts the first Data Analyst (/api/overview: $OVERVIEW)" $?
curl -s http://127.0.0.1:28070/api/languages -H "Authorization: Bearer $TOKEN" | grep -q '"primary":"de"'; check "portal-api's default language for a person with none is the mission's (de)" $?
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28070/api/overview)" = 401 ]; check "without a sign-in the portal refuses (401)" $?
[ -f "$WORK/answers.json" ] && r=1 || r=0; check "the answers file (with the password) is deleted at the end" $r
live_unchanged

echo; [ "$failed" = 0 ] && echo "All checks passed." || echo "$failed check(s) failed."
exit "$failed"
