#!/usr/bin/env bash
# dataease/seed-dashboards.sh: sets up DataEase for the portal's Dashboards (the three dashboards) and checks it, by running
# dataease/seed-dashboards.mjs in a short-lived node container on DataEase's private network, with the values of dataease/.env.
# The shell twin of seed-dashboards.ps1. Run it after DataEase has started (about a minute).
#   bash dataease/seed-dashboards.sh [--check | --reset | --export | --reader-check] [--allow-empty]     GFM_DATAEASE_PROJECT (gfm-dataease)
#   --allow-empty: a chart with no rows is not a problem (a new mission has no people loaded yet)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1; MOUNT=$(cd "$HERE" && pwd -W) ;; *) MOUNT=$HERE ;; esac
PROJECT=${GFM_DATAEASE_PROJECT:-gfm-dataease}
SCRIPT=dataease/seed-dashboards.mjs; ARGS=(); RW=ro; EMPTY=0
for a in "$@"; do
  case "$a" in
    --check) ARGS+=(--check) ;; --reset) ARGS+=(--reset) ;; --export) ARGS+=(--export); RW=rw ;;
    --reader-check) SCRIPT=dataease/tests/reader-check.mjs ;;
    --allow-empty) EMPTY=1 ;;
    *) echo "Unknown option $a" >&2; exit 2 ;;
  esac
done
[ -f "$HERE/.env" ] || { echo "dataease/.env is missing (the installer writes it)." >&2; exit 1; }
docker network inspect "$PROJECT-internal" >/dev/null 2>&1 || { echo "Docker network $PROJECT-internal is missing: start DataEase first." >&2; exit 1; }
docker run --rm --name "$PROJECT-seed" --memory 256m --network "$PROJECT-internal" --env-file "$MOUNT/.env" \
  -e DE_BASE=http://dataease:8100 -e GFM_DATAEASE_DB_HOST=dbproxy -e GFM_ALLOW_EMPTY_CHARTS=$EMPTY -v "$MOUNT:/repo/dataease:$RW" -w /repo \
  node:24-alpine node "$SCRIPT" ${ARGS[@]+"${ARGS[@]}"}
