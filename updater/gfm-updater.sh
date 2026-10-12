#!/usr/bin/env bash
# GFM updater (shell version, for Mac, Linux and Windows with Git Bash): brings the mission system on this computer up to date, safely.
# It does the same as updater/gfm-updater.ps1 (read that file's header: it explains each step in plain words) and writes the same files,
# so DA Management > Updates works with either:
#   check    asks the remote for news (git fetch) and writes what is new into the status file. Nothing else changes.
#   update   installs the new version, only when a person asked (the Updates page, or `update` in a terminal): only forward; the quick tests
#            on a copy first; the system must be healthy now; a way back is saved (database backup, image tags, portal pages, commit); then
#            the new code, the new migrations (each followed by 019), the parts that changed; health again; on failure the old version is back.
#   watch    keeps running: looks every 5 seconds for a request from the Updates page, checks by itself every CheckEveryHours, never updates
#            by itself. (register-watcher.sh makes the computer's own scheduler start it.)
#   status   prints the status file.
# What it follows is set in updater/settings.json:  {"Remote": "origin", "Branch": "main", "Track": "tags", "CheckEveryHours": 6}
#   Track "branch" (default): the newest commit of Remote/Branch (the Frankfurt server follows its own branch).
#   Track "tags": the newest release tag vX.Y.Z of Remote (a new mission follows the public releases).
# The page never runs a shell: it leaves a tiny request file that this script checks field by field. Programs are always started with a fixed
# list of arguments. Passwords and tokens are never written (this script reads no .env file for secrets; web addresses with a password are hidden).
# Names for tests only: GFM_UPDATER_REPO (the code folder), GFM_PROJECT_PREFIX, GFM_DB_CONTAINER, GFM_POLL_SECONDS.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MODE=${1:-check}
shift || true
CONFIRMED=no
for arg in "$@"; do [ "$arg" = --confirmed ] && CONFIRMED=yes; done
# (On Windows the folder is written C:/Users/... : git and docker are Windows programs and do not understand /c/Users/...; bash understands both.)
REPO=$(cd "${GFM_UPDATER_REPO:-$HERE/..}" && { pwd -W 2>/dev/null || pwd; })

case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;; esac
UPD="$REPO/updater"
REQUESTS="$UPD/requests"; STATUS_DIR="$UPD/status"; PARTS="$STATUS_DIR/.parts"; LOGS="$UPD/logs"; BACKUPS="$REPO/backups/updater"
REQUEST_FILE="$REQUESTS/request.json"; STATUS_FILE="$STATUS_DIR/status.json"
mkdir -p "$REQUESTS" "$STATUS_DIR" "$PARTS" "$LOGS" "$BACKUPS"
export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never

PREFIX=${GFM_PROJECT_PREFIX:-}
MAX_REQUEST_BYTES=4096
RIGHTS_CHECK='portal-api/migrations/019_restrict_public_functions.sql'
BY_HAND_MARKER='updater: install by hand'
HEALTH_TRIES=${GFM_HEALTH_TRIES:-6}; HEALTH_PAUSE=${GFM_HEALTH_PAUSE:-30}
POLL=${GFM_POLL_SECONDS:-5}

