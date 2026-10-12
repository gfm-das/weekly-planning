#!/bin/bash
# Tests of nightly.sh, with stand-ins for the PostgreSQL tools (pg_dump, pg_restore, pg_dumpall): no database, no
# network, nothing outside a temporary folder. The stand-ins are shell functions that write small fake files.
#
# What is checked: the names of the parts, a whole night (dumps, roles, hooks, a target that cannot be reached, the
# retry of only the parts that failed, last-run.txt, the log), a dump without table data, the lock, the 14-day
# clean-up, the first start, and "nightly.sh --now" as a program.
#
# Run it from the repository root, in the backup container's own image:
#   docker run --rm --network none -v "<repository>/nightly-backup:/backup:ro" postgres:15-alpine bash /backup/tests/test-nightly.sh
# (ops-tests/run-all.ps1 does this.) Exit code 0 means every check passed.
set -u -o pipefail

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export BACKUP_DIR=$work/backups HOOKS_DIR=$work/hooks PASSWORD_FILE=$work/db-password
export BACKUP_TARGETS="beta=db-beta production=db-prod:5433/other bad=db-bad"
export RETRIES=1 RETRY_MINUTES=0 KEEP_DAYS=14
mkdir -p "$BACKUP_DIR" "$HOOKS_DIR"
printf 'secret\r\n' > "$PASSWORD_FILE"   # saved with a Windows line ending on purpose
# shellcheck source=../nightly.sh
source "$here/../nightly.sh"             # only the functions: the scheduler does not start

passes=0
failures=0
check() {  # check "what is checked" <command that must succeed>
    local name=$1; shift
    if "$@"; then passes=$((passes + 1)); echo "PASS  $name"; else failures=$((failures + 1)); echo "FAIL  $name"; fi
}
count() { grep -c -- "$1" "$2" 2>/dev/null || true; }
logged() { grep -q -- "$1" "$LOG"; }
not_logged() { ! logged "$1"; }

# ---- the stand-ins -----------------------------------------------------------------------------------------------
pg_dump() {  # writes a small fake dump; "db-bad" cannot be reached, "db-empty" gives a dump without table data
    local host='' port='' db='' file=''
    while [ $# -gt 0 ]; do
        case $1 in -h) host=$2; shift ;; -p) port=$2; shift ;; -d) db=$2; shift ;; -f) file=$2; shift ;; esac
        shift
    done
    echo "pg_dump -h $host -p $port -d $db password=[$PGPASSWORD]" >> "$work/calls"
    [ "$host" = db-bad ] && { echo 'pg_dump: error: could not translate host name "db-bad"' >&2; return 1; }
    [ "$host" = db-empty ] && { echo empty > "$file"; return 0; }
    echo "dump of $host" > "$file"
}
pg_restore() {  # --list <file>: one line per table with data
    grep -q empty "$2" && return 0
    printf '1; 1259 16386 TABLE DATA public areas postgres\n2; 1259 16387 TABLE DATA public zones postgres\n'
}
pg_dumpall() { echo 'CREATE ROLE gfm_dashboard_reader;'; }
export -f pg_dump pg_restore pg_dumpall
export work

# ---- 1. the names of the parts -----------------------------------------------------------------------------------
check 'part names: a target and a hook' [ "$(part_names 'target:beta=h/db' 'hook:/backup/hooks.d/dataease.sh')" = 'beta, hook dataease' ]
check 'part names: one part' [ "$(part_names 'target:beta=h')" = 'beta' ]
check 'part names: none' [ -z "$(part_names)" ]

