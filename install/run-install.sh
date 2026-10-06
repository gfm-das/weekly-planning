#!/usr/bin/env bash
# run-install.sh: builds the system from the saved answers (install/.work/answers.json). Started by install.sh.
# Steps, in this order (a step only starts when the one before it worked):
#   1. write the settings files (.env) with new secrets          5. the mission and the first Data Analyst account
#   2. Docker network and volumes                                 6. the programs: portal, DA Management, Presentations, backups
#   3. the database stack (Supabase)                              7. Dashboards (DataEase)
#   4. the database: baseline, then newer migrations              8. the health check, then the address to open
# The names below can be changed through the environment, so a test can run next to a live system without touching it:
#   GFM_SUPA_PROJECT (gfm-beta)  GFM_DB_CONTAINER  GFM_NETWORK (gfm-network)  GFM_AUTH_BASE  GFM_SUPA_SERVICES  GFM_VOLUMES
#   GFM_PROJECT_PREFIX (added to every other compose project name)  GFM_OVERRIDE_DIR (a folder, relative to the repository: <part>.yml
#   is one more compose file of that part)  GFM_SKIP_DATAEASE=yes  and the names and ports health.sh reads (see health.sh).
set -eu

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
WORK="$HERE/.work"
IMAGE=node:24-alpine

SUPA_PROJECT=${GFM_SUPA_PROJECT:-gfm-beta}
DB_CONTAINER=${GFM_DB_CONTAINER:-${SUPA_PROJECT}-supabase-db-1}
NETWORK=${GFM_NETWORK:-gfm-network}
AUTH_BASE=${GFM_AUTH_BASE:-http://gfm-beta-supabase-kong-1:8000/auth/v1}
PREFIX=${GFM_PROJECT_PREFIX:-}
OVERRIDE_DIR=${GFM_OVERRIDE_DIR:-}
SUPA_SERVICES=${GFM_SUPA_SERVICES:-}           # only these services of the stack (tests); empty: all of them
VOLUMES=${GFM_VOLUMES:-portal-data slidev-data}

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
stop() { printf '\nStopped: %s\n' "$*" >&2; exit 1; }

case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) OS=windows; export MSYS_NO_PATHCONV=1; host_path() { (cd "$1" && pwd -W); } ;;
  Darwin) OS=mac; host_path() { (cd "$1" && pwd -P); } ;;
  *) OS=linux; host_path() { (cd "$1" && pwd -P); } ;;
esac

# This computer's address in the office network (the other computers' browsers use it). 127.0.0.1 when it cannot be found.
detect_host_ip() {
  local ip=""
  case "$OS" in
    mac) ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true) ;;
    linux) ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true) ;;
    # Windows: the address of the adapter that has a default gateway (the one that reaches the network), else the first
    # private address of an adapter that is not WSL, Hyper-V, Docker or a virtual machine. (ipconfig's words differ by language.)
    windows) ip=$(ipconfig 2>/dev/null | tr -d '\015' | awk '
        function flush() { if (addr != "" && gate != "" && best == "") best = addr; if (addr != "" && !skip && first == "") first = addr; addr = ""; gate = "" }
        /^[^ ]/ { flush(); skip = ($0 ~ /vEthernet|WSL|Docker|Hyper-V|VirtualBox|VMware|Loopback|Bluetooth/) }
        /IPv4/ { v = $0; sub(/.*: /, "", v); addr = v }
        /ateway/ { v = $0; sub(/.*: /, "", v); if (v ~ /[0-9a-fA-F]/) gate = v }
        END { flush(); print (best != "" ? best : first) }') ;;
  esac
  printf '%s' "${ip:-127.0.0.1}"
}

node_run() {   # node_run [docker options] -- script and arguments (the repository is /r, the work folder /work)
  local opts=()
  while [ "$1" != "--" ]; do opts+=("$1"); shift; done
  shift
  docker run --rm ${opts[@]+"${opts[@]}"} -v "$(host_path "$REPO"):/r" -v "$(host_path "$WORK"):/work" -w /r/install/app "$IMAGE" node "$@"
}