env_value() { [ -f "$1" ] && grep -E "^$2=" "$1" | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//' || true; }
DB_CONTAINER=${GFM_DB_CONTAINER:-gfm-beta-supabase-db-1}
PORTAL_CONTAINER=${GFM_PORTAL_CONTAINER:-$(env_value "$REPO/portal/.env" GFM_PORTAL_CONTAINER)}; PORTAL_CONTAINER=${PORTAL_CONTAINER:-portal-ydpgd5zwrjrvz5aa188sa60u}
SLIDEV_CONTAINER=${GFM_SLIDEV_CONTAINER:-$(env_value "$REPO/slidev/.env" GFM_SLIDEV_CONTAINER)}; SLIDEV_CONTAINER=${SLIDEV_CONTAINER:-slidev-j5iyrpjbsssqlilqhw9axugx}
# Every image a rebuild replaces, and the name its rollback copy gets.
IMAGES=("${PREFIX}gfm-portal-portal-api:portal-api-rollback" "${PREFIX}gfm-portal-portal-reminders:portal-reminders-rollback" "${PREFIX}roster-importer-roster-importer:roster-importer-rollback")

# ------------------------------------------------------------------------------------------------------ text helpers
now() { date '+%Y-%m-%dT%H:%M:%S%z' | sed -E 's/([+-][0-9]{2})([0-9]{2})$/\1:\2/'; }
# Hides passwords and tokens: web addresses with a name and password, GitHub tokens, signed web tokens.
protect() { sed -E -e 's#([A-Za-z][A-Za-z0-9+.-]*://)[^/@[:space:]]+@#\1***@#g' -e 's/(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})/***/g' -e 's/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/***/g'; }
LOG_FILE=""
log() {
  LOG_FILE="$LOGS/updater-$(date +%Y-%m).log"
  local line; line="$(date '+%Y-%m-%d %H:%M:%S')  $(printf '%s' "$*" | protect)"
  printf '%s\n' "$line" >> "$LOG_FILE"
  printf '%s\n' "$line"
}
# A JSON string from any text (no control characters, quotes and backslashes escaped).
jq_str() { printf '%s' "$1" | tr -d '\000-\010\013\014\016-\037' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' | awk 'BEGIN{ORS=""} NR>1{print "\\n"} {print}'; }
q() { printf '"%s"' "$(jq_str "$1")"; }
json_list() { local out="" first=yes line; while IFS= read -r line; do [ -n "$line" ] || continue; [ $first = yes ] || out="$out, "; out="$out$(q "$line")"; first=no; done; printf '[%s]' "$out"; }

# ------------------------------------------------------------------------------------------------------ settings
S_REMOTE=origin; S_BRANCH=main; S_TRACK=branch; S_HOURS=6
read_settings() {
  local file="$UPD/settings.json" v
  if [ -f "$file" ]; then
    v=$(sed -n 's/.*"Remote"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -1); [ -n "$v" ] && S_REMOTE=$v
    v=$(sed -n 's/.*"Branch"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -1); [ -n "$v" ] && S_BRANCH=$v
    v=$(sed -n 's/.*"Track"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -1); [ -n "$v" ] && S_TRACK=$v
    v=$(sed -n 's/.*"CheckEveryHours"[[:space:]]*:[[:space:]]*\([0-9.]*\).*/\1/p' "$file" | head -1); [ -n "$v" ] && S_HOURS=$v
  fi
  # The remote and branch names become git arguments, so only plain names are accepted.
  [[ "$S_REMOTE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { log "updater/settings.json: Remote must be a plain name like origin (it is '$S_REMOTE')."; return 1; }
  if ! [[ "$S_BRANCH" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || [[ "$S_BRANCH" == *..* || "$S_BRANCH" == *//* || "$S_BRANCH" == */ || "$S_BRANCH" == *.lock ]]; then
    log "updater/settings.json: Branch must be a plain branch name like main (it is '$S_BRANCH')."; return 1
  fi
  [ "$S_TRACK" = branch ] || [ "$S_TRACK" = tags ] || { log "updater/settings.json: Track must be branch or tags (it is '$S_TRACK')."; return 1; }
  [[ "$S_HOURS" =~ ^[0-9]+([.][0-9]+)?$ ]] || { log "updater/settings.json: CheckEveryHours must be a number."; return 1; }
  # seconds between two checks (at least 15 minutes)
  CHECK_SECONDS=$(awk -v h="$S_HOURS" 'BEGIN { s = h * 3600; if (s < 900) s = 900; printf "%d", s }')
  [ -n "${GFM_CHECK_SECONDS:-}" ] && CHECK_SECONDS=$GFM_CHECK_SECONDS
  return 0
}

# ------------------------------------------------------------------------------------------------------ the status file
scalar_get() { [ -f "$PARTS/scalars.env" ] && grep -E "^$1=" "$PARTS/scalars.env" | tail -1 | cut -d= -f2- || true; }
scalar_set() {  # scalar_set key value ... (single line values)
  local f="$PARTS/scalars.env" tmp="$PARTS/scalars.env.tmp" key value
  [ -f "$f" ] || : > "$f"
  while [ $# -ge 2 ]; do
    key=$1; value=$(printf '%s' "$2" | tr -d '\r\n'); shift 2
    grep -vE "^$key=" "$f" > "$tmp" || true
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    mv -f "$tmp" "$f"
  done
}
part_set() { printf '%s\n' "$2" > "$PARTS/$1.tmp"; mv -f "$PARTS/$1.tmp" "$PARTS/$1"; }
part_get() { if [ -f "$PARTS/$1" ]; then cat "$PARTS/$1"; else printf '%s' "$2"; fi; }
bool() { [ "$1" = true ] && printf true || printf false; }

# Written whole through a temporary file, so the page never reads half a file.
save_status() {
  local tmp="$STATUS_FILE.tmp"
  {
    printf '{\n "schema": 1,\n'
    printf ' "updater_seen_at": %s,\n' "$(q "$(now)")"
    printf ' "state": %s,\n "step": %s,\n' "$(q "$(scalar_get state)")" "$(q "$(scalar_get step)")"
    printf ' "settings_problem": %s,\n' "$(bool "$(scalar_get settings_problem)")"
    printf ' "checked_at": %s,\n "checked_head": %s,\n "follows": %s,\n' "$(q "$(scalar_get checked_at)")" "$(q "$(scalar_get checked_head)")" "$(q "$(scalar_get follows)")"
    printf ' "check_result": %s,\n "blocked": %s,\n "can_update": %s,\n' "$(q "$(scalar_get check_result)")" "$(q "$(scalar_get blocked)")" "$(bool "$(scalar_get can_update)")"
    printf ' "current": %s,\n "remote": %s,\n' "$(part_get current null)" "$(part_get remote null)"
    printf ' "new_changes": %s,\n "migrations": %s,\n "other_parts": %s,\n' "$(part_get new_changes '[]')" "$(part_get migrations '[]')" "$(part_get other_parts '[]')"
    printf ' "last_update": %s\n}\n' "$(part_get last_update null)"
  } | protect > "$tmp"
  mv -f "$tmp" "$STATUS_FILE"
}
set_state() { scalar_set state "$1" step "${2:-}"; save_status; }

# ------------------------------------------------------------------------------------------------------ running programs
git_() { git -C "$REPO" "$@"; }
run_step() {  # run_step "what" program args...  (output goes to the log; false when it did not work)
  local what=$1; shift
  log "  $what"
  local out code
  out=$("$@" 2>&1); code=$?
  [ -n "$out" ] && printf '%s\n' "$out" | while IFS= read -r l; do [ -n "${l// /}" ] && log "    $l"; done
  [ $code -eq 0 ] || { log "  $what did not work (exit code $code)."; return 1; }
}

# ------------------------------------------------------------------------------------------------------ looking at the code
SEP=$'\x1f'
version_json() {  # version_json revision
  local line; line=$(git_ log -1 --format="%H${SEP}%cI${SEP}%s" "$1" 2>/dev/null) || { printf null; return; }
  local c d s; IFS=$SEP read -r c d s <<<"$line"
  printf '{"commit": %s, "short": %s, "date": %s, "subject": %s%s}' "$(q "$c")" "$(q "${c:0:7}")" "$(q "$d")" "$(q "$s")" "${2:-}"
}
current_branch() { git_ symbolic-ref --quiet --short HEAD 2>/dev/null || true; }
commit_count() { git_ rev-list --count "$1" 2>/dev/null || echo 0; }
changed_files() { git_ diff --name-only --diff-filter="$3" "$1" "$2"; }
tree_clean() { [ -z "$(git_ status --porcelain --untracked-files=no)" ]; }
migration_header() { sed -n '/^[[:space:]]*BEGIN/q;/^[[:space:]]*--/p'; }
migration_user() { local u; u=$(printf '%s\n' "$1" | grep -oE 'psql -U (postgres|supabase_admin)' | head -1 | awk '{print $3}'); printf '%s' "${u:-supabase_admin}"; }

# Which running parts an update renews (tests and docs need nothing), and which folders a person must install.
parts_to_renew() {
  local files; files=$(cat | grep -vE '^[^/]+/tests/')
  echo "$files" | grep -E '^portal-api/' | grep -qvE '^portal-api/migrations/' && echo portal-api
  echo "$files" | grep -qE '^roster-importer/' && echo da-management
  echo "$files" | grep -qE '^slidev/' && echo slidev
  echo "$files" | grep -qE '^portal/' && echo portal
  return 0
}
other_parts() { cat | grep '/' | cut -d/ -f1 | grep -vxE 'docs|ops-tests|updater|portal|portal-api|roster-importer|slidev|wiki|install' | sort -u; }

# The newest release tag: vX.Y.Z only (a tag like v2-beta or v1.2 is not a release).
latest_release_tag() { git_ tag --list 'v[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1; }

# P_* hold the plan. Asks the remote for news and works out what an update would do. Changes nothing in the code.
plan() {
  P_RESULT=''; P_BLOCKED=''; P_CAN=false; P_FOLLOWS="$S_REMOTE/$S_BRANCH"; P_REMOTE=''; P_CHANGES=''; P_MIGS=''; P_PARTS=''; P_OTHER=''
  [ "$S_TRACK" = tags ] && P_FOLLOWS="$S_REMOTE releases"
  P_HEAD=$(git_ rev-parse HEAD 2>/dev/null); P_BRANCH=$(current_branch)
  if ! git_ remote | grep -qxF "$S_REMOTE"; then log "This computer has no Git remote called '$S_REMOTE' yet."; P_RESULT=no_remote; return; fi
  local target
  if [ "$S_TRACK" = tags ]; then
    log "Asking $S_REMOTE for new releases."
    git_ fetch --quiet --tags --force "$S_REMOTE" >/dev/null 2>&1 || { log "The remote could not be reached."; P_RESULT=fetch_failed; return; }
    local tag; tag=$(latest_release_tag)
    if [ -z "$tag" ]; then log "There is no release (vX.Y.Z) at $S_REMOTE yet."; P_RESULT=up_to_date; return; fi
    P_FOLLOWS="$S_REMOTE releases (newest: $tag)"
    target=$(git_ rev-parse --verify "refs/tags/$tag^{commit}")
  else
    log "Asking $S_REMOTE for new changes ($S_REMOTE/$S_BRANCH)."
    git_ fetch --quiet --no-tags "$S_REMOTE" "+refs/heads/$S_BRANCH:refs/remotes/$S_REMOTE/$S_BRANCH" >/dev/null 2>&1 || { log "The remote could not be reached."; P_RESULT=fetch_failed; return; }
    target=$(git_ rev-parse --verify "refs/remotes/$S_REMOTE/$S_BRANCH^{commit}")
  fi
  P_REMOTE=$target
  local behind ahead
  behind=$(commit_count "$P_HEAD..$target"); ahead=$(commit_count "$target..$P_HEAD")
  if [ "$behind" = 0 ] && [ "$ahead" = 0 ]; then P_RESULT=up_to_date
  elif [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then P_RESULT=diverged
  elif [ "$ahead" -gt 0 ]; then P_RESULT=local_ahead
  else P_RESULT=updates; fi
  if [ "$behind" -gt 0 ]; then
    P_CHANGES=$(git_ log --max-count=100 --format="%H${SEP}%cI${SEP}%s" "$P_HEAD..$target")
    P_MIGS=$(changed_files "$P_HEAD" "$target" A | grep -E '^portal-api/migrations/[0-9]{3}_[A-Za-z0-9_]+\.sql$' | grep -v '_rollback\.sql$' | sort)
    local all; all=$(changed_files "$P_HEAD" "$target" ACDMRT)
    P_PARTS=$(printf '%s\n' "$all" | parts_to_renew)
    P_OTHER=$(printf '%s\n' "$all" | other_parts)
    local edited
    for edited in $(changed_files "$P_HEAD" "$target" M | grep -E '^portal-api/migrations/'); do log "Note: the update edits $edited, which is not run again (a person decides)."; done
  fi
  P_BLOCKED=$(blocked_reason)
  [ "$P_RESULT" = updates ] && [ -z "$P_BLOCKED" ] && P_CAN=true
  log "Result: $P_RESULT; $(printf '%s' "$P_CHANGES" | grep -c .) new change(s)$([ -n "$P_BLOCKED" ] && echo "; cannot update: $P_BLOCKED")."
}
blocked_reason() {
  case "$P_RESULT" in local_ahead|diverged) echo "$P_RESULT"; return ;; updates) ;; *) return ;; esac
  [ -n "$P_BRANCH" ] || { echo not_on_branch; return; }
  tree_clean || { echo changed_by_hand; return; }
  local m
  for m in $P_MIGS; do
    if git_ show "$P_REMOTE:$m" 2>/dev/null | migration_header | grep -qF "$BY_HAND_MARKER"; then log "$m says it is installed by hand."; echo by_hand; return; fi
  done
}
changes_json() {  # the P_CHANGES lines as a JSON list of versions
  local out="" first=yes c d s
  while IFS=$SEP read -r c d s; do
    [ -n "$c" ] || continue
    [ $first = yes ] || out="$out, "; first=no
    out="$out{\"commit\": $(q "$c"), \"short\": $(q "${c:0:7}"), \"date\": $(q "$d"), \"subject\": $(q "$s")}"
  done <<<"$P_CHANGES"
  printf '[%s]' "$out"
}
save_check_result() {
  scalar_set state idle step '' checked_at "$(now)" checked_head "$P_HEAD" follows "$P_FOLLOWS" check_result "$P_RESULT" blocked "$P_BLOCKED" can_update "$P_CAN"
  part_set current "$(version_json "$P_HEAD" ", \"branch\": $(q "$P_BRANCH")")"
  if [ -n "$P_REMOTE" ]; then part_set remote "$(version_json "$P_REMOTE")"; else part_set remote null; fi
  part_set new_changes "$(changes_json)"
  part_set migrations "$(printf '%s\n' "$P_MIGS" | json_list)"
  part_set other_parts "$(printf '%s\n' "$P_OTHER" | json_list)"
  save_status
}

# ------------------------------------------------------------------------------------------------------ locks (one check or update at a time)
LOCKS_HELD=()
enter_lock() {  # enter_lock name: true when this process now holds it
  local dir="$STATUS_DIR/.lock-$1" pid
  if mkdir "$dir" 2>/dev/null; then echo $$ > "$dir/pid"; LOCKS_HELD+=("$dir"); return 0; fi
  pid=$(cat "$dir/pid" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then return 1; fi
  # the last holder stopped without letting go: the lock is ours now
  rm -rf "$dir"; mkdir "$dir" 2>/dev/null || return 1; echo $$ > "$dir/pid"; LOCKS_HELD+=("$dir"); return 0
}
exit_lock() { rm -rf "$STATUS_DIR/.lock-$1"; }
release_all() { local d; for d in ${LOCKS_HELD[@]+"${LOCKS_HELD[@]}"}; do rm -rf "$d"; done; }
trap release_all EXIT

# ------------------------------------------------------------------------------------------------------ requests from DA Management
REQ_ACTION=''; REQ_TARGET=''; REQ_BY=''
read_request() {
  REQ_ACTION=''; REQ_TARGET=''; REQ_BY=''
  [ -e "$REQUEST_FILE" ] || [ -L "$REQUEST_FILE" ] || return 1
  local text="" ok=no
  if [ -f "$REQUEST_FILE" ] && [ ! -L "$REQUEST_FILE" ] && [ "$(wc -c < "$REQUEST_FILE")" -le "$MAX_REQUEST_BYTES" ]; then text=$(cat "$REQUEST_FILE"); ok=yes; fi
  rm -rf "$REQUEST_FILE"          # read once, even a wrong one: it can never run twice
  [ $ok = yes ] || { log 'A request was ignored: it was not a small plain file.'; return 1; }
  local action role user target confirmed
  action=$(printf '%s' "$text" | sed -n 's/.*"action"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' | head -1)
  if [ "$action" != check ] && [ "$action" != update ]; then log 'A request was ignored: it was not readable, or it asked for something the updater does not do.'; return 1; fi
  role=$(printf '%s' "$text" | sed -n 's/.*"role"[[:space:]]*:[[:space:]]*"\([A-Z_]*\)".*/\1/p' | head -1)
  user=$(printf '%s' "$text" | sed -n 's/.*"user_id"[[:space:]]*:[[:space:]]*"\([0-9a-fA-F-]*\)".*/\1/p' | head -1)
  local by=someone
  case "$role" in AP|PRESIDENT|DATA_ADMIN) by=$role ;; esac
  [[ "$user" =~ ^[0-9a-fA-F-]{36}$ ]] && by="$by (user $user)"
  REQ_BY="DA Management, $by"
  if [ "$action" = update ]; then
    target=$(printf '%s' "$text" | sed -n 's/.*"target"[[:space:]]*:[[:space:]]*"\([0-9a-f]*\)".*/\1/p' | head -1)
    confirmed=$(printf '%s' "$text" | grep -cE '"confirmed"[[:space:]]*:[[:space:]]*true')
    if ! [[ "$target" =~ ^[0-9a-f]{40}$ ]] || [ "$confirmed" = 0 ]; then log 'An update request was ignored: it did not name one version, or it was not confirmed.'; return 1; fi
    REQ_TARGET=$target
  fi
  REQ_ACTION=$action
  return 0
}

# ------------------------------------------------------------------------------------------------------ check
do_check() {
  enter_lock Work || { log 'The updater is busy with something else; the check waits.'; return 1; }
  set_state checking
  plan
  save_check_result
  exit_lock Work
}

# ------------------------------------------------------------------------------------------------------ the update
complete_update() {  # result reason from to asked_by started [point folder]
  local result=$1 reason=$2 from=$3 to=$4 by=$5 started=$6 folder=${7:-}
  [ -n "$folder" ] && folder=${folder#"$REPO"/}
  local logrel=''; [ -n "$LOG_FILE" ] && logrel=${LOG_FILE#"$REPO"/}
  log "=== Update result: $result $reason ==="
  part_set last_update "{\"result\": $(q "$result"), \"reason\": $(q "$reason"), \"from\": $(q "$from"), \"to\": $(q "$to"), \"asked_by\": $(q "$by"), \"started_at\": $(q "$started"), \"finished_at\": $(q "$(now)"), \"rollback_folder\": $(q "$folder"), \"log\": $(q "$logrel")}"
  scalar_set state idle step ''
  save_status
  if [ -n "$folder" ]; then plan; save_check_result; fi   # the new state is shown at once
}

test_health() { log 'Health check (health.sh):'; local out code; out=$(cd "$REPO" && bash health.sh 2>&1); code=$?; printf '%s\n' "$out" | while IFS= read -r l; do [ -n "${l// /}" ] && log "    $l"; done; return $code; }
wait_for_health() {
  local try
  for try in $(seq 1 "$HEALTH_TRIES"); do
    test_health && return 0
    [ "$try" -lt "$HEALTH_TRIES" ] && { log "Not healthy yet (try $try of $HEALTH_TRIES); trying again in $HEALTH_PAUSE s."; sleep "$HEALTH_PAUSE"; }
  done
  return 1
}

# The quick tests run on a copy of the new version, with that version's own list (updater/quick-tests.sh). Nothing is installed when they fail.
quick_tests() {  # quick_tests commit stamp
  local folder="$BACKUPS/$2-tests" rc=0
  mkdir -p "$folder"
  log 'Running the quick tests on a copy of the new version.'
  # (tar -C with a Windows-style folder name C:/... would take "C" for a remote computer: so tar runs inside the folder)
  if git_ archive --format=tar "$1" | ( cd "$folder" && tar -x ); then
    local tests="$folder/updater/quick-tests.sh"; [ -f "$tests" ] || tests="$REPO/updater/quick-tests.sh"
    if [ -f "$tests" ]; then
      if run_step 'Quick tests' bash "$tests" --root "$folder"; then log 'The quick tests passed.'; else rc=1; fi
    else log 'There is no quick-tests.sh: the quick tests are skipped.'; fi
  else log 'The copy of the new version could not be unpacked.'; rc=1; fi
  rm -rf "$folder"
  [ $rc -eq 0 ] || log 'The quick tests did not pass, so nothing is installed.'
  return $rc
}

run_sql_file() {  # run_sql_file file user: copied into the container first (no text through a pipe), psql stops at the first error
  local file=$1 user=$2 name inside
  name=$(basename "$file"); inside="/tmp/gfm-updater-$name"
  log "  Database: $name (as $user)"
  docker cp "$file" "$DB_CONTAINER:$inside" >/dev/null 2>&1 || return 1
  local code=0
  docker exec "$DB_CONTAINER" psql -U "$user" -d postgres -v ON_ERROR_STOP=1 -f "$inside" >/dev/null 2>&1 || code=$?
  docker exec "$DB_CONTAINER" rm -f "$inside" >/dev/null 2>&1
  return $code
}
rights_check() { run_sql_file "$REPO/$RIGHTS_CHECK" supabase_admin || { log 'Migration 019 (the rights check) did not work.'; return 1; }; }

# ---- the way back
POINT_STAMP=''; POINT_FOLDER=''; POINT_HEAD=''; POINT_DUMP=''; POINT_MIGS=''; POINT_APPLIED=''; POINT_RENEWED=''; POINT_CODE=no
save_rollback_point() {
  POINT_STAMP=$1; POINT_FOLDER="$BACKUPS/$1"; POINT_HEAD=$P_HEAD; POINT_MIGS=$P_MIGS; POINT_APPLIED=''; POINT_RENEWED=''; POINT_CODE=no
  POINT_DUMP="$REPO/backups/beta-pre-update-$1.dump"
  mkdir -p "$POINT_FOLDER"
  log "Saving the way back in $POINT_FOLDER."
  printf '%s\n' "$POINT_HEAD" > "$POINT_FOLDER/repo-head.txt"
  local inside="/tmp/gfm-updater-$1.dump"
  run_step 'Database backup (pg_dump)' docker exec "$DB_CONTAINER" pg_dump -U postgres -Fc -d postgres -f "$inside" || return 1
  run_step 'Copying the backup out' docker cp "$DB_CONTAINER:$inside" "$POINT_DUMP" || return 1
  docker exec "$DB_CONTAINER" rm -f "$inside" >/dev/null 2>&1
  local pair image rb
  for pair in "${IMAGES[@]}"; do
    image=${pair%%:*}; rb=${pair#*:}
    run_step "Rollback tag $rb:upd-$1" docker tag "$image:latest" "$rb:upd-$1" || return 1
  done
  run_step 'Copy of the portal pages' docker cp "$PORTAL_CONTAINER:/usr/share/nginx/html" "$POINT_FOLDER/portal-html" || return 1
}

update_code() {
  log "  New code (git merge --ff-only $1)"
  POINT_CODE=yes
  git_ merge --ff-only "$1" >/dev/null 2>&1 || { log "git merge --ff-only did not work."; return 1; }
  local head; head=$(git_ rev-parse HEAD)
  [ "$head" = "$1" ] || { log "After the update the code is at $head, not at $1."; return 1; }
  # The rollback files of the new migrations exist only in the new version: keep a copy for the way back.
  mkdir -p "$POINT_FOLDER/rollback-sql"
  local m rb
  for m in $POINT_MIGS; do rb="$REPO/${m%.sql}_rollback.sql"; [ -f "$rb" ] && cp "$rb" "$POINT_FOLDER/rollback-sql/"; done
  return 0
}
install_migrations() {
  local m file user
  for m in $POINT_MIGS; do
    file="$REPO/$m"
    user=$(migration_user "$(migration_header < "$file")")
    if ! run_sql_file "$file" "$user"; then
      # A migration waits at most 10 s for a lock and then stops, having changed nothing. Once more.
      log "  $m did not finish; trying once more in ${GFM_MIGRATION_RETRY:-15} s."
      sleep "${GFM_MIGRATION_RETRY:-15}"
      run_sql_file "$file" "$user" || { log "Migration $m did not work."; return 1; }
    fi
    POINT_APPLIED="$POINT_APPLIED $m"
    rights_check || return 1
  done
  return 0
}
# (GFM_OVERRIDE_DIR, for tests only: a folder, relative to the code folder, whose <part>.yml is one more compose file; see install/tests/overrides.)
compose_cmd() {
  local project=$1 file=$2 extra=() part; shift 2
  part=$(basename "$(dirname "$file")")
  [ -n "${GFM_OVERRIDE_DIR:-}" ] && [ -f "$REPO/$GFM_OVERRIDE_DIR/$part.yml" ] && extra=(-f "$REPO/$GFM_OVERRIDE_DIR/$part.yml")
  docker compose -p "$PREFIX$project" -f "$REPO/$file" ${extra[@]+"${extra[@]}"} "$@"
}
update_parts() {
  local p
  for p in $1; do
    POINT_RENEWED="$POINT_RENEWED $p"
    case "$p" in
      portal-api) run_step 'Rebuilding portal-api and portal-reminders' compose_cmd gfm-portal portal-api/compose.yml up -d --build || return 1 ;;
      da-management) run_step 'Rebuilding DA Management' compose_cmd roster-importer roster-importer/docker-compose.yml up -d --build --no-deps roster-importer || return 1 ;;
      slidev) run_step 'Restarting Presentations (Slidev)' docker restart "$SLIDEV_CONTAINER" || return 1 ;;
      portal) run_step 'Portal pages (portal/deploy.sh)' bash "$REPO/portal/deploy.sh" || return 1 ;;
    esac
  done
}

undo_step() { log "Way back: $1"; shift; "$@" || { log "  did not work."; return 1; }; }
undo_parts() {
  local stamp="upd-$POINT_STAMP" rc=0
  case "$POINT_RENEWED" in *portal-api*)
    run_step 'portal-api image back' docker tag "portal-api-rollback:$stamp" "${PREFIX}gfm-portal-portal-api:latest" || rc=1
    run_step 'portal-reminders image back' docker tag "portal-reminders-rollback:$stamp" "${PREFIX}gfm-portal-portal-reminders:latest" || rc=1
    run_step 'Starting the previous portal-api' compose_cmd gfm-portal portal-api/compose.yml up -d --no-build --no-deps --force-recreate portal-api portal-reminders || rc=1 ;; esac
  case "$POINT_RENEWED" in *da-management*)
    run_step 'DA Management image back' docker tag "roster-importer-rollback:$stamp" "${PREFIX}roster-importer-roster-importer:latest" || rc=1
    run_step 'Starting the previous DA Management' compose_cmd roster-importer roster-importer/docker-compose.yml up -d --no-build --no-deps --force-recreate roster-importer || rc=1 ;; esac
  case "$POINT_RENEWED" in *slidev*) run_step 'Restarting Presentations with the previous code' docker restart "$SLIDEV_CONTAINER" || rc=1 ;; esac
  case "$POINT_RENEWED" in *portal*)
    run_step 'Portal pages back' docker cp "$POINT_FOLDER/portal-html/." "$PORTAL_CONTAINER:/usr/share/nginx/html" || rc=1
    run_step 'Portal reload' docker exec "$PORTAL_CONTAINER" nginx -s reload || rc=1 ;; esac
  return $rc
}
undo_migrations() {  # the migrations this update applied, newest first, each with its own rollback file, then 019
  local m name file user rc=0
  for m in $(printf '%s\n' $POINT_APPLIED | sort -r); do
    name=$(basename "$m" .sql)_rollback.sql; file="$POINT_FOLDER/rollback-sql/$name"
    [ -f "$file" ] || { log "$m has no rollback file; the database stays as it is."; return 1; }
    user=$(migration_user "$(migration_header < "$file")")
    run_sql_file "$file" "$user" || { log "The rollback of $m did not work."; rc=1; continue; }
    rights_check || rc=1
  done
  return $rc
}
undo_update() {
  local all=true
  if [ "$POINT_CODE" = yes ]; then undo_step 'Code back to the previous commit' git_ reset --hard "$POINT_HEAD" >/dev/null || all=false; fi
  undo_step 'Services back to the previous images' undo_parts || all=false
  undo_step 'Database back (rollback files of the new migrations)' undo_migrations || all=false
  if ! wait_for_health; then log 'After putting the previous version back, the health check still does not pass.'; all=false; fi
  if [ $all = true ]; then log 'The previous version is back and healthy.'; return 0; fi
  log "A person needs to look at this. Everything to go back by hand is in $POINT_FOLDER and $POINT_DUMP."
  return 1
}

install_update() {  # asked_by started
  local from=$P_HEAD to=$P_REMOTE stamp; stamp=$(date +%Y%m%d-%H%M%S)
  log "Updating from ${from:0:7} to ${to:0:7} ($(printf '%s' "$P_CHANGES" | grep -c .) change(s)); new migrations: $(printf '%s' "$P_MIGS" | tr '\n' ' ' | sed 's/ $//;s/^$/none/'); renews: $(printf '%s' "$P_PARTS" | tr '\n' ' ' | sed 's/ $//;s/^$/none/')."
  set_state testing quick_tests
  quick_tests "$to" "$stamp" || { complete_update tests_failed '' "$from" "$to" "$1" "$2"; return; }
  set_state updating health_before
  test_health || { log 'The system is not fully healthy now, so the update waits (the health check above says what).'; complete_update refused not_healthy "$from" "$to" "$1" "$2"; return; }
  set_state updating rollback_point
  save_rollback_point "$stamp" || { log 'The way back could not be saved, so nothing is installed.'; complete_update refused rollback_point_failed "$from" "$to" "$1" "$2"; return; }
  local failed=''
  set_state updating code;       update_code "$to" || failed='code'
  [ -n "$failed" ] || { set_state updating migrations; install_migrations || failed='migrations'; }
  [ -n "$failed" ] || { set_state updating services; update_parts "$P_PARTS" || failed='services'; }
  [ -n "$failed" ] || { set_state updating health_after; wait_for_health || failed='health'; }
  if [ -n "$failed" ]; then
    log "The update did not work ($failed). Putting the previous version back."
    set_state rolling_back
    if undo_update; then complete_update rolled_back '' "$from" "$to" "$1" "$2" "$POINT_FOLDER"
    else complete_update needs_person '' "$from" "$to" "$1" "$2" "$POINT_FOLDER"; fi
    return
  fi
  log "Update finished well. The way back stays in $POINT_FOLDER."
  complete_update done '' "$from" "$to" "$1" "$2" "$POINT_FOLDER"
}

do_update() {  # do_update target asked_by
  enter_lock Work || { log 'The updater is busy with something else; this update request is not run.'; return 1; }
  local started from=''; started=$(now)
  log "=== Update asked for by $2 ==="
  set_state checking
  plan
  save_check_result
  from=$P_HEAD
  if [ "$P_CAN" != true ]; then complete_update refused "${P_BLOCKED:-$P_RESULT}" "$from" '' "$2" "$started"; exit_lock Work; return; fi
  if [ -n "$1" ] && [ "$1" != "$P_REMOTE" ]; then
    log 'New changes arrived after the list was shown; nothing is installed. Please look at the list again.'
    complete_update refused list_changed "$from" '' "$2" "$started"; exit_lock Work; return
  fi
  install_update "$2" "$started"
  exit_lock Work
}

# ------------------------------------------------------------------------------------------------------ watching
repair_interrupted_state() {
  case "$(scalar_get state)" in
    testing|updating|rolling_back)
      log 'The last update was interrupted (the computer or the updater stopped). A person should look at the log.'
      part_set last_update "{\"result\": \"needs_person\", \"reason\": \"interrupted\", \"from\": \"\", \"to\": \"\", \"asked_by\": \"\", \"started_at\": \"\", \"finished_at\": $(q "$(now)"), \"rollback_folder\": \"\", \"log\": \"\"}"
      scalar_set state idle step ''; save_status ;;
    checking) scalar_set state idle step '' check_result check_failed can_update false; save_status ;;
  esac
}
heartbeat() {
  enter_lock Work || return 0
  repair_interrupted_state
  local head branch; head=$(git_ rev-parse HEAD 2>/dev/null); branch=$(current_branch)
  part_set current "$(version_json "$head" ", \"branch\": $(q "$branch")")"
  # the version can change without the updater (a person deploying by hand): then the last check no longer fits
  local checked; checked=$(scalar_get checked_head)
  if [ -n "$checked" ] && [ "$checked" != "$head" ]; then scalar_set check_result '' can_update false checked_head ''; part_set new_changes '[]'; fi
  save_status
  exit_lock Work
}
start_watching() {
  enter_lock Watch || { echo 'The updater is already watching.'; return 0; }
  log "The updater watches $REQUESTS (follows $S_REMOTE $([ "$S_TRACK" = tags ] && echo releases || echo "branch $S_BRANCH"), checks every $S_HOURS h)."
  heartbeat
  local next_check=0 next_beat=$(( $(date +%s) + 60 )) t
  while :; do
    t=$(date +%s)
    if read_request; then
      if [ "$REQ_ACTION" = check ]; then log "Check asked for by $REQ_BY."; do_check
      else do_update "$REQ_TARGET" "$REQ_BY"; fi
      next_beat=$(( $(date +%s) + 60 ))
      # A finished update may have brought a new version of this script: stop, so the scheduler starts the new one.
      if [ "$REQ_ACTION" = update ] && grep -q '"result": "done"' "$PARTS/last_update" 2>/dev/null; then log 'Stopping so that the new version of the updater starts.'; return 0; fi
    elif [ "$t" -ge "$next_check" ]; then do_check; next_check=$(( $(date +%s) + CHECK_SECONDS )); next_beat=$(( $(date +%s) + 60 ))
    elif [ "$t" -ge "$next_beat" ]; then heartbeat; next_beat=$(( $(date +%s) + 60 )); fi
    sleep "$POLL"
  done
}

# ------------------------------------------------------------------------------------------------------ by hand in a terminal
show_plan() {
  echo
  echo "This computer: $(git_ log -1 --format='%h  %cs  %s' HEAD)"
  echo "Follows: $P_FOLLOWS   Result: $P_RESULT"
  local c d s; while IFS=$SEP read -r c d s; do [ -n "$c" ] && echo "  new: ${c:0:7}  ${d:0:10}  $s"; done <<<"$P_CHANGES"
  [ -n "$P_BLOCKED" ] && echo "Cannot update now: $P_BLOCKED (updater/README.md explains each reason)."
  echo
}
update_by_hand() {
  do_check || return
  show_plan
  [ "$P_CAN" = true ] || return 0
  if [ "$CONFIRMED" != yes ]; then
    local answer; read -r -p 'Type UPDATE to install these changes: ' answer
    [ "$answer" = UPDATE ] || { echo 'Nothing was installed.'; return 0; }
  fi
  do_update "$P_REMOTE" 'a person in a terminal'
}

# ------------------------------------------------------------------------------------------------------ start
if [ "${GFM_UPDATER_NO_RUN:-}" = 1 ]; then return 0 2>/dev/null || exit 0; fi
if ! read_settings; then scalar_set settings_problem true; save_status; exit 1; fi
[ "$(scalar_get settings_problem)" = true ] && { scalar_set settings_problem false; save_status; }
case "$MODE" in
  check) do_check && show_plan ;;
  update) update_by_hand ;;
  watch) start_watching ;;
  status) if [ -f "$STATUS_FILE" ]; then cat "$STATUS_FILE"; else echo 'No status yet: run check.'; fi ;;
  *) echo "Modes: check, update, watch, status." >&2; exit 2 ;;
esac