# ---- 2. a whole night --------------------------------------------------------------------------------------------
printf 'echo "fine" > "$BACKUP_DIR/check-$STAMP.txt"\r\necho fine\r\n' > "$HOOKS_DIR/aok.sh"   # Windows line endings
printf 'echo oops\nexit 3\n' > "$HOOKS_DIR/zfail.sh"
printf 'exit 9\n' > "$HOOKS_DIR/off.sh.example"                                                  # not a hook
backup_night > /dev/null
rc=$?
stamp=$STAMP
check 'a night with a failed part ends with exit code 1' [ "$rc" -eq 1 ]
check 'the Beta dump is there' [ -s "$BACKUP_DIR/beta-$stamp.dump" ]
check 'its roles file is there and is a good gzip file' gzip -t "$BACKUP_DIR/beta-roles-$stamp.sql.gz"
check 'the roles file holds the roles' sh -c "gunzip -c '$BACKUP_DIR/beta-roles-$stamp.sql.gz' | grep -q 'CREATE ROLE'"
check 'the second target is dumped with its own port and database' grep -q 'pg_dump -h db-prod -p 5433 -d other' "$work/calls"
check 'the password reaches pg_dump without the Windows line ending' grep -q 'password=\[secret\]$' "$work/calls"
check 'nothing is dumped for the target that cannot be reached' [ -z "$(ls "$BACKUP_DIR" | grep '^bad-')" ]
check 'no half-written .partial file is left' [ -z "$(ls "$BACKUP_DIR" | grep '\.partial$')" ]
check 'the hook with Windows line endings ran' [ -f "$BACKUP_DIR/check-$stamp.txt" ]
check 'only the parts that failed were tried again' test "$(count 'db-beta' "$work/calls")" -eq 1 -a "$(count 'db-bad' "$work/calls")" -eq 2
check 'the log says what is tried again' logged 'Retry 1 of 1 in 0 min: bad, hook zfail'
check 'the log names the error of the target' logged 'FAILED bad (db-bad/postgres): pg_dump: error: could not translate host name'
check 'the log gives the failing hook, its exit code and its output' logged 'FAILED hook zfail (exit 3): oops'
check 'the log gives the good hook and its last line' logged 'OK hook aok: fine'
check 'the log gives the dump, its size and its tables' logged "OK beta-$stamp.dump [0-9]* kB, 2 tables, [0-9]* s; beta-roles-$stamp.sql.gz"
check 'a file that is not *.sh is not run' not_logged 'hook off'
check 'last-run.txt says FAILED and names the parts' grep -q "^FAILED .*: bad, hook zfail$" "$STATUS"
check 'the lock is gone after the night' [ ! -d "$LOCK" ]

# ---- 3. a dump without table data --------------------------------------------------------------------------------
rm -f "$HOOKS_DIR"/*.sh
BACKUP_TARGETS="empty=db-empty" RETRIES=0 run_night > /dev/null
check 'a dump without table data is refused' logged 'FAILED empty: the dump cannot be read or holds no table data'
check 'and not kept' [ -z "$(ls "$BACKUP_DIR" | grep '^empty-')" ]

# ---- 4. only one backup at a time --------------------------------------------------------------------------------
mkdir "$LOCK"
backup_night > /dev/null
rc=$?
check 'while another backup runs, a second one is skipped' [ "$rc" -eq 1 ]
check 'and the log says so' logged 'Skipped: another backup is running'
rmdir "$LOCK"

# ---- 5. the 14-day clean-up --------------------------------------------------------------------------------------
days_ago() { touch -d "@$(( $(date +%s) - $1 * 86400 ))" "$BACKUP_DIR/$2"; }
days_ago 15 beta-20260901-0230.dump
days_ago 15 beta-roles-20260901-0230.sql.gz
days_ago 13 dataease-20260916-0215.sql.gz
days_ago 30 notes-by-hand.txt
days_ago 2 x-20260927-0230.dump.partial
touch "$BACKUP_DIR/y-20260929-0230.dump.partial"
prune > /dev/null
check 'a dump older than 14 days is deleted' [ ! -e "$BACKUP_DIR/beta-20260901-0230.dump" ]
check 'its roles file too' [ ! -e "$BACKUP_DIR/beta-roles-20260901-0230.sql.gz" ]
check 'a hook file of 13 days is kept' [ -e "$BACKUP_DIR/dataease-20260916-0215.sql.gz" ]
check 'a file put there by hand is never deleted' [ -e "$BACKUP_DIR/notes-by-hand.txt" ]
check 'a forgotten .partial file older than a day is deleted' [ ! -e "$BACKUP_DIR/x-20260927-0230.dump.partial" ]
check 'a new .partial file is kept (a backup may be writing it)' [ -e "$BACKUP_DIR/y-20260929-0230.dump.partial" ]
check 'the log says how many files were deleted' logged 'Deleted 2 file(s) older than 14 days'

# ---- 6. the first start ------------------------------------------------------------------------------------------
rm -f "$STATE"; BACKUP_AT=00:00 remember_first_start
check 'first start after the backup time: tonight counts as done' [ "$(cat "$STATE")" = "$(date +%F)" ]
rm -f "$STATE"; BACKUP_AT=24:00 remember_first_start
check 'first start before the backup time: the backup runs tonight' [ "$(cat "$STATE")" = none ]
echo 2026-01-01 > "$STATE"; BACKUP_AT=00:00 remember_first_start
check 'a later start keeps the date of the last night' [ "$(cat "$STATE")" = 2026-01-01 ]

# ---- 7. "nightly.sh --now" as a program --------------------------------------------------------------------------
rm -rf "$BACKUP_DIR"
BACKUP_TARGETS="beta=db-beta" bash "$here/../nightly.sh" --now > /dev/null
rc=$?
check 'nightly.sh --now makes one backup and ends with exit code 0' [ "$rc" -eq 0 ]
check 'and last-run.txt says OK' grep -q '^OK ' "$BACKUP_DIR/last-run.txt"

echo "Nightly backup tests: $passes passed, $failures did not pass."
[ "$failures" -eq 0 ]
