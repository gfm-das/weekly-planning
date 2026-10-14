#!/usr/bin/env bash
# tools/add-analyst-login.sh: makes one Data Analyst's personal database login (for DBeaver and Jupyter), or gives an existing one a new password.
# Run it ON THE SERVER, from the repository folder, by a person who has decided to give someone database access (the owner's "go").
#
#   bash tools/add-analyst-login.sh <name>                make the login <name> (small letters, digits, _; 3 to 31 characters)
#   bash tools/add-analyst-login.sh <name> --reset        give <name> a new password
#   bash tools/add-analyst-login.sh <name> --dry-run      check the name and show what would happen; changes nothing
#   --yes             do not ask for the typed confirmation (needed when there is no terminal)
#   --secrets-dir D   where the password file is written (default: $GFM_SECRETS_DIR, else ~/gfm-secrets). It must be OUTSIDE the repository.
#
# What it does: makes a long random password; writes it to <secrets-dir>/analyst-<name>.txt (mode 600, never in Git, never printed here);
# runs install/sql/add-analyst-login.sql as supabase_admin inside the database container (login + BYPASSRLS + member of gfm_db_analysts, the
# group role of migration 043: full read/write/create in public, portal and dashboards, not a superuser); checks that the new login can
# connect and write. Give the file's content to the person privately (not by chat, not in Git). They reach the database through an
# SSH tunnel: docs/DBEAVER.md.
#
# Settings (environment): GFM_DB_CONTAINER (default <GFM_SUPA_PROJECT>-supabase-db-1), GFM_SUPA_PROJECT (default gfm-beta),
# GFM_SECRETS_DIR, GFM_DB_PORT (the database's port on the server, default 54322: only used in the text of the password file).
# This script was tested against a fake database program and (install/tests/test-analyst-login.sh) on a throw-away database; running it on
# the live server needs the owner's "go".
set -eu

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/.." && pwd -P)
SQL="$REPO/install/sql/add-analyst-login.sql"
SUPA_PROJECT=${GFM_SUPA_PROJECT:-gfm-beta}
DB_CONTAINER=${GFM_DB_CONTAINER:-${SUPA_PROJECT}-supabase-db-1}
DB_PORT=${GFM_DB_PORT:-54322}

say() { printf '%s\n' "$*"; }
stop() { printf 'Stopped: %s\n' "$*" >&2; exit "${2:-1}"; }
usage() { sed -n '2,/^set -eu/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

NAME="" ACTION=create DRY=no YES=no SECRETS=${GFM_SECRETS_DIR:-$HOME/gfm-secrets}
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --reset) ACTION=reset; shift ;;
    --dry-run) DRY=yes; shift ;;
    --yes) YES=yes; shift ;;
    --secrets-dir) SECRETS=${2:?--secrets-dir needs a folder}; shift 2 ;;
    -*) stop "unknown option $1 (see --help)" 2 ;;
    *) [ -z "$NAME" ] || stop "give one login name only." 2; NAME=$1; shift ;;
  esac
done
[ -n "$NAME" ] || { usage >&2; exit 2; }

# The name: the same rule as the SQL file, and no system roles.
[[ "$NAME" =~ ^[a-z][a-z0-9_]{2,30}$ ]] || stop "the login name must be small letters, digits and _ (3 to 31 characters, starting with a letter)." 2
case "$NAME" in
  pg_*|supabase_*|pgbouncer*|authenticator*|dashboard_user*|postgres|anon|authenticated|service_role|gfm_db_analysts|gfm_dashboard_reader|public)
    stop "'$NAME' is the name of a system role. Choose a person's name, for example anna_k." 2 ;;
esac

