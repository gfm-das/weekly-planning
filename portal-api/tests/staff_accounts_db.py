"""Staff accounts (migration 027) against a THROWAWAY database copy with 021 and 027 applied.

Refuses unless DATABASE_URL names a database containing "test" and STAFF_TEST_THROWAWAY=yes. Creates a President,
an Office and a Data Analyst account with no missionary link (home mission 2), plus a turned-off President and a
President of a second, temporary mission, then checks the portal and the database helpers as each of them. Identity
lookups are replaced in-process (as in callins_db.py); database roles, RLS and the Call-ins RPCs are the real ones.
Everything it creates is removed at the end.

Run inside a temporary portal-api container:
  python tests/staff_accounts_db.py
"""
import base64
import json
import os
import secrets
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('STAFF_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')
os.environ['PORTAL_SERVICE_KEY'] = service_key = secrets.token_urlsafe(24)

import app as api  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.fixture'


def call(user, path, method='GET', body=None):
    response = client.open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def helper(user, expression, args=()):
    """A database helper as the signed-in user would call it (authenticated role, row-level security on)."""
    with api.db() as conn:
        api.rows(conn, "SELECT set_config('request.jwt.claims',%s,true)", (json.dumps({'sub': str(user), 'role': 'authenticated'}),))
        api.rows(conn, 'SET LOCAL ROLE authenticated')
        return api.rows(conn, f'SELECT {expression} AS ok', args)[0]['ok']


other_mission = sql("INSERT INTO public.missions(name) VALUES ('Staff test mission') RETURNING id")[0]['id']
people = {}


def staff(key, role, mission=2, active=True):
    user = str(uuid.uuid4())
    sql("""INSERT INTO auth.users(id,instance_id,aud,role,email)
           VALUES(%s,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s)""",
        (user, f'staff-db-{key}@example.invalid'))
    sql("""INSERT INTO public.user_profiles(id,missionary_id,app_role,active,display_name,home_mission_id)
           VALUES(%s,NULL,%s,%s,%s,%s)""", (user, role, active, f'Staff {key}', mission))
    people[key] = user
    return user


try:
    president, office, analyst = staff('president', 'PRESIDENT'), staff('office', 'OFFICE'), staff('analyst', 'DATA_ADMIN')
    turned_off, elsewhere = staff('off', 'PRESIDENT', active=False), staff('elsewhere', 'PRESIDENT', other_mission)
    area, zone = sql('''SELECT a.id area,z.id zone FROM public.areas a JOIN public.districts d ON d.id=a.district_id
        JOIN public.zones z ON z.id=d.zone_id WHERE z.mission_id=2 AND a.active ORDER BY a.id LIMIT 1''')[0].values()

    # The check constraint: a home mission without a missionary only for President, Office or Data Analyst.
    try:
        sql("UPDATE public.user_profiles SET app_role='DL' WHERE id=%s", (office,))
        check('constraint refuses a DL staff account', False)
    except Exception as error:
        check('constraint refuses a DL staff account', 'user_profiles_home_mission_staff_check' in str(error), error)

    status, data = call(president, '/api/options')
    check('President signs in (options)', status == 200 and data.get('role') == 'PRESIDENT', (status, data))
    status, data = call(president, '/api/overview')
    check('President opens Home without an area', status == 200, (status, data))
    status, data = call(president, '/api/dashboard?weeks=1')
    check('President gets the glimpse numbers (Dashboards)', status == 200 and len(data.get('weeks', [])) == 1, (status, str(data)[:200]))
    status, data = call(president, '/api/callins')
    check('President gets mission Call-ins', status == 200 and data.get('role') == 'PRESIDENT', (status, str(data)[:200]))
    response = client.post('/internal/presentations/check', json={'user_id': president, 'deck_slugs': []},
                           headers={'X-Service-Key': service_key})
    check('President manages Presentations', response.status_code == 200 and response.get_json().get('can_manage') is True,
          response.get_data(as_text=True))
    status, data = call(analyst, '/api/callins')
    check('Data Analyst gets mission Call-ins', status == 200, (status, str(data)[:200]))

    status, data = call(office, '/api/events')
    check('Office signs in and edits the calendar', status == 200 and data.get('can_edit') is True, (status, data))
    status, data = call(office, '/api/announcements')
    check('Office may publish announcements', status == 200 and data.get('can_publish') is True, (status, data))
    check('Office gets no Call-ins', call(office, '/api/callins')[0] == 403)
    check('Office gets no Dashboards (no glimpse numbers)', call(office, '/api/dashboard?weeks=1')[0] == 403)
    check('A turned-off staff account is refused', call(turned_off, '/api/options')[0] == 403)

    for who, expected in ((president, True), (analyst, True), (office, False), (turned_off, False), (elsewhere, False)):
        name = next(k for k, v in people.items() if v == who)
        got = [helper(who, 'public.can_access_mission(%s)', (2,)), helper(who, 'public.can_access_zone(%s)', (zone,)),
               helper(who, 'public.is_mission_manager_for_area(%s)', (area,)), helper(who, 'public.can_access_area(%s)', (area,))]
        check(f'database helpers in mission 2 for {name}', got == [expected] * 4, got)
    check('the other mission President passes there', helper(elsewhere, 'public.can_access_mission(%s)', (other_mission,)) is True)
    check('the President does not pass in the other mission', helper(president, 'public.can_access_mission(%s)', (other_mission,)) is False)
    own = [helper(president, "(SELECT count(*) FROM public.current_user_context)"),
           helper(president, "(SELECT home_mission_id FROM public.current_user_context)"),
           helper(president, "(SELECT display_name FROM public.current_user_context)")]
    check('the views show the President only their own row, with home mission and name', own == [1, 2, 'Staff president'], own)
finally:
    for user in people.values():
        sql('DELETE FROM auth.users WHERE id=%s', (user,))
    sql('DELETE FROM public.missions WHERE id=%s', (other_mission,))

print(f'{sum(results)}/{len(results)} passed', flush=True)
sys.exit(0 if all(results) else 1)
