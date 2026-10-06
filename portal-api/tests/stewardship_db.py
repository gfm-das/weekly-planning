"""Stewardship (round 6, migration 032 and the portal-api chart/KPI changes) against a THROWAWAY database copy.

The rule: a ZL or STL sees and changes only their own zone, a DL only their own district, never other zones and never
mission-wide data or totals; the AP, the President and the Data Analysts see the whole mission.

Checks, with the real ZL, DL and AP accounts of the copy (each as the signed-in person: request.jwt.claims plus
SET LOCAL ROLE authenticated, as PostgREST and portal-api's user_db do it):
- database: no row outside their stewardship in the tables behind plans, people, companionships and missionaries; no
  mission-level check passes;
- database, the path 032 closes: the same ZL and DL with a stale app_role 'AP' (no current AP assignment) still reach
  nothing outside their stewardship, and cannot read other missionaries' language assignments (the account is changed
  only inside a transaction that is rolled back);
- portal-api: a pinned mission-level chart with the old "deck" audience shows a ZL only their zone and a DL only their
  district, a district chart shows a ZL only their zone's districts, and /internal/presentations/kpis gives them the
  totals of their zone or district, never the mission's;
- managers still see the whole mission (database and portal-api).
Prints counts and booleans only, never names or ids.

Refuses unless DATABASE_URL names a database containing "test" and STEWARDSHIP_TEST_THROWAWAY=yes. It adds one
presentation access rule for a made-up deck and deletes it at the end. Run inside a temporary portal-api container
on the test network (postgres must be a member of gfm_dashboard_reader, as migration 025 sets up):
  docker run --rm --network gfm-test-r2-net -e STEWARDSHIP_TEST_THROWAWAY=yes -e DATABASE_URL=... \\
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/stewardship_db.py [--expect-before-032]
With --expect-before-032 (a copy WITHOUT 032) the stale-AP checks are expected to FAIL: that run proves the test
sees the gap 032 closes.
"""
import json
import os
import sys
import uuid
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('STEWARDSHIP_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')
os.environ.setdefault('PORTAL_SERVICE_KEY', 'stewardship-db-test-key')
BEFORE_032 = '--expect-before-032' in sys.argv

import app as api  # noqa: E402

client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {detail}' if detail != '' else ''), flush=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def leader(role):
    found = sql('''SELECT up.id, up.missionary_id, la.zone_id, la.district_id,
                          coalesce(la.mission_id, z.mission_id, dz.mission_id) AS mission_id
                   FROM public.user_profiles up
                   JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id AND la.role = %s
                    AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                   LEFT JOIN public.zones z ON z.id = la.zone_id
                   LEFT JOIN public.districts d ON d.id = la.district_id LEFT JOIN public.zones dz ON dz.id = d.zone_id
                   WHERE up.active AND up.app_role NOT IN ('PRESIDENT', 'DATA_ADMIN')
                     AND NOT ('DATA_ADMIN' = ANY(up.additional_roles))
                   ORDER BY up.id LIMIT 1''', (role,))
    return found[0] if found else None


zl, dl, ap = leader('ZL'), leader('DL'), leader('AP')
print(f'fixture: ZL={bool(zl)} DL={bool(dl)} AP={bool(ap)}', flush=True)
if not (zl and dl and ap):
    sys.exit('This copy needs a ZL, a DL and an AP account.')
if dl['district_id'] and not dl['zone_id']:
    dl['zone_id'] = sql('SELECT zone_id FROM public.districts WHERE id=%s', (dl['district_id'],))[0]['zone_id']
mission = ap['mission_id']

# The stewardship's areas, and the tables whose rows carry an area (directly or through the plan).
OWN = {
    'zl': ('d.zone_id = %s', zl['zone_id']),
    'dl': ('a.district_id = %s', dl['district_id']),
}
TABLES = {
    'weekly_area_reports': 'SELECT area_id FROM public.weekly_area_reports',
    'weekly_planning_answers': '''SELECT w.area_id FROM public.weekly_planning_answers x
                                  JOIN public.weekly_area_reports w ON w.id = x.weekly_area_report_id''',
    'weekly_new_members': '''SELECT w.area_id FROM public.weekly_new_members x
                             JOIN public.weekly_area_reports w ON w.id = x.weekly_area_report_id''',
    'weekly_baptismal_date_friends': '''SELECT w.area_id FROM public.weekly_baptismal_date_friends x
                                        JOIN public.weekly_area_reports w ON w.id = x.weekly_area_report_id''',
    'new_members': 'SELECT area_id FROM public.new_members',
    'baptismal_date_person_area_assignments': 'SELECT area_id FROM public.baptismal_date_person_area_assignments',
    'companionships': 'SELECT area_id FROM public.companionships',
    'missionary_assignments': 'SELECT area_id FROM public.missionary_assignments',
    'call_in_planning_details': 'SELECT area_id FROM public.call_in_planning_details',
}


