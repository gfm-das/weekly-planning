#!/usr/bin/env bash
# test-dataease.sh: checks the Dashboards part of the installer on its own (DataEase needs about 1.1 GB, so it is not part of
# test-install.sh): the database only, then DataEase with its read-only database login, the three dashboards and their copies in
# the 13 other languages. Everything has names and ports of its own (see _isolated.sh) and is removed at the end.
#   bash install/tests/test-dataease.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$HERE/_isolated.sh"
export GFM_SUPA_SERVICES="supabase-db"

isolated_guard
trap isolated_cleanup EXIT
write_answers

echo "free memory in Docker before: $(memory)"
# shellcheck disable=SC1091
. "$INSTALL/run-install.sh"
set +e
step_generate && step_network && step_supabase && step_database || { echo "FAIL  the database part did not work"; exit 1; }
step_dataease
check "the Dashboards step ran to the end" $?
[ "$(docker exec gfmtest-dataease printenv TZ)" = America/Denver ]; check "DataEase runs in the mission's time zone" $?
echo "free memory in Docker with DataEase running: $(memory)"

echo; echo "---- checks"
# (the gate signs in to DataEase again by itself after the dashboards were changed: give it up to a minute)
g=1; for _ in $(seq 1 20); do curl -s http://127.0.0.1:28088/gfm-gate-health | grep -q '"signed-in"' && { g=0; break; }; sleep 3; done
check "DataEase's gate holds a working DataEase sign-in" $g
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28088/de2api/user/info)" = 401 ]; check "without the portal's cookie DataEase answers 401" $?
GFM_DATAEASE_PROJECT=gfmtest-dataease bash "$REPO/dataease/seed-dashboards.sh" --check --allow-empty >/dev/null 2>&1; check "the three dashboards are there (seed-dashboards --check)" $?
GFM_DATAEASE_PROJECT=gfmtest-dataease bash "$REPO/dataease/translate-dashboards.sh" --check >/dev/null 2>&1; check "their copies in the other languages are there (translate-dashboards --check)" $?
READER=$(GFM_DATAEASE_PROJECT=gfmtest-dataease bash "$REPO/dataease/seed-dashboards.sh" --reader-check 2>&1); r=$?
check "the read-only login may read only what it should (--reader-check)" $r
[ "$r" = 0 ] || echo "$READER" | grep -E "FAIL|ERROR|rror" | sed 's/^/      /' | head -12
live_unchanged

echo; [ "$failed" = 0 ] && echo "All checks passed." || echo "$failed check(s) failed."
exit "$failed"
