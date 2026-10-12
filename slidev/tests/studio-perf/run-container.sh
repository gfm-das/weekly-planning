#!/bin/sh
# TEST ONLY: starts the throw-away measurement container (see README.md). Usage: run-container.sh [extra docker -e options]
# The decks live in a named volume so Slidev's per-deck cache survives a restart of the container (a "warm cache" start).
HERE="$(cd "$(dirname "$0")/../.." && pwd -W 2>/dev/null || pwd)"
docker rm -f gfm-test-studio-perf >/dev/null 2>&1
docker volume create gfm-test-studio-decks >/dev/null
MSYS_NO_PATHCONV=1 docker run -d --name gfm-test-studio-perf -p 18581:18581 -p 18589:18589 -p 18599:18599 \
  -v gfm-test-studio-nm:/slidev/node_modules -v gfm-test-studio-decks:/slidev/decks \
  -v "$HERE/manager:/slidev/manager:ro" -v "$HERE/tests:/slidev/tests:ro" -v "$HERE/package.json:/slidev/package.json:ro" \
  -v j5iyrpjbsssqlilqhw9axugx_slidev-data:/livedecksvol:ro -e SEED_DECKS_FROM=/livedecksvol/decks -e SEED=chart-gallery \
  "$@" -w /slidev node:24-alpine node /slidev/tests/studio-perf/serve-studio-perf.mjs
