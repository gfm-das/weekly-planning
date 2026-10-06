"""Unit checks for the Dashboards (DataEase) sign-in cookie and POST /api/dataease/session (no database, no network).

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_dataease_auth.py
pytest works too: python -m pytest portal-api/tests/test_dataease_auth.py
The gate in front of DataEase checks the same cookie (dataease/gate/gate.mjs); both test suites check the shared
example VECTOR below, so the two cannot drift apart.
"""
import base64
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# The mission's public domain is a setting (GFM_PUBLIC_DOMAIN); these checks use Frankfurt's.
os.environ.setdefault('GFM_PUBLIC_DOMAIN', 'example.org')
import dataease_auth  # noqa: E402

KEY = b'k' * 40
NOW = 1_790_000_000
USER = '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10'
# Shared with dataease/tests/gate.test.mjs: this identity signed with KEY gives exactly this cookie value.
VECTOR_IDENTITY = {'sub': USER, 'exp': NOW + 900}
VECTOR = ('eyJleHAiOjE3OTAwMDA5MDAsInN1YiI6IjZmMWMwYTUyLTNjMWQtNGQ3ZS05YTUzLTBkM2Y4ZjJjMWExMCJ9'
          '.kqW8zu3RZA_ONlKm09zZfSVPOil9hVF2CyFgBTnb8tU')


def person(app_role='MISSIONARY', leadership_role=None, additional_roles=()):
    """A context row as current_user_context gives it (the main role comes from these fields, see roles.py)."""
    return {'user_id': USER, 'app_role': app_role, 'leadership_role': leadership_role,
            'additional_roles': list(additional_roles), 'display_name': 'Elder Sample'}


