#!/usr/bin/env bash
# updater/tests/test-updater.sh: checks updater/gfm-updater.sh (the shell updater) without Docker, a database or the internet. A local bare
# folder stands in for GitHub, a second folder is "this computer", and a fake `docker` (a script that writes down what it is asked and
# can be told to fail) stands in for Docker. Nothing real is touched.
#   bash updater/tests/test-updater.sh        (about a minute)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
UPDATER_DIR=$(cd "$HERE/.." && pwd)
TMP=$(mktemp -d)
# A folder name that git (a Windows program under Git Bash) and bash both understand.
TMP=$(cd "$TMP" && { pwd -W 2>/dev/null || pwd; })
# SAFETY: this test makes commits, tags and pushes. It works only inside its own temporary folder: it starts there, git is told never to look at a
# folder above it, every git command names its folder, and it only ever pushes to its own stand-in "GitHub". If the set-up fails it stops.
cd "$TMP" || exit 1
export GIT_CEILING_DIRECTORIES=$(dirname "$TMP")
# (GFM_TEST_KEEP=1 keeps the temporary folder, to read the updater's log after a failure.)
trap 'kill $(jobs -p) 2>/dev/null; [ -n "${GFM_TEST_KEEP:-}" ] || rm -rf "$TMP"' EXIT
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=t@example.org GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=t@example.org
export GIT_CONFIG_GLOBAL="$TMP/gitconfig"; : > "$GIT_CONFIG_GLOBAL"; git config --global init.defaultBranch main; git config --global advice.detachedHead false
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;; esac

failed=0; checks=0
check() { checks=$((checks + 1)); if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=$((failed + 1)); fi; }
has() { grep -q -- "$1" "$2" 2>/dev/null; }
hasnt() { ! grep -q -- "$1" "$2" 2>/dev/null; }

# ---- the fake docker: writes every call to docker.log; STUB_FAIL (a text) makes a call fail when its arguments contain it
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$GFM_TEST_DIR/docker.log"
if [ -n "${STUB_FAIL:-}" ] && [[ "$*" == *"$STUB_FAIL"* ]]; then echo "stub: this call fails on purpose" >&2; exit 1; fi
case "$1" in
  cp)  # a copy out of a container makes the target; a copy in only needs to succeed
    if [[ "$2" == *:* && "$2" != /* ]]; then mkdir -p "$(dirname "$3")"; if [[ "$2" == */html ]]; then mkdir -p "$3"; echo page > "$3/index.html"; else echo dump > "$3"; fi; fi ;;
  compose) # a bad build makes the system unhealthy; the previous image started again makes it healthy
    [[ "$*" == *"--build"* ]] && echo "${STUB_BAD_BUILD:-0}" > "$GFM_TEST_HEALTH"
    [[ "$*" == *"--no-build"* ]] && echo 0 > "$GFM_TEST_HEALTH" ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/docker"
# SAFETY, layer 1: the fake docker goes first in PATH. (PATH entries cannot contain a colon: the bash-style folder name /c/... is used, not C:/...)
STUB_DIR=$(cd "$TMP/bin" && pwd)
export PATH="$STUB_DIR:$PATH" GFM_TEST_DIR="$TMP" GFM_TEST_HEALTH="$TMP/health.code"
# ... and it is checked. If a real docker would be used, the test stops before it does anything.
[ "$(command -v docker)" = "$STUB_DIR/docker" ] || { echo "Stopped: the fake docker is not the one in use (nothing was run)."; exit 1; }
# SAFETY, layer 2: even a real docker could not touch the live system: no container or project of the test has a real name.
export GFM_DB_CONTAINER=gfmtest-stub-db GFM_PORTAL_CONTAINER=gfmtest-stub-portal GFM_SLIDEV_CONTAINER=gfmtest-stub-slidev GFM_PROJECT_PREFIX=gfmtest-stub-
echo 0 > "$GFM_TEST_HEALTH"