def as_user(conn, user_id):
    api.rows(conn, "SELECT set_config('request.jwt.claims', %s, true)",
             (json.dumps({'sub': str(user_id), 'role': 'authenticated'}),))
    api.rows(conn, 'SET LOCAL ROLE authenticated')


def database_view(conn, who, person):
    """Counts as the signed-in person: rows outside the stewardship per table, and the mission-level checks."""
    where, value = OWN[who]
    own = f'(SELECT a.id FROM public.areas a JOIN public.districts d ON d.id = a.district_id WHERE {where})'
    outside = {}
    for name, query in TABLES.items():
        outside[name] = api.rows(conn, f'SELECT count(*) AS n FROM ({query}) t WHERE t.area_id NOT IN {own}',
                                 (value,))[0]['n']
    outside['areas passing can_access_area'] = api.rows(conn, f'''SELECT count(*) AS n FROM public.areas a
        WHERE a.id NOT IN {own} AND public.can_access_area(a.id)''', (value,))[0]['n']
    outside['areas passing is_mission_manager_for_area'] = api.rows(conn, '''SELECT count(*) AS n FROM public.areas a
        WHERE public.is_mission_manager_for_area(a.id)''')[0]['n']
    outside['other missionaries\' language rows'] = api.rows(conn, '''SELECT count(*) AS n
        FROM public.missionary_language_assignments WHERE missionary_id IS DISTINCT FROM %s''',
                                                            (person['missionary_id'],))[0]['n']
    mission_ok = api.rows(conn, 'SELECT public.can_access_mission(%s) AS a, public.can_view_call_in(%s, %s) AS b',
                          (mission, 'mission', mission))[0]
    return outside, bool(mission_ok['a'] or mission_ok['b'])


# 1. The real ZL and DL, as they are.
for who, person in (('zl', zl), ('dl', dl)):
    with api.db() as conn:
        as_user(conn, person['id'])
        outside, mission_level = database_view(conn, who, person)
        conn.rollback()
    check(f'database: the {who.upper()} reads no row outside their {"zone" if who == "zl" else "district"}',
          not any(outside.values()), {k: v for k, v in outside.items() if v})
    check(f'database: no mission-level check passes for the {who.upper()}', not mission_level)

# 2. The path 032 closes: the same accounts with a stale app_role 'AP' (inside a transaction that is rolled back).
for who, person in (('zl', zl), ('dl', dl)):
    with api.db() as conn:
        api.rows(conn, "UPDATE public.user_profiles SET app_role = 'AP' WHERE id = %s", (person['id'],))
        as_user(conn, person['id'])
        outside, mission_level = database_view(conn, who, person)
        conn.rollback()
    leaked = {k: v for k, v in outside.items() if v}
    name = f'database (032): a {who.upper()} whose app_role still says AP reaches nothing outside their stewardship'
    if BEFORE_032:
        check('before 032, as expected, the stale AP role opens the mission: ' + name, bool(leaked), sorted(leaked))
    else:
        check(name, not leaked and not mission_level, leaked)

# 3. Managers still see the whole mission.
with api.db() as conn:
    total = api.rows(conn, 'SELECT count(*) AS n FROM public.weekly_area_reports')[0]['n']
    areas = api.rows(conn, '''SELECT count(*) AS n FROM public.areas a JOIN public.districts d ON d.id = a.district_id
                              JOIN public.zones z ON z.id = d.zone_id WHERE z.mission_id = %s''', (mission,))[0]['n']
    as_user(conn, ap['id'])
    seen = api.rows(conn, 'SELECT count(*) AS n FROM public.weekly_area_reports')[0]['n']
    managed = api.rows(conn, 'SELECT count(*) AS n FROM public.areas a WHERE public.is_mission_manager_for_area(a.id)')[0]['n']
    mission_ok = api.rows(conn, 'SELECT public.can_access_mission(%s) AS a', (mission,))[0]['a']
    conn.rollback()
check('database: the AP still reads every plan and manages every area of the mission',
      seen == total and managed == areas and mission_ok, (seen == total, managed == areas, mission_ok))


