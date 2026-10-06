#!/usr/bin/env bash
# test-trial.sh: the trial install (Phase E). Installs Weekly Planning the way another mission would: from a PUBLISHED release, using the starter
# script, then updates it to the next release with the real updater. The "public repository" is a folder on this computer, so nothing goes to
# GitHub. Everything the trial makes has other names and ports than the live system (see _isolated.sh); the live containers are compared before
# and after. The trial stays up between the steps so that you can look at it in a browser.
#   bash install/tests/test-trial.sh up v1.0.0            publish the built release to the stand-in repository, install it with the starter, check it
#   bash install/tests/test-trial.sh update v1.0.1        publish the next built release, install it with the shell updater, check again
#   bash install/tests/test-trial.sh down                 remove everything the trial made (the trial folder goes to /path/to\_to-delete-<date>)
# The releases must be built first (bash release/build-release.sh v1.0.0); v1.0.1 can be a copy of the built tree with a small change.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
WORKTREE=$(cd "$HERE/../.." && pwd)
# shellcheck disable=SC1091
. "$HERE/_isolated.sh"      # the names, ports and helpers of a test copy (this sets REPO and WORK to the worktree: changed below)
# (Windows: git and docker are Windows programs, so the folders are written C:/...; bash and MSYS_NO_PATHCONV=1 need that.)
WORKTREE=$(cd "$WORKTREE" && { pwd -W 2>/dev/null || pwd; })
TRIAL=${GFM_TRIAL_DIR:-$(cd "$WORKTREE/.." && { pwd -W 2>/dev/null || pwd; })/trial}
STAND_IN="$TRIAL/public.git"
CLONE="$TRIAL/mission"
REPO="$CLONE"; WORK="$CLONE/install/.work"; export GFM_BACKUP_DIR="$CLONE/backups/nightly"
export GFM_SUPA_SERVICES="supabase-db supabase-auth supabase-rest supabase-kong" GFM_SKIP_DATAEASE=yes
export GIT_AUTHOR_NAME=Trial GIT_AUTHOR_EMAIL=trial@example.org GIT_COMMITTER_NAME=Trial GIT_COMMITTER_EMAIL=trial@example.org

live_before=$(docker ps -a --format '{{.ID}} {{.Names}} {{.Image}}' | grep -E ' (gfm-|portal|roster-importer|slidev|supabase)' | grep -v ' gfmtest' | grep -v ' gfm-test-' | sort)
checks() {   # the checks that must hold after an install and after an update
  echo; echo "---- checks ($1)"
  [ "$(tr -d '\r' < "$CLONE/VERSION")" = "${1#v}" ]; check "the installed code is $1" $?
  [ "$(Q "select id||'|'||name||'|'||default_language||'|'||time_zone from public.missions order by id")" = "1|Testland Example Mission|de|America/Denver" ]; check "mission 1 with the typed name, language and time zone" $?
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28070/)" = 200 ]; check "the portal opens" $?
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28090/health)" = 200 ]; check "DA Management answers" $?
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:23030/)" = 200 ]; check "Presentations answer" $?
  local anon token
  anon=$(grep '^SERVICE_SUPABASEANON_KEY=' "$CLONE/supabase/.env" | cut -d= -f2)
  token=$(curl -s -X POST "http://127.0.0.1:28070/auth/v1/token?grant_type=password" -H "apikey: $anon" -H 'Content-Type: application/json' \
    -d '{"email":"analyst@testland.example","password":"Fake-Install-Test-2026"}' | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
  [ -n "$token" ]; check "the first Data Analyst can sign in" $?
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:28070/api/overview -H "Authorization: Bearer $token")" = 200 ]; check "portal-api accepts the sign-in" $?
  grep -q '"Track": "tags"' "$CLONE/updater/settings.json"; check "the updater follows the release tags" $?
}