# ---- "GitHub" and "the maker's clone"
GITHUB="$TMP/github.git"; MAKER="$TMP/maker"; COMPUTER="$TMP/computer"
git init -q --bare "$GITHUB"
git clone -q "$GITHUB" "$MAKER" 2>/dev/null
[ -d "$MAKER/.git" ] || { echo "Stopped: the stand-in repositories could not be made (nothing was changed)."; exit 1; }
cd "$MAKER" || exit 1
git config user.name Test; git config user.email t@example.org
mkdir -p portal-api/migrations portal updater/tests
cat > health.sh <<'SH'
#!/usr/bin/env bash
exit "$(cat "$GFM_TEST_HEALTH" 2>/dev/null || echo 0)"
SH
cat > portal/deploy.sh <<'SH'
#!/usr/bin/env bash
echo "portal deploy ran" >> "$GFM_TEST_DIR/docker.log"
SH
cat > updater/quick-tests.sh <<'SH'
#!/usr/bin/env bash
echo "quick tests ran" >> "$GFM_TEST_DIR/docker.log"
[ "$(cat "$GFM_TEST_DIR/quick.code" 2>/dev/null || echo 0)" = 0 ]
SH
echo 0 > "$TMP/quick.code"
printf -- '-- 019: the rights check\nBEGIN;\nCOMMIT;\n' > portal-api/migrations/019_restrict_public_functions.sql
echo "print('v1')" > portal-api/app.py
echo "1.0.0" > VERSION
printf 'updater/status/\nupdater/requests/\nupdater/logs/\nupdater/settings.json\nbackups/\n' > .gitignore
cp "$UPDATER_DIR/gfm-updater.sh" updater/gfm-updater.sh
git add -A; git commit -q -m "Release 1.0.0"; git tag v1.0.0; git push -q "$GITHUB" main --tags 2>/dev/null
git clone -q "$GITHUB" "$COMPUTER" 2>/dev/null
[ -d "$COMPUTER/.git" ] || { echo "Stopped: the stand-in computer could not be made (nothing was changed)."; exit 1; }
git -C "$COMPUTER" config user.name Test; git -C "$COMPUTER" config user.email t@example.org
git -C "$COMPUTER" checkout -q -B main v1.0.0
cd "$TMP" || exit 1
mkdir -p "$COMPUTER/updater"
export GFM_UPDATER_REPO="$COMPUTER" GFM_HEALTH_PAUSE=0 GFM_MIGRATION_RETRY=0 GFM_POLL_SECONDS=1
RUN() { bash "$COMPUTER/updater/gfm-updater.sh" "$@"; }
STATUS="$COMPUTER/updater/status/status.json"
LOGFILE() { ls "$COMPUTER"/updater/logs/*.log | tail -1; }
head_of() { git -C "$COMPUTER" rev-parse HEAD; }
release() {  # release VERSION "message" files-to-write...  (in the maker's clone: commit, tag, push)
  local v=$1 msg=$2; shift 2
  ( cd "$MAKER" || exit 1; echo "${v#v}" > VERSION; "$@"; git add -A; git commit -q -m "$msg"; git tag "$v"; git push -q "$GITHUB" main --tags 2>/dev/null )
}
settings() { printf '{"Remote": "origin", "Branch": "main", "Track": "%s", "CheckEveryHours": 6}\n' "$1" > "$COMPUTER/updater/settings.json"; }
snap() { cp "$STATUS" "$TMP/snap-$1.json"; }
settings tags

echo "---- following release tags"
RUN check >/dev/null 2>&1; snap 1
has '"check_result": "up_to_date"' "$STATUS"; check "at the newest release: up to date" $?
has '"follows": "origin releases (newest: v1.0.0)"' "$STATUS"; check "the page is told what is followed (releases, and the newest one)" $?
has '"state": "idle"' "$STATUS"; check "the state is idle after a check" $?

( cd "$MAKER" || exit 1; echo x > a.txt; git add -A; git commit -q -m "work after the release"; git tag v2-beta; git tag v1.2; git tag v1.0.0-rc1; git push -q "$GITHUB" main --tags 2>/dev/null )
RUN check >/dev/null 2>&1
has '"check_result": "up_to_date"' "$STATUS"; check "tags that are not releases (v2-beta, v1.2, v1.0.0-rc1) are ignored" $?

MIG='-- Migration 041. Run as supabase_admin.
BEGIN;
SELECT 1;
COMMIT;'
release v1.1.0 "Release 1.1.0" bash -c "echo \"print('v1.1')\" > portal-api/app.py; printf '%s\n' '$MIG' > portal-api/migrations/041_thing.sql; printf -- '-- rollback 041\nBEGIN;\nCOMMIT;\n' > portal-api/migrations/041_thing_rollback.sql; mkdir -p slidev/tests; echo t > slidev/tests/x.mjs"
B=$(git -C "$MAKER" rev-parse HEAD)
release v1.9.0 "Release 1.9.0" bash -c "echo 9 > b9.txt"
release v1.10.0 "Release 1.10.0" bash -c "echo 10 > b10.txt"
D=$(git -C "$MAKER" rev-parse HEAD)
RUN check >/dev/null 2>&1; snap 2
has '"check_result": "updates"' "$STATUS"; check "a new release: updates" $?
has "\"commit\": \"$D\"" "$STATUS"; check "the newest release by version number is chosen (v1.10.0 after v1.9.0, not by letters)" $?
has '"follows": "origin releases (newest: v1.10.0)"' "$STATUS"; check "the page names the release" $?
[ "$(grep -o '"short"' "$STATUS" | wc -l)" -ge 4 ]; check "the list of new changes holds the commits since this computer's version" $?
has '041_thing.sql' "$STATUS"; check "the new migration is listed" $?
has '"can_update": true' "$STATUS"; check "an update is possible" $?

echo "---- what blocks an update"
echo changed >> "$COMPUTER/portal-api/app.py"
RUN check >/dev/null 2>&1; has '"blocked": "changed_by_hand"' "$STATUS"; check "a file changed by hand blocks it" $?
git -C "$COMPUTER" checkout -q -- portal-api/app.py
( cd "$COMPUTER" || exit 1; echo local > local.txt; git add -A; git commit -q -m "a local change" )
RUN check >/dev/null 2>&1; has '"check_result": "diverged"' "$STATUS"; check "a local change plus a new release: diverged" $?
git -C "$COMPUTER" reset -q --hard v1.0.0
git -C "$COMPUTER" checkout -q --detach; RUN check >/dev/null 2>&1; has '"blocked": "not_on_branch"' "$STATUS"; check "code not on a branch blocks it" $?
git -C "$COMPUTER" checkout -q main

echo "---- the update: tests, health, way back saved, code, migration, parts, health"
: > "$TMP/docker.log"
RUN update --confirmed >/dev/null 2>&1; snap 3
[ "$(head_of)" = "$D" ]; check "the computer is now at the newest release" $?
has '"result": "done"' "$STATUS"; check "the page says the update is done" $?
has 'quick tests ran' "$TMP/docker.log"; check "the quick tests ran first" $?
has 'pg_dump' "$TMP/docker.log"; check "the database was saved before anything changed" $?
[ "$(grep -c 'docker tag' "$TMP/docker.log")" = 3 ]; check "the three images got rollback tags" $?
has 'psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -f /tmp/gfm-updater-041_thing.sql' "$TMP/docker.log"; check "the new migration ran as supabase_admin" $?
n019=$(grep -c 'gfm-updater-019_restrict_public_functions.sql' "$TMP/docker.log" | tr -d ' '); [ "$n019" -ge 2 ]; check "migration 019 ran after it (cp and exec: $n019 lines)" $?
has 'compose -p gfmtest-stub-gfm-portal' "$TMP/docker.log"; check "portal-api was rebuilt (portal-api changed)" $?
hasnt 'compose -p gfmtest-stub-roster-importer' "$TMP/docker.log"; check "DA Management was not rebuilt (it did not change)" $?
hasnt 'portal deploy ran' "$TMP/docker.log"; check "the portal pages were not deployed (they did not change)" $?
roll=$(ls -d "$COMPUTER"/backups/updater/*/ 2>/dev/null | head -1)
[ -f "${roll}repo-head.txt" ] && [ -f "${roll}rollback-sql/041_thing_rollback.sql" ] && [ -d "${roll}portal-html" ]; check "the way back is kept: commit, rollback SQL, portal pages" $?
has 'updater/status' "$COMPUTER/.gitignore"; check "(the stand-in repository ignores the updater's own folders)" $?

