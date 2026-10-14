#!/usr/bin/env bash
# test-analyst-login.sh: tests tools/add-analyst-login.sh and install/sql/add-analyst-login.sql on a THROW-AWAY database built the way the
# installer builds it (baseline, then every migration newer than 040, each followed by 019). Checks that:
#   - the script makes a login that can connect with the generated password and READ, WRITE, CREATE and DROP in public, portal and dashboards;
#   - the login has BYPASSRLS, is in gfm_db_analysts, is not a superuser, cannot create a role, cannot create objects in auth or storage;
#   - a table made later by supabase_admin (like a new migration does) is open to the login at once (default rights of migration 043);
#   - a second create with the same name is refused, a reset gives a new password (the old one stops working), a system name is refused;
#   - 019 (the rights check) still passes after the login exists, and the generated password appears in no database log line.
# One container (about 500 MB), removed at the end. Needs Docker and the image supabase/postgres:15.8.1.085. Never touches a live database.
#   bash install/tests/test-analyst-login.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;; esac
NAME=gfm-test-analyst-login
SECRETS=$(mktemp -d)
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=$((failed + 1)); fi; }
docker rm -f "$NAME" >/dev/null 2>&1
trap 'docker rm -f "$NAME" >/dev/null 2>&1; rm -rf "$SECRETS"' EXIT
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=x --memory 1g supabase/postgres:15.8.1.085 >/dev/null || exit 1
psql_admin() { docker exec -i "$NAME" psql -h 127.0.0.1 -U supabase_admin -d postgres -v ON_ERROR_STOP=1 "$@"; }
Q() { psql_admin -At -c "$1"; }
# As the new login: the password is sent on standard input.
as_login() {  # as_login <login> <password> <sql>
  printf '%s\n' "$2" | docker exec -i "$NAME" sh -c 'read -r PGPASSWORD; export PGPASSWORD; exec psql -X -q -At -h 127.0.0.1 -U "$1" -d postgres -v ON_ERROR_STOP=1 -c "$2"' sh "$1" "$3"
}
for _ in $(seq 1 60); do docker exec "$NAME" pg_isready -h 127.0.0.1 -U supabase_admin >/dev/null 2>&1 && break; sleep 2; done
for _ in $(seq 1 30); do Q "select 1 from pg_roles where rolname='supabase_auth_admin'" 2>/dev/null | grep -q 1 && break; sleep 2; done

M="$REPO/portal-api/migrations"
psql_admin -q --single-transaction < "$REPO/portal-api/baseline/000_baseline.sql" >/dev/null || { echo "FAIL  the baseline did not apply"; exit 1; }
psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null
for f in "$M"/[0-9][0-9][0-9]_*.sql; do
  n=$(basename "$f"); case "$n" in *_rollback.sql|019_*) continue ;; esac
  [ "${n%%_*}" -gt 40 ] || continue
  psql_admin -q < "$f" >/dev/null && psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null || { echo "FAIL  $n did not apply"; exit 1; }
done
[ "$(Q "select count(*) from pg_roles where rolname='gfm_db_analysts'")" = 1 ]; check "the group role gfm_db_analysts exists (migration 043)" $?

export GFM_DB_CONTAINER="$NAME"
bash "$REPO/tools/add-analyst-login.sh" test_analyst --yes --secrets-dir "$SECRETS" >"$SECRETS/out.txt" 2>&1; check "the script makes the login" $?
PW=$(sed -n 's/^Password:  //p' "$SECRETS/analyst-test_analyst.txt")
[ "${#PW}" = 32 ]; check "a 32-character password was written to a file outside the repository" $?
! grep -q "$PW" "$SECRETS/out.txt"; check "the password was not printed" $?
[ "$(Q "select rolbypassrls and rolcanlogin and not rolsuper and not rolcreaterole and not rolcreatedb and pg_has_role(rolname,'gfm_db_analysts','member') from pg_roles where rolname='test_analyst'")" = t ]; check "BYPASSRLS login, member of gfm_db_analysts, not a superuser" $?

