"""Main role plus additional roles (Data Analyst, Office) through the real portal routes, against a THROWAWAY database.

It changes user_profiles.additional_roles and app_role for a moment and adds one calendar event and one
announcement (all put back or deleted at the end), so it refuses to run unless DATABASE_URL names a database
containing "test" and ROLES_TEST_THROWAWAY=yes. Identity lookups are replaced in-process (as in
planning_people_db.py); database roles, row-level security and the SECURITY DEFINER checks are the real ones.

Run inside a temporary portal-api container, after migration 021:
  python tests/roles_db.py
On a copy WITHOUT migration 021, run it with --before-021: it then only checks that the portal works as before
(no additional roles; the missing column counts as empty).
"""
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('ROLES_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')
BEFORE_021 = '--before-021' in sys.argv
# Test-only key for this process: the internal presentation endpoints need it.
os.environ['PORTAL_SERVICE_KEY'] = 'roles-db-test-service-key'

import app as api  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    if callable(ok):
        try:
            ok = ok()
        except Exception as error:  # noqa: BLE001
            ok, detail = False, f'{type(error).__name__}: {error} {detail}'
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {str(detail)[:300]}' if detail != '' else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 600}) + '.fixture'


def call(user, method, path, body=None):
    response = client.open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True)


def internal(user, path, body=None):
    response = client.post(path, json={'user_id': str(user), **(body or {})},
                           headers={'X-Service-Key': os.environ['PORTAL_SERVICE_KEY']})
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def leader(role):
    found = sql('''SELECT DISTINCT user_id FROM public.current_user_context WHERE user_active AND leadership_role=%s
                   AND area_id IS NOT NULL ORDER BY user_id LIMIT 1''', (role,))
    return found[0]['user_id'] if found else None


ap, zl, dl = leader('AP'), leader('ZL'), leader('DL')
# A linked account in an area with no leadership assignment at all (main role Missionary).
plain = sql('''SELECT c.user_id FROM public.current_user_context c JOIN public.user_profiles up ON up.id=c.user_id
    WHERE c.user_active AND c.area_id IS NOT NULL AND c.leadership_role IS NULL
      AND up.app_role NOT IN ('AP','PRESIDENT','DATA_ADMIN','OFFICE')
      AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments la WHERE la.missionary_id=up.missionary_id
                      AND (la.end_date IS NULL OR la.end_date>=CURRENT_DATE))
    ORDER BY c.user_id LIMIT 1''')
plain = plain[0]['user_id'] if plain else None
print(f'fixture: AP={bool(ap)} ZL={bool(zl)} DL={bool(dl)} plain={bool(plain)}', flush=True)
if not all((ap, zl, dl, plain)):
    sys.exit('This copy needs an AP, a ZL, a DL and a linked missionary without leadership, each with an area.')

mission_areas = sql('''SELECT count(*) AS n FROM public.areas a JOIN public.districts d ON d.id=a.district_id
    JOIN public.zones z ON z.id=d.zone_id WHERE z.mission_id=(SELECT mission_id FROM public.current_user_context
    WHERE user_id=%s AND mission_id IS NOT NULL LIMIT 1)''', (dl,))[0]['n']
saved = {r['id']: r for r in sql('SELECT id::text AS id,app_role FROM public.user_profiles WHERE id=ANY(%s::uuid[])', ([str(dl), str(plain)],))}


def set_roles(user, additional=None, app_role=None):
    if additional is not None:
        sql('UPDATE public.user_profiles SET additional_roles=%s WHERE id=%s', (list(additional), str(user)))
    if app_role is not None:
        sql('UPDATE public.user_profiles SET app_role=%s WHERE id=%s', (app_role, str(user)))


def options(user, purpose=None):
    return call(user, 'GET', '/api/options' + (f'?purpose={purpose}' if purpose else ''))


