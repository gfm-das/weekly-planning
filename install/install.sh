#!/usr/bin/env bash
# install.sh: the one command that starts the Weekly Planning installer (macOS, Linux, and Windows through Git Bash).
#   ./install/install.sh                 opens the setup form in your browser (on a computer with a screen)
#   ./install/install.sh --cli           the same questions in this terminal (a computer with no screen, for example over SSH)
#   ./install/install.sh --answers FILE  no questions: uses an answers file you wrote earlier
#   options: --port 8099   the port of the form (this computer only)    --no-open   do not open the browser myself
# Only Docker is needed on the computer. The form runs in a small throw-away container; this script only starts it,
# and (in a later step) hands the saved answers to run-install.sh, which builds the system.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
PORT=8099
OPEN=yes
ANSWERS=""
MODE=""   # web or cli; empty: the form when there is a screen, the terminal when there is none

say() { printf '%s\n' "$*"; }
stop() { printf '\nStopped: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT=${2:?--port needs a number}; shift 2 ;;
    --no-open) OPEN=no; shift ;;
    --answers) ANSWERS=${2:?--answers needs a file}; shift 2 ;;
    --web) MODE=web; shift ;;
    --cli) MODE=cli; shift ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) stop "I do not know the option '$1'. Try --help." ;;
  esac
done

# ---- which computer is this? (only the way paths are written differs)
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *) OS=unknown ;;
esac
# Docker (a program on Windows) wants Windows-style folder names; the shell's own /c/... names would be taken literally.
if [ "$OS" = windows ]; then
  export MSYS_NO_PATHCONV=1
  host_path() { (cd "$1" && pwd -W); }
else
  host_path() { (cd "$1" && pwd -P); }
fi

# ---- Docker there and running?
command -v docker >/dev/null 2>&1 || stop "Docker is not installed. Install Docker Desktop (Windows, Mac) or Docker Engine (Linux): https://docs.docker.com/get-docker/ , then run this command again."
docker info >/dev/null 2>&1 || stop "Docker is installed but not running. Start Docker Desktop (or the Docker service) and run this command again."
docker compose version >/dev/null 2>&1 || stop "Docker Compose is missing. Docker Desktop includes it; on Linux install the 'docker-compose-plugin' package."

INSTALL_HOST=$(host_path "$HERE")
I18N_HOST=$(host_path "$REPO/portal/i18n")
WORK="$HERE/.work"
mkdir -p "$WORK"
chmod 700 "$WORK" 2>/dev/null || true
IMAGE=node:24-alpine

run_in_container() {  # run_in_container [docker options] -- node arguments
  local opts=()
  while [ "$1" != "--" ]; do opts+=("$1"); shift; done
  shift
  # (an empty list is written ${x[@]+"${x[@]}"} because macOS's old bash stops on an empty one)
  local run=(docker)
  # In Git Bash a terminal for Docker needs winpty.
  if [ "$OS" = windows ] && command -v winpty >/dev/null 2>&1 && [[ " ${opts[*]-} " == *" -it "* ]]; then run=(winpty docker); fi
  "${run[@]}" run --rm ${opts[@]+"${opts[@]}"} -v "$INSTALL_HOST:/install" -v "$I18N_HOST:/i18n:ro" -w /install/app "$IMAGE" node setup.mjs "$@"
}

open_browser() {
  local url=$1
  case "$OS" in
    mac) open "$url" ;;
    windows) cmd.exe //c start "" "$url" >/dev/null 2>&1 ;;
    linux) xdg-open "$url" >/dev/null 2>&1 ;;
  esac
}

# ---- a screen? (Linux without one, or over SSH, cannot open a browser)
has_screen() {
  [ "$OS" != linux ] && return 0
  [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ -z "${SSH_CONNECTION:-}" ]
}

rm -f "$WORK/answers.json"

if [ -n "$ANSWERS" ]; then
  [ -f "$ANSWERS" ] || stop "I cannot find the answers file '$ANSWERS'."
  cp "$ANSWERS" "$WORK/answers.json"
  chmod 600 "$WORK/answers.json" 2>/dev/null || true
  say "Checking the answers file ..."
  run_in_container -- --check /install/.work/answers.json || { rm -f "$WORK/answers.json"; stop "the answers file needs fixing (see above)."; }
else
  if [ -z "$MODE" ]; then
    if has_screen; then MODE=web; else MODE=cli; fi
  fi
  if [ "$MODE" = cli ]; then
    [ -t 0 ] || stop "the terminal mode needs a real terminal to type in. For a script, write an answers file and use --answers FILE."
    run_in_container -it -e "GFM_TZ=${TZ:-$(cat /etc/timezone 2>/dev/null || true)}" -- --cli || stop "the questions were not finished, so nothing was saved."
  else
    say "Starting the setup form on http://localhost:$PORT ..."
    say "(Press Ctrl+C to stop without installing.)"
    if [ "$OPEN" = yes ]; then
      ( for _ in $(seq 1 60); do
          if curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then open_browser "http://localhost:$PORT"; break; fi
          sleep 1
        done ) &
    fi
    TTY=()
    if [ -t 0 ]; then TTY=(-it); fi
    # The form only listens on this computer's own address (127.0.0.1).
    run_in_container ${TTY[@]+"${TTY[@]}"} --name gfm-installer-form -p "127.0.0.1:$PORT:$PORT" -- --web --port "$PORT" || stop "the form stopped before your settings were saved (is port $PORT already in use? try --port 8100)."
  fi
fi

[ -f "$WORK/answers.json" ] || stop "no settings were saved."

if [ -f "$HERE/run-install.sh" ]; then
  exec bash "$HERE/run-install.sh" "$WORK/answers.json"
fi
say ""
say "Your settings are saved in install/.work/answers.json (only you can read it)."
say "Building the system from them is the next part of the installer and is not built yet."
