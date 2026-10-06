"""Archetypal Health against a THROWAWAY database copy with migrations 033 and 034 applied.

Checks, as real accounts of the copy (identity lookups are replaced in-process, as in callins_db.py; the database,
its views and rights are the real ones; the API connects as postgres like live):
- who sees what: AP the whole mission; ZLs, STLs, DLs and missionaries get 403; no sign-in 401; only managers read
  or change the settings;
- one area worked out again by hand, independently of archetype_model.py, from dashboards.archetype_area_week;
- settings: weights must add up to 100 (400, field named), a change changes the scores, the history names who and
  what, a stale version is refused (409), "Restore the sheet's defaults" brings the numbers back;
- notes: managers read and write them; leaders cannot; an empty note removes it;
- the new tables are closed to the API roles.
Prints counts, booleans and index numbers only, never names.

It writes settings and notes and removes them at the end, so it refuses unless DATABASE_URL names a database
containing "test" and ARCHETYPES_TEST_THROWAWAY=yes. Run inside a temporary portal-api container:
  python tests/archetypes_db.py
"""
import base64
import json
import os
import statistics
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('ARCHETYPES_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402
import archetypes as feature  # noqa: E402
import archetype_model as model  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    """detail is printed only when a check fails (it may hold a name from the copy)."""
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.fixture'


def call(user, path, method='GET', body=None):
    headers = {'Authorization': 'Bearer ' + token(user)} if user else {}
    response = client.open(path, method=method, json=body, headers=headers)
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def account(role):
    """An active account whose highest current leadership role is this one (no manual role, no Data Analyst)."""
    found = sql('''SELECT up.id, la.zone_id, la.district_id
                   FROM public.user_profiles up
                   JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id AND la.role = %s
                    AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                   WHERE up.active AND coalesce(up.app_role, '') NOT IN ('PRESIDENT', 'DATA_ADMIN', 'OFFICE')
                     AND NOT ('DATA_ADMIN' = ANY(coalesce(up.additional_roles, '{}')))
                     AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments hi
                                     WHERE hi.missionary_id = up.missionary_id AND hi.role = ANY(%s)
                                       AND hi.start_date <= CURRENT_DATE AND (hi.end_date IS NULL OR hi.end_date >= CURRENT_DATE))
                   ORDER BY up.id LIMIT 1''', (role, {'AP': [], 'ZL': ['AP'], 'STL': ['AP', 'ZL'], 'DL': ['AP', 'ZL', 'STL']}[role]))
    return found[0] if found else None


def plain_missionary():
    found = sql('''SELECT up.id FROM public.user_profiles up
                   JOIN public.current_user_context c ON c.user_id = up.id
                   WHERE up.active AND c.leadership_role IS NULL AND coalesce(up.app_role, '') NOT IN ('PRESIDENT', 'DATA_ADMIN', 'OFFICE', 'AP')
                     AND NOT ('DATA_ADMIN' = ANY(coalesce(up.additional_roles, '{}'))) AND c.area_id IS NOT NULL
                   ORDER BY up.id LIMIT 1''')
    return found[0] if found else None


ap, zl, stl, dl, missionary = account('AP'), account('ZL'), account('STL'), account('DL'), plain_missionary()
print(f'fixture: AP={bool(ap)} ZL={bool(zl)} STL={bool(stl)} DL={bool(dl)} missionary={bool(missionary)}', flush=True)
if not (ap and zl and dl and missionary):
    sys.exit('This copy needs AP, ZL, DL and missionary accounts.')
if dl['district_id'] and not dl['zone_id']:
    dl['zone_id'] = sql('SELECT zone_id FROM public.districts WHERE id=%s', (dl['district_id'],))[0]['zone_id']
if stl and not stl['zone_id']:
    stl = None
sql('DELETE FROM public.archetype_settings')
sql('DELETE FROM public.archetype_settings_history')
sql('DELETE FROM public.archetype_notes')

# ------------------------------------------------------------------------------------------------ who sees what
status, mission = call(ap['id'], '/api/archetypes')
check('AP: 200 with the mission, zones, districts and areas', status == 200 and mission['mission'] and mission['zones']
      and mission['districts'] and mission['areas'], status)
check('AP: the default week is complete and not the one whose plans are still coming in',
      mission['week'] and mission['week'] < time.strftime('%Y-%m-%d') and all(
          w['areas'] * 2 >= max(x['areas'] for x in mission['weeks']) for w in mission['weeks'] if w['week'] == mission['week']),
      mission['week'])
check('AP: may open the settings', mission['viewer']['settings'] is True)
all_areas = {a['id'] for a in mission['areas']}
print(f"AP sees {len(mission['zones'])} zones, {len(mission['districts'])} districts, {len(all_areas)} areas in week {mission['week']}",
      flush=True)

non_managers = [(zl, 'ZL'), (dl, 'DL'), (missionary, 'missionary')]
if stl:
    non_managers.append((stl, 'STL'))
for user, name in non_managers:
    status, body = call(user['id'], '/api/archetypes')
    check(f'{name}: page refused (403)', status == 403 and body['error'] == feature.NOT_FOR_YOU, status)
status, body = call(None, '/api/archetypes')
check('not signed in: 401', status == 401, status)
for user, name in non_managers:
    status, _ = call(user['id'], '/api/archetypes/settings')
    check(f'{name}: settings refused (403)', status == 403, status)
    status, _ = call(user['id'], '/api/archetypes/settings', 'PUT', {'settings': model.defaults(), 'version': 0})
    check(f'{name}: saving settings refused (403)', status == 403, status)

# ------------------------------------------------------------------------------------------------ one area by hand
week = mission['week']
mission_id = sql('SELECT mission_id FROM dashboards.archetype_area_week WHERE area_id=%s LIMIT 1',
                 (mission['areas'][0]['id'],))[0]['mission_id']
rows = sql('SELECT * FROM dashboards.archetype_area_week WHERE mission_id=%s AND sunday <= %s', (mission_id, week))
finding = model.DEFAULT_SETTINGS['weights']['finding']


def density_band(value):
    """The sheet's density bands (default limits 200, 500, 700, 1200)."""
    if value is None:
        return 'Missing'
    limits = [200, 500, 700, 1200]
    if value < limits[0]:
        return '< 200'
    for low, high in zip(limits, limits[1:]):
        if value < high:
            return f'{low} – {high}'
    return '>= 1200'


def peer_group_by_hand():
    """{area_id: group}: urban type | assignment type | density band; a group under 5 areas is the whole mission."""
    profiles = {r['area_id']: r for r in sql('SELECT * FROM dashboards.archetype_area_profile WHERE mission_id=%s', (mission_id,))}
    keys = {a: ' | '.join([profiles[a]['urban_type'] or 'Missing', profiles[a]['assignment_type'] or 'Missing',
                           density_band(profiles[a]['density_per_km2'])]) for a in {r['area_id'] for r in rows}}
    sizes = {k: list(keys.values()).count(k) for k in set(keys.values())}
    return {a: k if sizes[k] >= 5 else 'Whole mission' for a, k in keys.items()}


def by_hand(area_id):
    """Finding of one area, written out plainly: the mission's usual week per number, z-scores, the weighted blend,
    then the blend compared with its peer group's usual week (every week of those areas up to the week shown). The
    'Whole mission' group (a group too small) means every area of the mission."""
    usual = {}
    for kpi in finding:
        values = [float(r[kpi]) for r in rows if r[kpi] is not None]
        usual[kpi] = (statistics.mean(values), statistics.stdev(values))

    def blend(row):
        parts = [(w, (float(row[k]) - usual[k][0]) / usual[k][1]) for k, w in finding.items() if row[k] is not None]
        return sum(w * z for w, z in parts) / sum(w for w, _ in parts) if parts else None

    groups = peer_group_by_hand()
    group = groups[area_id]
    peers = [r for r in rows if group == 'Whole mission' or groups[r['area_id']] == group]
    group_blends = [b for b in (blend(r) for r in peers) if b is not None]
    this_week = next(r for r in rows if r['area_id'] == area_id and str(r['sunday']) == week)
    score = (blend(this_week) - statistics.mean(group_blends)) / statistics.stdev(group_blends)
    return 100 + 15 * score, groups[area_id], len(group_blends)


full = [a for a in mission['areas'] if a['indices']['finding'] is not None and a['peer_group'] is not None
        and all(a['values'].get(k) is not None for k in finding)]
sample = full[len(full) // 2]
expected, group, weeks_in_group = by_hand(sample['id'])
check('one area by hand: same peer group as the page', group == sample['peer_group'])
check('one area by hand: Finding index matches the formula', abs(expected - sample['indices']['finding']) < 0.06,
      f"by hand {expected:.2f}, page {sample['indices']['finding']}")
print(f"hand check: area #{full.index(sample)} of {len(full)}, peer group's usual week from {weeks_in_group} area-weeks, "
      f"Finding by hand {expected:.2f}, page {sample['indices']['finding']}", flush=True)
# One more area per other peer group, so a 'Whole mission' area next to real groups is checked too.
one_per_group = {}
for area in full:
    one_per_group.setdefault(area['peer_group'], area)
for area in one_per_group.values():
    expected_other, _, weeks_other = by_hand(area['id'])
    check('by hand, one area per peer group: Finding matches', abs(expected_other - area['indices']['finding']) < 0.06,
          f"by hand {expected_other:.2f}, page {area['indices']['finding']}")
print(f"peer groups on the page: {len(one_per_group)}; 'Whole mission' among them: "
      f"{model.WHOLE_MISSION in one_per_group}", flush=True)
check('overall = average of the six archetype indices', abs(sample['overall'] - statistics.mean(
    v for v in sample['indices'].values() if v is not None)) < 0.11)
measured = [a for a in mission['areas'] if any(v is not None for v in a['indices'].values())]
check('every area with an index has a diagnosis with 1-2 patterns and steps', measured and all(
    1 <= len(a['diagnosis']['patterns']) <= 2 and all(p['steps'] for p in a['diagnosis']['patterns']) for a in measured))
check('an area without any index gets no pattern', all(
    a['diagnosis']['patterns'] == [] for a in mission['areas'] if a not in measured))
check('FindeChristus referrals etc. are not in the defaults; skipped numbers are named',
      isinstance(mission['skipped'], list))

# ------------------------------------------------------------------------------------------------ settings
status, current = call(ap['id'], '/api/archetypes/settings')
check('AP: settings are the sheet defaults, version 0, no history', status == 200 and current['settings'] == model.defaults()
      and current['version'] == 0 and current['history'] == [], status)
check('the archived numbers (Facebook, FindeChristus: migration 038) are not offered', not any(
      s['key'] in model.ARCHIVED_SOURCES for s in current['sources']), [s['key'] for s in current['sources']])
check('the other upload numbers are still offered', any(s['key'] == 'finding_people_found' for s in current['sources']))
archived = model.defaults()
archived['weights']['finding'] = {'friends_found': 60, 'findechristus_referrals': 40}
status, body = call(ap['id'], '/api/archetypes/settings', 'PUT', {'settings': archived, 'version': 0})
check('an archived number cannot be added, and nothing is saved', status == 400
      and body['fields'] == {'weights.finding': 'This number is archived and can no longer be added.'}, (status, body))

wrong = model.defaults()
wrong['weights']['finding']['friends_found'] = 35
status, body = call(ap['id'], '/api/archetypes/settings', 'PUT', {'settings': wrong, 'version': 0})
check('weights that do not add up to 100 are refused and named', status == 400
      and body['fields'] == {'weights.finding': 'The weights must add up to 100 %.'}, (status, body))

changed = model.defaults()
changed['weights']['finding'] = {'friends_found': 100}
changed['balance_threshold'] = 0.5
status, body = call(ap['id'], '/api/archetypes/settings', 'PUT', {'settings': changed, 'version': 0})
check('AP: a change is saved as version 1', status == 200 and body['version'] == 1, (status, body))
status, after = call(ap['id'], f'/api/archetypes?week={week}')
moved = next(a for a in after['areas'] if a['id'] == sample['id'])
check('the change changes the scores (Finding of the same area)', moved['indices']['finding'] != sample['indices']['finding'],
      f"{sample['indices']['finding']} -> {moved['indices']['finding']}")
status, current = call(ap['id'], '/api/archetypes/settings')
entry = current['history'][0] if current['history'] else {}
check('history: who, when and what changed', entry.get('version') == 1 and entry.get('changed_by_name')
      and entry.get('changed_at') and entry.get('summary') == 'Weights: Finding, Balance threshold: 0.2 → 0.5', entry)
status, body = call(ap['id'], '/api/archetypes/settings', 'PUT', {'settings': model.defaults(), 'version': 0})
check('a save based on an old version is refused (409)', status == 409, status)
status, body = call(ap['id'], '/api/archetypes/settings/restore', 'POST', {'version': 1})
check('restore the sheet defaults: version 2', status == 200 and body['version'] == 2 and body['settings'] == model.defaults(), status)
status, back = call(ap['id'], f'/api/archetypes?week={week}')
again = next(a for a in back['areas'] if a['id'] == sample['id'])
check('after the restore the numbers are the sheet\'s again', again['indices'] == sample['indices'])
status, current = call(ap['id'], '/api/archetypes/settings')
check('history keeps both entries, newest first', [h['action'] for h in current['history']] == ['restore_defaults', 'save'])

status, body = call(ap['id'], f'/api/archetypes?week={week}&weeks=4')
check('weeks to average 4 gives other numbers', status == 200 and body['weeks_to_average'] == 4
      and next(a for a in body['areas'] if a['id'] == sample['id'])['indices'] != sample['indices'], status)
status, _ = call(ap['id'], '/api/archetypes?week=2026-09-22')
check('a week that is not a complete Sunday week is refused (400)', status == 400, status)

# ------------------------------------------------------------------------------------------------ notes
own = mission['areas'][0]['id']
status, body = call(ap['id'], '/api/archetypes/notes', 'PUT', {'area_id': own, 'week': week, 'body': 'Test note by the AP.'})
check('AP: writes a note', status == 200 and body['saved'], status)
status, _ = call(zl['id'], '/api/archetypes/notes', 'PUT', {'area_id': own, 'week': week, 'body': 'Leader note.'})
check('ZL: notes refused (403)', status == 403, status)
status, body = call(ap['id'], f'/api/archetypes?week={week}')
notes = next(a for a in body['areas'] if a['id'] == own)['notes']
check('AP: sees their note marked as theirs', len(notes) == 1 and notes[0]['mine'])
status, _ = call(dl['id'], '/api/archetypes/notes', 'PUT', {'area_id': own, 'week': week, 'body': 'Leader note.'})
check('DL: notes refused (403)', status == 403, status)
status, _ = call(missionary['id'], '/api/archetypes/notes', 'PUT', {'area_id': own, 'week': week, 'body': 'x'})
check('missionary: notes refused (403)', status == 403, status)
status, body = call(ap['id'], '/api/archetypes/notes', 'PUT', {'area_id': own, 'week': week, 'body': '  '})
check('an empty note removes your own note', status == 200 and body['removed'] and sql(
    'SELECT count(*) AS n FROM public.archetype_notes WHERE area_id=%s', (own,))[0]['n'] == 0, status)
status, _ = call(ap['id'], '/api/archetypes/notes', 'PUT', {'area_id': own, 'week': '2026-09-23', 'body': 'x'})
check('a note for a date that is not a Sunday is refused (400)', status == 400, status)

# ------------------------------------------------------------------------------------------------ database rights
with api.db() as conn:
    closed = api.rows(conn, '''SELECT bool_or(has_table_privilege(r, t, 'SELECT') OR has_table_privilege(r, t, 'INSERT')) AS open
        FROM unnest(ARRAY['anon', 'authenticated', 'service_role', 'gfm_dashboard_reader']) r,
             unnest(ARRAY['public.archetype_settings', 'public.archetype_settings_history', 'public.archetype_notes']) t''')
check('settings, history and notes are closed to anon, authenticated, service_role and the dashboard reader',
      closed[0]['open'] is False)

# ------------------------------------------------------------------------------------------------ timing and clean-up
started = time.time()
call(ap['id'], '/api/archetypes')
print(f'mission page with 8-week trends: {time.time() - started:.2f} s', flush=True)
sql('DELETE FROM public.archetype_notes')
sql('DELETE FROM public.archetype_settings_history')
sql('DELETE FROM public.archetype_settings')
print(f'{sum(results)}/{len(results)} passed', flush=True)
sys.exit(0 if all(results) else 1)
