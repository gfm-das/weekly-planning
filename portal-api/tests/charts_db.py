"""Database charts (charts.py, migration 025) against a THROWAWAY database copy.

Refuses unless DATABASE_URL names a database containing "test" and CHARTS_TEST_THROWAWAY=yes. Apply migration 025
first (as supabase_admin, like live). Checks, as the real portal-api does it (postgres, then SET LOCAL ROLE
gfm_dashboard_reader in a read-only transaction):
- every measure at every level answers, each in under a second (104 weeks, the most a chart can ask for);
- area people numbers below 3 are hidden, and the unsuppressed view is not readable by the reader;
- gfm_dashboard_reader cannot read the people tables;
- the sums add up (district and zone, zone and mission) for a few measures;
- stewardship: a real DL gets only their district, a ZL their zone, an AP the mission (whatever the audience);
- a viewer needs a pinned chart of a deck shared with them (a presentation_access row written in the copy).
Prints counts and ids only, never names.

Run inside a temporary portal-api container on the test network:
  python tests/charts_db.py
"""
import os
import sys
import time
import uuid
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('CHARTS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')
os.environ.setdefault('PORTAL_SERVICE_KEY', 'charts-db-test-key')

import psycopg2  # noqa: E402
import app as api  # noqa: E402
import charts  # noqa: E402

client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' else ''), flush=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def post(path, user_id, body):
    started = time.time()
    response = client.post(path, json={'user_id': str(user_id), **body},
                           headers={'X-Service-Key': os.environ['PORTAL_SERVICE_KEY']})
    return response.status_code, response.get_json(silent=True), time.time() - started


def user(role):
    found = sql('''SELECT user_id FROM public.current_user_context WHERE user_active AND leadership_role=%s
                   ORDER BY user_id LIMIT 1''', (role,))
    return found[0]['user_id'] if found else None


ap, zl, dl = user('AP'), user('ZL'), user('DL')
print(f'fixture: AP={bool(ap)} ZL={bool(zl)} DL={bool(dl)}', flush=True)
if not ap:
    sys.exit('No AP in this copy.')

# 1. Every measure at every level, 104 weeks, under a second each.
slowest = (0, '')
failures = []
times = []
for level in charts.LEVELS:
    for m in charts.MEASURES:
        # Week by week an area chart needs chosen areas (at most 40 lines); one bar per area needs none.
        spec = {'measures': [m], 'level': level, 'weeks': 104, 'audience': 'deck', 'by': 'unit' if level == 'area' else 'week'}
        status, body, took = post('/internal/presentations/chart-data', ap, {'spec': spec})
        if status != 200 or not body.get('table', {}).get('labels'):
            failures.append((level, m, status, (body or {}).get('error')))
        slowest = max(slowest, (took, f'{level} {m}'))
        times.append(took)
times.sort()
check('every measure at every level answers (104 weeks)', not failures, failures[:5])
check('each in under a second', slowest[0] < 1.0,
      f'{len(times)} charts, median {times[len(times) // 2]:.2f} s, slowest {slowest[0]:.2f} s ({slowest[1]})')

status, body, _ = post('/internal/presentations/chart-data', ap, {'spec': {'measures': ['friends_found.actual'], 'level': 'area', 'weeks': 4}})
check('week by week for every area is refused with a clear sentence', status == 400 and 'lines' in body['error'], (status, (body or {}).get('error')))

# Several sources at once, by unit, with transforms.
for extra in ({'by': 'unit', 'transform': 'pct_of_goal', 'measures': ['baptismal_dates.actual', 'baptismal_dates.previous_goal']},
              {'transform': 'rolling4', 'measures': ['friends_found.actual', 'new_members.total']},
              {'by': 'unit', 'transform': 'per_area', 'measures': ['sacrament_attendance.actual', 'high_potentials.total'], 'sort': 'desc', 'top': 5}):
    spec = {'level': 'zone', 'weeks': 26, 'audience': 'deck', **extra}
    status, body, took = post('/internal/presentations/chart-data', ap, {'spec': spec})
    check(f'zone chart {extra.get("transform")} answers in time', status == 200 and took < 1.0, f'{status} {took:.2f} s {(body or {}).get("error", "")}')

# 2. Suppression and the reader's rights (straight SQL, as the reader).
conn = api.connect()
try:
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute('SET ROLE gfm_dashboard_reader')
        cur.execute('''SELECT count(*) AS n FROM dashboards.people_area_week WHERE new_members < 3 OR new_members_at_church < 3
                       OR baptismal_date_friends < 3 OR high_potentials < 3 OR high_potentials_at_church < 3''')
        check('no area number below 3 is shown', cur.fetchone()['n'] == 0)
        cur.execute('SELECT count(*) AS shown, count(*) FILTER (WHERE new_members IS NULL) AS hidden FROM dashboards.people_area_week')
        counts = cur.fetchone()
        check('area rows exist and small ones are hidden', counts['shown'] > 0 and counts['hidden'] > 0, dict(counts))
    conn.rollback()
    for table in ('public.weekly_new_members', 'public.weekly_baptismal_date_friends', 'public.weekly_high_potential_friends',
                  'public.new_members', 'public.baptismal_date_people', 'public.new_members_clean',
                  'dashboards.people_area_week_counts'):
        with conn.cursor() as cur:
            cur.execute('SET ROLE gfm_dashboard_reader')
            try:
                cur.execute(f'SELECT 1 FROM {table} LIMIT 1')
                refused = False
            except (psycopg2.errors.InsufficientPrivilege, psycopg2.errors.UndefinedTable):  # 029 drops new_members_clean
                refused = True
        conn.rollback()
        check(f'the reader cannot read {table}', refused)
