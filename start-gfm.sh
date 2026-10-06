#!/usr/bin/env bash
# start-gfm.sh: starts the whole mission system after the computer or Docker stopped (the shell twin of start-gfm.ps1).
# It makes sure Docker runs (on Mac and Windows it starts Docker Desktop and waits; on Linux it only says what to do), starts every
# part that is stopped (the containers restart by themselves when Docker starts; this also catches the ones that did not), and then
# waits until health.sh says every part answers.   bash start-gfm.sh [--wait 240]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
WAIT=240
[ "${1:-}" = --wait ] && WAIT=${2:-240}
OS=linux
case "$(uname -s 2>/dev/null)" in Darwin) OS=mac ;; MINGW*|MSYS*|CYGWIN*) OS=windows; export MSYS_NO_PATHCONV=1 ;; esac

docker_ready() { docker version --format '{{.Server.Version}}' >/dev/null 2>&1; }

if ! docker_ready; then
  case "$OS" in
    mac) echo "Starting Docker Desktop ..."; open -a Docker ;;
    windows)
      desktop="$LOCALAPPDATA\\Programs\\DockerDesktop\\Docker Desktop.exe"
      [ -f "$(cygpath -u "$desktop" 2>/dev/null || echo "$desktop")" ] || { echo "Docker Desktop was not found at $desktop" >&2; exit 1; }
      echo "Starting Docker Desktop ..."; cmd.exe //c start "" "$desktop" >/dev/null 2>&1 ;;
    linux) echo "Docker is not running. Start it with: sudo systemctl start docker" >&2; exit 1 ;;
  esac
  for _ in $(seq 1 60); do docker_ready && break; sleep 2; done
fi
docker_ready || { echo "Docker did not become ready in time." >&2; exit 1; }
echo "Docker engine $(docker version --format '{{.Server.Version}}') is ready."

# Containers with a restart rule come back by themselves; start the ones that are stopped anyway (never creates or removes any).
stopped=$(docker ps -a --filter status=exited --filter status=created --format '{{.Names}}' | grep -E '^(gfm-|portal|roster-importer|slidev)' || true)
[ -n "$stopped" ] && echo "$stopped" | xargs docker start >/dev/null 2>&1

bash "$HERE/health.sh" --wait "$WAIT"