# compose_part NAME PROJECT FILE... -- ARGS: runs docker compose for one part, from the repository folder (FILEs relative to it).
compose_part() {
  local name=$1 project=$2; shift 2
  local files=()
  while [ "$1" != "--" ]; do files+=(-f "$1"); shift; done
  shift
  [ -n "$OVERRIDE_DIR" ] && [ -f "$REPO/$OVERRIDE_DIR/$name.yml" ] && files+=(-f "$OVERRIDE_DIR/$name.yml")
  (cd "$REPO" && docker compose -p "$PREFIX$project" "${files[@]}" "$@")
}
compose_supabase() {
  local files=(supabase/supabase-compose.yml supabase/beta-override.yml)
  local extra=()
  [ -n "$OVERRIDE_DIR" ] && [ -f "$REPO/$OVERRIDE_DIR/supabase.yml" ] && extra=(-f "$OVERRIDE_DIR/supabase.yml")
  (cd "$REPO" && docker compose -p "$SUPA_PROJECT" --env-file supabase/.env -f "${files[0]}" -f "${files[1]}" ${extra[@]+"${extra[@]}"} "$@")
}

# psql as one of the database's users, reading the file or the text on standard input.
db_psql() { local user=$1; shift; docker exec -i "$DB_CONTAINER" psql -U "$user" -d postgres -v ON_ERROR_STOP=1 "$@"; }

step_generate() {
  step "1/10 Writing the settings files"
  [ -f "$WORK/answers.json" ] || stop "install/.work/answers.json is missing."
  GFM_HOST_IP=$(detect_host_ip)
  node_run -e "GFM_HOST_IP=$GFM_HOST_IP" -- generate.mjs /work/answers.json /r || stop "the settings files could not be written (see above)."
  # shellcheck disable=SC1091
  . "$WORK/install.env"
  say "This computer's address in the network: $GFM_HOST_IP"
}

step_network() {
  step "2/10 Docker network and volumes"
  docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
  # The portal's pages and the decks live in volumes the compose files expect to exist.
  local volume
  for volume in $VOLUMES; do
    docker volume inspect "$volume" >/dev/null 2>&1 || docker volume create "$volume" >/dev/null
  done
  say "Network $NETWORK and the volumes ($VOLUMES) are ready."
}

step_supabase() {
  step "3/10 The database stack (Supabase)"
  # All services: compose starts each one when the ones it needs are healthy. A test names only the few services it needs, and then
  # they are started without their neighbours (--no-deps).
  local no_deps=""
  [ -n "$SUPA_SERVICES" ] && no_deps="--no-deps"
  # shellcheck disable=SC2086
  if ! compose_supabase up -d $no_deps $SUPA_SERVICES >"$WORK/compose.log" 2>&1; then
    tail -15 "$WORK/compose.log" >&2
    stop "the database stack did not start (the log is install/.work/compose.log)."
  fi
  say "Waiting for the database ..."
  local i
  for i in $(seq 1 90); do
    if docker exec "$DB_CONTAINER" pg_isready -U supabase_admin -h 127.0.0.1 >/dev/null 2>&1; then
      # pg_isready answers during the first start before the setup scripts finished: wait until they have.
      if db_psql supabase_admin -Atc "select 1 from pg_roles where rolname='supabase_auth_admin'" 2>/dev/null | grep -q 1; then
        say "The database is ready."
        return 0
      fi
    fi
    sleep 2
  done
  stop "the database did not become ready in three minutes (docker logs $DB_CONTAINER)."
}

# The user a migration is run as, from its header: "psql -U postgres", else supabase_admin (as updater/gfm-updater.ps1).
migration_user() {
  local u
  u=$(sed -n '/^[[:space:]]*BEGIN/q;p' "$1" | grep -oE 'psql -U (postgres|supabase_admin)' | head -1 | awk '{print $3}')
  printf '%s' "${u:-supabase_admin}"
}

step_database() {
  step "4/10 The database: baseline, then newer migrations"
  local rights="$REPO/portal-api/migrations/019_restrict_public_functions.sql"
  if [ "$(db_psql supabase_admin -Atc "select count(*) from information_schema.tables where table_schema='public' and table_name='missions'")" != 0 ]; then
    stop "the database already has the mission tables. This installer is for an empty database."
  fi
  say "baseline (the schema as of migration 040) ..."
  db_psql supabase_admin --single-transaction -q < "$REPO/portal-api/baseline/000_baseline.sql" >/dev/null || stop "the baseline failed (see above); nothing of it stays."
  db_psql supabase_admin -q < "$rights" >/dev/null || stop "the rights check (019) failed."
  local file name
  for file in "$REPO"/portal-api/migrations/[0-9][0-9][0-9]_*.sql; do
    name=$(basename "$file")
    case "$name" in *_rollback.sql) continue ;; 019_*) continue ;; esac
    [ "${name%%_*}" -gt 40 ] || continue
    say "migration $name ..."
    db_psql "$(migration_user "$file")" -q < "$file" >/dev/null || stop "migration $name failed (see above)."
    db_psql supabase_admin -q < "$rights" >/dev/null || stop "the rights check (019) failed after $name."
  done
  say "The database is up to date."
}

