#!/bin/bash
# TEST ONLY: a throw-away copy of the Whiteboard chain for portal-api/tests/edge_whiteboard.ps1 (headless Edge):
#   browser -> portal stand-in (nginx, this checkout's portal/ and a test shell page) -> portal-api (this checkout)
#           -> a THROWAWAY database copy (migration 031 applied)
#   browser -> Presentation Manager (this checkout's slidev/manager; node_modules copied from the live Slidev volume)
#           -> the same portal-api (chart numbers, manager check)
#   both sign in through slidev/tests/dashboard-deck/supabase_stub.py (ids only; stands in for Supabase Auth).
# Nothing live is changed: the live Slidev volume is only read (mounted read-only, once, to copy its node_modules into
# the test volume gfm-test-whiteboard2-nm). Every container is named gfm-test-whiteboard2-*, has a memory limit and is
# removed by "whiteboard_env.sh down" ("down all" also removes the node_modules volume). Run from Git Bash:
#   DB=gfm_test_whiteboard2_2 bash portal-api/tests/whiteboard_env.sh up     (needs /path/to\gfm-worktrees\.testdb.env)
#   bash portal-api/tests/whiteboard_env.sh down all
# The portal stand-in answers on http://127.0.0.1:18470, the manager on http://127.0.0.1:18471.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd -W 2>/dev/null || pwd)
NET=gfm-test-whiteboard2-net
PORTAL_PORT=${PORTAL_PORT:-18470}
MANAGER_PORT=${MANAGER_PORT:-18471}
export MSYS_NO_PATHCONV=1

down() {
  docker rm -f gfm-test-whiteboard2-web gfm-test-whiteboard2-mgr gfm-test-whiteboard2-api gfm-test-whiteboard2-auth >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  if [ "${1:-}" = all ]; then docker volume rm gfm-test-whiteboard2-nm >/dev/null 2>&1 || true; fi
  echo "whiteboard test chain removed"
}

if [ "${1:-}" = down ]; then down "${2:-}"; exit 0; fi
: "${DB:?set DB to the throw-away database copy, e.g. gfm_test_whiteboard2_1}"
case "$DB" in *test*) ;; *) echo "Refusing: $DB is not a test database"; exit 1;; esac
set -a; . /c/GFM/gfm-worktrees/.testdb.env; set +a
URL="postgresql://postgres:${TEST_PGPASSWORD}@gfm-test-r2-db:5432/${DB}"
down >/dev/null
docker network create "$NET" >/dev/null
# The Presentation Manager's packages: a copy of the live Slidev volume's node_modules (read-only look), made once.
if ! docker volume inspect gfm-test-whiteboard2-nm >/dev/null 2>&1; then
  docker volume create gfm-test-whiteboard2-nm >/dev/null
  docker run --rm --memory 256m -v j5iyrpjbsssqlilqhw9axugx_slidev-data:/live:ro -v gfm-test-whiteboard2-nm:/nm node:24-alpine sh -c 'cp -a /live/node_modules/. /nm/'
fi

docker run -d --name gfm-test-whiteboard2-auth --network gfm-test-r2-net --memory 256m -e DASHDECK_TEST_THROWAWAY=yes \
  -e DATABASE_URL="$URL" -v "$REPO/slidev/tests/dashboard-deck:/stub:ro" gfm-portal-portal-api python /stub/supabase_stub.py >/dev/null

docker run -d --name gfm-test-whiteboard2-api --network gfm-test-r2-net --memory 384m \
  -e DATABASE_URL="$URL" -e SUPABASE_URL=http://gfm-test-whiteboard2-auth:8000 -e SUPABASE_SERVICE_ROLE_KEY=test-only \
  -e PORTAL_SERVICE_KEY=whiteboard-test-service-key -e VAPID_PUBLIC_KEY=test-only \
  -v "$REPO/portal-api:/app:ro" gfm-portal-portal-api \
  gunicorn --bind 0.0.0.0:8091 --workers 2 --threads 4 --timeout 40 app:app >/dev/null
docker network connect "$NET" gfm-test-whiteboard2-api

docker run -d --name gfm-test-whiteboard2-mgr --network "$NET" --memory 768m -p "127.0.0.1:${MANAGER_PORT}:3040" \
  -e SUPABASE_URL=http://gfm-test-whiteboard2-auth:8000 -e SUPABASE_SERVICE_ROLE_KEY=test-only \
  -e PRESENTATION_ACL_API_URL=http://gfm-test-whiteboard2-api:8091 -e PORTAL_SERVICE_KEY=whiteboard-test-service-key \
  -e PRESENTATIONS_PORTAL_ORIGINS="http://127.0.0.1:${PORTAL_PORT}" -e PRESENTATION_MANAGER_PORT=3040 \
  -e SLIDEV_PRESTART=0 -e SLIDEV_ADDON_REBUILD=0 -w /slidev \
  -v gfm-test-whiteboard2-nm:/slidev/node_modules:ro -v "$REPO/slidev/manager:/slidev/manager:ro" \
  -v "$REPO/slidev/package.json:/slidev/package.json:ro" --tmpfs /slidev/decks node:24-alpine node /slidev/manager/server.mjs >/dev/null
docker network connect gfm-test-r2-net gfm-test-whiteboard2-mgr

# The portal stand-in: portal/ as deployed (the whiteboard location of portal/nginx.conf, with the test manager's port
# instead of 3030), /api/ to the test portal-api, and the test shell page (whiteboard_shell.html) at /test-shell.html.
CONF=$(mktemp)
{
  echo 'server {'
  echo ' listen 80; root /usr/share/nginx/html; index index.html; client_max_body_size 16m; resolver 127.0.0.11 valid=30s;'
  echo ' location /api/ { set $b http://gfm-test-whiteboard2-api:8091; proxy_pass $b$request_uri; proxy_read_timeout 40s; add_header Cache-Control "no-store" always; }'
  echo ' location = /test-shell.html { alias /tests/whiteboard_shell.html; default_type text/html; add_header Cache-Control "no-store"; }'
  sed -n '/^ location = \/whiteboard {/,/^ location = \/service-worker.js/p' "$REPO/portal/nginx.conf" | sed '$d' | tr -d '\r' | sed "s/:3030/:${MANAGER_PORT}/g"
  echo ' location / { try_files $uri $uri/ /index.html; add_header Cache-Control "no-cache" always; }'
  echo '}'
} > "$CONF"
docker run -d --name gfm-test-whiteboard2-web --network "$NET" --memory 128m -p "127.0.0.1:${PORTAL_PORT}:80" \
  -v "$REPO/portal:/usr/share/nginx/html:ro" -v "$REPO/portal-api/tests:/tests:ro" nginx:alpine >/dev/null
docker cp "$(cygpath -w "$CONF" 2>/dev/null || echo "$CONF")" gfm-test-whiteboard2-web:/etc/nginx/conf.d/default.conf >/dev/null
rm -f "$CONF"
docker exec gfm-test-whiteboard2-web nginx -s reload >/dev/null 2>&1 || true

for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${MANAGER_PORT}/health" >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:${PORTAL_PORT}/whiteboard/" >/dev/null 2>&1; then
    echo "whiteboard test chain up: portal http://127.0.0.1:${PORTAL_PORT}  manager http://127.0.0.1:${MANAGER_PORT}"
    exit 0
  fi
  sleep 1
done
echo "the chain did not come up"; docker logs --tail 20 gfm-test-whiteboard2-mgr; docker logs --tail 20 gfm-test-whiteboard2-api; exit 1