echo "---- refused or failed updates leave things as they were (or put them back)"
before=$(head_of)
release v1.11.0 "Release 1.11.0" bash -c "echo 11 > b11.txt; echo \"print('v1.11')\" > portal-api/app.py; printf '%s\n' '-- Migration 042. Run as supabase_admin.' 'BEGIN;' 'COMMIT;' > portal-api/migrations/042_more.sql; printf -- '-- rollback 042\nBEGIN;\nCOMMIT;\n' > portal-api/migrations/042_more_rollback.sql"
E=$(git -C "$MAKER" rev-parse HEAD)
echo 1 > "$GFM_TEST_HEALTH"; : > "$TMP/docker.log"
RUN update --confirmed >/dev/null 2>&1
[ "$(head_of)" = "$before" ] && has '"reason": "not_healthy"' "$STATUS" && hasnt 'docker tag' "$TMP/docker.log"; check "an unhealthy system is not updated (refused: not_healthy, nothing saved or changed)" $?
echo 0 > "$GFM_TEST_HEALTH"
echo 1 > "$TMP/quick.code"
RUN update --confirmed >/dev/null 2>&1
[ "$(head_of)" = "$before" ] && has '"result": "tests_failed"' "$STATUS"; check "failing quick tests: nothing is installed (tests_failed)" $?
echo 0 > "$TMP/quick.code"
: > "$TMP/docker.log"
STUB_FAIL="--build" RUN update --confirmed >/dev/null 2>&1
[ "$(head_of)" = "$before" ] && has '"result": "rolled_back"' "$STATUS"; check "a failed rebuild puts the previous version back (code and status)" $?
has 'gfm-updater-042_more_rollback.sql' "$TMP/docker.log"; check "and takes the new migration back with its rollback file" $?
echo 0 > "$GFM_TEST_HEALTH"
: > "$TMP/docker.log"
STUB_BAD_BUILD=1 RUN update --confirmed >/dev/null 2>&1
[ "$(head_of)" = "$before" ] && has '"result": "rolled_back"' "$STATUS"; check "a system that is unhealthy after the update is put back (rolled_back)" $?
echo 0 > "$GFM_TEST_HEALTH"
STUB_FAIL="042_more_rollback" STUB_BAD_BUILD=1 RUN update --confirmed >/dev/null 2>&1
has '"result": "needs_person"' "$STATUS"; check "when even the way back fails, the page says a person is needed" $?
git -C "$COMPUTER" reset -q --hard "$before"; echo 0 > "$GFM_TEST_HEALTH"
RUN update --confirmed >/dev/null 2>&1
[ "$(head_of)" = "$E" ] && has '"result": "done"' "$STATUS"; check "after all that, a normal update still works" $?

