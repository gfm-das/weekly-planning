#!/usr/bin/env bash
# updater/tests/test-prune.sh: the way-back pruning of gfm-updater.sh must never make an update refuse, even when a folder cannot be
# removed (v1.0.6 refused every update with "rollback_point_failed" when old quick-test copies held files owned by root).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
REPO=$TMP; BACKUPS=$TMP/backups/updater; mkdir -p "$BACKUPS"
log() { :; }
eval "$(sed -n '/^prune_rollback_points()/,/^}/p' "$HERE/../gfm-updater.sh")"
rm() { case "$*" in *-tests*) return 1 ;; esac; command rm "$@"; }   # the stand-in for a folder that cannot be removed
for s in 094925 115541 173035 173134; do
  mkdir -p "$BACKUPS/20261015-$s" "$BACKUPS/20261015-$s-tests"
  touch -d "2026-10-15 ${s:0:2}:${s:2:2}" "$BACKUPS/20261015-$s" "$TMP/backups/beta-pre-update-20261015-$s.dump"
  touch -d "2026-10-15 ${s:0:2}:${s:2:2} - 1 minute" "$BACKUPS/20261015-$s-tests"   # the oldest entry is a quick-test copy, as on the server
done
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=1; fi; }
prune_rollback_points; check "pruning succeeds although a folder cannot be removed" $?
[ ! -d "$BACKUPS/20261015-094925" ] && [ ! -d "$BACKUPS/20261015-115541" ] && [ -d "$BACKUPS/20261015-173035" ] && [ -d "$BACKUPS/20261015-173134" ]; check "only the two newest ways back are kept" $?
[ -d "$BACKUPS/20261015-173134-tests" ]; check "the quick-test copies are left to the quick tests" $?
exit $failed