[ "$(as_login test_analyst "$PW" "select current_user")" = test_analyst ]; check "the login connects with the generated password (scram, over TCP)" $?
for schema in public portal dashboards; do
  as_login test_analyst "$PW" "create table $schema.zz_check(x int); insert into $schema.zz_check values (1),(2); update $schema.zz_check set x=3 where x=1; delete from $schema.zz_check where x=2; select count(*) from $schema.zz_check; drop table $schema.zz_check" >/dev/null; check "it can create, write, read and drop in $schema" $?
done
[ "$(as_login test_analyst "$PW" "select count(*) from public.missions")" -ge 0 ] 2>/dev/null; check "it can read an existing table (public.missions)" $?
as_login test_analyst "$PW" "update public.planning_questions set help_text = help_text where false; select count(*) from public.planning_questions" >/dev/null; check "it can read and write the planning catalogue tables" $?
as_login test_analyst "$PW" "create role zz_evil" >/dev/null 2>&1; [ $? -ne 0 ]; check "it cannot create roles" $?
as_login test_analyst "$PW" "create table auth.zz_evil(x int)" >/dev/null 2>&1; [ $? -ne 0 ]; check "it cannot create objects in Supabase's auth schema" $?
as_login test_analyst "$PW" "create table storage.zz_evil(x int)" >/dev/null 2>&1; [ $? -ne 0 ]; check "it cannot create objects in Supabase's storage schema" $?

psql_admin -q -c "create table public.zz_later(x int); create table portal.zz_later(x int); create table dashboards.zz_later(x int)" >/dev/null
as_login test_analyst "$PW" "select count(*) from public.zz_later; select count(*) from portal.zz_later; select count(*) from dashboards.zz_later" >/dev/null; check "tables made later by supabase_admin are open to the login at once" $?
psql_admin -q -c "drop table public.zz_later; drop table portal.zz_later; drop table dashboards.zz_later" >/dev/null

bash "$REPO/tools/add-analyst-login.sh" test_analyst --yes --secrets-dir "$SECRETS" >/dev/null 2>&1; [ $? -ne 0 ]; check "a second create with the same name is refused" $?
[ "$(sed -n 's/^Password:  //p' "$SECRETS/analyst-test_analyst.txt")" = "$PW" ]; check "...and the password file is unchanged" $?
bash "$REPO/tools/add-analyst-login.sh" postgres --yes --secrets-dir "$SECRETS" >/dev/null 2>&1; [ $? -ne 0 ]; check "the name 'postgres' is refused" $?
bash "$REPO/tools/add-analyst-login.sh" nobody_here --reset --yes --secrets-dir "$SECRETS" >/dev/null 2>&1; [ $? -ne 0 ]; check "a reset of a login that does not exist is refused" $?

bash "$REPO/tools/add-analyst-login.sh" test_analyst --reset --yes --secrets-dir "$SECRETS" >/dev/null 2>&1; check "a reset works" $?
NEW=$(sed -n 's/^Password:  //p' "$SECRETS/analyst-test_analyst.txt")
[ "$NEW" != "$PW" ] && [ "$(as_login test_analyst "$NEW" "select current_user")" = test_analyst ]; check "the new password works" $?
as_login test_analyst "$PW" "select 1" >/dev/null 2>&1; [ $? -ne 0 ]; check "the old password no longer works" $?

psql_admin -q < "$M/019_restrict_public_functions.sql" >/dev/null; check "019 (the rights check) still passes with the login present" $?
! docker logs "$NAME" 2>&1 | grep -qE "$PW|$NEW"; check "neither password appears in the database log" $?

echo; [ "$failed" = 0 ] && echo "All checks passed." || echo "$failed check(s) failed."
exit "$failed"
