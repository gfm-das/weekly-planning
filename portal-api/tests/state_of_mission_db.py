"""Round 28 end to end: State of the Mission charts through POST /internal/presentations/chart-data.

THROWAWAY test database with the SYNTHETIC seed in tests/state_of_mission_seed.sql only (refuses otherwise).
Seed: 4 areas in 3 units, 13 Q3 2026 weeks, every area reports 3 friends found (mission sum 12 a week).
Area 1 has 2 companionships, area 2 none recorded (counts 1) plus a stale one that must not count,
area 3 (2 sisters) opens on 2026-08-01, area 4 has no missionaries.
Expected: companionships 3 a week until 26 Jul, 4 from 2 Aug, so friends found per companionship 4.0 then 3.0.
"""
import os
import sys
import uuid
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('CHARTS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')
os.environ.setdefault('PORTAL_SERVICE_KEY', 'charts-db-test-key')

import app as api  # noqa: E402

client = api.app.test_client()
fails = 0


def check(name, ok, detail=''):
    global fails
    fails += not ok
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:400]}' if detail != '' else ''), flush=True)


with api.db() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM public.user_profiles WHERE missionary_id=1')
        if not cur.fetchone():
            uid = str(uuid.uuid4())
            cur.execute('INSERT INTO auth.users(id) VALUES (%s)', (uid,))
            cur.execute("INSERT INTO public.user_profiles(id,app_role,missionary_id) VALUES (%s,'AP',1)", (uid,))
            cur.execute("INSERT INTO public.leadership_assignments(id,missionary_id,role,start_date,mission_id) VALUES (1,1,'AP','2026-06-01',1)")
        conn.commit()
    ap = api.rows(conn, "SELECT user_id FROM public.current_user_context WHERE leadership_role='AP' LIMIT 1")[0]['user_id']


def post(spec):
    r = client.post('/internal/presentations/chart-data', json={'user_id': str(ap), 'spec': spec},
                    headers={'X-Service-Key': os.environ['PORTAL_SERVICE_KEY']})
    body = r.get_json(silent=True) or {}
    return r.status_code, {**(body.get('table') or {}), 'meta': body.get('meta')}


def series(body, i):
    found = body.get('series') or []
    return found[i]['values'] if len(found) > i else None


q3 = {'from': '2026-07-01', 'to': '2026-09-30'}
st, body = post({'measures': ['friends_found.actual', 'friends_found.previous_goal'], 'level': 'mission',
                 'transform': 'per_companionship', 'weeks': q3})
print('per companionship response:', st, {k: body.get(k) for k in ('labels', 'series', 'value_kind')})
vals = series(body, 0)
check('goal line comes along', series(body, 1) is not None and len(series(body, 1)) == 13, series(body, 1))
check('per companionship: 13 week labels Jul-Sep', st == 200 and len(body.get('labels', [])) == 13, body.get('labels'))
check('per companionship = 4.0 for 4 weeks of July, then 3.0 (12 / distinct companionships that week)',
      vals == [4.0] * 4 + [3.0] * 9, vals)

st, body = post({'measures': ['roster.missionaries'], 'level': 'unit', 'by': 'unit', 'weeks': {'last': 1}, 'sort': 'desc'})
print('unit bar response:', st, {k: body.get(k) for k in ('labels', 'series')})
check('missionaries per unit (latest week), most first', st == 200 and body.get('labels') == ['Ward Alpha', 'Branch Gamma', 'Ward Beta']
      and series(body, 0) == [4, 2, 2], body)

st, body = post({'measures': ['roster.units', 'roster.missionaries', 'roster.companionships'], 'level': 'mission', 'weeks': {'last': 1}})
print('units tiles response:', st, body.get('series'))
st2, body2 = post({'measures': ['roster.elders', 'roster.sisters', 'roster.missionaries'], 'level': 'mission', 'weeks': {'last': 1}})
print('gender response:', st2, body2.get('series'))
tiles = [series(body, i) for i in range(3)]
check('units 3, missionaries 8, companionships 4 (stale one not counted)', st == 200 and tiles == [[3], [8], [4]], tiles)
gender = [series(body2, i) for i in range(3)]
check('elders 6, sisters 2, missionaries 8', st2 == 200 and gender == [[6], [2], [8]], gender)
sys.exit(1 if fails else 0)
