"""Zone presentations (round 7, migration 035) against a THROWAWAY database copy, with the copy's real ZL, DL and AP.

The rule: a ZL or STL makes, edits, publishes, presents and downloads their own zone's presentations, opens a deck a
manager shared with them (read-only), and never sees another zone's or a mission deck otherwise; managers see and
change every deck; a DL opens only decks shared with them (never another zone's deck); missionaries have no
Presentations. A zone's deck is shared only inside its zone, and a leader's copy is shared with nobody. The chart
builder offers a ZL or STL only their own zone, and the numbers are always narrowed to it.

Checks the portal-api endpoints the presentation manager calls (/internal/presentations/check, access, chart-catalog,
chart-data, kpis) exactly as it calls them (X-Service-Key and the person's user id). Prints counts and booleans only,
never names or ids. It adds presentation rules for made-up decks (zdtest-*) and deletes them at the end.

Refuses unless DATABASE_URL names a database containing "test" and ZONE_DECKS_TEST_THROWAWAY=yes. Run inside a
temporary portal-api container on the test network, after migration 035:
  docker run --rm --network gfm-test-r2-net -e ZONE_DECKS_TEST_THROWAWAY=yes -e DATABASE_URL=... \\
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/zone_decks_db.py
"""
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('ZONE_DECKS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')
os.environ.setdefault('PORTAL_SERVICE_KEY', 'zone-decks-db-test-key')

import app as api  # noqa: E402

client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {detail}' if detail != '' else ''), flush=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def post(path, person, body):
    response = client.post(path, json={'user_id': str(person['id']), **body},
                           headers={'X-Service-Key': os.environ['PORTAL_SERVICE_KEY']})
    return response.status_code, response.get_json()


def leader(role):
    """The first active account whose current leadership is `role` (no manager rights), with its zone."""
    found = sql('''SELECT up.id, s.leadership_zone_id AS zone_id, c.mission_id
                   FROM public.user_profiles up
                   JOIN public.current_user_context c ON c.user_id = up.id AND c.leadership_role = %s
                   JOIN public.current_user_scope s ON s.user_id = up.id AND s.leadership_role = %s
                   WHERE up.active AND up.app_role NOT IN ('PRESIDENT', 'DATA_ADMIN')
                     AND NOT ('DATA_ADMIN' = ANY(up.additional_roles))
                   ORDER BY up.id LIMIT 1''', (role, role))
    return found[0] if found else None


zl, dl, ap = leader('ZL'), leader('DL'), leader('AP')
print(f'fixture: ZL={bool(zl)} DL={bool(dl)} AP={bool(ap)}', flush=True)
if not (zl and dl and ap and zl['zone_id']):
    sys.exit('This copy needs a ZL (with a zone), a DL and an AP account.')
mission = zl['mission_id']
other_zone = sql('SELECT id FROM public.zones WHERE mission_id=%s AND id<>%s ORDER BY id LIMIT 1', (mission, zl['zone_id']))[0]['id']
OWN, OTHER, MISSION, SHARED = 'zdtest-own', 'zdtest-other-zone', 'zdtest-mission', 'zdtest-shared'
DECKS = [OWN, OTHER, MISSION, SHARED, 'zdtest-none']


def check_answer(person):
    return post('/internal/presentations/check', person, {'deck_slugs': DECKS})


def cleanup():
    with api.db() as conn:
        api.rows(conn, 'DELETE FROM portal.presentation_access WHERE deck_slug LIKE %s', ('zdtest-%',))


