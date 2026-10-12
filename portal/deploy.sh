#!/usr/bin/env bash
# portal/deploy.sh: puts the portal's pages live (the shell twin of portal/deploy.ps1, for Mac, Linux and Git Bash).
# What it does, in this order:
#   1. checks that the Docker network and volume the portal compose files need exist (else it stops before copying anything);
#   2. makes index.html from index.template.html, filling in the public Supabase "anon" key from supabase/.env;
#   3. writes site-config.js: the public web name (GFM_PUBLIC_DOMAIN in portal/.env, empty: none), the mission's time zone
#      (GFM_TIME_ZONE, default Europe/Berlin) and the mission's default language (read from the database; "en" when it
#      cannot be read);
#   4. puts the pages, scripts, styles, icons, the i18n and whiteboard folders in one staging folder and copies it into the
#      portal container in one go;
#   5. removes what the portal no longer has, makes sure the container runs with the current settings, checks nginx.conf
#      and reloads nginx.
# Run from anywhere:  bash portal/deploy.sh          Roll back: docs/README-start-here.md, "Roll back".
# For tests only (so a test can run next to a live system): GFM_PROJECT_PREFIX (added to the compose project name), GFM_NETWORK (the
# Docker network, gfm-network), GFM_OVERRIDE_DIR (a folder, relative to the repository, whose portal.yml is one more compose file),
# GFM_DB_CONTAINER.
set -eu
PORTAL=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$PORTAL/.." && pwd)
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1; STAGING_MIXED=$(cd "$ROOT" && pwd -W) ;; *) STAGING_MIXED=$ROOT ;; esac

die() { echo "Nothing was deployed: $*" >&2; exit 1; }
env_value() {  # env_value FILE NAME  (the last NAME=value line, without quotes)
  [ -f "$1" ] && grep -E "^$2=" "$1" | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//' || true
}

# The container's and volume's names are settings (portal/.env), as in portal-compose.yml; the defaults are the Frankfurt server's.
CONTAINER=${GFM_PORTAL_CONTAINER:-$(env_value "$PORTAL/.env" GFM_PORTAL_CONTAINER)}
CONTAINER=${CONTAINER:-portal-ydpgd5zwrjrvz5aa188sa60u}
VOLUME=${GFM_PORTAL_VOLUME:-$(env_value "$PORTAL/.env" GFM_PORTAL_VOLUME)}
VOLUME=${VOLUME:-ydpgd5zwrjrvz5aa188sa60u_portal-data}
DB_CONTAINER=${GFM_DB_CONTAINER:-gfm-beta-supabase-db-1}
HTML=/usr/share/nginx/html
STAGING="$ROOT/backups/.tmp-portal-deploy"
# What the portal no longer has (deleted in the container; a path that is back in portal/ is kept).
RETIRED="grafana-session.html i18n/i18n management.html"
NETWORK=${GFM_NETWORK:-gfm-network}
EXTRA=()
[ -n "${GFM_OVERRIDE_DIR:-}" ] && [ -f "$ROOT/$GFM_OVERRIDE_DIR/portal.yml" ] && EXTRA=(-f "$GFM_OVERRIDE_DIR/portal.yml")
compose() { (cd "$ROOT" && docker compose -p "${GFM_PROJECT_PREFIX:-}portal" -f portal/portal-compose.yml -f portal/local-override.yml ${EXTRA[@]+"${EXTRA[@]}"} "$@"); }

# 1. The network and volume the compose files call "external" must exist.
docker network inspect "$NETWORK" >/dev/null 2>&1 || die "Docker network $NETWORK is missing."
docker volume inspect "$VOLUME" >/dev/null 2>&1 || die "Docker volume $VOLUME is missing."
compose config >/dev/null 2>&1 || die "reading the portal compose files failed."

# 2. The public anon key (a signed web token: it always starts with eyJ).
ANON=$(env_value "$ROOT/supabase/.env" SERVICE_SUPABASEANON_KEY)
[ -n "$ANON" ] || ANON=$(env_value "$ROOT/supabase/.env" ANON_KEY)
[[ "$ANON" == eyJ* ]] || die "the public Supabase anon key is missing."

# 3. The public domain, and the mission's default language.
DOMAIN=${GFM_PUBLIC_DOMAIN:-$(env_value "$PORTAL/.env" GFM_PUBLIC_DOMAIN)}
DOMAIN=$(printf '%s' "$DOMAIN" | tr 'A-Z' 'a-z' | sed -e 's/^\.*//' -e 's/\.*$//')
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then die "GFM_PUBLIC_DOMAIN is not a domain name: $DOMAIN"; fi
LANGUAGE=$(docker exec "$DB_CONTAINER" psql -U postgres -d postgres -Atc "select default_language from public.missions order by id limit 1" 2>/dev/null | head -1 | tr -d '\r' || true)
[[ "$LANGUAGE" =~ ^[a-z]{2,3}$ ]] || LANGUAGE=en
# The mission's name for the pages (empty: the pages keep their built-in name). Quotes and backslashes are escaped for a JavaScript string.
MISSION_NAME=$(docker exec "$DB_CONTAINER" psql -U postgres -d postgres -Atc "select name from public.missions order by id limit 1" 2>/dev/null | head -1 | tr -d '\r' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' || true)
TIMEZONE=${GFM_TIME_ZONE:-$(env_value "$PORTAL/.env" GFM_TIME_ZONE)}
TIMEZONE=${TIMEZONE:-Europe/Berlin}
[[ "$TIMEZONE" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$ ]] || die "GFM_TIME_ZONE is not a time zone name: $TIMEZONE"

# 4. Staging, then one copy.
rm -rf "$STAGING"; mkdir -p "$STAGING"
trap 'rm -rf "$STAGING"' EXIT
sed "s|__ANON_KEY__|$ANON|g" "$PORTAL/index.template.html" > "$STAGING/index.html"
for f in "$PORTAL"/*.html "$PORTAL"/*.css "$PORTAL"/*.js "$PORTAL"/*.svg "$PORTAL"/*.webmanifest; do
  [ -f "$f" ] || continue
  [ "$(basename "$f")" = index.template.html ] && continue
  cp "$f" "$STAGING/"
done
for folder in i18n whiteboard; do [ -d "$PORTAL/$folder" ] && cp -R "$PORTAL/$folder" "$STAGING/"; done
printf '// Written by portal/deploy.sh from GFM_PUBLIC_DOMAIN, GFM_TIME_ZONE and the mission. Do not edit.\nwindow.GFM_SITE = { publicDomain: "%s", defaultLanguage: "%s", timeZone: "%s", missionName: "%s" };\n' "$DOMAIN" "$LANGUAGE" "$TIMEZONE" "$MISSION_NAME" > "$STAGING/site-config.js"
docker cp "$STAGING_MIXED/backups/.tmp-portal-deploy/." "$CONTAINER:$HTML" || die "copying the portal pages failed."

# 5. Retired paths, the container's settings, nginx.
for retired in $RETIRED; do
  [ -e "$PORTAL/$retired" ] && continue
  docker exec "$CONTAINER" rm -rf "$HTML/$retired" || die "removing the retired $retired failed (the new pages are already copied)."
done
compose up -d --no-deps portal >/dev/null 2>&1 || die "the portal container could not be started (the new pages are already copied)."
docker exec "$CONTAINER" nginx -t >/dev/null 2>&1 || { docker exec "$CONTAINER" nginx -t >&2; die "the nginx configuration is wrong."; }
docker exec "$CONTAINER" nginx -s reload >/dev/null 2>&1 || die "nginx could not be reloaded."
echo "Portal assets and API proxy deployed."
