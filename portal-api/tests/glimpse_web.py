"""TEST ONLY: the portal (files from portal/) and the real portal-api on a THROWAWAY database copy, on one port, for the
browser check of the managers' Overview with the mission glimpse (tests/edge_glimpse.ps1, round 6).

- /api/* is the real portal-api (this worktree's app.py) on the copy. The bearer token's `sub` is trusted without
  asking Supabase (as fixture_server.py does), so it refuses to start unless DATABASE_URL names a *test* database and
  GLIMPSE_TEST_THROWAWAY=yes.
- Everything else is served from portal/ (mounted at /portal); / and /index.html are index.template.html with a
  dummy public key. Supabase (:18000) is never contacted: the browser script answers it inside the page.
- GET /stub/log lists the /api/ and /grafana requests seen (method and path only); POST /stub/reset empties it.

  docker network create gfm-test-portalx-net
  docker run -d --name gfm-test-portalx-web --memory 512m --network gfm-test-portalx-net -p 127.0.0.1:18078:8080 \
      -e GLIMPSE_TEST_THROWAWAY=yes -e DATABASE_URL=postgresql://postgres:...@gfm-test-r2-db:5432/gfm_test_x \
      -v <repo>/portal-api:/app:ro -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/glimpse_web.py
  docker network connect gfm-test-r2-net gfm-test-portalx-web
"""
import base64
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('GLIMPSE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to start: fixture sign-in needs a throwaway *test* database.')
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'test-only')

import app as api  # noqa: E402
from flask import Response, abort, jsonify, request, send_from_directory  # noqa: E402

PORTAL = Path('/portal')
log = []


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
app = api.app


# The portal's own sign-in check applies to /api/ only here; the page files and /stub/ need none.
def api_only_sign_in(original=api.authenticate):
    if request.path.startswith('/api/'):
        return original()


app.before_request_funcs[None] = [api_only_sign_in if f is api.authenticate else f for f in app.before_request_funcs[None]]


@app.before_request
def remember():
    if request.path.startswith('/api/') or 'grafana' in request.path:
        log.append({'method': request.method, 'path': request.path, 'query': request.query_string.decode()})


@app.get('/stub/log')
def stub_log():
    return jsonify(log=log)


@app.post('/stub/reset')
def stub_reset():
    log.clear()
    return jsonify(ok=True)


@app.get('/')
@app.get('/index.html')
def index():
    html = (PORTAL / 'index.template.html').read_text(encoding='utf-8').replace('__ANON_KEY__', 'eyJ.stub.anon')
    return Response(html, mimetype='text/html', headers={'Cache-Control': 'no-cache'})


@app.get('/<path:name>')
def files(name):
    if name.startswith('api/') or name == 'index.template.html':
        abort(404)
    return send_from_directory(PORTAL, name, max_age=0)


app.run(host='0.0.0.0', port=8080, threaded=True)