# The "DL alone" checks need a DL without additional roles. On a copy of live Beta the DL account may have Office or
# Data Analyst ticked (it has Office since 27 Sep): take them away on this throwaway copy (the end does it again).
if not BEFORE_021:
    set_roles(dl, [])


created = {'events': [], 'announcements': []}
try:
    # ---- as before: one role each ------------------------------------------------------------------------------
    status, body = options(ap)
    check('AP: main role AP, manager, mission-wide targets', status == 200 and body['role'] == 'AP'
          and body['my_roles'] == ['AP'] and body['capabilities']['manager'] and body['capabilities']['dashboards']
          and len(body['areas']) == mission_areas and body['roles'] == api.ROLES, (status, body and body.get('capabilities')))
    status, body = options(zl)
    check('ZL: zone targets, Call-ins yes, Dashboards no', status == 200 and body['role'] == 'ZL'
          and len({a['zone_id'] for a in body['areas']}) == 1 and body['capabilities']['callins']
          and not body['capabilities']['dashboards'] and not body['capabilities']['calendar'], body and body.get('capabilities'))
    status, dl_body = options(dl)
    dl_districts = {a['district_id'] for a in (dl_body or {}).get('areas', [])}
    check('DL: district targets, label "DL"', status == 200 and dl_body['role'] == 'DL' and len(dl_districts) == 1
          and dl_body['role_label'] == 'DL' and not dl_body['capabilities']['manager'], dl_body and dl_body.get('role_label'))
    status, body = options(plain)
    check('Missionary: own area only, no editing', status == 200 and body['role'] == 'MISSIONARY' and len(body['areas']) == 1
          and not any(body['capabilities'][k] for k in ('manager', 'calendar', 'publish', 'dashboards', 'management', 'callins')),
          body and body.get('capabilities'))
    check('unknown ?purpose= is a 400 with a plain message', options(dl, 'everything') == (400, {'error': 'Choose calendar or announcements.'}))
    status, body = call(dl, 'GET', '/api/dashboard?weeks=1')
    check('DL alone: no Dashboards', status == 403, (status, body))
    status, body = internal(dl, '/internal/presentations/check', {'deck_slugs': []})
    check('DL alone: presentations role DL, cannot manage', status == 200 and body['role'] == 'DL' and body['can_manage'] is False
          and body['roles'] == ['DL'], body)
    status, body = call(dl, 'GET', '/api/overview')
    check('DL alone: overview stewardship is the district', status == 200 and body['stewardship']['scope'] == 'district'
          and body['assignment']['roles'] == ['DL'], (status, body and body.get('stewardship', {}).get('scope')))

    for name, user, role in (('AP', ap, 'AP'), ('ZL', zl, 'ZL'), ('DL', dl, 'DL')):
        status, body = call(user, 'GET', '/api/callins')
        check(f'Call-ins still open for the {name} (role {role})', status == 200 and body['role'] == role, (status, body and body.get('role')))

    if BEFORE_021:
        mine = [options(u)[1] for u in (ap, zl, dl, plain)]
        check('no migration 021: nobody has additional roles', all(b['my_roles'] == [b['role']] for b in mine))
        print(f'{sum(results)} of {len(results)} checks passed')
        sys.exit(0 if all(results) else 1)

    # ---- DL who also works in the Office ------------------------------------------------------------------------
    set_roles(dl, ['OFFICE'])
    status, body = options(dl, 'calendar')
    check('DL + Office: calendar targets the whole mission', status == 200 and len(body['areas']) == mission_areas
          and body['capabilities']['calendar'] and body['role_label'] == 'DL · Office', body and body.get('role_label'))
    status, body = options(dl)
    check('DL + Office: announcements target the whole mission', status == 200
          and len(body['areas']) == mission_areas and body['capabilities']['publish']
          and not body['capabilities']['manager'], len((body or {}).get('areas', [])))
    other_zone = sql('''SELECT z.id FROM public.zones z WHERE z.mission_id=(SELECT mission_id FROM public.current_user_context
        WHERE user_id=%s AND mission_id IS NOT NULL LIMIT 1) AND z.id NOT IN (SELECT d.zone_id FROM public.districts d
        WHERE d.id=ANY(%s)) ORDER BY z.id LIMIT 1''', (dl, list(dl_districts)))[0]['id']
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    event = {'title': 'zz-roles-test office meeting', 'description': '', 'starts_at': start.isoformat(),
             'ends_at': (start + timedelta(hours=1)).isoformat(), 'zone_ids': [other_zone], 'roles': ['OFFICE'],
             'reminder_minutes': 30}
    status, body = call(dl, 'POST', '/api/events', event)
    if status == 200:
        created['events'].append(body['event']['id'])
    check('DL + Office: may add an event for another zone', status == 200, (status, body))
    status, body = call(dl, 'POST', '/api/announcements', {'title': 'zz-roles-test', 'body': 'Test', 'zone_ids': [other_zone]})
    if status == 200:
        created['announcements'].append(body['announcement']['id'])
    check('DL + Office: may publish an announcement for another zone', status == 200, (status, body))
    status, body = call(dl, 'GET', f'/api/events?start={(start - timedelta(days=1)).isoformat().replace("+", "%2B")}')
    check('DL + Office: the calendar says "can edit"', status == 200 and body['can_edit'], (status, body and body.get('can_edit')))
    status, body = call(ap, 'POST', '/api/events', dict(event, title='zz-roles-test office only', zone_ids=[]))
    if status == 200:
        created['events'].append(body['event']['id'])
        occurrence = start.isoformat().replace('+', '%2B')
        status, body = call(ap, 'GET', f"/api/events/{body['event']['id']}/attendance?occurrence={occurrence}")
        listed = {str(u['user_id']) for u in (body or {}).get('users', [])}
        check('attendance list of an Office event: the DL who also works in the office, not the DL alone',
              status == 200 and str(dl) in listed and str(zl) not in listed, (status, len(listed)))
    else:
        check('AP may add an Office event', False, (status, body))
    status, body = call(dl, 'GET', '/api/dashboard?weeks=1')
    check('DL + Office: still no Dashboards', status == 403, (status, body))

    # ---- DL who is also the Data Analyst ------------------------------------------------------------------------
    set_roles(dl, ['DATA_ADMIN'])
    status, body = options(dl)
    check('DL + Data Analyst: manager rights, main role still DL', status == 200 and body['role'] == 'DL'
          and body['my_roles'] == ['DL', 'DATA_ADMIN'] and body['role_label'] == 'DL · Data Analyst'
          and all(body['capabilities'][k] for k in ('manager', 'calendar', 'publish', 'dashboards', 'management', 'callins'))
          and len(body['areas']) == mission_areas, body and body.get('capabilities'))
    status, body = call(dl, 'GET', '/api/dashboard?weeks=1')
    check('DL + Data Analyst: the glimpse numbers (as Dashboards)', status == 200 and len(body['weeks']) == 1, (status, str(body)[:200]))
    status, body = internal(dl, '/internal/presentations/check', {'deck_slugs': []})
    check('DL + Data Analyst: presentations role DL, can manage', status == 200 and body['role'] == 'DL'
          and body['can_manage'] is True and body['roles'] == ['DL', 'DATA_ADMIN'], body)
    status, body = call(dl, 'GET', '/api/overview')
    check('DL + Data Analyst: overview stewardship is the mission', status == 200 and body['stewardship']['scope'] == 'mission'
          and body['assignment']['role_label'] == 'DL · Data Analyst' and body['mission_focus']['can_edit'],
          (status, body and body.get('stewardship', {}).get('scope')))

    # ---- Office alone and Data Analyst alone ---------------------------------------------------------------------
    set_roles(dl, [])
    set_roles(plain, ['OFFICE'])
    status, body = options(plain, 'calendar')
    check('Missionary + Office: calendar and announcement publishing for the whole mission', status == 200
          and len(body['areas']) == mission_areas and body['capabilities'] == {
              'manager': False, 'calendar': True, 'publish': True, 'dashboards': False, 'management': False,
              'callins': False, 'presentations': False, 'glimpse': False, 'archetypes': False},
          body and body.get('capabilities'))
    status, body = call(plain, 'POST', '/api/announcements', {'title': 'zz-roles-test', 'body': 'Test'})
    if status == 200:
        created['announcements'].append(body['announcement']['id'])
    check('Missionary + Office: may publish a mission-wide announcement', status == 200, (status, body))
    status, body = call(plain, 'GET', '/api/dashboard?weeks=1')
    check('Missionary + Office: no Dashboards', status == 403, (status, body))
    status, body = internal(plain, '/internal/presentations/kpis', {'weeks': 2})
    check('Missionary + Office: no presentation charts', status == 403, (status, body))
    set_roles(plain, ['DATA_ADMIN'])
    status, body = call(plain, 'POST', '/api/announcements', {'title': 'zz-roles-test mission', 'body': 'Test'})
    if status == 200:
        created['announcements'].append(body['announcement']['id'])
    check('Missionary + Data Analyst: may publish to the whole mission', status == 200, (status, body))
    status, body = internal(plain, '/internal/presentations/kpis', {'weeks': 2})
    check('Missionary + Data Analyst: presentation charts', status == 200 and isinstance(body, list), status)
    set_roles(plain, [])
    status, body = call(plain, 'GET', '/api/dashboard?weeks=1')
    check('Data Analyst removed: Dashboards refused again at once', status == 403, (status, body))

    # ---- STL: presentations yes, Call-ins and plan unlocking no (checked at the database) --------------------------
    stl_zone = sql('SELECT zone_id FROM public.current_user_context WHERE user_id=%s AND zone_id IS NOT NULL LIMIT 1', (plain,))[0]['zone_id']
    sql('''INSERT INTO public.leadership_assignments(missionary_id,role,zone_id,start_date)
           SELECT missionary_id,'STL',%s,CURRENT_DATE-1 FROM public.user_profiles WHERE id=%s''', (stl_zone, str(plain)))
    set_roles(plain, app_role='STL')
    status, body = options(plain)
    check('STL: zone targets for announcements, no Call-ins', status == 200 and body['role'] == 'STL'
          and body['capabilities']['publish'] and not body['capabilities']['callins']
          and body['capabilities']['presentations'], body and body.get('capabilities'))
    status, body = internal(plain, '/internal/presentations/kpis', {'weeks': 2})
    check('STL: presentation charts allowed', status == 200, status)
    with api.db() as conn:
        api.rows(conn, "SELECT set_config('request.jwt.claims',%s,true)", (json.dumps({'sub': str(plain), 'role': 'authenticated'}),))
        api.rows(conn, 'SET LOCAL ROLE authenticated')
        zone_ok = api.rows(conn, 'SELECT public.can_access_zone(%s) AS ok', (stl_zone,))[0]['ok']
    check('STL: the database refuses the zone Call-ins (can_access_zone)', zone_ok is False, zone_ok)
finally:
    sql('DELETE FROM portal.events WHERE id=ANY(%s::uuid[])', (created['events'],))
    sql('DELETE FROM portal.announcements WHERE id=ANY(%s::uuid[])', (created['announcements'],))
    if not BEFORE_021:
        sql('''DELETE FROM public.leadership_assignments WHERE role='STL' AND start_date=CURRENT_DATE-1
               AND missionary_id=(SELECT missionary_id FROM public.user_profiles WHERE id=%s)''', (str(plain),))
        for user, row in saved.items():
            sql("UPDATE public.user_profiles SET app_role=%s,additional_roles='{}' WHERE id=%s", (row['app_role'], user))

print(f'{sum(results)} of {len(results)} checks passed')
sys.exit(0 if all(results) else 1)