step_account() {
  step "5/10 The mission and the first Data Analyst"
  db_psql supabase_admin -q -v "mission_name=$GFM_MISSION_NAME" -v "default_language=$GFM_DEFAULT_LANGUAGE" -v "time_zone=$GFM_TIME_ZONE" < "$HERE/sql/mission.sql" >/dev/null || stop "the mission could not be made (see above)."
  say "Mission 1: $GFM_MISSION_NAME ($GFM_MISSION_CODE), default language $GFM_DEFAULT_LANGUAGE, time zone $GFM_TIME_ZONE."
  local uid
  uid=$(node_run --network "$NETWORK" -e "AUTH_BASE=$AUTH_BASE" -- first-account.mjs /work/answers.json /r/supabase/.env) || stop "the first sign-in could not be made (see above)."
  [[ "$uid" =~ ^[0-9a-f-]{36}$ ]] || stop "Supabase Auth did not give a sign-in id."
  db_psql supabase_admin -q -v "uid=$uid" -v "display_name=$GFM_FIRST_NAME" <<'SQL' >/dev/null || stop "the first account's profile could not be made."
INSERT INTO public.user_profiles (id, missionary_id, app_role, active, display_name, home_mission_id)
VALUES (:'uid'::uuid, NULL, 'DATA_ADMIN', true, :'display_name', 1);
SQL
  say "The first Data Analyst ($GFM_FIRST_EMAIL) can sign in."
}

# The programs, one after the other. Each is built from the files in this folder (the first build takes several minutes).
step_programs() {
  step "6/10 The programs: portal, DA Management, Presentations, backups"
  mkdir -p "$REPO/backups/nightly" "$REPO/updater/requests" "$REPO/updater/status" "$REPO/updater/logs"
  say "portal-api and the reminders ..."
  compose_part portal-api gfm-portal portal-api/compose.yml -- up -d --build >"$WORK/programs.log" 2>&1 || program_failed portal-api
  say "DA Management ..."
  compose_part roster-importer roster-importer roster-importer/docker-compose.yml -- up -d --build --no-deps roster-importer >>"$WORK/programs.log" 2>&1 || program_failed "DA Management"
  # Presentations installs about 500 MB of packages on its first start. Done here, in view, the container then starts in seconds (the
  # packages stay in the slidev-data volume). Nothing is printed by npm meanwhile, so a dot every 20 seconds shows it is working.
  say "Presentations: installing its packages (the first time this takes 5 to 10 minutes; a dot every 20 seconds) ..."
  docker run --rm -v "${GFM_SLIDEV_VOLUME:-slidev-data}:/slidev" -v "$(host_path "$REPO/slidev")/package.json:/slidev/package.json:ro" -w /slidev "$IMAGE"     npm install --no-audit --no-fund >>"$WORK/programs.log" 2>&1 &
  local installer_pid=$!
  while kill -0 "$installer_pid" 2>/dev/null; do printf '.'; sleep 20; done
  printf '
'
  wait "$installer_pid" || program_failed "Presentations (installing its packages)"
  say "Presentations ..."
  compose_part slidev slidev slidev/slidev-compose.yml slidev/local-override.yml -- up -d --no-deps slidev >>"$WORK/programs.log" 2>&1 || program_failed Presentations
  say "the portal ..."
  compose_part portal portal portal/portal-compose.yml portal/local-override.yml -- up -d --no-deps portal >>"$WORK/programs.log" 2>&1 || program_failed "the portal"
  bash "$REPO/portal/deploy.sh" >>"$WORK/programs.log" 2>&1 || program_failed "the portal pages"
  say "nightly backups ..."
  compose_part backup gfm-backup nightly-backup/backup-compose.yml -- up -d >>"$WORK/programs.log" 2>&1 || program_failed "the nightly backup"
  say "All programs are started."
}
program_failed() {
  tail -15 "$WORK/programs.log" >&2
  stop "$1 did not start (the whole log is install/.work/programs.log)."
}