echo "---- requests from DA Management"
git -C "$COMPUTER" reset -q --hard "$before"; RUN check >/dev/null 2>&1
( RUN watch >/dev/null 2>&1 ) & WATCHER=$!
sleep 4
second=$(RUN watch 2>&1 | head -1); echo "$second" | grep -q "already watching"; check "a second watcher does not start (lock)" $?
REQ="$COMPUTER/updater/requests/request.json"
sleep 2; : > "$TMP/seen"
send() { printf '%s' "$1" > "$REQ"; }
# Waits (up to about two minutes) until a file contains a text. This computer can be slow, so nothing is checked on a fixed delay.
wait_for() { local i; for i in $(seq 1 "${3:-60}"); do grep -q -- "$2" "$1" 2>/dev/null && return 0; sleep 2; done; return 1; }
wait_gone() { local i; for i in $(seq 1 60); do [ -e "$REQ" ] || [ -L "$REQ" ] || return 0; sleep 1; done; return 1; }
send 'this is not json'; wait_gone; check "an unreadable request is read once and thrown away" $?
send '{"action": "reboot"}'; wait_gone; wait_for "$(LOGFILE)" "asked for something the updater does not do" 15; check "a request for anything but check or update is ignored" $?
send '{"action": "update", "target": "'$E'"}'; wait_gone; wait_for "$(LOGFILE)" "not confirmed" 15; check "an update request that is not confirmed is ignored" $?
send '{"action": "update", "target": "abc", "confirmed": true}'; wait_gone; check "an update request without a full version is ignored" $?
head -c 5000 /dev/zero | tr '\0' 'a' > "$REQ"; wait_gone; wait_for "$(LOGFILE)" "not a small plain file" 15; check "a request over 4096 bytes is ignored" $?
ln -s "$TMP/seen" "$REQ" 2>/dev/null && [ -L "$REQ" ] && { wait_gone; sleep 2; [ "$(grep -c 'not a small plain file' "$(LOGFILE)")" -ge 2 ]; check "a link instead of a file is ignored" $?; } || echo "SKIP  (this computer cannot make a symbolic link)"
[ "$(head_of)" = "$before" ]; check "none of those changed the code" $?
t1=$(grep -c '"checked_at"' "$STATUS"); send '{"action": "check", "role": "DATA_ADMIN", "user_id": "6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10"}'; wait_gone
wait_for "$(LOGFILE)" "Check asked for by DA Management, DATA_ADMIN (user 6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10)" 15; check "a check request runs, and the log says who asked (role and user)" $?
send '{"action": "update", "target": "0000000000000000000000000000000000000000", "confirmed": true}'; wait_gone
wait_for "$STATUS" '"reason": "list_changed"' 40; check "an update for a version other than the one shown is refused (list_changed)" $?
[ "$(head_of)" = "$before" ]; check "and changes nothing" $?
send '{"action": "update", "target": "'$E'", "confirmed": true, "role": "AP"}'; wait_gone
wait_for "$STATUS" '"result": "done"' 60 && [ "$(head_of)" = "$E" ]; check "a confirmed update of the exact version shown works through the watcher" $?
gone=1; for _ in $(seq 1 30); do kill -0 "$WATCHER" 2>/dev/null || { gone=0; break; }; sleep 2; done; check "the watcher stops after an update, so the scheduler starts the new version" $gone

