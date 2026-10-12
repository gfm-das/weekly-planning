#!/usr/bin/env bash
# dataease/translate-dashboards.sh: makes the Dashboards copies in the portal's 13 other languages (translate-dashboards.mjs), in
# a short-lived node container on DataEase's private network. The shell twin of translate-dashboards.ps1.
#   bash dataease/translate-dashboards.sh [--check | --remove | --only de,ar]     GFM_DATAEASE_PROJECT (gfm-dataease)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1; MOUNT=$(cd "$HERE" && pwd -W) ;; *) MOUNT=$HERE ;; esac
PROJECT=${GFM_DATAEASE_PROJECT:-gfm-dataease}
[ -f "$HERE/.env" ] || { echo "dataease/.env is missing (the installer writes it)." >&2; exit 1; }
docker network inspect "$PROJECT-internal" >/dev/null 2>&1 || { echo "Docker network $PROJECT-internal is missing: start DataEase first." >&2; exit 1; }
docker run --rm --name "$PROJECT-translate" --memory 256m --network "$PROJECT-internal" --env-file "$MOUNT/.env" \
  -e DE_BASE=http://dataease:8100 -v "$MOUNT:/repo/dataease:ro" -w /repo node:24-alpine node dataease/translate-dashboards.mjs "$@"
