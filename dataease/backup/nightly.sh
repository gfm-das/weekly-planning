#!/bin/bash
# gfm-dataease-backup (dataease/compose.yml): every night at BACKUP_AT (Europe/Berlin), what people build in
# Dashboards goes into /backups, the host folder backups\nightly that the nightly job (gfm-backup, nightly-backup/)
# also writes to:
#   dataease-<YYYYMMDD-HHMM>.sql.gz        DataEase's metadata: one consistent mysqldump of the database "dataease"
#                                          (dashboards, charts, datasets, the data source, DataEase's settings)
#   dataease-files-<YYYYMMDD-HHMM>.tgz     its two small file volumes (settings files, pictures in dashboards)
# They are named like the other nightly files, so gfm-backup deletes them after 14 days with the rest.
# dataease-last-run.txt says how the last night went. The gfm-backup hook (nightly-backup/hooks.d/dataease.sh, from
# dataease-sidecar.sh.example) checks it and the newest dump, so a missing or failed DataEase backup turns the
# "Nightly backup" row of health.ps1 to FAIL. It uses DataEase's own MySQL tools (this image is the database's), so
# gfm-backup needs no MySQL client. Restore: dataease/backup-dataease.ps1 -RestoreFrom <.sql.gz> [-FilesFrom <.tgz>].
#   docker exec gfm-dataease-backup /backup/nightly.sh --now      one backup now (a test, or before a change)
# Never prints the password (MYSQL_PWD comes from dataease/.env through compose).
set -u -o pipefail
DIR=${BACKUP_DIR:-/backups}
AT=${BACKUP_AT:-02:15}
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

backup() {
    local stamp sql files size
    stamp=$(date +%Y%m%d-%H%M)
    sql="$DIR/dataease-$stamp.sql.gz"
    files="$DIR/dataease-files-$stamp.tgz"
    if ! mysqldump -h "${DB_HOST:-mysql}" -uroot --single-transaction --routines --triggers --events \
            --set-gtid-purged=OFF --databases dataease 2>/tmp/dataease-dump.err | gzip -6 > "$sql.partial"; then
        rm -f "$sql.partial"
        echo "FAILED $stamp: mysqldump: $(tail -n 1 /tmp/dataease-dump.err)" > "$DIR/dataease-last-run.txt"
        log "FAILED: mysqldump: $(tail -n 1 /tmp/dataease-dump.err)"
        return 1
    fi
    size=$(stat -c %s "$sql.partial")
    if ! gzip -t "$sql.partial" || [ "$size" -lt 1000 ]; then
        rm -f "$sql.partial"
        echo "FAILED $stamp: the dump is damaged or empty ($size bytes)" > "$DIR/dataease-last-run.txt"
        log "FAILED: the dump is damaged or empty ($size bytes)"
        return 1
    fi
    mv "$sql.partial" "$sql"
    if ! tar -czf "$files.partial" -C /dataease conf static 2>/tmp/dataease-tar.err; then
        rm -f "$files.partial"
        echo "FAILED $stamp: files: $(tail -n 1 /tmp/dataease-tar.err)" > "$DIR/dataease-last-run.txt"
        log "FAILED: files: $(tail -n 1 /tmp/dataease-tar.err)"
        return 1
    fi
    mv "$files.partial" "$files"
    echo "OK $stamp: $(basename "$sql") $(du -k "$sql" | cut -f1) kB, $(basename "$files") $(du -k "$files" | cut -f1) kB" > "$DIR/dataease-last-run.txt"
    log "$(cat "$DIR/dataease-last-run.txt")"
}

if [ "${1:-}" = "--now" ]; then backup; exit $?; fi

trap 'exit 0' TERM INT
log "DataEase nightly backup: every night at $AT ($(date +%Z)) into backups\\nightly."
while true; do
    now=$(date +%s)
    next=$(date -d "today $AT" +%s)
    [ "$next" -gt "$now" ] || next=$(date -d "tomorrow $AT" +%s)
    sleep $((next - now)) & wait $!
    # Two more tries, 15 minutes apart (DataEase's database may be restarting).
    backup || { sleep 900 & wait $!; backup; } || { sleep 900 & wait $!; backup; } || true
done
