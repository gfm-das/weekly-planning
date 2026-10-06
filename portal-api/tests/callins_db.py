"""Call-ins against a THROWAWAY database copy with migration 022 applied: home scopes, drill-down, the people lists,
GEMIKO, every save and refusal (API and database), the completion lock, zone-notes readers, and timings.

It writes fixture accounts and call-in notes, so it refuses unless DATABASE_URL names a database containing "test"
and CALLINS_TEST_THROWAWAY=yes. Identity lookups are replaced in-process (as in planning_people_db.py); database
roles, RLS and the Call-ins functions are the real ones. The API connects as postgres, like live.

Fixture accounts (fixed ids 00000000-0000-4000-8000-0000000ca1xx, linked to existing missionaries without an
account): an STL, a second DL in the ZL's zone, a missionary without a leadership role, a President and a Data
Analyst (app_role DATA_ADMIN). The AP, ZL and DL accounts already in Beta are used as they are.

Run inside a temporary portal-api container:
  python tests/callins_db.py [--quick] [--capture DIR] [--timings]
--quick skips the slower repeated reads; --timings measures every endpoint 3 times (median); --capture writes
the ZL/DL/mission responses with names and free text replaced, for a stub API used in browser tests.
Results that depend on migration 021 (not applied on this copy) are printed as "021:" lines, not as checks.
"""
import base64
import json
import os
import statistics
import sys
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote, urlparse

import psycopg2

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('CALLINS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402
import callins  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []
QUICK = '--quick' in sys.argv
TIMINGS = '--timings' in sys.argv
CAPTURE = sys.argv[sys.argv.index('--capture') + 1] if '--capture' in sys.argv else None


def check(name, ok, detail=''):
    results.append(bool(ok))
    detail = str(detail)
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {detail[:300]}' if detail and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.fixture'


def call(user, path, method='GET', body=None):
    started = time.time()
    response = client.open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True), round(time.time() - started, 3)


def sql(query, args=()):
    """As the server (postgres, no signed-in user: a trusted write for the call-in guards)."""
    with api.db() as conn:
        return api.rows(conn, query, args)


def as_user(user_id, query, args=()):
    """As a signed-in user through the authenticated role, rolled back: (SQLSTATE or 'ok', rows or message)."""
    try:
        with api.db() as conn:
            api.rows(conn, "SELECT set_config('request.jwt.claims',%s,true)", (json.dumps({'sub': str(user_id), 'role': 'authenticated'}),))
            api.rows(conn, 'SET LOCAL ROLE authenticated')
            found = api.rows(conn, query, args)
            conn.rollback()
            return 'ok', found
    except psycopg2.Error as error:
        return error.pgcode, error.diag.message_primary


def uid(n):
    return f'00000000-0000-4000-8000-0000000ca1{n:02d}'


CURRENT = '''la.start_date<=CURRENT_DATE AND (la.end_date IS NULL OR la.end_date>=CURRENT_DATE)'''
FREE = '''NOT EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id)
    AND EXISTS (SELECT 1 FROM public.missionary_assignments ma WHERE ma.missionary_id=m.id
                AND ma.start_date<=CURRENT_DATE AND (ma.end_date IS NULL OR ma.end_date>=CURRENT_DATE))'''


def leader(role):
    # The accounts already in Beta, not this test's fixtures (their ids sort first).
    found = sql('''SELECT c.user_id FROM public.current_user_context c WHERE c.user_active AND c.leadership_role=%s
                     AND c.user_id::text NOT LIKE %s ORDER BY c.user_id LIMIT 1''', (role, uid(0)[:-2] + '%'))
    return found[0]['user_id'] if found else None


