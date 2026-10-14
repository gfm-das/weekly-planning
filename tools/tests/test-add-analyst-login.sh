#!/usr/bin/env bash
# tools/tests/test-add-analyst-login.sh: tests tools/add-analyst-login.sh against a FAKE `docker` (no database, no network, nothing live).
# It checks the script's own work: the name rules, the dry run, the secrets folder rules, that the password goes to a private file and to the
# database program's standard input but never onto a command line or the screen, that a refusal of the database keeps no file, and that a
# reset keeps the old file. The SQL itself needs a real database: install/tests/test-analyst-login.sh.
#   bash tools/tests/test-add-analyst-login.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
SCRIPT="$REPO/tools/add-analyst-login.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=$((failed + 1)); fi; }

# A fake docker: writes down its arguments and its standard input, answers `inspect` with true, and fails when FAKE_FAIL is set and the
# call is the one that makes the login (it runs psql as supabase_admin).
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  inspect) echo true; exit 0 ;;
  exec)
    if [ "$2" = "-i" ]; then { echo "=== call: $*"; cat; } >> "$FAKE_STDIN"; fi
    case "$*" in *supabase_admin*) [ -z "${FAKE_FAIL:-}" ] || { echo "ERROR: fake refusal" >&2; exit 3; } ;; esac
    exit 0 ;;
esac
exit 0
EOF
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH" FAKE_LOG="$TMP/docker.log" FAKE_STDIN="$TMP/stdin.log"
S="$TMP/secrets"
run() { : > "$FAKE_LOG"; : > "$FAKE_STDIN"; bash "$SCRIPT" "$@" </dev/null >"$TMP/out.txt" 2>&1; echo $? > "$TMP/rc"; return 0; }
rc() { cat "$TMP/rc"; }

run anna_k --dry-run --secrets-dir "$S"
[ "$(rc)" = 0 ] && [ ! -s "$FAKE_LOG" ] && grep -q "Dry run" "$TMP/out.txt"; check "dry run: says what it would do and does not call docker" $?
[ ! -e "$S/analyst-anna_k.txt" ]; check "dry run: no password file" $?

for bad in ab Anna anna-k 1anna "anna k" postgres supabase_admin pg_monitor authenticator gfm_db_analysts; do
  run "$bad" --yes --secrets-dir "$S"
  [ "$(rc)" = 2 ] && [ ! -s "$FAKE_LOG" ]; check "the name '$bad' is refused before docker is called" $?
done

run anna_k --yes --secrets-dir "$REPO/tools/zz-secrets-test"
[ "$(rc)" = 2 ] && grep -q "inside the repository" "$TMP/out.txt"; check "a secrets folder inside the repository is refused" $?
rm -rf "$REPO/tools/zz-secrets-test"

run anna_k --secrets-dir "$S"
[ "$(rc)" = 2 ] && grep -q "no terminal" "$TMP/out.txt" && [ ! -e "$S/analyst-anna_k.txt" ]; check "without --yes and without a terminal it refuses" $?

run anna_k --yes --secrets-dir "$S"
[ "$(rc)" = 0 ]; check "create: succeeds against the fake database" $?
FILE="$S/analyst-anna_k.txt"
[ -f "$FILE" ]; check "create: the password file exists outside the repository" $?
PW=$(sed -n 's/^Password:  //p' "$FILE")
[[ "$PW" =~ ^[A-Za-z0-9]{32}$ ]]; check "create: the password is 32 letters and digits" $?
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) ;; *) [ "$(stat -c %a "$FILE")" = 600 ]; check "create: the file is private (mode 600)" $? ;; esac
grep -q "^Login:     anna_k" "$FILE" && grep -q "ssh -L 54322:127.0.0.1:54322" "$FILE"; check "create: the file names the login and the SSH tunnel" $?
grep -q "set analyst_login 'anna_k'" "$FAKE_STDIN" && grep -q "set analyst_action 'create'" "$FAKE_STDIN" && grep -q "CREATE ROLE %I LOGIN" "$FAKE_STDIN"; check "create: the variables and the SQL file go to psql on standard input" $?
grep -q "set analyst_password '$PW'" "$FAKE_STDIN"; check "create: the password goes to psql on standard input" $?
! grep -q "$PW" "$FAKE_LOG"; check "create: the password is on no command line" $?
! grep -q "$PW" "$TMP/out.txt"; check "create: the password is not shown on the screen" $?
grep -q "supabase_admin" "$FAKE_LOG" && grep -q "inspect -f {{.State.Running}} gfm-beta-supabase-db-1" "$FAKE_LOG"; check "create: it uses the default container name from the project name" $?
[ -z "$(ls -A "$S" | grep '^\.analyst-')" ]; check "create: no temporary file is left" $?

run anna_k --reset --yes --secrets-dir "$S"
[ "$(rc)" = 0 ] && [ -f "$FILE.previous" ] && grep -q "set analyst_action 'reset'" "$FAKE_STDIN"; check "reset: new password, the old file is kept as .previous" $?
NEWPW=$(sed -n 's/^Password:  //p' "$FILE"); [ "$NEWPW" != "$PW" ]; check "reset: the password is a new one" $?

rm -rf "$S"
FAKE_FAIL=1 run berta_m --yes --secrets-dir "$S"
[ "$(rc)" != 0 ] && [ ! -e "$S/analyst-berta_m.txt" ] && [ -z "$(ls -A "$S" | grep '^\.analyst-')" ]; check "a refusal by the database keeps no password file and no temporary file" $?
GFM_DB_CONTAINER=other-db run carla_z --yes --secrets-dir "$S"
grep -q "inspect -f {{.State.Running}} other-db" "$FAKE_LOG"; check "GFM_DB_CONTAINER chooses the container" $?
GFM_SUPA_PROJECT=my-stack run dora_p --yes --secrets-dir "$S"
grep -q "my-stack-supabase-db-1" "$FAKE_LOG"; check "GFM_SUPA_PROJECT chooses the container name" $?

# The SQL file: the pieces the shell script relies on.
SQL="$REPO/install/sql/add-analyst-login.sql"
grep -q "BYPASSRLS" "$SQL" && grep -q "IN ROLE gfm_db_analysts" "$SQL" && grep -q "NOSUPERUSER" "$SQL"; check "the SQL makes a BYPASSRLS login in gfm_db_analysts, not a superuser" $?
grep -q "SET LOCAL log_statement = 'none'" "$SQL"; check "the SQL switches statement logging off for its transaction" $?
! grep -qE "password +'[^:]|PASSWORD +'[A-Za-z0-9]" "$SQL"; check "the SQL holds no literal password" $?
! grep -rEq --exclude-dir=tests "(ghp_|BEGIN PRIVATE KEY|PASSWORD '[A-Za-z0-9]{8,}')" "$REPO/tools"; check "no secret in tools/" $?

echo; [ "$failed" = 0 ] && echo "All checks passed." || echo "$failed check(s) failed."
exit "$failed"
