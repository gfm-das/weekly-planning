"""End-to-end check of the planning add-person endpoints against a THROWAWAY database copy.

It commits rows, so it refuses to run unless DATABASE_URL points at a database whose
name contains "test" and PEOPLE_TEST_THROWAWAY=yes. Identity lookups are replaced
in-process (same idea as api_workflows.py isolated mode); database roles, RLS,
SECURITY DEFINER RPCs and area checks are the real ones.

Run inside a temporary portal-api container:  python tests/planning_people_db.py
"""
import base64
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('PEOPLE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402
import planning  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail != '' else ''))


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 600}) + '.fixture'


def call(user, method, path, body=None):
    response = client.open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


users = sql('''SELECT c.user_id, c.area_id FROM public.current_user_context c
               WHERE c.user_active AND c.area_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM public.area_units au WHERE au.area_id=c.area_id)
               ORDER BY c.area_id, c.user_id''')
first = users[0]
other = next(u for u in users if u['area_id'] != first['area_id'])
user = first['user_id']
print(f"fixture: {len(users)} users with areas; testing area {first['area_id']} vs {other['area_id']}")

status, form = call(user, 'GET', '/api/planning/form')
check('planning form loads and includes choice lists', status == 200 and len(form['person_options']['finding_source']) == 14, status)
report_id, unit_id = form['report']['report_id'], form['report']['unit_id']
before_nm = max([p['display_order'] for p in form['people']['new_members']] or [0])
if form['report']['status'] != 'DRAFT':
    sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL WHERE id=%s", (report_id,))

status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/new_member', {})
check('empty New Member -> 400 with every field except the optional second language', status == 400
      and set(body.get('fields', {})) == set(planning.NEW_MEMBER_FIELDS) - {'second_language'}, body)
count_before = sql('SELECT count(*) AS n FROM public.new_members')[0]['n']
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/new_member',
                    {'first_name': 'Zz Test', 'gender': 'Robot'})
check('invalid choice -> 400, nothing written', status == 400 and body['fields'].get('gender') == 'Choose one of the listed options.'
      and sql('SELECT count(*) AS n FROM public.new_members')[0]['n'] == count_before, body)

payload = {'first_name': 'Zz Portal', 'last_name': 'Testperson', 'age_range': '31-45', 'gender': 'Female',
           'living_situation': 'Living with Parents', 'marital_status': 'Single',
           'mission_language_competency': 'Conversational/basic', 'finding_source': 'Member/Member',
           'baptismal_date_extended': '2026-09-01', 'baptism_date': '2026-09-20', 'confirmation_date': '2026-09-26',
           'date_of_birth': '1995-03-04',
           'child_dependents': '1', 'native_language': 'Italian', 'country_of_origin': 'Italy',
           'conversion_success_notes': 'Ward council helped.\nCame to every activity.'}
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/new_member', payload)
check('valid New Member -> 201', status == 201 and body.get('id'), (status, body))
nm_id = body['id']
row = sql('''SELECT nm.*, u.stake_id AS unit_stake FROM public.new_members nm JOIN public.units u ON u.id=nm.unit_id
             WHERE nm.id=%s''', (nm_id,))[0]
check('new_members row: area/unit/stake/creator from the signed-in user',
      row['area_id'] == first['area_id'] and row['unit_id'] == unit_id and row['stake_id'] == row['unit_stake']
      and str(row['created_by']) == str(user), {k: row[k] for k in ('area_id', 'unit_id', 'stake_id')})
check('new_members row: every field of the New Member form stored',
      row['living_situation'] == 'Living with Parents' and row['mission_language_competency'] == 'Conversational/basic'
      and row['child_dependents'] == 1 and row['display_name'] == 'Zz Portal Testperson'
      and row['conversion_success_notes'].count('\n') == 1 and str(row['date_of_birth']) == '1995-03-04')
assign = sql('SELECT area_id, unit_id, start_date FROM public.new_member_area_assignments WHERE new_member_id=%s', (nm_id,))
check('area assignment created (start = baptism date)', len(assign) == 1 and assign[0]['area_id'] == first['area_id']
      and str(assign[0]['start_date']) == '2026-09-20', assign)
weekly = sql('SELECT id, display_order FROM public.weekly_new_members WHERE weekly_area_report_id=%s AND new_member_id=%s', (report_id, nm_id))
check('added to this week\'s plan after everyone already on it', len(weekly) == 1 and weekly[0]['display_order'] == before_nm + 1, weekly)
status, form2 = call(user, 'GET', '/api/planning/form')
mine = [p for p in form2['people']['new_members'] if p['new_member_id'] == nm_id]
check('new person appears in the planning form (becomes a tab)', len(mine) == 1 and mine[0]['display_name'] == 'Zz Portal Testperson')
people = {g: [{'id': p['id']} for p in form2['people'][g]] for g in ('new_members', 'baptismal_friends')}
for p in people['new_members']:
    if p['id'] == mine[0]['id']:
        p.update(lessons_actual=2, how_are_they_doing='Good first week')
status, _ = call(user, 'PUT', f'/api/planning/reports/{report_id}/people', {'people': {'changes_only': True, **people}})
saved = sql('SELECT lessons_actual, how_are_they_doing FROM public.weekly_new_members WHERE id=%s', (mine[0]['id'],))[0]
check('per-person fields save for the new tab', status == 200 and saved['lessons_actual'] == 2, (status, saved))

status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/baptismal', {'last_name': 'Only'})
check('Baptismal person without first name and finding source -> 400 field errors', status == 400 and body['fields'] == {
    'first_name': 'Enter the first name.', 'finding_source': 'Please choose one.'}, body)
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/baptismal',
                    {'first_name': 'Zz Date', 'last_name': 'Friend', 'finding_source': 'Media/Referral'})
check('valid Baptismal Date person -> 201', status == 201, (status, body))
bd_id = body['id']
bd = sql('''SELECT b.display_name, b.finding_source, b.created_by, a.area_id, a.unit_id
            FROM public.baptismal_date_people b JOIN public.baptismal_date_person_area_assignments a ON a.baptismal_date_person_id=b.id
            WHERE b.id=%s''', (bd_id,))
check('baptismal_date_people + area assignment rows', len(bd) == 1 and bd[0]['area_id'] == first['area_id'] and bd[0]['unit_id'] == unit_id
      and bd[0]['finding_source'] == 'Media/Referral', bd)
check('added to weekly_baptismal_date_friends', len(sql('SELECT 1 FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s AND baptismal_date_person_id=%s', (report_id, bd_id))) == 1)

status, body = call(other['user_id'], 'POST', f'/api/planning/reports/{report_id}/people/baptismal', {'first_name': 'Zz Intruder'})
check('user from another area -> 403, nothing written', status == 403 and not sql("SELECT 1 FROM public.baptismal_date_people WHERE first_name='Zz Intruder'"), (status, body))
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/robot', {'first_name': 'X'})
check('unknown person type -> 400', status == 400, (status, body))
sql("UPDATE public.weekly_area_reports SET status='SUBMITTED', submitted_at=now() WHERE id=%s", (report_id,))
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/people/baptismal', {'first_name': 'Zz Late'})
check('submitted plan -> 400, nothing written', status == 400 and not sql("SELECT 1 FROM public.baptismal_date_people WHERE first_name='Zz Late'"), (status, body))
response = client.post(f'/api/planning/reports/{report_id}/people/baptismal', json={'first_name': 'Zz Anon'})
check('no sign-in -> 401', response.status_code == 401)
print(f'\n{sum(results)}/{len(results)} passed (throwaway database {dbname})')
sys.exit(0 if all(results) else 1)
