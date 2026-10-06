"""TEST ONLY: a stand-in for Supabase Auth and PostgREST, for the manager chain check of the Mission Dashboard deck.

The presentation manager signs people in with GET /auth/v1/user (the bearer token) and GET
/rest/v1/current_user_context?user_id=eq.<id>. This answers both from a THROWAWAY database copy, with ids only:
- a token is accepted when it is a JWT-shaped string whose payload has a future "exp" and a "sub" that is an active
  account in the copy (the signature is not checked; nothing here is reachable from outside the test network);
- the context row holds only user_id, user_active and mission_id (all the manager uses; portal-api reads the full
  context from the copy itself);
- GET /stub/users gives the ids of one active AP, DL and ZL, for the check script (ids only, never names).
Refuses unless DATABASE_URL names a database containing "test" and DASHDECK_TEST_THROWAWAY=yes.

  docker run --rm -d --name gfm-test-dash-auth --network gfm-test-r2-net --memory 256m -e DASHDECK_TEST_THROWAWAY=yes \
      -e DATABASE_URL=... -v <repo>/slidev/tests/dashboard-deck:/stub:ro gfm-portal-portal-api python /stub/supabase_stub.py
"""
import base64
import json
import os
import sys
import time
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request

dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('DASHDECK_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this stand-in needs a throwaway *test* database.')

app = Flask(__name__)


def rows(query, args=()):
    with psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor, connect_timeout=8) as conn:
        with conn.cursor() as cur:
            cur.execute(query, args)
            return cur.fetchall()


def token_user():
    auth = request.headers.get('Authorization', '')
    try:
        payload = auth.split(' ', 1)[1].split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except Exception:
        return None
    if not isinstance(claims, dict) or float(claims.get('exp', 0)) <= time.time():
        return None
    found = rows('SELECT user_id FROM public.current_user_context WHERE user_active AND user_id::text = %s LIMIT 1',
                 (str(claims.get('sub', '')),))
    return str(found[0]['user_id']) if found else None


@app.get('/auth/v1/user')
def auth_user():
    uid = token_user()
    return (jsonify(id=uid), 200) if uid else (jsonify(msg='invalid token'), 401)


@app.get('/rest/v1/current_user_context')
def user_context():
    wanted = request.args.get('user_id', '')
    if not wanted.startswith('eq.'):
        return jsonify([])
    found = rows('''SELECT user_id::text AS user_id, user_active, mission_id FROM public.current_user_context
                    WHERE user_id::text = %s ORDER BY mission_id NULLS LAST LIMIT 1''', (wanted[3:],))
    return jsonify([dict(r) for r in found])


@app.get('/stub/users')
def users():
    out = {}
    for role in ('AP', 'DL', 'ZL'):
        found = rows('''SELECT user_id::text AS user_id FROM public.current_user_context
                        WHERE user_active AND leadership_role = %s ORDER BY user_id LIMIT 1''', (role,))
        out[role.lower()] = found[0]['user_id'] if found else None
    return jsonify(out)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True)