step_dataease() {
  step "7/10 Dashboards (DataEase)"
  if [ "${GFM_SKIP_DATAEASE:-}" = yes ]; then say "Skipped (GFM_SKIP_DATAEASE=yes)."; return 0; fi
  say "starting DataEase (the first start takes a minute or two) ..."
  compose_part dataease gfm-dataease dataease/compose.yml -- up -d >"$WORK/dataease.log" 2>&1 || { tail -15 "$WORK/dataease.log" >&2; stop "DataEase did not start (install/.work/dataease.log)."; }
  say "the read-only database login ..."
  GFM_DB_CONTAINER=$DB_CONTAINER bash "$REPO/dataease/set-reader-password.sh" >>"$WORK/dataease.log" 2>&1 || { tail -15 "$WORK/dataease.log" >&2; stop "the Dashboards database login could not be set."; }
  say "waiting for DataEase ..."
  local i name=${GFM_DATAEASE_NAME:-gfm-dataease} port=${GFM_PORT_DATAEASE:-8088}
  for i in $(seq 1 90); do
    curl -fs "http://127.0.0.1:$port/gfm-gate-health" 2>/dev/null | grep -q '"signed-in"' && break
    sleep 4
  done
  say "the three dashboards ..."
  GFM_DATAEASE_PROJECT=$name bash "$REPO/dataease/seed-dashboards.sh" --allow-empty >>"$WORK/dataease.log" 2>&1 || { tail -15 "$WORK/dataease.log" >&2; stop "the dashboards could not be set up (install/.work/dataease.log)."; }
  say "their copies in the other languages ..."
  GFM_DATAEASE_PROJECT=$name bash "$REPO/dataease/translate-dashboards.sh" >>"$WORK/dataease.log" 2>&1 || { tail -15 "$WORK/dataease.log" >&2; stop "the dashboard translations failed (install/.work/dataease.log)."; }
  say "Dashboards are ready."
}

# The routes to enter in Cloudflare, one per public name. From inside the tunnel's container the programs of this computer are reached as
# host.docker.internal:<port>. Also written to cloudflared/ROUTES.txt (no secret in it).
tunnel_routes() {
  local d=$GFM_PUBLIC_DOMAIN h=http://host.docker.internal
  printf '%-30s %-38s %s\n' "Public name" "Service (type HTTP)" "What it is"
  printf '%-30s %-38s %s\n' "$d" "$h:${GFM_PORT_PORTAL:-8070}" "the portal"
  printf '%-30s %-38s %s\n' "www.$d" "$h:${GFM_PORT_PORTAL:-8070}" "the portal"
  printf '%-30s %-38s %s\n' "dashboards.$d" "$h:${GFM_PORT_DATAEASE:-8088}" "Dashboards"
  printf '%-30s %-38s %s\n' "presentations.$d" "$h:${GFM_PORT_SLIDEV:-3030}" "Presentations"
  printf '%-30s %-38s %s\n' "decks.$d" "$h:${GFM_PORT_DECKS:-8089}" "Presentation decks"
  printf '%-30s %-38s %s\n' "management.$d" "$h:${GFM_PORT_IMPORTER:-8090}" "DA Management"
}

step_cloudflare() {
  step "8/10 The Cloudflare tunnel"
  if [ "$GFM_CLOUDFLARE" != yes ]; then say "Skipped: no tunnel token was given (the portal works on the local network only)."; return 0; fi
  local name=${GFM_CLOUDFLARED_CONTAINER:-gfm-cloudflared}
  say "starting the tunnel ..."
  if ! compose_part cloudflared gfm-cloudflared cloudflared/compose.yml -- up -d >"$WORK/cloudflared.log" 2>&1; then
    # The system works without the tunnel, so this does not stop the installation.
    tail -8 "$WORK/cloudflared.log" >&2
    say "The tunnel container could not be started (above). The rest is installed; try again later with: docker compose -p gfm-cloudflared -f cloudflared/compose.yml up -d"
    return 0
  fi
  tunnel_routes > "$REPO/cloudflared/ROUTES.txt"
  local i status=""
  for i in $(seq 1 25); do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null || true)
    [ "$status" = healthy ] && break
    sleep 3
  done
  if [ "$status" = healthy ]; then say "The tunnel is connected to Cloudflare."
  else say "The tunnel container runs but is not connected yet. Check the token and the internet connection (docker logs $name). The rest is installed."; fi
  say ""
  say "One more thing, in Cloudflare: add these routes to your tunnel (Public hostnames, type HTTP):"
  say ""
  tunnel_routes | sed 's/^/    /'
  say ""
  say "(The list is also in cloudflared/ROUTES.txt.)"
}