cleanup()
try:
    # ---- making decks ----
    status, body = post('/internal/presentations/access', zl, {'operation': 'create', 'deck_slug': OWN})
    owner = sql('SELECT owner_zone_id FROM portal.presentation_access WHERE deck_slug=%s', (OWN,))
    check("create: a ZL's new deck belongs to their zone", status == 200 and owner and owner[0]['owner_zone_id'] == zl['zone_id'], status)
    status, _ = post('/internal/presentations/access', ap, {'operation': 'create', 'deck_slug': MISSION})
    owner = sql('SELECT owner_zone_id FROM portal.presentation_access WHERE deck_slug=%s', (MISSION,))
    check("create: a manager's new deck belongs to the mission", status == 200 and owner and owner[0]['owner_zone_id'] is None, status)
    status, _ = post('/internal/presentations/access', dl, {'operation': 'create', 'deck_slug': 'zdtest-dl'})
    check('create: a DL cannot make a presentation', status == 403 and not sql("SELECT 1 FROM portal.presentation_access WHERE deck_slug='zdtest-dl'"), status)
    with api.db() as conn:
        api.rows(conn, '''INSERT INTO portal.presentation_access(mission_id,deck_slug,owner_zone_id) VALUES(%s,%s,%s)''',
                 (mission, OTHER, other_zone))
        api.rows(conn, '''INSERT INTO portal.presentation_access(mission_id,deck_slug,roles,everyone) VALUES(%s,%s,%s,true)''',
                 (mission, SHARED, ['ZL']))

    # ---- who sees and changes what ----
    status, body = check_answer(zl)
    check('check: the ZL opens only their zone\'s deck and the deck shared with ZLs',
          status == 200 and sorted(body['allowed_slugs']) == sorted([OWN, SHARED]), (status, len((body or {}).get('allowed_slugs', []))))
    check('check: the ZL changes only their zone\'s deck', body['editable_slugs'] == [OWN], len(body['editable_slugs']))
    check('check: the ZL may use Presentations and create (their zone)', body['can_use'] and body['can_create']
          and body['zone_id'] == zl['zone_id'] and not body['can_manage'] and body['owner_zones'] == {})
    status, body = check_answer(ap)
    check('check: the AP opens and changes every deck', status == 200 and body['allowed_slugs'] == DECKS and body['editable_slugs'] == DECKS)
    check('check: the AP sees which zone owns the zone decks', set(body['owner_zones']) == {OWN, OTHER})
    status, body = check_answer(dl)
    check('check: a DL opens only the deck shared with everyone, changes none and makes none', status == 200
          and body['can_use'] and not body['can_create'] and body['allowed_slugs'] == [SHARED] and body['editable_slugs'] == [])

    # ---- rename, duplicate, delete ----
    status, _ = post('/internal/presentations/access', zl, {'operation': 'duplicate', 'deck_slug': OWN, 'new_slug': 'zdtest-own-copy'})
    copy = sql("SELECT owner_zone_id FROM portal.presentation_access WHERE deck_slug='zdtest-own-copy'")
    check('duplicate: the ZL\'s copy stays with their zone', status == 200 and copy and copy[0]['owner_zone_id'] == zl['zone_id'], status)
    status, _ = post('/internal/presentations/access', zl, {'operation': 'rename', 'deck_slug': 'zdtest-own-copy', 'new_slug': 'zdtest-own-renamed'})
    moved = sql('SELECT deck_slug, owner_zone_id FROM portal.presentation_access WHERE deck_slug LIKE %s', ('zdtest-own-%',))
    check('rename: the rule moves with its owner', status == 200 and [(r['deck_slug'], r['owner_zone_id']) for r in moved]
          == [('zdtest-own-renamed', zl['zone_id'])], status)
    status, body = post('/internal/presentations/access', zl, {'operation': 'delete', 'deck_slug': 'zdtest-own-renamed'})
    check('delete: the ZL removes their own copy', status == 200 and body['deleted'], status)

    # A leader's copy is shared with nobody until a manager shares it; a manager's copy keeps the sharing (review finding).
    with api.db() as conn:
        api.rows(conn, '''UPDATE portal.presentation_access SET roles=%s, everyone=true, zone_ids=%s
                          WHERE deck_slug=%s''', (['DL', 'ZL', 'STL'], [zl['zone_id']], OWN))
    status, _ = post('/internal/presentations/access', zl, {'operation': 'duplicate', 'deck_slug': OWN, 'new_slug': 'zdtest-own-zlcopy'})
    copy = sql("SELECT * FROM portal.presentation_access WHERE deck_slug='zdtest-own-zlcopy'")
    check("duplicate: the ZL's copy keeps the zone but is shared with nobody",
          status == 200 and copy and copy[0]['owner_zone_id'] == zl['zone_id'] and not copy[0]['everyone']
          and not any(copy[0][k] for k in ('roles', 'zone_ids', 'district_ids', 'user_ids')), status)
    status, _ = post('/internal/presentations/access', ap, {'operation': 'duplicate', 'deck_slug': OWN, 'new_slug': 'zdtest-own-apcopy'})
    copy = sql("SELECT * FROM portal.presentation_access WHERE deck_slug='zdtest-own-apcopy'")
    check("duplicate: a manager's copy keeps the sharing", status == 200 and copy and copy[0]['everyone']
          and copy[0]['roles'] == ['DL', 'ZL', 'STL'] and copy[0]['owner_zone_id'] == zl['zone_id'], status)
    with api.db() as conn:
        api.rows(conn, '''UPDATE portal.presentation_access SET roles='{}', everyone=false, zone_ids='{}' WHERE deck_slug=%s''', (OWN,))
        api.rows(conn, "DELETE FROM portal.presentation_access WHERE deck_slug IN ('zdtest-own-zlcopy','zdtest-own-apcopy')")
    refused = [post('/internal/presentations/access', zl, {'operation': op, 'deck_slug': slug, 'new_slug': 'zdtest-taken'})[0]
               for op in ('rename', 'duplicate', 'delete') for slug in (OTHER, MISSION, SHARED, 'zdtest-none')]
    check('rename, duplicate, delete: refused for another zone\'s, a mission, a shared and an unknown deck',
          set(refused) == {403} and not sql("SELECT 1 FROM portal.presentation_access WHERE deck_slug='zdtest-taken'"), refused)

    # ---- Manage access (managers only) sets the owner ----
    rule = {'roles': [], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': False}
    status, _ = post('/internal/presentations/access', zl, {'operation': 'save', 'deck_slug': OWN, 'rule': rule})
    check('save: a ZL cannot change who sees a deck', status == 403, status)
    status, _ = post('/internal/presentations/access', zl, {'operation': 'get', 'deck_slug': OWN})
    check('get: a ZL cannot read the access rule', status == 403, status)
    status, body = post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': MISSION, 'rule': dict(rule, owner_zone_id=other_zone)})
    check('save: the AP hands a mission deck to a zone', status == 200 and body['access']['owner_zone_id'] == other_zone, status)
    status, body = post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': MISSION, 'rule': dict(rule, roles=['ZL'])})
    check('save: without owner_zone_id the owner stays', status == 200 and body['access']['owner_zone_id'] == other_zone, status)
    status, body = post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': MISSION, 'rule': dict(rule, owner_zone_id=None)})
    check('save: the AP gives it back to the mission', status == 200 and body['access']['owner_zone_id'] is None, status)
    bad = [post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': MISSION, 'rule': dict(rule, owner_zone_id=z)})[0]
           for z in (987654321,)]
    status, _ = post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': MISSION, 'rule': dict(rule, roles=['MISSIONARY'])})
    check('save: a zone that is not in the mission, or missionaries as viewers, are refused', bad == [400] and status == 400, (bad, status))
    status, body = post('/internal/presentations/access', ap, {'operation': 'get', 'deck_slug': MISSION})
    check('get: the options offer DL, ZL and STL', status == 200 and body['options']['roles'] == ['DL', 'ZL', 'STL'], status)

    # A zone's deck is shared only inside its zone (review finding): its slides are its leaders' page code.
    other_district = sql('SELECT id FROM public.districts WHERE zone_id=%s ORDER BY id LIMIT 1', (other_zone,))[0]['id']
    own_district = sql('SELECT id FROM public.districts WHERE zone_id=%s ORDER BY id LIMIT 1', (zl['zone_id'],))[0]['id']
    outside_person = sql('''SELECT user_id FROM public.current_user_context WHERE user_active AND mission_id=%s
                            AND zone_id<>%s ORDER BY user_id LIMIT 1''', (mission, zl['zone_id']))
    print(f'fixture: a person of another zone={bool(outside_person)}', flush=True)
    outside = [post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': OWN,
                                                          'rule': dict(rule, owner_zone_id=zl['zone_id'], **extra)})[0]
               for extra in ({'zone_ids': [other_zone]}, {'district_ids': [other_district]},
                             {'user_ids': [str(r['user_id']) for r in outside_person]})]
    kept = sql('SELECT zone_ids, district_ids, user_ids FROM portal.presentation_access WHERE deck_slug=%s', (OWN,))[0]
    check("save: a zone deck cannot be shared with another zone, its districts or its people",
          outside == [400, 400, 400 if outside_person else 200] and not any(kept.values()), outside)
    status, _ = post('/internal/presentations/access', ap, {'operation': 'save', 'deck_slug': OWN,
                                                           'rule': dict(rule, owner_zone_id=zl['zone_id'], district_ids=[own_district])})
    check('save: a zone deck may be shared with its own districts', status == 200, status)
    # Shared with every leader of the mission: still only the zone's own people open it.
    with api.db() as conn:
        api.rows(conn, '''UPDATE portal.presentation_access SET roles=%s, everyone=true WHERE deck_slug=%s''',
                 (['DL', 'ZL', 'STL'], OTHER))
    status, body = check_answer(zl)
    check("check: another zone's deck shared with everyone still does not open for the ZL", OTHER not in body['allowed_slugs'])
    dl_zone = sql('SELECT zone_id FROM public.current_user_context WHERE user_id=%s LIMIT 1', (dl['id'],))[0]['zone_id']
    status, body = check_answer(dl)
    check("check: the DL opens the deck shared with everyone only when it is their zone's or the mission's",
          (OTHER in body['allowed_slugs']) == (dl_zone == other_zone))
    with api.db() as conn:
        api.rows(conn, '''UPDATE portal.presentation_access SET roles='{}', everyone=false WHERE deck_slug=%s''', (OTHER,))
        api.rows(conn, '''UPDATE portal.presentation_access SET district_ids='{}' WHERE deck_slug=%s''', (OWN,))

    # ---- the chart builder and the numbers ----
    status, body = post('/internal/presentations/chart-catalog', zl, {})
    zone_districts = sql('SELECT count(*) AS n FROM public.districts WHERE zone_id=%s', (zl['zone_id'],))[0]['n']
    zone_areas = sql('''SELECT count(*) AS n FROM public.areas a JOIN public.districts d ON d.id=a.district_id
                        WHERE d.zone_id=%s''', (zl['zone_id'],))[0]['n']
    check('catalog: the ZL is offered only their zone, its districts and areas, and no mission level',
          status == 200 and [z['id'] for z in body['zones']] == [zl['zone_id']] and len(body['districts']) == zone_districts
          and len(body['areas']) == zone_areas and [lv['id'] for lv in body['levels']] == ['zone', 'district', 'area']
          and body['scope'] == 'zone', (status, len((body or {}).get('zones', [])), len((body or {}).get('districts', []))))
    status, body = post('/internal/presentations/chart-catalog', ap, {})
    check('catalog: the AP is offered the whole mission', status == 200 and len(body['zones']) > 1 and body['scope'] == 'mission', status)
    check('catalog: a DL is refused', post('/internal/presentations/chart-catalog', dl, {})[0] == 403)

    mission_chart = {'measures': ['friends_found.actual'], 'level': 'mission', 'weeks': {'last': 8}}
    status, body = post('/internal/presentations/chart-data', zl, {'spec': mission_chart, 'deck': OWN})
    check("chart: in their own zone's deck the ZL may preview a chart not written yet, and gets their zone, not the mission",
          status == 200 and body['meta']['level'] == 'zone' and body['meta']['stewardship'] and body['meta']['units'] <= 1, status)
    other_zone_chart = {'measures': ['friends_found.actual'], 'level': 'district', 'filter': {'zones': [other_zone]}, 'weeks': {'last': 8}}
    status, body = post('/internal/presentations/chart-data', zl, {'spec': other_zone_chart, 'deck': OWN})
    check("chart: another zone's districts show the ZL nothing", status == 200 and body['meta']['units'] == 0
          and not any(v for s in body['table']['series'] for v in s['values'] if v), status)
    for slug in (OTHER, MISSION, SHARED):
        status, _ = post('/internal/presentations/chart-data', zl, {'spec': mission_chart, 'deck': slug})
        check(f'chart: a preview in a deck the ZL may not change is refused ({slug[7:]})', status == 403, status)
    status, body = post('/internal/presentations/chart-data', dl, {'spec': mission_chart, 'deck': SHARED, 'pinned': True})
    check("chart and key numbers: a DL gets only their own district's numbers in a deck shared with them",
          status == 200 and body['meta']['level'] == 'district' and body['meta']['stewardship']
          and post('/internal/presentations/kpis', dl, {'weeks': 4})[0] == 200, status)
finally:
    cleanup()

print(f'\n{sum(results)} of {len(results)} checks passed', flush=True)
sys.exit(0 if all(results) else 1)
