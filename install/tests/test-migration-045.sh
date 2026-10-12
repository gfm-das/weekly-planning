#!/usr/bin/env bash
# test-migration-045.sh: checks migration 045 (the database counts in the mission's time zone) on a throw-away database built the way
# the installer builds it (baseline, then migrations 041 to 044, each followed by 019). Checks that:
#   - for Europe/Berlin every result is exactly what the old text gave (reporting_sunday_at on thousands of moments, over both clock changes);
#   - another zone moves the week boundary, and changing the mission's zone changes it back;
#   - the roles that need it can run gfm_time_zone() and read the dashboards views, the reader still cannot read missions;
#   - 019 (the rights check) still passes;
#   - the rollback puts back every changed definition exactly (compared one by one), and 045 can be applied again.
# One container (about 500 MB), removed at the end.     bash install/tests/test-migration-045.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;; esac
NAME=gfm-test-migration-045
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=$((failed + 1)); fi; }
docker rm -f "$NAME" >/dev/null 2>&1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=x --memory 1g supabase/postgres:15.8.1.085 >/dev/null || exit 1
psql_admin() { docker exec -i "$NAME" psql -h 127.0.0.1 -U supabase_admin -d postgres -v ON_ERROR_STOP=1 "$@"; }
Q() { psql_admin -At -c "$1"; }
for _ in $(seq 1 60); do docker exec "$NAME" pg_isready -h 127.0.0.1 -U supabase_admin >/dev/null 2>&1 && break; sleep 2; done
for _ in $(seq 1 30); do Q "select 1 from pg_roles where rolname='supabase_auth_admin'" 2>/dev/null | grep -q 1 && break; sleep 2; done

M="$REPO/portal-api/migrations"
psql_admin -q --single-transaction < "$REPO/portal-api/baseline/000_baseline.sql" >/dev/null || { echo "FAIL  the baseline did not apply"; exit 1; }
psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null
for f in 041_no_new_member_delete 042_prefill_person_answers 043_mission_default_language 044_dashboard_reader_settings; do
  psql_admin -q < "$M/$f.sql" >/dev/null && psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null || { echo "FAIL  $f did not apply"; exit 1; }
done

# The changed objects, by a stable name, with a fingerprint of each definition (carriage returns left out: some of the old function
# texts have Windows line ends inside them, which the migration files do not keep; that changes nothing in what they do).
FINGERPRINTS="select 'view '||c.oid::regclass::text||' '||md5(pg_get_viewdef(c.oid)||coalesce(c.reloptions::text,'')) from pg_class c join pg_namespace n on n.oid=c.relnamespace where c.relkind='v' and n.nspname in ('public','dashboards') and c.relname in ('current_baptismal_date_people','current_new_members','baptism_history_week','findechristus_referrals_week','finding_area_week','finding_cohort_week','finding_rate_week','people_area_week_counts','referral_archive_week','zone_history_week') union all select 'function '||p.oid::regprocedure::text||' '||md5(replace(pg_get_functiondef(p.oid), chr(13), '')) from pg_proc p where p.proname in ('area_week_rows','reporting_sunday_at') order by 1"
before=$(Q "$FINGERPRINTS")
[ "$(echo "$before" | wc -l)" = 12 ]; check "12 objects will change (10 views, 2 functions)" $?

# A set of moments, in both directions of the clock change and around every Sunday midnight in the mission's zone.
MOMENTS="generate_series(timestamptz '2025-01-01 00:00+00', timestamptz '2027-12-31 23:00+00', interval '37 minutes') t"
OLD_RESULTS=$(Q "select md5(string_agg(((t AT TIME ZONE 'Europe/Berlin')::date - extract(dow FROM (t AT TIME ZONE 'Europe/Berlin'))::integer)::text, ',' order by t)) from $MOMENTS")