case "${1:-}" in
up)
  V1=${2:?give the version, for example v1.0.0}
  [ ! -e "$TRIAL" ] || { echo "Refusing: $TRIAL exists (run 'down' first)."; exit 2; }
  mkdir -p "$TRIAL"; isolated_guard
  git init -q --bare -b main "$STAND_IN"
  export GFM_PUBLIC_URL="$STAND_IN" GFM_PUBLIC_REPO=example/none GFM_PUBLISH_NAME=Trial GFM_PUBLISH_EMAIL=trial@example.org
  case "$GFM_PUBLIC_URL" in http*|git@*|ssh://*) echo "Stopped: the stand-in must be a folder."; exit 1 ;; esac
  for v in "$V1"; do
    GFM_RELEASE_OUT="$WORKTREE/backups/release/$v" env -u MSYS_NO_PATHCONV bash "$WORKTREE/release/publish.sh" "$v" --go > "$TRIAL/publish-$v.log" 2>&1; check "published $v to the stand-in repository" $?
  done
  [ "$failed" = 0 ] || exit 1
  # The starter that a mission downloads, run from the published release's files.
  cp "$WORKTREE/backups/release/$V1/assets/install-weekly-planning.sh" "$TRIAL/starter.sh"
  cat > "$TRIAL/answers.json" <<'JSON'
{ "missionName": "Testland Example Mission", "missionCode": "TEM", "language": "de", "languageRequest": null,
  "admin": { "name": "Test Analyst", "email": "analyst@testland.example", "password": "Fake-Install-Test-2026" },
  "email": null, "publicDomain": "", "timeZone": "America/Denver", "cloudflareToken": "", "logo": null }
JSON
  echo "free memory in Docker before: $(memory)"
  GFM_REPO_URL="$STAND_IN" bash "$TRIAL/starter.sh" "$CLONE" --answers "$TRIAL/answers.json" 2>&1 | tee "$TRIAL/install.log" | sed -e 's/^/    /'
  check "the starter and the installer ran to the end" "${PIPESTATUS[0]}"
  rm -f "$TRIAL/answers.json"
  echo "free memory in Docker after: $(memory)"
  checks "$V1"
  [ "$(git -C "$CLONE" rev-parse --abbrev-ref HEAD)" = main ]; check "the copy is on a branch called main (so the updater can move it)" $?
  echo; [ "$failed" = 0 ] && echo "Install checks passed." || echo "$failed check(s) failed."
  exit "$failed" ;;
update)
  [ -d "$CLONE" ] || { echo "Nothing installed: run 'up' first."; exit 2; }
  V2=${2:?give the next version, for example v1.0.1}
  GFM_PUBLIC_URL="$STAND_IN" GFM_PUBLIC_REPO=example/none GFM_PUBLISH_NAME=Trial GFM_PUBLISH_EMAIL=trial@example.org GFM_RELEASE_OUT="$WORKTREE/backups/release/$V2"     env -u MSYS_NO_PATHCONV bash "$WORKTREE/release/publish.sh" "$V2" --go > "$TRIAL/publish-$V2.log" 2>&1; check "published $V2 to the stand-in repository" $?
  before=$(tr -d '\r' < "$CLONE/VERSION")
  export GFM_UPDATER_REPO="$CLONE" GFM_HEALTH_TRIES=10 GFM_HEALTH_PAUSE=10
  bash "$CLONE/updater/gfm-updater.sh" check 2>&1 | sed -e 's/^/    /'
  bash "$CLONE/updater/gfm-updater.sh" status > "$TRIAL/status-before.json" 2>&1
  grep -q '"can_update": true' "$TRIAL/status-before.json"; check "the check offers an update (from $before)" $?
  bash "$CLONE/updater/gfm-updater.sh" update --confirmed 2>&1 | tee "$TRIAL/update.log" | sed -e 's/^/    /'
  bash "$CLONE/updater/gfm-updater.sh" status > "$TRIAL/status-after.json" 2>&1
  grep -q '"result": "done"' "$TRIAL/status-after.json"; check "the updater says done" $?
  [ "$(tr -d '\r' < "$CLONE/VERSION")" != "$before" ]; check "the version changed" $?
  checks "v$(tr -d '\r' < "$CLONE/VERSION")"
  live_unchanged
  echo; [ "$failed" = 0 ] && echo "Update checks passed." || echo "$failed check(s) failed."
  exit "$failed" ;;
down)
  isolated_cleanup
  if [ -e "$TRIAL" ]; then
    dest="$(cd "$WORKTREE/../.." && pwd)/_to-delete-$(date +%F)"; mkdir -p "$dest"
    mv "$TRIAL" "$dest/trial-install-$(date +%H%M%S)" && echo "The trial folder was moved to $dest (delete it when you like)."
  fi
  echo "Trial removed."; live_unchanged ;;
*) echo "Use: up VERSION [NEXT_VERSION] | update | down"; exit 2 ;;
esac
