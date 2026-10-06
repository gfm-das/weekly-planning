"""Round 8: portal-api answers only the portal's own pages (origin_guard.py), never a presentation page.

Presentations run on their own address since round 8 (port 8089, slidev/manager/deck-origin.mjs). Two ports of one
computer are "same-site" for the browser, so a deck page can send requests to the portal's API on 8070. They carry no
sign-in (portal-api only takes a Bearer token), and portal-api sends no CORS headers, so the browser never lets such a
page read an answer or add the token; the guard refuses them anyway, even with a valid token.

Run in the portal-api image (no pytest needed, no database, no network):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_origin_guard.py
pytest works too: python -m pytest portal-api/tests/test_origin_guard.py
"""
import base64
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import origin_guard  # noqa: E402

USER = '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10'


def test_the_portal_s_own_pages_pass():
    for headers in ({}, {'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Site': 'none'},
                    {'Sec-Fetch-Site': 'same-origin', 'Origin': 'http://192.168.1.20:8070'}):
        assert origin_guard.refusal('/api/overview', headers) is None, headers
    # The health check and the server's own routes are not the guard's business.
    assert origin_guard.refusal('/api/health', {'Sec-Fetch-Site': 'same-site'}) is None
    assert origin_guard.refusal('/internal/presentations/check', {'Sec-Fetch-Site': 'same-site'}) is None


def test_other_pages_and_presentation_pages_are_refused():
    refused = origin_guard.REFUSED
    for headers in ({'Sec-Fetch-Site': 'same-site'}, {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'Same-Site'},
                    {'Origin': 'http://192.168.1.20:8089'}, {'Origin': 'http://localhost:8089'}, {'Origin': 'null'},
                    {'Origin': 'http://[bad'}):
        assert origin_guard.refusal('/api/dataease/session', headers) == refused, headers
    # Another deck port from the environment (PRESENTATIONS_DECK_PORT).
    assert origin_guard.refusal('/api/overview', {'Origin': 'http://localhost:9999'}, 9999) == refused
    assert origin_guard.deck_port({'PRESENTATIONS_DECK_PORT': '9999'}) == 9999
    assert origin_guard.deck_port({}) == 8089
    assert origin_guard.deck_port({'PRESENTATIONS_DECK_PORT': 'x'}) == 8089


# ---- the real app (Flask test client; Supabase and the database are replaced by stubs, as in test_dataease_auth) ----

@contextmanager
def portal_app():
    os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
    os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unused')
    old = os.environ.get('DATAEASE_PROXY_SECRET')
    os.environ['DATAEASE_PROXY_SECRET'] = 's' * 48
    import app as portal

    class Answer:
        status_code = 200

        @staticmethod
        def json():
            return {'id': USER}

    @contextmanager
    def no_db():
        yield None

    calls = []
    saved = portal.requests.get, portal.db, portal.context_for

    def signed_in(*args, **kwargs):
        calls.append(args)
        return Answer()

    portal.requests.get = signed_in
    portal.db = no_db
    portal.context_for = lambda conn, user_id: {'user_id': user_id, 'app_role': 'AP', 'leadership_role': 'AP',
                                                'additional_roles': [], 'display_name': 'Elder Sample'}
    try:
        yield portal.app.test_client(use_cookies=False), calls
    finally:
        portal.requests.get, portal.db, portal.context_for = saved
        if old is None:
            os.environ.pop('DATAEASE_PROXY_SECRET', None)
        else:
            os.environ['DATAEASE_PROXY_SECRET'] = old


def bearer():
    payload = base64.urlsafe_b64encode(json.dumps({'email': 'someone@example.org'}).encode()).rstrip(b'=').decode()
    return {'Authorization': f'Bearer eyJhbGciOiJIUzI1NiJ9.{payload}.signature'}


def test_a_presentation_page_is_refused_even_with_a_valid_token():
    with portal_app() as (client, calls):
        ok = client.post('/api/dataease/session', headers={**bearer(), 'Sec-Fetch-Site': 'same-origin'})
        assert ok.status_code == 200, ok.get_data(as_text=True)
        for extra in ({'Sec-Fetch-Site': 'same-site'}, {'Origin': 'http://192.168.1.20:8089'}, {'Origin': 'null'}):
            before = len(calls)
            refused = client.post('/api/dataease/session', headers={**bearer(), **extra})
            assert refused.status_code == 403, extra
            assert refused.get_json()['error'] == origin_guard.REFUSED
            assert 'Set-Cookie' not in refused.headers, 'no Dashboards sign-in for a deck page'
            assert len(calls) == before, 'refused before the token is even checked'


def test_no_cors_answer_ever_lets_another_address_in():
    with portal_app() as (client, _):
        for method, path in (('OPTIONS', '/api/overview'), ('OPTIONS', '/api/dataease/session'), ('GET', '/api/overview')):
            response = client.open(path, method=method, headers={'Origin': 'http://192.168.1.20:8089', 'Access-Control-Request-Method': 'POST',
                                                                  'Access-Control-Request-Headers': 'authorization'})
            assert response.status_code in (401, 403), (method, path, response.status_code)
            assert 'Access-Control-Allow-Origin' not in response.headers, (method, path)
            assert 'Access-Control-Allow-Credentials' not in response.headers, (method, path)


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
        print('ok', test.__name__)
    print(f'{len(tests)} passed')
