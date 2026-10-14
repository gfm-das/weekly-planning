#!/usr/bin/env bash
# Checks portal/nginx.conf in a throw-away nginx container (nginx:alpine, no network access needed), with this
# checkout's portal/ as the web root:
#   - nginx accepts the file (nginx -t);
#   - every text answer comes compressed (gzip): pages, scripts, styles, catalogs, the libraries, the Whiteboard;
#   - the vendored libraries (echarts.min.js, Sortable.min.js) and the Whiteboard bundle's fingerprinted parts may be
#     kept for a year;
#   - pages and scripts are checked again on every visit (no-cache), and only the portal may frame them;
#   - a missing tab icon is a short "not found", not the portal page;
#   - the translation catalogs may be read from DA Management and Presentations;
#   - the Whiteboard may frame Presentations only; old Grafana addresses lead to Dashboards;
#   - of Supabase only the sign-in routes the pages use are passed on (the rest is refused).
# Run from the repository root (Git Bash on Windows works): bash portal/tests/nginx-check.sh
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
PORTAL="$REPO/portal"
if command -v cygpath >/dev/null 2>&1; then PORTAL=$(cygpath -m "$PORTAL"); fi
NAME=gfm-test-nginx-check-$$
PORT=${NGINX_CHECK_PORT:-18795}
BASE="http://127.0.0.1:$PORT"
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=$((failed + 1)); fi; }
header() { curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip' "$BASE$1" | tr -d '\r' | grep -i "^$2:" | head -1 | cut -d' ' -f2-; }
status() { curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE$1"; }

MSYS_NO_PATHCONV=1 docker run -d --rm --name "$NAME" --memory 64m -p "127.0.0.1:$PORT:80" \
  -v "$PORTAL:/usr/share/nginx/html:ro" -v "$PORTAL/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine >/dev/null || exit 1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
for _ in $(seq 1 40); do curl -s -o /dev/null "$BASE/home.html" && break; sleep 0.25; done

docker exec "$NAME" nginx -t >/dev/null 2>&1; check 'nginx accepts nginx.conf' $?

for file in 'echarts.min.js?v=6.0.0' 'Sortable.min.js?v=1.15.6'; do
  [ "$(header "/$file" Content-Encoding)" = gzip ]; check "$file comes compressed (gzip)" $?
  [ "$(header "/$file" Cache-Control)" = 'public, max-age=31536000, immutable' ]; check "$file may be kept for a year" $?
  [ "$(header "/$file" Vary)" = 'Accept-Encoding' ]; check "$file: caches keep the compressed and the plain copy apart" $?
done
[ "$(header /echarts.min.js X-Content-Type-Options)" = nosniff ]; check 'the libraries are only ever run as scripts (nosniff)' $?

[ "$(header /home.html Cache-Control)" = no-cache ]; check 'pages are checked again on every visit (no-cache)' $?
[ "$(header /glimpse.js Cache-Control)" = no-cache ]; check 'the portal scripts too' $?
[ "$(header /home.html Content-Security-Policy)" = "frame-ancestors 'self'" ]; check 'only the portal may show its pages in a frame' $?
[ "$(header /home.html Referrer-Policy)" = no-referrer ]; check 'no address is passed on to other sites (no-referrer)' $?
[ "$(header /service-worker.js Cache-Control)" = no-cache ]; check 'the reminders worker is checked on every visit' $?

for file in /home.html /portal-enhancements.js /portal.css /i18n/en.json /i18n/rtl.css /whiteboard/whiteboard.js; do
  [ "$(header "$file" Content-Encoding)" = gzip ]; check "$file comes compressed (gzip)" $?
done
plain=$(wc -c < "$REPO/portal/i18n/en.json")
packed=$(curl -s -H 'Accept-Encoding: gzip' "$BASE/i18n/en.json" | wc -c)
[ "$packed" -lt $((plain * 30 / 100)) ]; check "en.json travels at under 30% of its size ($packed of $plain bytes)" $?
[ "$(status /favicon.png)" = '404 ' ] && [ "$(curl -s "$BASE/favicon.png" | wc -c)" -lt 1024 ]; check 'a missing tab icon is a short "not found", not the portal page' $?

CHUNK=$(ls "$REPO/portal/whiteboard/vendor/chunks" | head -1)
[ "$(header "/whiteboard/vendor/chunks/$CHUNK" Cache-Control)" = 'public, max-age=31536000, immutable' ]; check "the Whiteboard bundle's fingerprinted parts may be kept for a year ($CHUNK)" $?
[ "$(header "/whiteboard/vendor/chunks/$CHUNK" Content-Encoding)" = gzip ]; check '... and come compressed' $?
[ "$(header /whiteboard/vendor/gfm-excalidraw.js Cache-Control)" = no-cache ]; check "the bundle's entry file (same name after a new build) is checked on every visit" $?
[ "$(status /whiteboard/vendor/chunks/no-such-part.js)" = '404 ' ]; check 'a missing part is "not found", not a page' $?

[ "$(header /i18n/en.json Access-Control-Allow-Origin)" = '*' ]; check 'DA Management and Presentations may read the catalogs' $?

header /whiteboard/whiteboard.js Content-Security-Policy | grep -q "frame-src 'self' http://\*:3030"; check 'the Whiteboard may frame Presentations (:3030) only' $?
curl -s -o /dev/null -D - -H 'Host: www.example.org' "$BASE/whiteboard/whiteboard.js" | tr -d '' | grep -i '^content-security-policy:' | grep -q 'https://presentations\.example\.org;'; check 'on a public name the Whiteboard may also frame presentations.<that domain>' $?
[ "$(status /whiteboard)" = "302 $BASE/whiteboard/" ]; check '/whiteboard leads to /whiteboard/' $?
[ "$(status /grafana/d/abc)" = "302 $BASE/#insights" ]; check 'an old Grafana address leads to Dashboards' $?

# Supabase on the public address (docs/handoff/round10/public-domain.md): only the sign-in routes the pages use are
# passed on (this test container has no Supabase, so only the refusals are checked here).
raw() { curl -s -o /dev/null --path-as-is -w '%{http_code}' "$@"; }
[ "$(raw -X POST "$BASE/auth/v1/signup")" = 403 ]; check 'sign-up is refused on the portal address' $?
[ "$(raw "$BASE/auth/v1/admin/users")" = 403 ]; check "Supabase's admin routes are refused" $?
[ "$(raw -X POST "$BASE/auth/v1/recover")" = 403 ] && [ "$(raw -X POST "$BASE/auth/v1/otp")" = 403 ]; check 'password and magic-link emails cannot be asked for here' $?
[ "$(raw "$BASE/auth/v1/user/../admin/users")" = 403 ] && [ "$(raw "$BASE/auth/v1/user/..%2Fadmin%2Fusers")" = 403 ]; check 'no way round with ../ (plain or encoded)' $?
[ "$(raw "$BASE/rest/v1/")" = 403 ] && [ "$(raw "$BASE/rest/v1/profiles?select=*")" = 403 ]; check 'no other table or the REST overview' $?
[ "$(raw "$BASE/rest/v1/current_user_context?select=id,email")" = 403 ] && [ "$(raw -X DELETE "$BASE/rest/v1/current_user_context?select=*")" = 403 ]; check 'current_user_context only read, and only as the shell asks (?select=*)' $?
[ "$(header /auth/v1/signup Cache-Control)" = no-store ]; check 'refusals are never kept' $?
[ "$(status /office-only.html)" = '200 ' ]; check 'the "office only" page is there' $?

if [ "$failed" = 0 ]; then echo "nginx: all checks passed"; else echo "nginx: $failed checks failed"; exit 1; fi