# The secrets folder must be outside the repository (a password file inside it could be committed by mistake).
mkdir -p "$SECRETS" 2>/dev/null || stop "cannot make the secrets folder $SECRETS." 2
SECRETS=$(cd "$SECRETS" && pwd -P)
case "$SECRETS/" in "$REPO"/*) stop "the secrets folder ($SECRETS) is inside the repository. Choose a folder outside it (--secrets-dir)." 2 ;; esac
TARGET="$SECRETS/analyst-$NAME.txt"

if [ "$DRY" = yes ]; then
  say "Dry run: nothing is changed."
  say "Would $ACTION the login '$NAME' in the database container '$DB_CONTAINER' (member of gfm_db_analysts, BYPASSRLS)."
  say "Would write the new password to $TARGET (mode 600)."
  exit 0
fi

command -v docker >/dev/null 2>&1 || stop "Docker is not installed or not on the PATH."
[ -f "$SQL" ] || stop "$SQL is missing."
[ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || true)" = true ] || stop "the database container '$DB_CONTAINER' is not running (set GFM_DB_CONTAINER if it has another name)."

if [ "$YES" != yes ]; then
  [ -t 0 ] || stop "there is no terminal to ask you. Add --yes if you really mean it." 2
  say "About to $ACTION the full-access database login '$NAME' (reads, writes and creates in public, portal and dashboards; sees every row)."
  printf 'Type the login name again to confirm: '
  read -r answer
  [ "$answer" = "$NAME" ] || stop "not confirmed; nothing was changed." 2
fi

# A long random password (letters and digits only, so it is safe in every tool).
make_password() {
  local p=""
  if [ -r /dev/urandom ]; then p=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true); fi
  if [ "${#p}" -lt 32 ] && command -v openssl >/dev/null 2>&1; then p=$(openssl rand -base64 48 | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32 || true); fi
  [ "${#p}" -ge 32 ] || stop "could not make a random password."
  printf '%s' "$p"
}
PASSWORD=$(make_password)

# The password goes into a file first (mode 600), so it cannot be lost if the database step succeeds and this script is cut off.
umask 077
TMPFILE=$(mktemp "$SECRETS/.analyst-$NAME.XXXXXX")
trap 'rm -f "$TMPFILE"' EXIT
cat > "$TMPFILE" <<EOF
GFM database login for $NAME. Private: do not put this in Git, chat or email.
Created: $(date -u +%Y-%m-%dT%H:%M:%SZ) (action: $ACTION)

Login:     $NAME
Password:  $PASSWORD
Database:  postgres
Schemas:   public, portal, dashboards (full read/write/create; every row is visible)

The database listens on the server's own address only (127.0.0.1:$DB_PORT). From your computer open an SSH tunnel first:
  ssh -L 54322:127.0.0.1:$DB_PORT <your-server-user>@<the-server>
then connect DBeaver or Jupyter to host 127.0.0.1, port 54322 (docs/DBEAVER.md).
EOF

# Send the variables on standard input (a password on a command line shows in the process list), then the SQL file.
{
  printf "\\\\set analyst_login '%s'\n" "$NAME"
  printf "\\\\set analyst_password '%s'\n" "$PASSWORD"
  printf "\\\\set analyst_action '%s'\n" "$ACTION"
  cat "$SQL"
} | docker exec -i "$DB_CONTAINER" psql -X -q -U supabase_admin -d postgres -v ON_ERROR_STOP=1 >/dev/null \
  || stop "the database refused (see the message above). Nothing was changed, and no password file was kept."

# Keep the old file of a reset next to the new one until a person has removed it.
if [ -e "$TARGET" ]; then mv "$TARGET" "$TARGET.previous"; fi
mv "$TMPFILE" "$TARGET"
trap - EXIT

# Check: the new login can connect (inside the container, the password read from standard input, not from the command line) and create, write and drop a
# table in public (and so also read). Only a warning if this fails: the login itself was made.
CHECK_SQL="create table public.zz_gfm_login_check(x int); insert into public.zz_gfm_login_check values (1); select count(*) from public.zz_gfm_login_check; drop table public.zz_gfm_login_check;"
if printf '%s\n' "$PASSWORD" | docker exec -i "$DB_CONTAINER" sh -c 'read -r PGPASSWORD; export PGPASSWORD; exec psql -X -q -At -h 127.0.0.1 -U "$1" -d postgres -v ON_ERROR_STOP=1 -c "$2"' sh "$NAME" "$CHECK_SQL" >/dev/null 2>&1; then
  say "Checked: '$NAME' can connect and create, write and drop a table in public."
else
  say "WARNING: the login was made, but the test connection from inside the container did not work (the password file is still right). Check by hand."
fi

say "Done: the login '$NAME' is ready ($ACTION)."
say "The password is in $TARGET (mode 600). It is not shown here. Hand it over privately, never by chat or Git."
[ ! -e "$TARGET.previous" ] || say "The old password file was kept as $TARGET.previous: delete it when you do not need it."