echo "---- secrets and settings"
git -C "$COMPUTER" remote set-url origin "https://user:ghp_abcdefghijklmnop1234@example.invalid/x.git"
GIT_ASKPASS=true RUN check >/dev/null 2>&1
hasnt 'ghp_abcdefghijklmnop1234' "$(LOGFILE)" && hasnt 'ghp_abcdefghijklmnop1234' "$STATUS"; check "a token in the remote address never reaches the log or the status file" $?
has '"check_result": "fetch_failed"' "$STATUS"; check "an unreachable remote is reported as fetch_failed" $?
git -C "$COMPUTER" remote set-url origin "$GITHUB"
printf '{"Remote": "origin; rm -rf /", "Track": "tags"}\n' > "$COMPUTER/updater/settings.json"
RUN check >/dev/null 2>&1; code=$?
[ "$code" != 0 ] && has '"settings_problem": true' "$STATUS"; check "a remote name that is not a plain name stops the updater (and the page is told)" $?
printf '{"Remote": "origin", "Track": "everything"}\n' > "$COMPUTER/updater/settings.json"
RUN check >/dev/null 2>&1; [ $? != 0 ]; check "an unknown Track stops it too" $?

echo "---- following a branch (the Frankfurt way) still works"
settings branch
git -C "$COMPUTER" reset -q --hard "$before"
RUN check >/dev/null 2>&1
has '"check_result": "updates"' "$STATUS" && has '"follows": "origin/main"' "$STATUS"; check "Track branch: follows origin/main as before" $?

echo "---- the status files are valid JSON"
docker_real=$(PATH=$(echo "$PATH" | sed "s|$STUB_DIR:||") command -v docker)
if [ -n "$docker_real" ]; then
  W=$TMP; command -v cygpath >/dev/null 2>&1 && W=$(cygpath -m "$TMP")
  out=$("$docker_real" run --rm --network none -v "$W:/t:ro" node:24-alpine node -e '
    const fs=require("fs");let bad=0,n=0;
    for (const f of fs.readdirSync("/t").filter(f=>/^snap-.*\.json$/.test(f))) { n++; try { const j=JSON.parse(fs.readFileSync("/t/"+f,"utf8")); if (j.schema!==1||typeof j.state!=="string"||!("last_update" in j)||!Array.isArray(j.new_changes)) throw new Error("fields"); } catch (e) { bad++; console.log(f+": "+e.message); } }
    console.log("files="+n+" bad="+bad);' 2>&1 | tail -3)
  echo "$out" | grep -q "bad=0"; check "every saved status file parses and has the fields the page reads ($(echo "$out" | tail -1))" $?
else echo "SKIP  (no Docker here to parse the JSON)"; fi

echo; echo "$checks checks: $([ "$failed" = 0 ] && echo 'all passed' || echo "$failed failed")"
exit "$failed"
