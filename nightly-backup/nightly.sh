#!/bin/bash
# nightly-backup/nightly.sh: the nightly database backup. It is the whole program of the gfm-backup container
# (backup-compose.yml in this folder). The big picture, restore and tests: README.md in this folder.
#
# Every night at BACKUP_AT (Europe/Berlin, the container's time zone) it writes into BACKUP_DIR (on the server: the
# folder backups\nightly):
#   <name>-<YYYYMMDD-HHMM>.dump            pg_dump -Fc (compressed custom format) of each BACKUP_TARGETS database
#   <name>-roles-<YYYYMMDD-HHMM>.sql.gz    its roles, without passwords (needed to restore on a fresh server)
#   whatever the hooks in HOOKS_DIR write (for example the check of DataEase's backup; see hooks.d/README.md)
# Then it deletes those files once they are older than KEEP_DAYS days, and adds a few lines to nightly.log.
# last-run.txt holds the result of the latest night (health.ps1 shows it in its "Nightly backup" row).
#
# A night missed while Docker was not running is made up as soon as the container starts again. A part that fails
# is tried again every RETRY_MINUTES, at most RETRIES times, without repeating the parts that worked.
#
#   nightly.sh          the scheduler loop (the container's entrypoint)
#   nightly.sh --now    one backup at once, e.g. after the deploy: docker exec gfm-backup /backup/nightly.sh --now
set -u -o pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
BACKUP_AT=${BACKUP_AT:-02:30}
KEEP_DAYS=${KEEP_DAYS:-14}
RETRY_MINUTES=${RETRY_MINUTES:-15}
RETRIES=${RETRIES:-3}
# name=host[:port][/database], separated by spaces. The database defaults to postgres, the user to PGUSER (postgres).
BACKUP_TARGETS=${BACKUP_TARGETS:-beta=gfm-beta-supabase-db-1}
HOOKS_DIR=${HOOKS_DIR:-/backup/hooks.d}
PASSWORD_FILE=${PASSWORD_FILE:-/backup/secrets/db-password}
export PGUSER=${PGUSER:-postgres} PGCONNECT_TIMEOUT=${PGCONNECT_TIMEOUT:-20}

LOG=$BACKUP_DIR/nightly.log
STATUS=$BACKUP_DIR/last-run.txt
STATE=$BACKUP_DIR/.last-night
LOCK=$BACKUP_DIR/.running

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"
    printf '%s\n' "$*"
}

size_of() {  # the size of a file in words: "4.8 MB" from 1 MB on, else "730 kB"
    awk -v b="$(stat -c %s "$1" 2>/dev/null || echo 0)" 'BEGIN { printf (b >= 1048576 ? "%.1f MB" : "%.0f kB"), (b >= 1048576 ? b / 1048576 : b / 1024) }'
}

password() {  # only for the pg_* commands, never in the environment of the container or in the log
    [ -r "$PASSWORD_FILE" ] || { echo "no database password: $PASSWORD_FILE is missing (run set-db-password.ps1)"; return 1; }
    tr -d '\r\n' < "$PASSWORD_FILE"
}