def link(n, missionary_id, app_role='MISSIONARY'):
    sql('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (uid(n),))
    sql('''INSERT INTO public.user_profiles(id,missionary_id,app_role,active) VALUES(%s,%s,%s,true)
           ON CONFLICT(id) DO UPDATE SET missionary_id=excluded.missionary_id, app_role=excluded.app_role, active=true''',
        (uid(n), missionary_id, app_role))
    return uid(n)


# ---------------------------------------------------------------- fixtures
AP, ZL, DL = leader('AP'), leader('ZL'), leader('DL')
scope = {r['user_id']: r for r in sql('''SELECT user_id, leadership_zone_id, leadership_district_id, mission_id
                                         FROM public.current_user_scope WHERE user_id IN (%s,%s,%s)''', (AP, ZL, DL))}
ZONE = scope[ZL]['leadership_zone_id']
DISTRICT = scope[DL]['leadership_district_id']
MISSION = sql('SELECT z.mission_id FROM public.zones z WHERE z.id=%s', (ZONE,))[0]['mission_id']
DL_ZONE = sql('SELECT zone_id FROM public.districts WHERE id=%s', (DISTRICT,))[0]['zone_id']


def pick(query, args=()):
    rows = sql(query, args)
    return rows[0] if rows else None


stl = pick(f'''SELECT la.missionary_id, la.zone_id FROM public.leadership_assignments la JOIN public.missionaries m ON m.id=la.missionary_id
    WHERE la.role='STL' AND {CURRENT} AND (NOT EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id)
          OR EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id AND up.id=%s))
      AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments o WHERE o.missionary_id=m.id AND o.role<>'STL'
                      AND o.start_date<=CURRENT_DATE AND (o.end_date IS NULL OR o.end_date>=CURRENT_DATE))
    ORDER BY (la.zone_id=%s) DESC, la.missionary_id LIMIT 1''', (uid(1), ZONE))
dl_b = pick(f'''SELECT la.missionary_id, la.district_id FROM public.leadership_assignments la JOIN public.districts d ON d.id=la.district_id
    JOIN public.missionaries m ON m.id=la.missionary_id
    WHERE la.role='DL' AND {CURRENT} AND d.zone_id=%s AND (NOT EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id)
          OR EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id AND up.id=%s))
    ORDER BY la.missionary_id LIMIT 1''', (ZONE, uid(2)))
plain = sql(f'''SELECT m.id AS missionary_id FROM public.missionaries m
    WHERE (NOT EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id)
           OR EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id AND up.id IN (%s,%s,%s,%s)))
      AND EXISTS (SELECT 1 FROM public.missionary_assignments ma JOIN public.areas a ON a.id=ma.area_id
                  JOIN public.districts d ON d.id=a.district_id
                  WHERE ma.missionary_id=m.id AND d.zone_id=%s
                    AND ma.start_date<=CURRENT_DATE AND (ma.end_date IS NULL OR ma.end_date>=CURRENT_DATE))
      AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments la WHERE la.missionary_id=m.id AND {CURRENT})
    ORDER BY m.id LIMIT 4''', (uid(3), uid(4), uid(5), uid(7), ZONE))
STL = link(1, stl['missionary_id']) if stl else None
DL_B = link(2, dl_b['missionary_id']) if dl_b else None
PLAIN = link(3, plain[0]['missionary_id'])
PRESIDENT = link(4, plain[1]['missionary_id'], 'PRESIDENT')
DATA_ADMIN = link(5, plain[2]['missionary_id'], 'DATA_ADMIN')
DISTRICT_B = dl_b['district_id'] if dl_b else None
OTHER_ZONE = sql('SELECT min(id) AS id FROM public.zones WHERE id<>%s AND mission_id=%s', (ZONE, MISSION))[0]['id']
OUTSIDE_DISTRICT = sql('SELECT min(id) AS id FROM public.districts WHERE zone_id<>%s', (ZONE,))[0]['id']
OWN_AREA = sql('SELECT min(id) AS id FROM public.areas WHERE district_id=%s AND active', (DISTRICT,))[0]['id']
OTHER_AREA = sql('SELECT min(id) AS id FROM public.areas WHERE district_id<>%s AND active', (DISTRICT,))[0]['id']
ZONE_AREA = sql('''SELECT min(a.id) AS id FROM public.areas a JOIN public.districts d ON d.id=a.district_id
                   WHERE d.zone_id=%s AND a.active''', (ZONE,))[0]['id']
weeks = [w['sunday'] for w in sql('''SELECT sunday FROM public.reporting_weeks
    WHERE sunday<=public.current_reporting_sunday() ORDER BY sunday DESC''')]
WEEK = str(weeks[0])
WEEK_ID = sql('SELECT id FROM public.reporting_weeks WHERE sunday=%s', (weeks[0],))[0]['id']
# A week with baptismal-date friends, new members and high potentials, for the people checks.
PEOPLE_WEEK = sql('''SELECT rw.sunday FROM public.reporting_weeks rw WHERE rw.sunday<=public.current_reporting_sunday()
    ORDER BY (SELECT count(*) FROM public.weekly_area_reports r JOIN public.weekly_new_members w ON w.weekly_area_report_id=r.id
              WHERE r.reporting_week_id=rw.id AND w.new_member_id IS NOT NULL)
           + (SELECT count(*) FROM public.weekly_area_reports r JOIN public.weekly_baptismal_date_friends w ON w.weekly_area_report_id=r.id
              WHERE r.reporting_week_id=rw.id) DESC, rw.sunday DESC LIMIT 1''')[0]['sunday']
print(f'fixture: mission {MISSION}, ZL zone {ZONE}, DL district {DISTRICT} (zone {DL_ZONE}), second DL district {DISTRICT_B}, '
      f'STL zone {stl and stl["zone_id"]}, write week {WEEK}, people week {PEOPLE_WEEK}', flush=True)
# Start the write checks from an empty week (trusted server connection, like the importer).
sql('DELETE FROM public.call_in_districts WHERE reporting_week_id=%s', (WEEK_ID,))
sql('DELETE FROM public.call_in_zones WHERE reporting_week_id=%s', (WEEK_ID,))
has_021 = bool(sql('''SELECT 1 FROM information_schema.columns WHERE table_schema='public'
                      AND table_name='user_profiles' AND column_name='additional_roles' '''))
print(f'migration 021 applied on this copy: {has_021}', flush=True)

# ---------------------------------------------------------------- weeks and the time limit
for bad in ('garbage', '2026-02-30', '20260920', "2026-09-20'; SELECT 1 --"):
    status, body, _ = call(ZL, '/api/callins?week=' + quote(bad))
    check(f'malformed week {bad!r} -> 400 with a plain message', status == 400 and 'reporting week' in (body or {}).get('error', ''),
          (status, body))
saturday = weeks[0] - timedelta(days=1)
status, body, _ = call(ZL, f'/api/callins?week={saturday}')
check('a date with no reporting week -> 404', status == 404 and body == {'error': 'That reporting week is unavailable.'}, (status, body))
status, body, _ = call(AP, f'/api/callins/zones/{ZONE}', 'PUT', {'week': 'not-a-date', 'zone_notes': 'x'})
check('zone notes with a malformed week -> 400, nothing saved', status == 400, (status, body))

with patch.object(callins, 'CALLINS_STATEMENT_TIMEOUT', '1ms'):  # any real summary takes longer than this
    status, body, seconds = call(AP, '/api/callins')
left = sql('''SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database() AND state='active'
              AND pid<>pg_backend_pid() AND query LIKE '%%call_in_summary_with_planning%%' ''')[0]['n']
check('a summary over the time limit -> 503 with a plain message, nothing left running on the database',
      status == 503 and body == {'error': callins.SLOW} and left == 0, (status, body, f'{seconds}s', f'{left} still running'))

status, body, seconds = call(ZL, '/api/callins')
check('no ?week= -> 200 with the latest existing week', status == 200 and body['week']['sunday'] == str(weeks[0]), (status, body))
check('weeks list: the last 12, newest first', [w['sunday'] for w in body['weeks']] == [str(w) for w in weeks[:12]])
check('seven numbers including follow-up lessons', [m['key'] for m in body['metrics']][-1] == 'follow_up_lessons' and len(body['metrics']) == 7)

# ---------------------------------------------------------------- home scopes and drill-down
homes = [('AP', AP, 'mission', MISSION), ('ZL', ZL, 'zone', ZONE), ('DL', DL, 'district', DISTRICT),
         ('Data Analyst (app_role)', DATA_ADMIN, 'mission', MISSION)]
if DL_B:
    homes.append(('second DL', DL_B, 'district', DISTRICT_B))
for name, user, level, scope_id in homes:
    status, body, seconds = call(user, '/api/callins')
    check(f'{name} opens on their {level}', status == 200 and (body['scope']['level'], body['scope']['id']) == (level, scope_id),
          (status, body and body.get('scope', body)))
    # Computer-first for the AP and Data Analyst (they open on the mission), phone-first for ZLs and DLs.
    layout = 'desktop' if level == 'mission' else 'phone'
    check(f'{name}: {layout} layout', status == 200 and body['layout'] == layout, body and body.get('layout'))
status, body, _ = call(PRESIDENT, '/api/callins')
status2, body2, _ = call(PRESIDENT, f'/api/callins?level=zone&id={ZONE}')
check('President opens a zone', status2 == 200, (status2, body2))
if has_021:
    check('President opens the mission (021)', status == 200 and body['scope']['level'] == 'mission', (status, body))
else:
    print(f'021: President home (mission): {status} {"" if status == 200 else body} '
          f'(before 021 can_access_mission never lets a President in; expected 200 after 021)', flush=True)

# A DL who is also Data Analyst (additional role, migration 021): opens on the district, may go up to the mission.
dl_da = pick(f'''SELECT la.missionary_id, la.district_id FROM public.leadership_assignments la JOIN public.districts d ON d.id=la.district_id
    JOIN public.zones z ON z.id=d.zone_id JOIN public.missionaries m ON m.id=la.missionary_id
    WHERE la.role='DL' AND {CURRENT} AND z.mission_id=%s AND la.district_id NOT IN (%s,%s)
      AND (NOT EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id)
           OR EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=m.id AND up.id=%s))
    ORDER BY la.missionary_id LIMIT 1''', (MISSION, DISTRICT, DISTRICT_B or 0, uid(6)))
if has_021 and dl_da:
    DL_DA = link(6, dl_da['missionary_id'])
    sql("UPDATE public.user_profiles SET additional_roles='{DATA_ADMIN}' WHERE id=%s", (DL_DA,))
    status, body, _ = call(DL_DA, '/api/callins')
    check('DL + Data Analyst opens on their district (021)', status == 200 and (body['scope']['level'], body['scope']['id'])
          == ('district', dl_da['district_id']) and body['layout'] == 'phone', (status, body and body.get('scope')))
    check('DL + Data Analyst may go up to the mission (breadcrumb, 021)', status == 200 and all(c['allowed'] for c in body['scope']['breadcrumb']))
    status, body, _ = call(DL_DA, f'/api/callins?level=mission&id={MISSION}')
    check('DL + Data Analyst opens the mission (021)', status == 200 and body['scope']['level'] == 'mission', (status, body))
    status, body, _ = call(DL_DA, f'/api/callins/people?level=mission&id={MISSION}')
    check('DL + Data Analyst reads the mission people (021)', status == 200, (status, body))
else:
    print('021: DL + Data Analyst checks skipped (needs user_profiles.additional_roles from 021)', flush=True)

# A missionary who is Data Analyst only as an additional role (021): no DL or ZL home, so the mission, computer-first.
if has_021 and len(plain) > 3:
    MISSIONARY_DA = link(7, plain[3]['missionary_id'])
    sql("UPDATE public.user_profiles SET additional_roles='{DATA_ADMIN}' WHERE id=%s", (MISSIONARY_DA,))
    status, body, _ = call(MISSIONARY_DA, '/api/callins')
    check('Missionary + Data Analyst opens the mission with the computer layout (021)',
          status == 200 and body['scope']['level'] == 'mission' and body['layout'] == 'desktop', (status, body and body.get('layout')))
else:
    print('021: Missionary + Data Analyst check skipped (needs user_profiles.additional_roles from 021)', flush=True)

for name, user in (('plain missionary', PLAIN), ('STL', STL)):
    if not user:
        continue
    for path in ('/api/callins', f'/api/callins?level=zone&id={ZONE}', '/api/callins/people',
                 f'/api/callins/gemiko?level=district&id={DISTRICT}'):
        status, body, _ = call(user, path)
        check(f'{name}: {path} -> friendly 403', status == 403 and body['error'] == callins.NOT_FOR_YOU, (status, body))

refusals = [
    ('DL -> another district', DL, 'district', DISTRICT_B or OUTSIDE_DISTRICT), ('DL -> zone level', DL, 'zone', DL_ZONE),
    ('DL -> mission', DL, 'mission', MISSION), ('DL -> area of another district', DL, 'area', OTHER_AREA),
    ('ZL -> another zone', ZL, 'zone', OTHER_ZONE), ('ZL -> mission', ZL, 'mission', MISSION),
    ('ZL -> district of another zone', ZL, 'district', OUTSIDE_DISTRICT),
]
for name, user, level, scope_id in refusals:
    status, body, _ = call(user, f'/api/callins?level={level}&id={scope_id}')
    check(f'{name} -> 403', status == 403 and body['error'] == callins.OUTSIDE, (status, body))
    status, body, _ = call(user, f'/api/callins/people?level={level}&id={scope_id}')
    check(f'{name} (people) -> 403', status == 403, (status, body))
allowed = [('DL -> own area', DL, 'area', OWN_AREA), ('ZL -> area in own zone', ZL, 'area', ZONE_AREA),
           ('AP -> another zone', AP, 'zone', OTHER_ZONE), ('AP -> a district', AP, 'district', OUTSIDE_DISTRICT),
           ('AP -> an area', AP, 'area', OTHER_AREA)]
if DISTRICT_B:
    allowed.append(('ZL -> district in own zone', ZL, 'district', DISTRICT_B))
for name, user, level, scope_id in allowed:
    status, body, _ = call(user, f'/api/callins?level={level}&id={scope_id}')
    check(f'{name} -> 200', status == 200 and body['scope']['level'] == level, (status, body))

status, body, _ = call(DL, f'/api/callins?level=area&id={OWN_AREA}')
check('DL area: breadcrumb mission/zone plain text, district/area open',
      [c['allowed'] for c in body['scope']['breadcrumb']] == [False, False, True, True], body['scope']['breadcrumb'])
check('area level: one area in detail, no children', body['detail']['id'] == OWN_AREA and body['children'] == [])
status, body, _ = call(DL, '/api/callins')
check('DL at own district: may save DL notes and area updates and complete; not ZL notes',
      body['can'] == {'dl_notes': True, 'area_updates': True, 'complete': True, 'reopen': False, 'zl_notes': False}, body['can'])
check('DL sees DL notes but not the ZL notes', set(body['notes']) == {'dl_notes'}, body['notes'])
check('area cards carry missionaries (name and position only), six plans and the area update',
      all(set(c) >= {'missionaries', 'plans', 'area_update', 'metrics', 'planning_details'} and len(c['plans']) == 6 for c in body['children'])
      and all(set(m) == {'name', 'position'} for c in body['children'] for m in c['missionaries']))
status, body, _ = call(ZL, '/api/callins')
check('ZL at own zone: zone notes and ZL notes, district children with area updates',
      body['can'] == {'zone_notes': True, 'zl_notes': True} and 'zone_notes' in body['notes']
      and all('area_updates' in c and set(c['notes']) == {'dl_notes', 'zl_notes'} for c in body['children']), body['can'])
text = json.dumps(body)
check('no thank-you in any answer', 'thank_you' not in text)
status, body, _ = call(AP, '/api/callins')
check('AP mission: zones with DL call-in counts and report status, all may be opened',
      status == 200 and all(c['allowed'] and 'completed_district_count' in c['status'] for c in body['children']), status)

# ---------------------------------------------------------------- people
status, body, _ = call(AP, f'/api/callins/people?week={PEOPLE_WEEK}')
card_fields = {'baptismal_dates': {'id', 'person_id', 'name', 'area_id', 'area_name', 'unit_name', 'district_name', 'zone_name',
                                   'missionaries', 'finding_source', 'date_set', 'baptismal_date', 'days_until', 'weeks_until',
                                   'reading', 'praying', 'at_church', 'keeping_commandments', 'member_involvement', 'active'},
               'new_members': {'id', 'person_id', 'name', 'area_name', 'baptism_date', 'confirmation_date', 'finding_source',
                               'lessons_actual', 'lessons_goal', 'pmg_lessons_percentage', 'how_are_they_doing',
                               'discussed_in_gemiko', 'gemiko_support_plan', 'next_ordinance', 'at_church', 'has_calling',
                               'has_aaronic_priesthood', 'has_melchizedek_priesthood', 'ministers_to_someone',
                               'ministered_to_by_someone', 'has_active_temple_recommend', 'visited_temple_for_baptisms',
                               'reading', 'praying', 'member_involvement', 'active'},
               'high_potentials': {'id', 'name', 'area_name', 'at_church', 'notes', 'active'}}
ok = status == 200
for group, fields in card_fields.items():
    rows = body.get(group, []) if ok else []
    counts = (body.get('counts') or {}).get(group, {}) if ok else {}
    ok = ok and counts.get('total') == len(rows) and counts.get('active') == sum(1 for r in rows if r['active'] is True)
    ok = ok and all(fields <= set(r) and isinstance(r['active'], bool) for r in rows)
check('mission people: every card field, active flags and matching counts', ok, (status, body and body.get('counts')))
check('mission people week has people to show', status == 200 and sum(v['total'] for v in body['counts'].values()) > 0, body.get('counts'))
mission_people = body
for name, user, level, scope_id in (('ZL zone', ZL, 'zone', ZONE), ('DL district', DL, 'district', DISTRICT),
                                    ('DL area', DL, 'area', OWN_AREA)):
    status, body, _ = call(user, f'/api/callins/people?level={level}&id={scope_id}&week={PEOPLE_WEEK}')
    inside = all(r[level + '_id'] == scope_id for g in card_fields for r in body.get(g, [])) if status == 200 else False
    check(f'{name} people: 200 and only people of that {level}', status == 200 and inside, (status, body and body.get('counts')))
    mission_ids = {(g, r['id']) for g in card_fields for r in mission_people[g] if r[level + '_id'] == scope_id}
    check(f'{name} people: the same rows as the mission list for that {level}',
          {(g, r['id']) for g in card_fields for r in body[g]} == mission_ids)
# "active" is Beta's rule: compare with Beta's activity lists for every district that has people that week.
for group, beta in (('baptismal_dates', 'get_dl_call_in_bd_activity'), ('new_members', 'get_dl_call_in_nm_activity'),
                    ('high_potentials', 'get_dl_call_in_hp_activity')):
    districts = sorted({r['district_id'] for r in mission_people[group]})
    same = []
    for district_id in districts:
        code, found = as_user(AP, f"""SELECT count(*) AS n, count(*) FILTER (WHERE active) AS active FROM public.{beta}(%s,
            (SELECT id FROM public.reporting_weeks WHERE sunday=%s))""", (district_id, PEOPLE_WEEK))
        mine = [r for r in mission_people[group] if r['district_id'] == district_id]
        same.append(code == 'ok' and found[0]['n'] == len(mine) and found[0]['active'] == sum(1 for r in mine if r['active']))
    check(f"{group}: rows and active flags match Beta's {beta} ({len(districts)} districts)", all(same), same)

# Database level: only leaders of that scope and managers; never an STL or a plain missionary.
people_sql = 'SELECT public.get_call_in_people(%s,%s,%s) AS data'
for name, user, level, scope_id, expected in (
        ('STL -> own zone', STL, 'zone', stl and stl['zone_id'], '42501'), ('plain missionary -> own zone', PLAIN, 'zone', ZONE, '42501'),
        ('plain missionary -> own area', PLAIN, 'area', None, '42501'), ('DL -> own zone', DL, 'zone', DL_ZONE, '42501'),
        ('ZL -> mission', ZL, 'mission', MISSION, '42501'), ('ZL -> own zone', ZL, 'zone', ZONE, 'ok'),
        ('DL -> own district', DL, 'district', DISTRICT, 'ok'), ('AP -> mission', AP, 'mission', MISSION, 'ok')):
    if not user:
        continue
    if scope_id is None:
        scope_id = sql('''SELECT ma.area_id FROM public.missionary_assignments ma JOIN public.user_profiles up ON up.missionary_id=ma.missionary_id
                          WHERE up.id=%s AND ma.start_date<=CURRENT_DATE AND (ma.end_date IS NULL OR ma.end_date>=CURRENT_DATE)''', (user,))[0]['area_id']
    code, _ = as_user(user, people_sql, (level, scope_id, WEEK_ID))
    check(f'database: get_call_in_people {name} -> {expected}', code == expected, code)

# GEMIKO
status, body, _ = call(DL, f'/api/callins/gemiko?level=district&id={DISTRICT}')
check('GEMIKO for the DL district', status == 200 and isinstance(body['units'], list), (status, body))
status, body, _ = call(DL, f'/api/callins/gemiko?level=area&id={OWN_AREA}')
check('GEMIKO for one area lists only that area', status == 200 and all(u['area_id'] == OWN_AREA for u in body['units']), status)
status, body, _ = call(DL, f'/api/callins/gemiko?level=district&id={DISTRICT_B or OUTSIDE_DISTRICT}')
check('GEMIKO of another district -> 403', status == 403, status)

# ---------------------------------------------------------------- saves
W = {'week': WEEK}
sql('''INSERT INTO public.call_in_districts(district_id,reporting_week_id,thank_you) VALUES(%s,%s,'kept as it was')
       ON CONFLICT(district_id,reporting_week_id) DO UPDATE SET thank_you='kept as it was' ''', (DISTRICT, WEEK_ID))
status, body, _ = call(DL, f'/api/callins/districts/{DISTRICT}/dl-notes', 'PUT', dict(W, dl_notes='Zz DL notes'))
stored = sql('SELECT dl_notes, thank_you FROM public.call_in_districts WHERE district_id=%s AND reporting_week_id=%s', (DISTRICT, WEEK_ID))[0]
check('DL saves DL notes', status == 200 and body['saved']['dl_notes'] == 'Zz DL notes' and stored['dl_notes'] == 'Zz DL notes', (status, body))
check('saving DL notes leaves thank_you untouched', stored['thank_you'] == 'kept as it was', stored['thank_you'])
code, _ = as_user(DL, "SELECT public.save_dl_call_in_notes(%s,%s,'Zz from Beta',NULL)", (DISTRICT, WEEK_ID))
check("Beta's call (thank-you NULL) works for the DL and keeps thank_you", code == 'ok' and sql(
    'SELECT thank_you FROM public.call_in_districts WHERE district_id=%s AND reporting_week_id=%s', (DISTRICT, WEEK_ID))[0]['thank_you'] == 'kept as it was', code)
status, body, _ = call(DL, f'/api/callins/areas/{OWN_AREA}/update', 'PUT', dict(W, update_text='Zz area update'))
check('DL saves an area update of their district', status == 200 and body['saved']['update_text'] == 'Zz area update', (status, body))
status, body, _ = call(DL, '/api/callins')
check('the saved notes and area update come back', body['notes']['dl_notes'] == 'Zz DL notes'
      and any(c['area_update'] == 'Zz area update' for c in body['children']))

for name, user, method, path, payload in (
        ('DL -> ZL notes of own district', DL, 'PUT', f'/api/callins/districts/{DISTRICT}/zl-notes', {'zl_notes': 'x'}),
        ('DL -> zone notes', DL, 'PUT', f'/api/callins/zones/{DL_ZONE}', {'zone_notes': 'x'}),
        ('DL -> area update of another district', DL, 'PUT', f'/api/callins/areas/{OTHER_AREA}/update', {'update_text': 'x'}),
        ('DL -> complete another district', DL, 'POST', f'/api/callins/districts/{DISTRICT_B or OUTSIDE_DISTRICT}/complete', {}),
        ('ZL -> DL notes', ZL, 'PUT', f'/api/callins/districts/{DISTRICT_B or OUTSIDE_DISTRICT}/dl-notes', {'dl_notes': 'x'}),
        ('ZL -> complete a district', ZL, 'POST', f'/api/callins/districts/{DISTRICT_B or OUTSIDE_DISTRICT}/complete', {}),
        ('ZL -> ZL notes outside the zone', ZL, 'PUT', f'/api/callins/districts/{OUTSIDE_DISTRICT}/zl-notes', {'zl_notes': 'x'}),
        ('ZL -> zone notes of another zone', ZL, 'PUT', f'/api/callins/zones/{OTHER_ZONE}', {'zone_notes': 'x'}),
        ('STL -> zone notes of own zone', STL, 'PUT', f'/api/callins/zones/{stl and stl["zone_id"]}', {'zone_notes': 'x'}),
        ('plain missionary -> DL notes', PLAIN, 'PUT', f'/api/callins/districts/{DISTRICT}/dl-notes', {'dl_notes': 'x'})):
    if not user:
        continue
    status, body, _ = call(user, path, method, dict(W, **payload))
    check(f'{name} -> 403', status == 403, (status, body))

# The database refuses the same people even when asked directly (as Beta/PostgREST would).
for name, user, query, args in (
        ('STL save_zl_zone_call_in_notes (own zone)', STL, 'SELECT public.save_zl_zone_call_in_notes(%s,%s,%s)', (stl and stl['zone_id'], WEEK_ID, 'x')),
        ('STL save_zl_call_in_notes (district of own zone)', STL, 'SELECT public.save_zl_call_in_notes(%s,%s,%s)',
         (sql('SELECT min(id) AS id FROM public.districts WHERE zone_id=%s', (stl and stl['zone_id'],))[0]['id'], WEEK_ID, 'x')),
        ('DL save_zl_call_in_notes', DL, 'SELECT public.save_zl_call_in_notes(%s,%s,%s)', (DISTRICT, WEEK_ID, 'x')),
        ('ZL save_dl_call_in_notes', ZL, 'SELECT public.save_dl_call_in_notes(%s,%s,%s,NULL)', (DISTRICT_B or OUTSIDE_DISTRICT, WEEK_ID, 'x')),
        ('ZL complete_dl_call_in', ZL, 'SELECT public.complete_dl_call_in(%s,%s)', (DISTRICT_B or OUTSIDE_DISTRICT, WEEK_ID)),
        ('plain missionary save_call_in_area_update', PLAIN, 'SELECT public.save_call_in_area_update(%s,%s,%s,%s)', (DISTRICT, WEEK_ID, OWN_AREA, 'x')),
        ('DL TRUNCATE', DL, 'TRUNCATE public.call_in_zones', ())):
    if not user:
        continue
    code, message = as_user(user, query, args)
    check(f'database: {name} refused', code == '42501', (code, message))
code, _ = as_user(DL, 'SELECT public.save_dl_call_in_notes(%s,%s,%s,NULL)', (DISTRICT_B or OUTSIDE_DISTRICT, WEEK_ID, 'x'))
check('database: DL cannot write another district\'s DL notes', code == '42501', code)

if DISTRICT_B:
    status, body, _ = call(ZL, f'/api/callins/districts/{DISTRICT_B}/zl-notes', 'PUT', dict(W, zl_notes='Zz ZL notes'))
    check('ZL saves ZL notes for a district in the zone', status == 200 and body['saved']['zl_notes'] == 'Zz ZL notes', (status, body))
status, body, _ = call(ZL, f'/api/callins/zones/{ZONE}', 'PUT', dict(W, zone_notes='Zz zone notes'))
check('ZL saves zone notes', status == 200 and body['saved']['zone_notes'] == 'Zz zone notes', (status, body))
status, body, _ = call(ZL, '/api/callins')
check('ZL sees the zone notes and the ZL notes back', body['notes']['zone_notes'] == 'Zz zone notes'
      and (not DISTRICT_B or any(c['id'] == DISTRICT_B and c['notes']['zl_notes'] == 'Zz ZL notes' for c in body['children'])))

# Managers write everything in their mission.
for name, method, path, payload in (
        ('DL notes', 'PUT', f'/api/callins/districts/{OUTSIDE_DISTRICT}/dl-notes', {'dl_notes': 'Zz AP'}),
        ('ZL notes', 'PUT', f'/api/callins/districts/{OUTSIDE_DISTRICT}/zl-notes', {'zl_notes': 'Zz AP'}),
        ('zone notes', 'PUT', f'/api/callins/zones/{OTHER_ZONE}', {'zone_notes': 'Zz AP'}),
        ('area update', 'PUT', f'/api/callins/areas/{OTHER_AREA}/update', {'update_text': 'Zz AP'})):
    status, body, _ = call(AP, path, method, dict(W, **payload))
    check(f'AP saves {name} anywhere in the mission', status == 200, (status, body))
status, body, _ = call(DATA_ADMIN, f'/api/callins/zones/{ZONE}', 'PUT', dict(W, zone_notes='Zz zone notes by DA'))
check('Data Analyst (app_role) saves zone notes', status == 200, (status, body))
status, body, _ = call(PRESIDENT, f'/api/callins/zones/{OTHER_ZONE}', 'PUT', dict(W, zone_notes='Zz by President'))
check('President saves zone notes', status == 200, (status, body))
if has_021 and dl_da:
    status, body, _ = call(DL_DA, f'/api/callins/districts/{OUTSIDE_DISTRICT}/zl-notes', 'PUT', dict(W, zl_notes='Zz by DL + DA'))
    check('DL + Data Analyst saves ZL notes elsewhere in the mission (021)', status == 200, (status, body))

# Zone notes readers (was: anyone whose area is in the zone).
for name, user, expected in (('ZL of the zone', ZL, 'ok'), ('AP', AP, 'ok'), ('plain missionary of the zone', PLAIN, '42501'),
                             ('second DL of the zone', DL_B, '42501'), ('STL', STL, '42501')):
    if not user:
        continue
    code, found = as_user(user, 'SELECT zone_notes FROM public.get_zl_call_in_zone_notes(%s,%s)', (ZONE, WEEK_ID))
    check(f'database: zone notes readable by {name}: {expected}', code == expected, code)
    code, found = as_user(user, 'SELECT count(*) AS n FROM public.call_in_zones WHERE zone_id=%s', (ZONE,))
    check(f'call_in_zones read policy for {name}: {"row" if expected == "ok" else "no row"}',
          code == 'ok' and found[0]['n'] == (1 if expected == 'ok' else 0), (code, found))

# ---------------------------------------------------------------- completion lock
lock_district, lock_dl = (DISTRICT_B, DL_B) if DISTRICT_B else (DISTRICT, DL)
lock_area = sql('SELECT min(id) AS id FROM public.areas WHERE district_id=%s AND active', (lock_district,))[0]['id']
status, body, _ = call(lock_dl, f'/api/callins/districts/{lock_district}/complete', 'POST', W)
check('DL completes their call-in', status == 200 and body['saved']['dl_call_in_complete'] is True, (status, body))
status, body, _ = call(lock_dl, '/api/callins')
check('after Complete: DL notes and area updates locked, Reopen offered',
      body['can'] == {'dl_notes': False, 'area_updates': False, 'complete': False, 'reopen': True, 'zl_notes': False}, body['can'])
status, body, _ = call(lock_dl, f'/api/callins/districts/{lock_district}/dl-notes', 'PUT', dict(W, dl_notes='Zz late'))
check('DL notes on a completed call-in -> 409 with a plain message', status == 409 and body == {'error': callins.LOCKED}, (status, body))
status, body, _ = call(lock_dl, f'/api/callins/areas/{lock_area}/update', 'PUT', dict(W, update_text='Zz late'))
check('area update on a completed call-in -> 409', status == 409, (status, body))
status, body, _ = call(AP, f'/api/callins/districts/{lock_district}/dl-notes', 'PUT', dict(W, dl_notes='Zz AP late'))
check('the lock holds for managers too (409)', status == 409, (status, body))
code, message = as_user(lock_dl, "SELECT public.save_dl_call_in_notes(%s,%s,'Zz direct',NULL)", (lock_district, WEEK_ID))
check('database: DL notes on a completed call-in -> 55000', code == '55000', (code, message))
if lock_district in {DISTRICT_B}:
    status, body, _ = call(ZL, f'/api/callins/districts/{lock_district}/zl-notes', 'PUT', dict(W, zl_notes='Zz ZL after complete'))
    check('ZL notes are not locked by Complete', status == 200, (status, body))
status, body, _ = call(AP, f'/api/callins/districts/{lock_district}/reopen', 'POST', W)
check('a manager reopens the call-in', status == 200 and body['saved']['dl_call_in_complete'] is False, (status, body))
status, body, _ = call(lock_dl, f'/api/callins/districts/{lock_district}/dl-notes', 'PUT', dict(W, dl_notes='Zz after reopen'))
check('after Reopen the DL saves again', status == 200, (status, body))
status, body, _ = call(lock_dl, f'/api/callins/districts/{lock_district}/complete', 'POST', W)
status2, body2, _ = call(lock_dl, f'/api/callins/districts/{lock_district}/reopen', 'POST', W)
check('the DL reopens their own call-in', status == 200 and status2 == 200 and body2['saved']['dl_call_in_complete'] is False, (status2, body2))
completed = sql('SELECT dl_completed_by FROM public.call_in_districts WHERE district_id=%s AND reporting_week_id=%s', (lock_district, WEEK_ID))
check('reopen clears the completion', completed and completed[0]['dl_completed_by'] is None)

# Beta still reads through the same functions as these leaders.
for name, user, query, args in (('ZL get_zl_call_in_summary', ZL, 'SELECT count(*) AS n FROM public.get_zl_call_in_summary(%s,%s)', (ZONE, WEEK_ID)),
                                ('DL get_dl_call_in_summary', DL, 'SELECT count(*) AS n FROM public.get_dl_call_in_summary(%s,%s)', (DISTRICT, WEEK_ID)),
                                ('AP get_mission_call_in_summary', AP, 'SELECT count(*) AS n FROM public.get_mission_call_in_summary(%s,%s)', (MISSION, WEEK_ID)),
                                ('DL get_dl_call_in_nm_activity', DL, 'SELECT count(*) AS n FROM public.get_dl_call_in_nm_activity(%s,%s)', (DISTRICT, WEEK_ID))):
    code, found = as_user(user, query, args)
    check(f'Beta read still works: {name}', code == 'ok' and found[0]['n'] >= 0, (code, found))
code, _ = as_user(DL, 'SELECT public.save_call_in_area_update(%s,%s,%s,%s)', (DISTRICT, WEEK_ID, OWN_AREA, 'Zz Beta area update'))
check("Beta's area-update call works for the DL", code == 'ok', code)


# ---------------------------------------------------------------- timings
def timed(user, path, runs=3):
    values, status = [], None
    for _ in range(runs):
        status, _, seconds = call(user, path)
        values.append(seconds)
    return status, statistics.median(values)


if TIMINGS or not QUICK:
    print('timings (median of 3, seconds, includes the in-process sign-in stub):', flush=True)
    for name, user, path in (
            ('AP mission bundle', AP, '/api/callins'), ('AP mission people', AP, '/api/callins/people'),
            ('ZL zone bundle', ZL, '/api/callins'), ('ZL zone people', ZL, '/api/callins/people'),
            ('DL district bundle', DL, '/api/callins'), ('DL district people', DL, '/api/callins/people'),
            ('DL district GEMIKO', DL, f'/api/callins/gemiko?level=district&id={DISTRICT}'),
            ('DL area bundle', DL, f'/api/callins?level=area&id={OWN_AREA}'),
            ('DL area people', DL, f'/api/callins/people?level=area&id={OWN_AREA}'),
            ('DL area GEMIKO', DL, f'/api/callins/gemiko?level=area&id={OWN_AREA}'),
            ('AP mission bundle, people week', AP, f'/api/callins?week={PEOPLE_WEEK}'),
            ('AP mission people, people week', AP, f'/api/callins/people?week={PEOPLE_WEEK}')):
        status, seconds = timed(user, path)
        print(f'  {name}: {seconds:.3f} s (HTTP {status})', flush=True)
        if name == 'AP mission bundle':
            check('mission bundle within about a second', status == 200 and seconds < 1.5, seconds)


def scrub(value, key=''):
    """Replace names of people and free text so a capture can back a stub API without personal data."""
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    if isinstance(value, str) and key in {'name', 'missionaries', 'text', 'weekly_action_plan', 'information_up_chain',
                                          'dl_update', 'dl_notes', 'zl_notes', 'zone_notes', 'notes', 'how_are_they_doing',
                                          'gemiko_support_plan', 'label', 'update_text'} | set(callins.PLAN_KEYS):
        return f'Sample {key.replace("_", " ")}'
    return value


if CAPTURE:
    for name, user in (('ZL', ZL), ('DL', DL), ('mission', AP)):
        status, body, seconds = call(user, '/api/callins')
        if status == 200:
            with open(os.path.join(CAPTURE, f'callins-{name}.json'), 'w', encoding='utf-8') as out:
                json.dump(scrub(body), out, ensure_ascii=False, indent=1)

print(f'{sum(results)} of {len(results)} checks passed')
sys.exit(0 if all(results) else 1)
