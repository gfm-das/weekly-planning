#!/usr/bin/env bash
# watchdog.sh: protects the live system while test copies of it run next to it (install/tests/test-*.sh), for example overnight.
# Every 60 seconds it (1) reads the live system's health (health.sh, default ports and names: it only looks) and (2) the free memory of
# Docker. When the live system shows a FAIL three checks in a row, or less than 600 MB of memory is free twice in a row, it removes
# every container, network and volume whose name starts with "gfmtest" (the test copies, never anything else), writes a TRIPPED file and
# keeps watching. It never starts, stops, restarts or changes a live container.
#   bash install/tests/watchdog.sh start      starts it in the background (log: backups/watchdog.log in the repository folder)
#   bash install/tests/watchdog.sh status     is it running, what did it last see, has it tripped
#   bash install/tests/watchdog.sh stop       stops it
#   (run is the loop itself, used by start)
# A test script that wants to be careful checks:  [ ! -e backups/watchdog.TRIPPED ]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
LOG="$REPO/backups/watchdog.log"
PIDFILE="$REPO/backups/watchdog.pid"
TRIPPED="$REPO/backups/watchdog.TRIPPED"
LIVE_BACKUPS=${GFM_LIVE_BACKUP_DIR:-/c/GFM/gfm-platform/backups/nightly}
MIN_MB=${GFM_WATCHDOG_MIN_MB:-600}
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;; esac

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
log() { mkdir -p "$REPO/backups"; printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }

free_mb() { docker run --rm --network none alpine sh -c 'awk "/MemAvailable/ {printf \"%d\", \$2/1024}" /proc/meminfo' 2>/dev/null; }

# FAIL rows of the live health check (empty = fine). The test copies' names and ports are not in the environment here.
live_fails() {
  env -u GFM_PORT_KONG -u GFM_PORT_PORTAL -u GFM_PORT_DECKS -u GFM_PORT_IMPORTER -u GFM_PORT_SLIDEV -u GFM_PORT_DATAEASE \
      -u GFM_SLIDEV_CONTAINER -u GFM_BACKUP_CONTAINER -u GFM_DATAEASE_NAME -u GFM_CLOUDFLARED_CONTAINER -u GFM_HEALTH_SKIP \
      GFM_BACKUP_DIR="$LIVE_BACKUPS" bash "$REPO/health.sh" 2>/dev/null | grep -E "FAIL|Unstable" | grep -v "^gfmtest" | sed 's/  */ /g' | head -5
}

trip() {  # trip REASON: remove the test copies only
  log "TRIPPED: $1. Removing the test copies (names starting with gfmtest)."
  echo "$(stamp) $1" >> "$TRIPPED"
  docker ps -aq --filter name=gfmtest | xargs -r docker rm -f >/dev/null 2>&1
  docker network ls --format '{{.Name}}' | grep '^gfmtest' | xargs -r docker network rm >/dev/null 2>&1
  docker volume ls -q --filter name=gfmtest | xargs -r docker volume rm >/dev/null 2>&1
  log "test copies removed."
}

run() {
  log "watchdog started (pid $$): live health every 60 s, memory floor ${MIN_MB} MB"
  local fails=0 low=0 f m
  while :; do
    f=$(live_fails)
    if [ -n "$f" ]; then fails=$((fails + 1)); log "live system: problem $fails of 3: $(echo "$f" | tr '\n' ';')"; else fails=0; fi
    m=$(free_mb); m=${m:-99999}
    if [ "$m" -lt "$MIN_MB" ]; then low=$((low + 1)); log "memory: only $m MB free ($low of 2)"; else low=0; fi
    [ "$fails" -ge 3 ] && { trip "the live system showed a problem 3 checks in a row"; fails=0; }
    [ "$low" -ge 2 ] && { trip "less than ${MIN_MB} MB of memory free twice in a row"; low=0; }
    echo "$(stamp) live=$([ -z "$f" ] && echo ok || echo PROBLEM) free=${m}MB tests=$(docker ps -q --filter name=gfmtest | wc -l)" > "$REPO/backups/watchdog.last"
    sleep 60
  done
}

case "${1:-}" in
  start)
    mkdir -p "$REPO/backups"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    nohup bash "$0" run >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
    sleep 2; echo "watchdog started (pid $(cat "$PIDFILE")); log: $LOG" ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "running (pid $(cat "$PIDFILE"))"; else echo "NOT running"; fi
    [ -f "$REPO/backups/watchdog.last" ] && echo "last look: $(cat "$REPO/backups/watchdog.last")"
    [ -f "$TRIPPED" ] && { echo "TRIPPED:"; cat "$TRIPPED"; } || echo "never tripped"
    tail -5 "$LOG" 2>/dev/null ;;
  stop)
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; rm -f "$PIDFILE"; log "watchdog stopped"; echo stopped ;;
  run) run ;;
  *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
