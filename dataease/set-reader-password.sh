#!/usr/bin/env bash
# dataease/set-reader-password.sh: sets the password of gfm_dashboard_reader (the read-only login DataEase uses) from dataease/.env.
# Needed once on a new install (the installer runs it). Only a SCRAM-SHA-256 hash travels, through standard input.
# The shell twin of set-reader-password.ps1.   bash dataease/set-reader-password.sh   (GFM_DB_CONTAINER: the database container)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1; MOUNT=$(cd "$HERE" && pwd -W) ;; *) MOUNT=$HERE ;; esac
DB=${GFM_DB_CONTAINER:-gfm-beta-supabase-db-1}
docker run --rm --network none -v "$MOUNT:/d:ro" -w /d node:24-alpine node scram.mjs /d/.env \
  | docker exec -i "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q
echo "The password of gfm_dashboard_reader is set."