psql_admin -q < "$M/045_mission_time_zone.sql" >/dev/null; check "045 applies" $?
psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null; check "019 (the rights check) passes after 045" $?
[ "$(Q "select count(*) from pg_class c where c.relkind='v' and pg_get_viewdef(c.oid) ilike '%Europe/Berlin%'")" = 0 ]; check "no view still has the text Europe/Berlin written in" $?
[ "$(Q "select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','dashboards','portal') and p.proname in ('area_week_rows','reporting_sunday_at') and pg_get_functiondef(p.oid) ilike '%Europe/Berlin%'")" = 0 ]; check "the two functions use gfm_time_zone()" $?
[ "$(Q "select public.gfm_time_zone()")" = "Europe/Berlin" ]; check "with no mission yet the zone is Europe/Berlin" $?
NEW_RESULTS=$(Q "select md5(string_agg(public.reporting_sunday_at(t)::text, ',' order by t)) from $MOMENTS")
[ "$OLD_RESULTS" = "$NEW_RESULTS" ]; check "Europe/Berlin: reporting_sunday_at gives exactly the old answer for $(Q "select count(*) from $MOMENTS") moments" $?

psql_admin -q -c "insert into public.missions(id,name,time_zone) values (1,'Test','America/Denver')"
[ "$(Q "select public.gfm_time_zone()")" = "America/Denver" ]; check "the mission's zone is read from its row" $?
# 2026-09-27 05:30 UTC: Sunday 07:30 in Berlin, but still Saturday 23:30 in Denver (summer time, UTC-6): the week's Sunday is the 20th there.
[ "$(Q "select public.reporting_sunday_at(timestamptz '2026-09-27 05:30+00')")" = "2026-09-20" ]; check "America/Denver: Saturday night belongs to the week of the 20th" $?
psql_admin -q -c "update public.missions set time_zone='Europe/Berlin' where id=1"
[ "$(Q "select public.reporting_sunday_at(timestamptz '2026-09-27 05:30+00')")" = "2026-09-27" ]; check "back to Europe/Berlin: the same moment belongs to the week of the 27th" $?
psql_admin -q -c "update public.missions set time_zone='Not a zone!' where id=1" >/dev/null 2>&1; [ $? -ne 0 ]; check "a text that is not a zone name is refused by the table" $?
psql_admin -q -c "update public.missions set time_zone='Mars/Olympus' where id=1" >/dev/null 2>&1
Q "select public.reporting_sunday_at(now())" >/dev/null 2>&1; [ $? -ne 0 ]; check "a well-formed but unknown zone fails loudly, it is not guessed" $?
psql_admin -q -c "update public.missions set time_zone='Europe/Berlin' where id=1"

# Rights: the roles that need the function can run it; the reader still cannot read missions.
for role in anon authenticated service_role gfm_dashboard_reader; do
  [ "$(Q "set role $role; select public.gfm_time_zone()" | tail -1)" = "Europe/Berlin" ]; check "$role can run gfm_time_zone()" $?
done
Q "set role gfm_dashboard_reader; select count(*) from dashboards.finding_area_week; select count(*) from dashboards.zone_history_week" >/dev/null 2>&1; check "the dashboards reader can read the changed dashboards views" $?
Q "set role gfm_dashboard_reader; select count(*) from public.missions" >/dev/null 2>&1; [ $? -ne 0 ]; check "the dashboards reader still cannot read the missions table" $?
Q "set role authenticated; select count(*) from public.current_new_members; select count(*) from public.current_baptismal_date_people" >/dev/null 2>&1; check "a signed-in role can read the two changed security_invoker views" $?

# Rollback: every definition is exactly the old one again.
psql_admin -q < "$M/045_mission_time_zone_rollback.sql" >/dev/null; check "the rollback applies" $?
psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null; check "019 passes after the rollback" $?
after=$(Q "$FINGERPRINTS")
[ "$before" = "$after" ]; check "after the rollback all 12 definitions are exactly as before" $?
[ "$before" = "$after" ] || diff <(echo "$before") <(echo "$after") | sed 's/^/      /' | head -6
[ "$(Q "select count(*) from pg_proc where proname='gfm_time_zone'")" = 0 ]; check "the function is gone after the rollback" $?
[ "$(Q "select count(*) from information_schema.columns where table_name='missions' and column_name='time_zone'")" = 0 ]; check "the column is gone after the rollback" $?
psql_admin -q < "$M/045_mission_time_zone.sql" >/dev/null && psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null; check "045 can be applied again after a rollback" $?

echo; [ "$failed" = 0 ] && echo "All checks passed." || echo "$failed check(s) failed."
exit "$failed"
