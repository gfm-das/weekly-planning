"""The read-only Vollzogen list (GET /api/vollzogen) against a THROWAWAY database copy that has migration 051.

It writes two invented people into public.vollzogen_records (and removes them again), then asks the route as an Office
account, a manager, a DL and a missionary. It refuses unless DATABASE_URL names a database containing "test" and
VOLLZOGEN_TEST_THROWAWAY=yes. NOT run in the round-13 session (no Docker or Postgres): run it on a throw-away copy first.

Run inside a temporary portal-api container (same way as callins_db.py):
  VOLLZOGEN_TEST_THROWAWAY=yes python tests/vollzogen_view_db.py
Needs: one mission (any Beta copy has one). Identity lookups are replaced in-process; the route reads with the service
connection, as live.
"""
import os
import sys
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('VOLLZOGEN_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail and not ok else ''), flush=True)


def ask(context, path, method='GET', body=None):
    with patch.object(api, 'context_for', lambda conn, user: dict(context)), \
            patch.object(api, 'signed_in_user', lambda header: ('00000000-0000-4000-8000-0000000ca1ff', {'sub': 'x', 'role': 'authenticated'})):
        response = api.app.test_client().open(path, method=method, json=body, headers={'Authorization': 'Bearer fixture'})
    return response.status_code, response.get_json(silent=True)


with api.db() as conn:
    mission_id = api.rows(conn, 'SELECT id FROM public.missions ORDER BY id LIMIT 1')[0]['id']
    api.rows(conn, "DELETE FROM public.vollzogen_records WHERE record_key LIKE %s", ('vtest %',))
    for key, name, day, zone, confirmed in (('vtest one|2026-09-20', 'Vtest Person One', '2026-09-20', 'Vtest Zone A', True),
                                            ('vtest two|2026-09-13', 'Vtest Person Two', '2026-09-13', 'Vtest Zone B', False)):
        api.rows(conn, '''INSERT INTO public.vollzogen_records (mission_id, record_key, full_name, baptism_date, zone, confirmed, fc_number)
            VALUES (%s,%s,%s,%s,%s,%s,'FC-VTEST1')''', (mission_id, key, name, day, zone, confirmed))

try:
    mission = {'mission_id': mission_id}
    office = dict(mission, app_role='OFFICE', leadership_role=None)
    manager = dict(mission, app_role='PRESIDENT', leadership_role=None)
    dl = dict(mission, app_role='MISSIONARY', leadership_role='DL', leadership_district_id=1)
    missionary = dict(mission, app_role='MISSIONARY', leadership_role=None)
    other_mission = dict(office, mission_id=mission_id + 100000)

    status, body = ask(office, '/api/vollzogen?q=vtest')
    check('office gets the list', status == 200 and body['read_only'] is True, (status, body))
    check('both fixture people are in it', {i['full_name'] for i in body['items']} == {'Vtest Person One', 'Vtest Person Two'}, body)
    check('no FC number or key leaves the route', not any('fc_number' in i or 'record_key' in i for i in body['items']), body)
    check('the Sunday filter works', ask(office, '/api/vollzogen?week=2026-09-20&q=vtest')[1]['items'][0]['full_name'] == 'Vtest Person One')
    check('the week list names the weeks by their Sunday', '2026-09-20' in ask(office, '/api/vollzogen?q=vtest')[1]['weeks'])
    check('the zone filter works', [i['full_name'] for i in ask(office, '/api/vollzogen?zone=Vtest%20Zone%20B')[1]['items']] == ['Vtest Person Two'])
    check('the text search finds by name, case does not matter', len(ask(office, '/api/vollzogen?q=PERSON%20ONE')[1]['items']) == 1)
    check('a percent sign in the search is not a wildcard', ask(office, '/api/vollzogen?q=%25')[1]['items'] == [])
    check('a month period keeps its people', {i['full_name'] for i in ask(office, '/api/vollzogen?period=2026-09&q=vtest')[1]['items']} == {'Vtest Person One', 'Vtest Person Two'})
    check('another year shows none of them', ask(office, '/api/vollzogen?period=2025&q=vtest')[1]['items'] == [])
    check('the months with baptisms are offered', '2026-09' in ask(office, '/api/vollzogen?period=month')[1]['months'])
    check('a bad period is a 400', ask(office, '/api/vollzogen?period=2026-13')[0] == 400)
    check('manager gets the list', ask(manager, '/api/vollzogen')[0] == 200)
    check('a DL does not', ask(dl, '/api/vollzogen')[0] == 403)
    check('a missionary does not', ask(missionary, '/api/vollzogen')[0] == 403)
    check('another mission sees none of these people', ask(other_mission, '/api/vollzogen?q=vtest')[1]['items'] == [])
    check('office cannot write', all(ask(office, '/api/vollzogen', m, {})[0] == 405 for m in ('PUT', 'POST', 'DELETE')))
finally:
    with api.db() as conn:
        api.rows(conn, "DELETE FROM public.vollzogen_records WHERE record_key LIKE %s", ('vtest %',))

print(f'{sum(results)} of {len(results)} checks passed')
sys.exit(0 if all(results) else 1)