# Updates: this folder is a copy of the public repository (the starter scripts make it one), so the updater follows its releases (Track tags).
# register-watcher.sh makes the computer's own scheduler keep the updater watching; DA Management > Updates then works.
step_updater() {
  step "9/10 Updates"
  local GREPO; GREPO=$(cd "$REPO" && { pwd -W 2>/dev/null || pwd; })   # (git is a Windows program on Windows: it needs C:/..., not /c/...)
  if ! git -C "$GREPO" rev-parse --git-dir >/dev/null 2>&1 || ! git -C "$GREPO" remote get-url origin >/dev/null 2>&1; then
    say "This folder is not a Git copy of the public repository, so the system cannot update itself. (Install with the starter script from the website,"
    say "or run: git clone https://github.com/gfm-das/weekly-planning , to get updates.)"
    return 0
  fi
  printf '{"Remote": "origin", "Branch": "main", "Track": "tags", "CheckEveryHours": 6}\n' > "$REPO/updater/settings.json"
  say "The updater follows the releases of $(git -C "$GREPO" remote get-url origin | sed -E 's#(://)[^/@]*@#\1#')."
  if [ "${GFM_SKIP_UPDATER_TASK:-}" = yes ]; then say "Skipped: the scheduler task is not made (GFM_SKIP_UPDATER_TASK=yes)."; return 0; fi
  if bash "$REPO/updater/register-watcher.sh" >"$WORK/updater.log" 2>&1; then say "The updater now runs in the background (every 5 minutes it makes sure it is watching)."
  else tail -5 "$WORK/updater.log" >&2; say "The scheduler task could not be made (above). Updates can still be started by hand: bash updater/gfm-updater.sh update"; fi
}

step_finish() {
  step "10/10 The health check"
  local out
  # Presentations installs its own packages from the internet on its first start, which can take several minutes on a slow line.
  if ! out=$(cd "$REPO" && bash health.sh --wait 600 2>&1); then
    printf '%s\n' "$out" >&2
    local c
    for c in "${GFM_SLIDEV_CONTAINER:-slidev}" portal-api "${GFM_PORTAL_CONTAINER:-portal}" "${GFM_CLOUDFLARED_CONTAINER:-gfm-cloudflared}"; do
      docker container inspect "$c" >/dev/null 2>&1 && { echo "--- last lines of $c:" >&2; docker logs --tail 8 "$c" >&2 2>&1; }
    done
    stop "the health check shows a problem (above). The system is installed but not all of it answers; docker logs <container> says why."
  fi
  printf '%s\n' "$out"
  # The answers file holds the first password: it is deleted now (the mission's data is in the database).
  rm -f "$WORK"/answers.json "$WORK"/logo.* "$WORK"/compose.log "$WORK"/programs.log "$WORK"/dataease.log "$WORK"/cloudflared.log "$WORK"/updater.log
  say ""
  say "============================================================"
  say "$GFM_MISSION_NAME ($GFM_MISSION_CODE) is installed."
  say ""
  say "Open the portal:   http://localhost:${GFM_PORT_PORTAL:-8070}"
  say "                   http://$GFM_HOST_IP:${GFM_PORT_PORTAL:-8070}   (from other computers in the office network)"
  [ -n "$GFM_PUBLIC_DOMAIN" ] && say "                   https://$GFM_PUBLIC_DOMAIN   (once its Cloudflare tunnel and routes are set up)"
  say "Sign in with:     $GFM_FIRST_EMAIL   and the password you typed."
  say "Next:             open DA Management (port ${GFM_PORT_IMPORTER:-8090}), create the other accounts, then Roster Import."
  [ "$GFM_CLOUDFLARE" = yes ] && say "Cloudflare:        the tunnel runs; its routes are in cloudflared/ROUTES.txt (enter them in Cloudflare once)."
  [ -f "$WORK/language-request.txt" ] && say "Your language request is in install/.work/language-request.txt."
  say "============================================================"
}

main() {
  command -v docker >/dev/null 2>&1 || stop "Docker is not installed."
  step_generate
  step_network
  step_supabase
  step_database
  step_account
  step_programs
  step_dataease
  step_cloudflare
  step_updater
  step_finish
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
