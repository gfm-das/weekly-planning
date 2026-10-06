"""The mission glimpse at the top of the managers' Overview (GET /api/dashboard and the "glimpse" flag of
GET /api/overview, round 6) against a THROWAWAY database copy like live.

Creates a President and a Data Analyst staff account (main role PRESIDENT / DATA_ADMIN, no missionary link, home
mission 2, as DA Management's Staff page does), an Office staff account and the President of a second, temporary
mission, then goes through the real portal routes (sign-in check replaced in-process, as in staff_accounts_db.py;
database roles, row-level security and the helper functions are the real ones) and checks:
- the President gets the glimpse: finished weeks that have plans only (every such week before current_reporting_sunday(), the latest
  finished week last), 12 by default and up to 26, every open zone of the mission (mission-wide), never a closed one;
- the numbers equal the dashboards views of migration 018 (read as postgres) for every week, zone and key indicator:
  results, goals set that week, the goal set the week before, and the plan counts;
- an AP and the Data Analyst get exactly the same numbers; a second visit is read again and gives the same numbers;
- DL, ZL, STL, Office (staff account) and a missionary are refused (403) before any plan is read;
- row-level security's own question really decides (round 9: asked once per area, dashboard.areas_open_to): asked as
  the other mission's President, or as a DL, for mission 2 it opens none of mission 2's areas (the President) or only
  the DL's own district (the DL), and the numbers then count only those plans;
- /api/options and /api/overview say glimpse for the managers only; the Grafana routes are gone.
Prints ids, counts and timings only, never names. Everything it creates is removed at the end.

Refuses unless DATABASE_URL names a database containing "test" and GLIMPSE_TEST_THROWAWAY=yes. Run inside a temporary
portal-api container on the test network:
  docker run --rm --network gfm-test-r2-net -e GLIMPSE_TEST_THROWAWAY=yes -e DATABASE_URL=postgresql://postgres:...@gfm-test-r2-db:5432/gfm_test_x \
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/glimpse_db.py
"""
import base64
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('GLIMPSE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes accounts and needs a throwaway *test* database.')
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'test-only')

import app as api  # noqa: E402
import dashboard  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []
KEYS = [key for key, *_ in dashboard.INDICATORS]


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.fixture'


def call(user, path, method='GET'):
    started = time.time()
    response = client.open(path, method=method, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True), time.time() - started


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


@contextmanager
def as_user(user):
    """The caller's own connection, exactly as app.user_db() makes it (role authenticated, their claims)."""
    with api.db() as conn:
        api.rows(conn, "SELECT set_config('request.jwt.claims',%s,true)", (json.dumps({'sub': str(user), 'role': 'authenticated'}),))
        api.rows(conn, 'SET LOCAL ROLE authenticated')
        conn.cursor_factory = None
        yield conn


def leader(role):
    # Without the Data Analyst role, so a DL or ZL here has no manager rights (live's DL may have Office ticked: fine).
    found = sql('''SELECT DISTINCT c.user_id FROM public.current_user_context c JOIN public.user_profiles up ON up.id=c.user_id
                   WHERE c.user_active AND c.leadership_role=%s AND NOT ('DATA_ADMIN'=ANY(COALESCE(up.additional_roles,'{}')))
                   AND c.area_id IS NOT NULL ORDER BY c.user_id LIMIT 1''', (role,))
    return found[0]['user_id'] if found else None


created_users, created_missions = [], []


def staff(key, role, mission):
    user = str(uuid.uuid4())
    sql("""INSERT INTO auth.users(id,instance_id,aud,role,email)
           VALUES(%s,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s)""",
        (user, f'glimpse-db-{key}-{user[:8]}@example.invalid'))
    sql("""INSERT INTO public.user_profiles(id,missionary_id,app_role,active,display_name,home_mission_id)
           VALUES(%s,NULL,%s,true,%s,%s)""", (user, role, f'Glimpse test {key}', mission))
    created_users.append(user)
    return user