# One database: dump to a .partial file, check that pg_restore can read it and that it holds table data, then give it
# its final name, so a file named *.dump is always complete. Then its roles (dump_roles).
dump_target() {
    local name=${1%%=*} spec=${1#*=} host port db out started pw entries
    host=${spec%%/*}; db=postgres; [ "$spec" != "$host" ] && db=${spec#*/}
    port=5432; [ "${host#*:}" != "$host" ] && { port=${host#*:}; host=${host%%:*}; }
    out="$BACKUP_DIR/$name-$STAMP.dump"
    pw=$(password) || { log "FAILED $name: $pw"; return 1; }
    started=$(date +%s)
    if ! PGPASSWORD=$pw pg_dump -h "$host" -p "$port" -d "$db" -Fc -f "$out.partial" 2> "$BACKUP_DIR/.error"; then
        log "FAILED $name ($host/$db): $(tail -n 2 "$BACKUP_DIR/.error" | tr '\n' ' ')"; rm -f "$out.partial" "$BACKUP_DIR/.error"; return 1
    fi
    entries=$(pg_restore --list "$out.partial" 2> "$BACKUP_DIR/.error" | grep -c ' TABLE DATA ')
    if [ "${entries:-0}" -eq 0 ]; then
        log "FAILED $name: the dump cannot be read or holds no table data ($(tail -n 1 "$BACKUP_DIR/.error"))"
        rm -f "$out.partial" "$BACKUP_DIR/.error"; return 1
    fi
    mv "$out.partial" "$out"
    dump_roles "$name" "$host" "$port" "$db" "$pw" || return 1
    rm -f "$BACKUP_DIR/.error"
    log "OK $(basename "$out") $(size_of "$out"), $entries tables, $(($(date +%s) - started )) s; $name-roles-$STAMP.sql.gz"
}

# The roles of one database server, without passwords, gzipped; written as .partial first, like the dump.
dump_roles() {
    local name=$1 host=$2 port=$3 db=$4 pw=$5
    local roles="$BACKUP_DIR/$name-roles-$STAMP.sql.gz"
    if PGPASSWORD=$pw pg_dumpall -h "$host" -p "$port" -l "$db" --roles-only --no-role-passwords 2> "$BACKUP_DIR/.error" | gzip -6 > "$roles.partial"; then
        mv "$roles.partial" "$roles"
    else
        log "FAILED $name roles: $(tail -n 1 "$BACKUP_DIR/.error")"; rm -f "$roles.partial" "$BACKUP_DIR/.error"; return 1
    fi
}

# One hook: hooks.d/<name>.sh with BACKUP_DIR and STAMP; exit 0 = done. Its output goes to the log (last lines only).
run_hook() {
    local hook=$1 name output
    name=$(basename "$hook" .sh)
    # The hook's text is run without its carriage returns, so a hook saved with Windows line endings (for example
    # from Notepad) still runs.
    if output=$(BACKUP_DIR=$BACKUP_DIR STAMP=$STAMP PASSWORD_FILE=$PASSWORD_FILE bash -c "$(tr -d '\r' < "$hook")" "$hook" 2>&1); then
        log "OK hook $name${output:+: $(printf '%s' "$output" | tail -n 1)}"
    else
        log "FAILED hook $name (exit $?): $(printf '%s' "$output" | tail -n 2 | tr '\n' ' ')"; return 1
    fi
}

# Files named <name>-YYYYMMDD-HHMM.<ext> or <name>-roles-... older than KEEP_DAYS days; nothing else in the folder
# (nightly.log, last-run.txt, files put there by hand) is ever deleted. Also forgotten .partial files.
prune() {
    local old
    old=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9].*' \
          ! -name '*.partial' -mmin +$(( KEEP_DAYS * 1440 )))
    if [ -n "$old" ]; then
        printf '%s\n' "$old" | while IFS= read -r f; do rm -f "$f"; done
        log "Deleted $(printf '%s\n' "$old" | wc -l) file(s) older than $KEEP_DAYS days"
    fi
    find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.partial' -mmin +1440 | while IFS= read -r f; do rm -f "$f"; done
    tail -n 1000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"  # keep the log small
}

# One night, at most one at a time (the loop and a --now run share the folder).
backup_night() {
    local rc
    if ! mkdir "$LOCK" 2>/dev/null; then log "Skipped: another backup is running"; return 1; fi
    run_night; rc=$?
    rmdir "$LOCK" 2>/dev/null
    return $rc
}

# Every target and hook, then the retries of the parts that failed, then the clean-up.
run_night() {
    local pending=() failed=() attempt=0 job
    STAMP=$(date +%Y%m%d-%H%M)
    for job in $BACKUP_TARGETS; do pending+=("target:$job"); done
    for job in "$HOOKS_DIR"/*.sh; do [ -f "$job" ] && pending+=("hook:$job"); done
    log "Backup $STAMP started (${#pending[@]} part(s), keep $KEEP_DAYS days)"
    while :; do
        failed=()
        for job in "${pending[@]}"; do
            case $job in
                target:*) dump_target "${job#target:}" || failed+=("$job") ;;
                hook:*) run_hook "${job#hook:}" || failed+=("$job") ;;
            esac
        done
        [ ${#failed[@]} -eq 0 ] || [ "$attempt" -ge "$RETRIES" ] && break
        attempt=$(( attempt + 1 )); pending=("${failed[@]}")
        log "Retry $attempt of $RETRIES in $RETRY_MINUTES min: $(part_names "${pending[@]}")"
        sleep $(( RETRY_MINUTES * 60 ))
    done
    prune
    if [ ${#failed[@]} -eq 0 ]; then
        printf 'OK %s\n' "$(date -Iseconds)" > "$STATUS"
        log "Backup $STAMP done"
    else
        printf 'FAILED %s: %s\n' "$(date -Iseconds)" "$(part_names "${failed[@]}")" > "$STATUS"
        log "Backup $STAMP FAILED: $(part_names "${failed[@]}")"
        return 1
    fi
}

part_names() {  # target:beta=host/db -> beta; hook:/backup/hooks.d/dataease.sh -> hook dataease
    local j names=()
    for j in "$@"; do
        case $j in
            target:*) j=${j#target:}; names+=("${j%%=*}") ;;
            hook:*) names+=("hook $(basename "${j#hook:}" .sh)") ;;
        esac
    done
    printf '%s' "${names[0]:-}"; [ ${#names[@]} -gt 1 ] && printf ', %s' "${names[@]:1}"; return 0
}

# The very first start: the first backup is the next BACKUP_AT, so a deploy in the evening does not back up at once.
remember_first_start() {
    [ -f "$STATE" ] && return 0
    if [[ ! $(date +%H:%M) < $BACKUP_AT ]]; then date +%F > "$STATE"; else echo none > "$STATE"; fi
}

# The scheduler: looks every 30 seconds. A night is due once BACKUP_AT has passed today and today's night has not run
# yet (this also makes up a night missed while Docker was off). STATE (.last-night) holds the date of the last night.
run_scheduler() {
    local today last
    [[ $BACKUP_AT =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "BACKUP_AT must be HH:MM, not $BACKUP_AT"; exit 1; }
    rmdir "$LOCK" 2>/dev/null  # left by a container stopped in the middle of a backup
    remember_first_start
    log "Scheduler started: every night at $BACKUP_AT ($(date +%Z)), keep $KEEP_DAYS days, targets: $BACKUP_TARGETS"
    while :; do
        today=$(date +%F)
        last=$(cat "$STATE" 2>/dev/null)
        if [[ ! $(date +%H:%M) < $BACKUP_AT ]] && [ "$last" != "$today" ]; then
            backup_night
            echo "$today" > "$STATE"  # done for today, also after the retries failed (last-run.txt says so)
        fi
        sleep 30
    done
}

main() {
    mkdir -p "$BACKUP_DIR"
    if [ "${1:-}" = "--now" ]; then
        backup_night
        exit $?
    fi
    run_scheduler
}

# Started as a program: run. Loaded with "source" (tests/test-nightly.sh): only define the functions.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
