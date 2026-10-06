"""The portal's Dashboards sign-in for DataEase (the dataease/ compose project, port 8088).

What it is: one route, POST /api/dataease/session, and the helpers that sign and check its cookie.
Who uses it: the portal shell (portal/portal-enhancements.js) when a manager opens Dashboards; the gate in front of
DataEase (dataease/gate/gate.mjs) checks the same cookie.
How it fits: DataEase Community Edition has a single account and no single sign-on, so people never sign in to
DataEase themselves. POST /api/dataease/session (a signed-in AP, President or Data Analyst) sets the cookie
gfm_dataease. Cookies belong to the host name, not the port, so the browser also sends it to DataEase on :8088 of the
same address; there the gate container checks it on every request and adds DataEase's own sign-in. Everyone else
gets "Please open Dashboards from the mission portal".

Cookie value: base64url(JSON {"exp", "sub"}) + "." + base64url(HMAC-SHA256 of that text), keyed with
DATAEASE_PROXY_SECRET (dataease/.env holds the same value as GFM_DATAEASE_PROXY_SECRET). The signed end time
inside makes it last 15 minutes; the portal renews it while Dashboards is open. No database call is needed to check
it. The cookie itself has no Max-Age, so it also ends with the browser session, and a refusal (403) clears it: on a
shared computer a manager's leftover cookie does not stay with the next person (the portal also clears it when
someone who is not a manager signs in, and whenever the sign-in page is shown).

The public address (https://example.org and www., a Cloudflare tunnel to the portal): there
DataEase has its own name, https://dashboards.example.org (a tunnel route to 8088). A host-only
cookie would not reach it, so on the public address the cookie is set for the domain (Domain=example.org)
and only over https (Secure). dashboards. is the same site as the portal, so SameSite=Strict still lets the portal's
frame and its "Full screen" tab send it. On every other address (localhost, the LAN) the cookie stays as it was.
(docs/handoff/round10/public-dashboards.md)
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, g, jsonify, request

import roles

COOKIE_NAME = 'gfm_dataease'
COOKIE_PATH = '/'
LIFETIME = 15 * 60
MIN_SECRET_LENGTH = 32
REFUSED = 'Dashboards are available to the APs, the President and the Data Analysts.'
# The portal's public address and its www. name (portal/index.template.html PORTAL_PUBLIC_SITE: the same rule).
# GFM_PUBLIC_DOMAIN in portal-api/.env names it (for example example.org); empty means the mission has no public address
# and the cookie stays on the host it was set for.
PUBLIC_DOMAIN = os.environ.get('GFM_PUBLIC_DOMAIN', '').strip().strip('.').lower()
_PUBLIC_HOST = (re.compile(r'^(www\.)?' + re.escape(PUBLIC_DOMAIN) + r'\.?$', re.IGNORECASE) if PUBLIC_DOMAIN
                else re.compile(r'(?!)'))


class NotConfigured(RuntimeError):
    """DATAEASE_PROXY_SECRET is missing, too short or still the value from dataease/.env.example."""


def signing_key(environ=None):
    """The secret that signs the cookie, as bytes. NotConfigured when it is missing, short or the example value."""
    value = (os.environ if environ is None else environ).get('DATAEASE_PROXY_SECRET', '')
    # The example value is public (it is in git): anyone could sign a cookie with it.
    if len(value) < MIN_SECRET_LENGTH or 'REPLACE' in value.upper():
        raise NotConfigured('DATAEASE_PROXY_SECRET must be set to at least 32 generated characters.')
    return value.encode('utf-8')


def allowed(context):
    """APs, the President and Data Analysts (also as an additional role): the portal's managers."""
    return roles.is_manager(context)


def identity_for(context, now=None):
    """What the cookie says: whose sign-in it is and until when. PermissionError for anyone but a manager."""
    if not allowed(context):
        raise PermissionError(REFUSED)
    now = int(time.time() if now is None else now)
    return {'sub': str(context['user_id']), 'exp': now + LIFETIME}


def _b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64decode(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _mac(key, body):
    return _b64encode(hmac.new(key, body.encode('ascii'), hashlib.sha256).digest())


def sign(identity, key):
    body = _b64encode(json.dumps(identity, separators=(',', ':'), sort_keys=True).encode('utf-8'))
    return body + '.' + _mac(key, body)


def verify(value, key, now=None):
    """The identity in a cookie value, or None. The gate (dataease/gate/gate.mjs) checks exactly the same."""
    if not isinstance(value, str) or not value or len(value) > 4096 or value.count('.') != 1:
        return None
    body, mac = value.split('.')
    try:
        body.encode('ascii')
        if not hmac.compare_digest(mac.encode('ascii'), _mac(key, body).encode('ascii')):
            return None
        identity = json.loads(_b64decode(body))
    except (UnicodeError, ValueError):
        return None
    now = int(time.time() if now is None else now)
    if (not isinstance(identity, dict) or not isinstance(identity.get('exp'), int)
            or isinstance(identity.get('exp'), bool) or identity['exp'] <= now
            or not isinstance(identity.get('sub'), str) or not identity['sub']):
        return None
    return identity


def cookie_scope(host):
    """Where the cookie goes: on the public address the whole domain over https only (so that
    dashboards.<the public domain> gets it); on any other address (localhost, the LAN) this host only,
    as before. host is the request's Host header (portal/nginx.conf passes it on), with or without a port."""
    name = re.sub(r':\d+$', '', str(host or '').strip())
    if _PUBLIC_HOST.match(name):
        return {'domain': PUBLIC_DOMAIN, 'secure': True}
    return {'domain': None, 'secure': False}


# ---- the route (registered in app.py; app.authenticate has set g.context for a signed-in portal user) ------------

dataease_bp = Blueprint('dataease', __name__)


@dataease_bp.post('/api/dataease/session')
def dataease_session():
    """Signs a manager in to Dashboards (DataEase) for 15 minutes; the portal calls it again to renew.

    The portal's sign-out clears the cookie through DataEase's own address (/gfm-signout on :8088, on the public
    address dashboards.example.org/gfm-signout), so no unauthenticated route is needed here."""
    scope = cookie_scope(request.host)
    if not allowed(g.context):
        # Also ends a manager's Dashboards sign-in left in this browser (a shared computer).
        refused = jsonify(error=REFUSED)
        refused.status_code = 403
        refused.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, samesite='Strict', **scope)
        refused.headers['Cache-Control'] = 'no-store'
        return refused
    try:
        key = signing_key()
    except NotConfigured:
        current_app.logger.error('DATAEASE_PROXY_SECRET is missing, too short or the example value; Dashboards sign-in is off.')
        abort(503, 'Dashboards are not set up yet. Please tell the Data Analysts.')
    identity = identity_for(g.context)
    response = jsonify(ok=True, expires_at=datetime.fromtimestamp(identity['exp'], timezone.utc).isoformat())
    # A browser-session cookie (no Max-Age): the signed end time inside limits it to 15 minutes.
    response.set_cookie(COOKIE_NAME, sign(identity, key), path=COOKIE_PATH, httponly=True, samesite='Strict', **scope)
    response.headers['Cache-Control'] = 'no-store'
    return response
