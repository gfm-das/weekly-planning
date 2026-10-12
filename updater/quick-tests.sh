#!/usr/bin/env bash
# updater/quick-tests.sh: the quick tests the updater runs on a copy of a new version before it installs anything (the shell twin of
# quick-tests.ps1; about a minute or two). They need no database and no network: each runs in a throw-away container started with
# --network none, on the copy only (never on the live files).
#   1. Presentations (Slidev): node --test tests/*.test.mjs        4. DA Management's Updates page
#   2. Portal page checks: node portal/tests/*.cjs and *.test.mjs   5. the installer's tests, the updater's own tests
#   3. Python files of portal-api and DA Management compile          6. every shell script parses
# Usage (the updater does this):  quick-tests.sh --root <folder with a copy of the version>      Exit code 0: everything passed.
set -u
ROOT=""
while [ $# -gt 0 ]; do case "$1" in --root) ROOT=${2:?--root needs a folder}; shift 2 ;; *) echo "Unknown option $1" >&2; exit 2 ;; esac; done
[ -d "$ROOT" ] || { echo "Usage: quick-tests.sh --root <folder>" >&2; exit 2; }
ROOT=$(cd "$ROOT" && pwd)
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1; MOUNT=$(cd "$ROOT" && pwd -W) ;; *) MOUNT=$ROOT ;; esac
FAILED=()

part() {  # part "name" command...: output is shown (the updater's log keeps it)
  local name=$1; shift
  echo "--- $name"
  local code=0
  "$@" 2>&1 || code=$?
  if [ $code -eq 0 ]; then echo "--- $name: passed"; else echo "--- $name: DID NOT PASS (exit code $code)"; fi
  return $code
}
in_container() {  # in_container "name" image workdir command...
  local name=$1 image=$2 dir=$3; shift 3
  part "$name" docker run --rm --network none -v "$MOUNT:/repo" -w "$dir" "$image" "$@"
}

# 1. Presentations. One of these tests measures time; a busy computer can make it fail once, so it gets a second try.
presentations() {
  in_container 'Presentations (Slidev) tests' node:24-alpine /repo/slidev sh -c 'node --test tests/*.test.mjs' && return 0
  in_container 'Presentations (Slidev) tests, second try' node:24-alpine /repo/slidev sh -c 'node --test tests/*.test.mjs'
}
# 2. Portal page checks.
portal() { in_container 'Portal page checks' node:24-alpine /repo sh -c 'for f in portal/tests/*.cjs; do echo "$f"; node "$f" || exit 1; done; node --test portal/tests/*.test.mjs'; }
# 3. Python compiles.
python_compiles() { in_container 'Python files compile' python:3.12-alpine /repo python -m compileall -q portal-api roster-importer; }
# 4. DA Management's Updates page, in DA Management's own image (it has Flask). The image has today's packages: when the new version changes
#    them (roster-importer/requirements.txt) they only arrive with the rebuild, so this test then waits for the next update.
updates_page() {
  [ -f "$ROOT/roster-importer/tests/test_updates_page.py" ] || return 0
  local in_image in_version
  in_image=$(docker run --rm --network none roster-importer-roster-importer cat /app/requirements.txt 2>/dev/null | tr -d '\r' | sed 's/^ *//;s/ *$//' | grep .)
  in_version=$(tr -d '\r' < "$ROOT/roster-importer/requirements.txt" | sed 's/^ *//;s/ *$//' | grep .)
  if [ "$in_image" != "$in_version" ]; then echo '--- DA Management Updates page: skipped (this version changes its packages; they arrive with the rebuild)'; return 0; fi
  part 'DA Management Updates page' docker run --rm --network none -v "$MOUNT:/repo" -w /repo/roster-importer -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none \
    -e PYTHONDONTWRITEBYTECODE=1 roster-importer-roster-importer python -m unittest tests.test_updates_page
}
# 5. The installer's tests and the updater's own tests.
installer() { [ -d "$ROOT/install/tests" ] || return 0; in_container "Installer tests" node:24-alpine /repo/install sh -c 'node --test tests/*.test.mjs'; }
# The updater's own test suite takes 10 minutes or more (it starts watchers and waits), and the release builder has already run it on exactly this
# code (release/verify.sh), so an update runs it only when asked: GFM_QUICK_UPDATER_TESTS=yes. The scripts' syntax is always checked (step 6).
updater_tests() {
  [ -f "$ROOT/updater/tests/test-updater.sh" ] || return 0
  if [ "${GFM_QUICK_UPDATER_TESTS:-}" = yes ]; then part 'Updater tests' bash "$ROOT/updater/tests/test-updater.sh"
  else echo "Updater tests: skipped (the release was tested before it was published; GFM_QUICK_UPDATER_TESTS=yes runs them here)"; fi
}
# 6. Every shell script parses (a typo would stop a deploy half-way).
shell_scripts() {
  echo '--- shell scripts parse'
  local f bad=0
  while IFS= read -r f; do bash -n "$f" 2>/dev/null || { echo "${f#"$ROOT"/}: does not parse"; bad=1; }; done < <(find "$ROOT" -name '*.sh' -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/backups/*' -not -path '*/legacy/*')
  return $bad
}

presentations || FAILED+=(Presentations)
portal || FAILED+=(Portal)
python_compiles || FAILED+=(Python)
updates_page || FAILED+=("Updates page")
installer || FAILED+=(Installer)
updater_tests || FAILED+=(Updater)
shell_scripts || FAILED+=("Shell scripts")

if [ ${#FAILED[@]} -gt 0 ]; then echo "Quick tests that did not pass: $(IFS=,; echo "${FAILED[*]}" | sed 's/,/, /g')"; exit 1; fi
echo 'All quick tests passed.'