def expected_from_views(sundays):
    """The dashboards views (018), read as postgres: {sunday: {'mission': row, 'zones': {zone_id: row}}}."""
    cols = ','.join(f'{k}_actual,{k}_goal,{k}_previous_goal' for k in KEYS)
    mission = sql(f'''SELECT sunday,reports,submitted_reports,{cols} FROM dashboards.kpi_mission_week
                      WHERE mission_id=2 AND sunday=ANY(%s)''', (sundays,))
    zones = sql(f'''SELECT sunday,zone_id,reports,submitted_reports,{cols} FROM dashboards.kpi_zone_week
                    WHERE mission_id=2 AND sunday=ANY(%s)''', (sundays,))
    out = {s: {'mission': None, 'zones': {}} for s in sundays}
    for row in mission:
        out[row['sunday']]['mission'] = row
    for row in zones:
        out[row['sunday']]['zones'][row['zone_id']] = row
    return out


def num(value):
    return None if value is None else int(value)


def same_as_views(body):
    """Differences between the glimpse and the views, as a list of short strings (empty when equal)."""
    from datetime import date
    sundays = [date.fromisoformat(w['sunday']) for w in body['weeks']]
    views = expected_from_views(sundays)
    problems = []
    for week, sunday in zip(body['weeks'], sundays):
        view = views[sunday]
        m, vm = week['mission'], view['mission']
        if vm is None:
            problems.append(f'{sunday}: no mission row in the view')
            continue
        if (m['reports'], m['submitted']) != (num(vm['reports']), num(vm['submitted_reports'])):
            problems.append(f"{sunday} mission plans {m['reports']}/{m['submitted']} vs {vm['reports']}/{vm['submitted_reports']}")
        for k in KEYS:
            for part, col in (('actual', '_actual'), ('goal', '_goal'), ('previous_goal', '_previous_goal')):
                if m[part][k] != num(vm[k + col]):
                    problems.append(f'{sunday} mission {k} {part} {m[part][k]} vs {vm[k + col]}')
        # Every zone the view lists (plans this week, or goals set last week) and no other.
        got = {int(z): cell for z, cell in week['zones'].items()}
        if set(got) != set(view['zones']):
            problems.append(f'{sunday} zones {sorted(got)} vs {sorted(view["zones"])}')
        for zone_id, vz in view['zones'].items():
            cell = got.get(zone_id)
            if not cell:
                continue
            if cell['reports'] != num(vz['reports']) or cell['submitted'] != num(vz['submitted_reports']):
                problems.append(f'{sunday} zone {zone_id} plans')
            for k in KEYS:
                for part, col in (('actual', '_actual'), ('goal', '_goal'), ('previous_goal', '_previous_goal')):
                    if cell[part][k] != num(vz[k + col]):
                        problems.append(f'{sunday} zone {zone_id} {k} {part} {cell[part][k]} vs {vz[k + col]}')
    return problems


