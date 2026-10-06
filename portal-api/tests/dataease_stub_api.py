"""TEST ONLY: tests/portal_stub_api.py plus the real Dashboards sign-in route, for the browser check of the portal's
Dashboards button with DataEase (tests/edge_dataease_portal.ps1).

- POST /api/dataease/session is the real route of dataease_auth.py (managers only, the signed cookie gfm_dataease).
  The portal sign-in is made up: the bearer token's "sub" says who is asking, u-ap (an AP) or u-dl (a DL), and
  g.context is set from that as current_user_context would. DATAEASE_PROXY_SECRET must be the test DataEase's
  GFM_DATAEASE_PROXY_SECRET (pass it with --env-file, never on a command line).
- portal-enhancements.js is served with DataEase's address changed from port 8088 to DATAEASE_PORT (the test
  DataEase, default 18100), so the portal on 127.0.0.1:18074 opens the throw-away DataEase on 127.0.0.1:18100.
- GET /stub/log also lists every /api/dataease/ request (who asked, the answer's status).
Made-up data only; no database.

  docker run --rm -d --name gfm-test-dataease-portal --memory 256m -p 127.0.0.1:18074:8080 --env-file <env> \
      -v <repo>/portal-api:/app:ro -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/dataease_stub_api.py
"""
import base64
import json
import os
import sys
from pathlib import Path

from flask import Response, g, request

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal_stub_api import PORTAL, app, log  # noqa: E402
os.environ.setdefault('GFM_PUBLIC_DOMAIN', 'example.org')  # the edge tests use Frankfurt's name
import dataease_auth  # noqa: E402

if not os.environ.get('DATAEASE_PROXY_SECRET') and os.environ.get('GFM_DATAEASE_PROXY_SECRET'):
    os.environ['DATAEASE_PROXY_SECRET'] = os.environ['GFM_DATAEASE_PROXY_SECRET']
DATAEASE_PORT = os.environ.get('DATAEASE_PORT', '18100')

PEOPLE = {
    'u-ap': {'user_id': 'u-ap', 'app_role': 'AP', 'leadership_role': 'AP', 'additional_roles': [], 'display_name': 'Elder Sample'},
    'u-dl': {'user_id': 'u-dl', 'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'additional_roles': [], 'display_name': 'Elder Leader'},
}


@app.before_request
def made_up_sign_in():
    if not request.path.startswith('/api/dataease/'):
        return None
    sub = ''
    try:
        token = request.headers.get('Authorization', '')[7:]
        sub = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))['sub']
    except Exception:  # noqa: BLE001 - a made-up token
        pass
    if sub not in PEOPLE:
        return Response(json.dumps({'error': 'Sign in through the mission portal.'}), status=401, mimetype='application/json')
    g.context = PEOPLE[sub]
    return None


@app.after_request
def log_dataease(response):
    if request.path.startswith('/api/dataease/'):
        log.append({'method': request.method, 'path': request.path, 'as': getattr(g, 'context', {}).get('user_id'),
                    'status': response.status_code, 'cookie': 'gfm_dataease=' in response.headers.get('Set-Cookie', '')})
    return response


app.register_blueprint(dataease_auth.dataease_bp)


def shell():
    source = (PORTAL / 'portal-enhancements.js').read_text(encoding='utf-8')
    wired = "PORTAL_HOST + ':8088'"
    assert source.count(wired) == 1, 'portal-enhancements.js no longer sets the DataEase address as expected'
    return Response(source.replace(wired, f"PORTAL_HOST + ':{DATAEASE_PORT}'"), mimetype='application/javascript')


original_files = app.view_functions['files']


def files(name):
    if name == 'portal-enhancements.js':
        return shell()
    return original_files(name)


app.view_functions['files'] = files


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