finally:
    conn.close()

# Compare hidden and shown against the unsuppressed counts (as postgres).
mismatch = sql('''SELECT count(*) AS n FROM dashboards.people_area_week s JOIN dashboards.people_area_week_counts c
    USING (reporting_week_id, area_id)
    WHERE (c.new_members >= 3) <> (s.new_members IS NOT NULL)
       OR (c.new_members_at_church >= 3 AND c.new_members - c.new_members_at_church >= 3) <> (s.new_members_at_church IS NOT NULL)
       OR (s.new_members IS NOT NULL AND s.new_members <> c.new_members)''')[0]['n']
check('area suppression follows the rule exactly (3 or more, and 3 or more not)', mismatch == 0, mismatch)
small = sql('''SELECT count(*) AS n FROM dashboards.people_area_week_counts WHERE new_members BETWEEN 1 AND 2''')[0]['n']
check('the copy has small area counts to hide', small > 0, small)

# 3. The sums add up.
bad = sql('''SELECT count(*) AS n FROM dashboards.people_mission_week m JOIN (SELECT reporting_week_id, mission_id,
    sum(new_members_at_church) a, sum(baptismal_date_friends_next_4_weeks) b FROM dashboards.people_district_week GROUP BY 1, 2) d
    USING (reporting_week_id, mission_id) WHERE (m.new_members_at_church, m.baptismal_date_friends_next_4_weeks) IS DISTINCT FROM (d.a::bigint, d.b::bigint)''')[0]['n']
check('districts add up to the mission (people)', bad == 0, bad)
bad = sql('''SELECT count(*) AS n FROM dashboards.kpi_mission_week m JOIN (SELECT reporting_week_id, mission_id,
    sum(baptismal_dates_actual) a, sum(areas_reporting) r FROM dashboards.kpi_district_week GROUP BY 1, 2) d
    USING (reporting_week_id, mission_id) WHERE (m.baptismal_dates_actual, m.areas_reporting) IS DISTINCT FROM (d.a::bigint, d.r::bigint)''')[0]['n']
check('districts add up to the mission (key indicators, areas reporting)', bad == 0, bad)

# 4. Stewardship with real leaders; 5. pinning. The copy gets a deck rule for DLs and ZLs.
slug = 'charts-db-test-' + uuid.uuid4().hex[:8]
mission = sql('SELECT mission_id FROM public.current_user_context WHERE user_id=%s LIMIT 1', (ap,))[0]['mission_id']
spec = {'measures': ['friends_found.actual'], 'level': 'zone', 'by': 'unit', 'weeks': 8, 'audience': 'stewardship'}
for who, uid, level in (('AP', ap, 'zone'), ('ZL', zl, 'zone'), ('DL', dl, 'district')):
    if not uid:
        continue
    status, body, _ = post('/internal/presentations/chart-data', uid, {'spec': spec, 'deck': slug, 'pinned': True})
    if who == 'AP':
        check('an AP sees every zone', status == 200 and body['meta']['level'] == 'zone' and not body['meta']['stewardship']
              and len(body['table']['labels']) > 1, (status, (body or {}).get('meta')))
        continue
    check(f'a {who} is refused without a deck rule', status == 403, status)
with api.db() as conn:
    api.rows(conn, '''INSERT INTO portal.presentation_access(mission_id,deck_slug,roles,zone_ids,district_ids,user_ids,everyone)
                      VALUES(%s,%s,%s,'{}','{}','{}'::uuid[],false)''', (mission, slug, ['DL', 'ZL']))
try:
    if zl:
        status, body, _ = post('/internal/presentations/chart-data', zl, {'spec': spec, 'deck': slug, 'pinned': True})
        zones = sql('''SELECT DISTINCT leadership_zone_id AS id FROM public.current_user_scope WHERE user_id=%s
                       AND leadership_role='ZL' ''', (zl,))
        check('a ZL sees only their zone', status == 200 and body['meta']['stewardship'] and body['meta']['level'] == 'zone'
              and len(body['table']['labels']) == len(zones), (status, (body or {}).get('meta', {}).get('units'), len(zones)))
        status, _, _ = post('/internal/presentations/chart-data', zl, {'spec': spec, 'deck': slug, 'pinned': False})
        check('a ZL is refused a chart that is not pinned', status == 403, status)
    if dl:
        # DLs keep the decks a manager shared with them (round 7, commit 14128db), with only their own district.
        status, body, _ = post('/internal/presentations/chart-data', dl, {'spec': spec, 'deck': slug, 'pinned': True})
        check('a DL the deck is shared with sees only their own district', status == 200
              and body['meta']['stewardship'] and body['meta']['level'] == 'district'
              and len(body['table']['labels']) <= 1, (status, (body or {}).get('meta', {}).get('level')))
        status, _, _ = post('/internal/presentations/chart-catalog', dl, {})
        check('the catalogue is not for DLs', status == 403, status)
finally:
    with api.db() as conn:
        api.rows(conn, 'DELETE FROM portal.presentation_access WHERE deck_slug=%s', (slug,))

status, body, took = post('/internal/presentations/chart-catalog', ap, {})
check('the catalogue answers an AP', status == 200 and len(body['measures']) == len(charts.MEASURES) and body['weeks']['available'],
      f'{status} {took:.2f} s')

print(f'\n{sum(results)} of {len(results)} checks passed', flush=True)
sys.exit(0 if all(results) else 1)