try:
    other_mission = sql("INSERT INTO public.missions(name) VALUES ('Glimpse test mission') RETURNING id")[0]['id']
    created_missions.append(other_mission)
    president = staff('president', 'PRESIDENT', 2)
    analyst = staff('analyst', 'DATA_ADMIN', 2)
    elsewhere = staff('elsewhere', 'PRESIDENT', other_mission)
    office = staff('office', 'OFFICE', 2)
    ap, zl, dl, stl = leader('AP'), leader('ZL'), leader('DL'), leader('STL')
    missionary = sql('''SELECT c.user_id FROM public.current_user_context c JOIN public.user_profiles up ON up.id=c.user_id
        WHERE c.user_active AND c.area_id IS NOT NULL AND c.leadership_role IS NULL
          AND up.app_role NOT IN ('AP','PRESIDENT','DATA_ADMIN','OFFICE') AND NOT ('DATA_ADMIN'=ANY(COALESCE(up.additional_roles,'{}')))
        ORDER BY c.user_id LIMIT 1''')
    missionary = missionary[0]['user_id'] if missionary else None
    print(f'fixture: AP={bool(ap)} ZL={bool(zl)} DL={bool(dl)} STL={bool(stl)} missionary={bool(missionary)}', flush=True)
    current = sql('SELECT public.current_reporting_sunday() AS s')[0]['s']
    # Round 12: only finished weeks that have at least one plan are listed.
    finished = sql('''SELECT sunday FROM public.reporting_weeks rw WHERE sunday < %s AND EXISTS
                      (SELECT 1 FROM public.weekly_area_reports war WHERE war.reporting_week_id = rw.id) ORDER BY sunday''', (current,))
    finished = [r['sunday'].isoformat() for r in finished]
    zones = sql('SELECT id FROM public.zones WHERE mission_id=2 AND active ORDER BY name')
    print(f'copy: {len(finished)} finished weeks (latest {finished[-1] if finished else None}), '
          f'week being reported {current}, {len(zones)} active zones', flush=True)

    # ---- The President --------------------------------------------------------------------------------------------
    status, body, cold = call(president, '/api/options')
    check('President: /api/options says glimpse (and Dashboards)', status == 200 and body['capabilities']['glimpse']
          and body['capabilities']['dashboards'] and body['role'] == 'PRESIDENT', (status, body and body.get('capabilities')))
    status, body, cold = call(president, '/api/dashboard')
    print(f'timing: President, 12 weeks, first visit {cold:.2f} s', flush=True)
    check('President: 200', status == 200, (status, body))
    weeks = [w['sunday'] for w in body['weeks']]
    check('President: finished weeks only, the latest finished week last',
          all(w < current.isoformat() for w in weeks) and weeks == finished[-12:], (weeks, finished[-12:]))
    check('President: 12 weeks by default (or all there are)', len(weeks) == min(12, len(finished)) and body['weeks_shown'] == 12,
          len(weeks))
    check('President: every open zone of the mission, and only open zones (round 12)',
          {z['id'] for z in zones} == {z['id'] for z in body['zones']}, (len(zones), len(body['zones'])))
    check('President: New people being taught first, the key indicator',
          body['indicators'][0] == {'key': 'friends_found', 'label': 'New people being taught', 'key_indicator': True})
    latest = body['weeks'][-1]['mission'] if body['weeks'] else {}
    check('President: the latest finished week has plans and results', latest.get('reports', 0) > 0
          and latest['actual']['friends_found'] is not None, latest.get('reports'))
    problems = same_as_views(body)
    check('President: every number equals the dashboards views (results, goals, goal set the week before, plans)',
          not problems, problems[:5])
    status, again, warm = call(president, '/api/dashboard')
    print(f'timing: President, 12 weeks, second visit {warm:.3f} s', flush=True)
    check('President: a second visit is read again, with the same numbers',
          status == 200 and again['read_at'] != body['read_at']
          and {k: v for k, v in again.items() if k != 'read_at'} == {k: v for k, v in body.items() if k != 'read_at'}, warm)
    status, body26, cold26 = call(president, '/api/dashboard?weeks=26')
    print(f'timing: President, 26 weeks, first visit {cold26:.2f} s', flush=True)
    check('President: 26 weeks (or all there are), the same numbers as the views',
          status == 200 and [w['sunday'] for w in body26['weeks']] == finished[-26:] and not same_as_views(body26),
          (status, len((body26 or {}).get('weeks', []))))
    check('President: 12-week answer is the tail of the 26-week one',
          body26['weeks'][-len(body['weeks']):] == body['weeks'] if body['weeks'] else True)
    check('President: 27 weeks is refused plainly', call(president, '/api/dashboard?weeks=27')[:2] ==
          (400, {'error': 'Choose between 1 and 26 weeks.'}))
    status, overview, took = call(president, '/api/overview')
    print(f'timing: President, /api/overview {took:.2f} s', flush=True)
    check('President: /api/overview says glimpse, with the mission\'s planning below it',
          status == 200 and overview.get('glimpse') is True and (overview.get('stewardship') or {}).get('scope') == 'mission'
          and (overview['stewardship']['total_areas'] or 0) > 0, (status, (overview or {}).get('glimpse')))

    # ---- An AP and the Data Analyst: the same numbers -------------------------------------------------------------
    strip = lambda b: {k: v for k, v in b.items() if k not in ('read_at', 'mission')}
    for name, user in (('AP', ap), ('Data Analyst', analyst)):
        if not user:
            print(f'note: no {name} on this copy', flush=True)
            continue
        status, other, took = call(user, '/api/dashboard')
        print(f'timing: {name}, 12 weeks, first visit {took:.2f} s', flush=True)
        check(f'{name}: 200 with exactly the President\'s numbers', status == 200 and strip(other) == strip(body), status)
        status, opts, _ = call(user, '/api/options')
        check(f'{name}: /api/options says glimpse and Dashboards',
              status == 200 and opts['capabilities']['glimpse'] and opts['capabilities']['dashboards'])
        status, overview, _ = call(user, '/api/overview')
        check(f'{name}: /api/overview says glimpse', status == 200 and overview.get('glimpse') is True,
              (status, (overview or {}).get('glimpse')))

    # ---- Everyone else: refused before any plan is read ----------------------------------------------------------
    for name, user in (('DL', dl), ('ZL', zl), ('STL', stl), ('Office staff account', office), ('Missionary', missionary)):
        if not user:
            print(f'note: no {name} on this copy', flush=True)
            continue
        with patch.object(dashboard, 'mission_dashboard', side_effect=AssertionError('read')) as reader:
            status, refused, _ = call(user, '/api/dashboard')
        check(f'{name}: refused (403), nothing read', status == 403 and not reader.called
              and 'mission glimpse' in (refused or {}).get('error', ''), (status, refused))
        status, opts, _ = call(user, '/api/options')
        check(f'{name}: /api/options says no glimpse', status == 200 and opts['capabilities']['glimpse'] is False)
        status, overview, _ = call(user, '/api/overview')
        check(f'{name}: /api/overview says no glimpse', status == 200 and overview.get('glimpse') is False,
              (status, (overview or {}).get('glimpse')))

    # ---- Row-level security decides (the same query, run for mission 2 as someone else) --------------------------
    with as_user(elsewhere) as conn:
        foreign_areas = dashboard.areas_open_to(conn, 2)
    with api.db() as conn:
        foreign = dashboard.mission_dashboard(conn, {'mission_id': 2}, 12, foreign_areas)
    check('RLS: the other mission\'s President may open none of mission 2\'s areas', foreign_areas == [], len(foreign_areas))
    check('RLS: the other mission\'s President finds none of mission 2\'s plans',
          foreign['weeks'] == [] and foreign['finished_weeks'] == 0,
          [w['mission']['reports'] for w in foreign['weeks']])
    status, own, _ = call(elsewhere, '/api/dashboard')
    check('The other mission\'s President: 200, only their own (empty) mission',
          status == 200 and all(w['mission']['reports'] == 0 for w in own['weeks'])
          and not own['zones'], (status, own and len(own.get('zones', []))))
    if dl:
        district = sql('''SELECT leadership_district_id AS d FROM public.current_user_scope
                          WHERE user_id=%s AND leadership_role='DL' LIMIT 1''', (dl,))[0]['d']
        with as_user(dl) as conn:
            dl_areas = dashboard.areas_open_to(conn, 2)
        own = [r['id'] for r in sql('SELECT id FROM public.areas WHERE district_id=%s ORDER BY id', (district,))]
        check('RLS: a DL may open exactly the areas of their own district', dl_areas == own, (len(dl_areas), len(own)))
        with api.db() as conn:
            dl_view = dashboard.mission_dashboard(conn, {'mission_id': 2}, 4, dl_areas)
        district_plans = sql('''SELECT count(*) AS n FROM public.weekly_area_reports war
            JOIN public.reporting_weeks rw ON rw.id=war.reporting_week_id JOIN public.areas a ON a.id=war.area_id
            WHERE a.district_id=%s AND rw.sunday=ANY(%s::date[])''', (district, [w['sunday'] for w in dl_view['weeks']]))[0]['n']
        seen = sum(w['mission']['reports'] for w in dl_view['weeks'])
        check('RLS: for a DL the numbers count only their own district\'s plans', seen == district_plans
              and seen < sum(w['mission']['reports'] for w in body['weeks'][-4:]), (seen, district_plans))

    # ---- Grafana is gone -------------------------------------------------------------------------------------------
    check('Grafana: POST /api/grafana/session is gone (404)', call(president, '/api/grafana/session', 'POST')[0] == 404)
    check('Grafana: GET /api/grafana/auth is gone (401 without sign-in, like any address)',
          client.get('/api/grafana/auth').status_code == 401)
finally:
    for user in created_users:
        sql('DELETE FROM public.user_profiles WHERE id=%s', (user,))
        sql('DELETE FROM auth.users WHERE id=%s', (user,))
    for mission in created_missions:
        sql('DELETE FROM public.missions WHERE id=%s', (mission,))
    left = sql("SELECT count(*) AS n FROM auth.users WHERE email LIKE 'glimpse-db-%%'")[0]['n']
    print(f'clean-up: {len(created_users)} test accounts and {len(created_missions)} test mission removed, {left} left', flush=True)

print(f'{sum(results)}/{len(results)} passed', flush=True)
sys.exit(0 if all(results) else 1)