# 4. portal-api: database charts and the KPI totals.
def post(path, user_id, body):
    response = client.post(path, json={'user_id': str(user_id), **body},
                           headers={'X-Service-Key': os.environ['PORTAL_SERVICE_KEY']})
    return response.status_code, response.get_json(silent=True)


def kpi_totals(level, column, value, weeks):
    view = {'zone': 'kpi_zone_week', 'district': 'kpi_district_week', 'mission': 'kpi_mission_week'}[level]
    rows = sql(f'''SELECT sunday, sum(friends_found_actual) AS actual FROM dashboards.{view}
                   WHERE mission_id = %s AND {column} = %s AND sunday <= public.current_reporting_sunday()
                   GROUP BY sunday ORDER BY sunday DESC LIMIT %s''', (mission, value, weeks))
    return [None if r['actual'] is None else float(r['actual']) for r in reversed(rows)]


def as_numbers(values):
    return [None if v is None else float(v) for v in values]


slug = 'stewardship-test-' + uuid.uuid4().hex[:8]
mission_chart = {'measures': ['friends_found.actual'], 'level': 'mission', 'weeks': 8, 'audience': 'deck'}
district_chart = {'measures': ['friends_found.actual'], 'level': 'district', 'by': 'unit', 'weeks': 8, 'audience': 'deck'}
with api.db() as conn:
    api.rows(conn, '''INSERT INTO portal.presentation_access(mission_id,deck_slug,roles,zone_ids,district_ids,user_ids,everyone)
                      VALUES(%s,%s,%s,'{}','{}','{}'::uuid[],true)''', (mission, slug, ['DL', 'ZL', 'STL']))
try:
    status, body = post('/internal/presentations/chart-data', ap['id'], {'spec': mission_chart})
    check('portal-api: the AP gets the mission chart as written', status == 200 and body['meta']['level'] == 'mission'
          and not body['meta']['stewardship'], status)
    status, body = post('/internal/presentations/chart-data', ap['id'], {'spec': district_chart})
    ap_districts = body['meta']['units'] if status == 200 else 0
    check('portal-api: the AP gets the districts of the whole mission', status == 200 and not body['meta']['stewardship']
          and ap_districts >= 1, status)
    mission_totals = kpi_totals('mission', 'mission_id', mission, 12)
    # DLs keep the decks a manager shared with them (round 7, commit 14128db): their own district only.
    for who, person, level in (('zl', zl, 'zone'), ('dl', dl, 'district')):
        column, value = ('zone_id', person['zone_id']) if level == 'zone' else ('district_id', person['district_id'])
        status, body = post('/internal/presentations/chart-data', person['id'],
                            {'spec': mission_chart, 'deck': slug, 'pinned': True})
        check(f'portal-api: a mission chart ("deck" audience) shows the {who.upper()} only their {level}',
              status == 200 and body['meta']['level'] == level and body['meta']['stewardship']
              and body['meta']['units'] <= 1, (status, (body or {}).get('meta', {}).get('level')))
        status, body = post('/internal/presentations/chart-data', person['id'],
                            {'spec': district_chart, 'deck': slug, 'pinned': True})
        mine = sql(f'SELECT count(*) AS n FROM public.districts d WHERE d.{"zone_id" if level == "zone" else "id"} = %s',
                   (value,))[0]['n']
        check(f'portal-api: a district chart of the mission shows the {who.upper()} only districts of their stewardship',
              status == 200 and body['meta']['stewardship'] and body['meta']['units'] <= mine
              and len(body['table']['labels']) <= mine, (status, (body or {}).get('meta', {}).get('units'), mine))
        status, body = post('/internal/presentations/kpis', person['id'], {'weeks': 12})
        got = as_numbers([w['friends_found']['actual'] for w in body]) if status == 200 else None
        expected = kpi_totals(level, column, value, 12)
        check(f'portal-api: /kpis gives the {who.upper()} the totals of their {level}, not the mission totals',
              status == 200 and got == expected and (got != mission_totals or expected == mission_totals),
              (status, len(got or []), len(expected), got != mission_totals))
    status, body = post('/internal/presentations/kpis', ap['id'], {'weeks': 12})
    check('portal-api: /kpis still gives the AP the mission totals',
          status == 200 and as_numbers([w['friends_found']['actual'] for w in body]) == mission_totals, status)
finally:
    with api.db() as conn:
        api.rows(conn, 'DELETE FROM portal.presentation_access WHERE deck_slug=%s', (slug,))

print(f'\n{sum(results)} of {len(results)} checks passed', flush=True)
sys.exit(0 if all(results) else 1)