def raises(exception, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except exception:
        return True
    raise AssertionError(f'{call.__name__} did not raise {exception.__name__}')


def test_only_managers_get_a_cookie():
    for context in (person('MISSIONARY', 'AP'), person('PRESIDENT'), person('DATA_ADMIN'),
                    person('MISSIONARY', 'DL', ['DATA_ADMIN']), person('MISSIONARY', None, ['DATA_ADMIN', 'OFFICE']),
                    person('OFFICE', None, ['DATA_ADMIN'])):
        assert dataease_auth.allowed(context), context
        assert dataease_auth.identity_for(context, now=NOW) == {'sub': USER, 'exp': NOW + 900}
    for context in (person(), person('MISSIONARY', 'DL'), person('MISSIONARY', 'ZL'), person('MISSIONARY', 'STL'),
                    person('OFFICE'), person('AP'),  # app_role AP without a current AP assignment is not an AP
                    person('MISSIONARY', 'ZL', ['OFFICE']), person('MISSIONARY', None, ['admin', 'AP'])):
        assert not dataease_auth.allowed(context), context
        raises(PermissionError, dataease_auth.identity_for, context, now=NOW)


def test_cookie_holds_only_the_user_id_and_the_end():
    identity = dataease_auth.identity_for(person('PRESIDENT'), now=NOW)
    assert set(identity) == {'sub', 'exp'}, 'no e-mail, name or role in the cookie'


def test_shared_vector_with_the_gate():
    value = dataease_auth.sign(VECTOR_IDENTITY, KEY)
    assert value == VECTOR, value
    assert dataease_auth.verify(VECTOR, KEY, now=NOW) == VECTOR_IDENTITY


def test_signed_cookie_round_trips_and_expires():
    value = dataease_auth.sign(dataease_auth.identity_for(person('PRESIDENT'), now=NOW), KEY)
    assert value.count('.') == 1 and value.isascii() and ';' not in value and ' ' not in value
    assert dataease_auth.verify(value, KEY, now=NOW)['sub'] == USER
    assert dataease_auth.verify(value, KEY, now=NOW + 899) is not None
    assert dataease_auth.verify(value, KEY, now=NOW + 900) is None
    assert dataease_auth.verify(value, KEY, now=NOW + 86400) is None


def test_tampered_foreign_and_malformed_cookies_are_rejected():
    value = dataease_auth.sign(VECTOR_IDENTITY, KEY)
    body, mac = value.split('.')
    longer = base64.urlsafe_b64encode(json.dumps(dict(VECTOR_IDENTITY, exp=NOW + 10 ** 6)).encode()).rstrip(b'=').decode()
    assert dataease_auth.verify(longer + '.' + mac, KEY, now=NOW) is None
    assert dataease_auth.verify(body + '.' + mac[:-1] + ('A' if mac[-1] != 'A' else 'B'), KEY, now=NOW) is None
    assert dataease_auth.verify(value, b'another-secret-of-sufficient-length!!', now=NOW) is None
    for bad in (None, '', '.', 'abc', 'a.b.c', 'ä.ö', 'x' * 5000, '!!!.???', 123, b'a.b'):
        assert dataease_auth.verify(bad, KEY, now=NOW) is None
    for payload in ([1, 2], 'text', dict(VECTOR_IDENTITY, exp='9999999999'), dict(VECTOR_IDENTITY, exp=True),
                    dict(VECTOR_IDENTITY, sub=''), dict(VECTOR_IDENTITY, sub=5), {'exp': NOW + 900}):
        signed_body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
        assert dataease_auth.verify(signed_body + '.' + dataease_auth._mac(KEY, signed_body), KEY, now=NOW) is None


def test_missing_short_or_example_secret_refuses_to_sign():
    raises(dataease_auth.NotConfigured, dataease_auth.signing_key, {})
    raises(dataease_auth.NotConfigured, dataease_auth.signing_key, {'DATAEASE_PROXY_SECRET': 'x' * 31})
    assert dataease_auth.signing_key({'DATAEASE_PROXY_SECRET': 'x' * 32}) == b'x' * 32
    example = Path(__file__).resolve().parents[1] / '.env.example'
    line = next(line for line in example.read_text(encoding='utf-8').splitlines()
                if line.startswith('DATAEASE_PROXY_SECRET='))
    placeholder = line.split('=', 1)[1]
    assert len(placeholder) >= dataease_auth.MIN_SECRET_LENGTH  # long enough, so only the marker check stops it
    raises(dataease_auth.NotConfigured, dataease_auth.signing_key, {'DATAEASE_PROXY_SECRET': placeholder})
    dataease_example = Path(__file__).resolve().parents[2] / 'dataease' / '.env.example'
    if dataease_example.exists():
        line = next(line for line in dataease_example.read_text(encoding='utf-8').splitlines()
                    if line.startswith('GFM_DATAEASE_PROXY_SECRET='))
        raises(dataease_auth.NotConfigured, dataease_auth.signing_key, {'DATAEASE_PROXY_SECRET': line.split('=', 1)[1]})


# ---- the route (Flask test client; the database and Supabase are replaced by stubs) ----

@contextmanager
def portal_app(secret='s' * 48, role='AP', additional=()):
    old = os.environ.get('DATAEASE_PROXY_SECRET')
    if secret is None:
        os.environ.pop('DATAEASE_PROXY_SECRET', None)
    else:
        os.environ['DATAEASE_PROXY_SECRET'] = secret
    os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
    os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unused')
    import app as portal

    class Answer:
        status_code = 200

        @staticmethod
        def json():
            return {'id': USER}

    @contextmanager
    def no_db():
        yield None

    saved = portal.requests.get, portal.db, portal.context_for
    portal.requests.get = lambda *a, **k: Answer()
    portal.db = no_db
    leader = role if role in ('DL', 'ZL', 'STL', 'AP') else None
    portal.context_for = lambda conn, user_id: dict(person(role, leader, additional), user_id=user_id)
    try:
        yield portal.app.test_client(use_cookies=False)
    finally:
        portal.requests.get, portal.db, portal.context_for = saved
        if old is None:
            os.environ.pop('DATAEASE_PROXY_SECRET', None)
        else:
            os.environ['DATAEASE_PROXY_SECRET'] = old


def bearer():
    payload = base64.urlsafe_b64encode(json.dumps({'email': 'someone@example.org'}).encode()).rstrip(b'=').decode()
    return {'Authorization': f'Bearer eyJhbGciOiJIUzI1NiJ9.{payload}.signature'}


def test_session_sets_a_strict_http_only_cookie_for_the_whole_host():
    with portal_app() as client:
        response = client.post('/api/dataease/session', headers=bearer())
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.get_json()['ok'] and response.get_json()['expires_at']
        assert response.headers['Cache-Control'] == 'no-store'
        set_cookie = response.headers['Set-Cookie']
        for flag in ('gfm_dataease=', 'HttpOnly', 'SameSite=Strict', 'Path=/'):
            assert flag in set_cookie, set_cookie
        # A browser-session cookie: it ends with the browser, and the signed exp limits it to 15 minutes.
        assert 'Max-Age' not in set_cookie and 'Expires' not in set_cookie, set_cookie
        assert 'Domain=' not in set_cookie, 'host-only: the same host name, any port'
        assert 'Secure' not in set_cookie, 'the LAN address is http'
        value = set_cookie.split(';')[0].split('=', 1)[1]
        assert dataease_auth.verify(value, b's' * 48) == {'sub': USER, 'exp': dataease_auth.verify(value, b's' * 48)['exp']}


def test_cookie_scope_public_address_only():
    public = {'domain': 'example.org', 'secure': True}
    for host in ('example.org', 'www.example.org', 'WWW.Example.ORG',
                 'example.org:443', 'example.org.'):
        assert dataease_auth.cookie_scope(host) == public, host
    for host in ('192.168.1.20:8070', '192.168.1.20', 'localhost:8070', '127.0.0.1', '', None, '[::1]:8070',
                 'dashboards.example.org', 'evil-example.org',
                 'example.org.evil.example', 'xexample.org', 'a.www.example.org'):
        assert dataease_auth.cookie_scope(host) == {'domain': None, 'secure': False}, host


def test_without_a_public_domain_no_host_counts_as_public():
    import importlib
    saved = os.environ.pop('GFM_PUBLIC_DOMAIN')
    try:
        importlib.reload(dataease_auth)
        for host in ('example.org', 'www.example.org', '', None):
            assert dataease_auth.cookie_scope(host) == {'domain': None, 'secure': False}, host
    finally:
        os.environ['GFM_PUBLIC_DOMAIN'] = saved
        importlib.reload(dataease_auth)


def test_session_on_the_public_address_sets_the_cookie_for_the_domain_over_https_only():
    for host in ('example.org', 'www.example.org'):
        with portal_app() as client:
            response = client.post('/api/dataease/session', headers=dict(bearer(), Host=host))
            assert response.status_code == 200, response.get_data(as_text=True)
            set_cookie = response.headers['Set-Cookie']
            for flag in ('gfm_dataease=', 'HttpOnly', 'SameSite=Strict', 'Path=/', 'Secure',
                         'Domain=example.org'):
                assert flag in set_cookie, set_cookie
            assert 'Max-Age' not in set_cookie and 'Expires' not in set_cookie, set_cookie
    with portal_app(role='DL') as client:
        response = client.post('/api/dataease/session', headers=dict(bearer(), Host='www.example.org'))
        assert response.status_code == 403
        cleared = response.headers['Set-Cookie']
        for flag in ('gfm_dataease=;', 'Max-Age=0', 'Path=/', 'Domain=example.org', 'Secure'):
            assert flag in cleared, cleared
    with portal_app() as client:  # the LAN address: exactly as before
        set_cookie = client.post('/api/dataease/session', headers=dict(bearer(), Host='192.168.1.20:8070')).headers['Set-Cookie']
        assert 'Domain=' not in set_cookie and 'Secure' not in set_cookie, set_cookie


def test_session_for_the_president_and_a_dl_who_is_also_the_data_analyst():
    with portal_app(role='PRESIDENT') as client:
        assert client.post('/api/dataease/session', headers=bearer()).status_code == 200
    with portal_app(role='DL', additional=['DATA_ADMIN']) as client:
        assert client.post('/api/dataease/session', headers=bearer()).status_code == 200


def test_session_is_refused_to_other_roles_without_sign_in_and_without_secret():
    for role, additional in (('DL', ()), ('ZL', ('OFFICE',)), ('STL', ()), ('MISSIONARY', ()), ('OFFICE', ())):
        with portal_app(role=role, additional=additional) as client:
            response = client.post('/api/dataease/session', headers=bearer())
            assert response.status_code == 403, role
            assert 'APs, the President and the Data Analysts' in response.get_json()['error']
            # The refusal clears a manager's cookie left in this browser (a shared computer).
            cleared = response.headers['Set-Cookie']
            assert cleared.startswith('gfm_dataease=;') and 'Max-Age=0' in cleared and 'Path=/' in cleared, cleared
    with portal_app() as client:
        assert client.post('/api/dataease/session').status_code == 401
        assert client.get('/api/dataease/session', headers=bearer()).status_code == 405
    for secret in (None, 'short'):
        with portal_app(secret=secret) as client:
            response = client.post('/api/dataease/session', headers=bearer())
            assert response.status_code == 503 and 'Set-Cookie' not in response.headers


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
        print('ok', test.__name__)
    print(f'{len(tests)} passed')
