"""The Mission Dashboard deck (slidev/showcase/mission-dashboard) against a THROWAWAY database copy.

Every chart query written in the deck's slides.md goes through the real portal-api chart code (charts.py, as the
manager's POST /api/charts/data reaches it), and must:
- answer for an AP (a manager), with and without the deck named, with weeks and at least one number;
- use finished weeks only (includeCurrent false: the week still being reported is left out);
- be refused for a DL and a ZL (the deck has no access rule, so it is for managers only), pinned or not, and for an
  STL, Office and a missionary (their contexts are the DL's with another role, marked "stand-in");
- and /internal/presentations/check must not offer the deck to a DL, ZL or STL, while an AP may manage it.
Also: the copy has no access rule for the deck, and the deck has no chart without a query.
Prints ids, counts and timings only, never names.

The covenant-path tiles (new_members.*, baptismal_date_friends.*, high_potentials.*) count the people on weekly plans.
In copies of gfm_test_r3_template those are the template's TEST people, which round 3 removed from live: live had 0
in every finished week on 28 Sep 2026 (a count of 0 is also "a number" here). The test prints their last-week total
as a note, so a copy's numbers are not mistaken for live's.

Refuses unless DATABASE_URL names a database containing "test" and DASHDECK_TEST_THROWAWAY=yes. Run inside a
temporary portal-api container on the test network, with the deck mounted read-only:
  docker run --rm --network gfm-test-r2-net -e DASHDECK_TEST_THROWAWAY=yes -e DATABASE_URL=... \
      -v <repo>/portal-api:/app:ro -v <repo>/slidev/showcase/mission-dashboard:/deck:ro -w /app \
      gfm-portal-portal-api python tests/dashboard_deck_db.py
"""
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('DASHDECK_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')
os.environ.setdefault('PORTAL_SERVICE_KEY', 'dashdeck-db-test-key')

import app as api  # noqa: E402
import charts  # noqa: E402

DECK = 'mission-dashboard'
DECK_FILE = os.environ.get('DECK_FILE', '/deck/slides.md')
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' else ''), flush=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def post(path, user_id, body, role=None):
    headers = {'X-Service-Key': os.environ['PORTAL_SERVICE_KEY']}
    if role:
        headers['X-Test-Role'] = role
    started = time.time()
    response = client.post(path, json={'user_id': str(user_id), **body}, headers=headers)
    return response.status_code, response.get_json(silent=True), time.time() - started


def user(role):
    found = sql('''SELECT user_id FROM public.current_user_context WHERE user_active AND leadership_role=%s
                   ORDER BY user_id LIMIT 1''', (role,))
    return found[0]['user_id'] if found else None


# Stand-ins for roles the copy has no account for: the DL's own context with another role (TEST ONLY; the request
# names the role in X-Test-Role, which only this test client sends).
real_internal_context = api.internal_context


def internal_context(conn):
    c = real_internal_context(conn)
    role = api.request.headers.get('X-Test-Role')
    if role == 'STL':
        c = {**c, 'app_role': 'MISSIONARY', 'leadership_role': 'STL', 'additional_roles': []}
    elif role == 'OFFICE':
        c = {**c, 'app_role': 'OFFICE', 'leadership_role': None, 'additional_roles': []}
    elif role == 'MISSIONARY':
        c = {**c, 'app_role': 'MISSIONARY', 'leadership_role': None, 'additional_roles': []}
    return c


api.internal_context = internal_context

# ---- the deck -------------------------------------------------------------------------------------------------------
text = open(DECK_FILE, encoding='utf-8').read()
tags = re.findall(r'<(MissionChart|MissionKpiChart)\b(.*?)/>', text, flags=re.S)
charts_in_deck = []
for name, attrs in tags:
    query = re.search(r":query='([^']*)'", attrs)
    kind = re.search(r'\btype="([a-z]+)"', attrs)
    title = re.search(r'\btitle="([^"]*)"', attrs)
    charts_in_deck.append({'component': name, 'query': query.group(1) if query else None,
                           'type': kind.group(1) if kind else 'line', 'title': title.group(1) if title else ''})
check('the deck has charts, every one a <MissionChart> with a query',
      len(charts_in_deck) >= 20 and all(c['component'] == 'MissionChart' and c['query'] for c in charts_in_deck),
      len(charts_in_deck))
specs = []
for c in charts_in_deck:
    spec = charts.normalize_spec(json.loads(c['query']))
    specs.append((c, spec))
check('every query is valid, uses finished weeks only and stays at mission, zone or district level',
      all(not s['includeCurrent'] and s['level'] in ('mission', 'zone', 'district') for _, s in specs))
check('district charts show each viewer only their own stewardship',
      all(s['audience'] == 'stewardship' for _, s in specs if s['level'] == 'district'))
print(f'deck: {len(specs)} charts, {len({charts.spec_hash(s) for _, s in specs})} different queries', flush=True)

ap, dl, zl = user('AP'), user('DL'), user('ZL')
print(f'fixture: AP={bool(ap)} DL={bool(dl)} ZL={bool(zl)}', flush=True)
if not (ap and dl and zl):
    sys.exit('This copy needs an AP, a DL and a ZL.')

rules = sql('SELECT count(*) AS n FROM portal.presentation_access WHERE deck_slug=%s', (DECK,))[0]['n']
check('the copy has no access rule for the deck (managers only)', rules == 0, rules)
current = sql('SELECT public.current_reporting_sunday() AS s')[0]['s'].isoformat()

# ---- every chart answers for an AP ------------------------------------------------------------------------------------
times = []
for number, (c, spec) in enumerate(specs, 1):
    label = f"{number:02d} {c['type']:<7} {c['title'] or '+'.join(spec['measures'])[:48]}"
    for body in ({'spec': spec}, {'spec': spec, 'deck': DECK, 'pinned': True}):
        status, answer, took = post('/internal/presentations/chart-data', ap, body)
        times.append(took)
        if status != 200:
            check(f'AP {label}', False, f'{status} {(answer or {}).get("error")}')
            break
    else:
        table, meta = answer['table'], answer['meta']
        values = [v for s in table['series'] for v in s['values']]
        present = [v for v in values if v is not None]
        weeks = meta['weeks']
        first = table['series'][0]['values'] if table['series'] else []
        ok = bool(table['labels']) and bool(table['series']) and bool(present) and weeks and max(weeks) < current
        if c['type'] == 'tile':
            ok = ok and first and first[-1] is not None
        if spec['transform'] == 'pct_of_goal':
            ok = ok and meta['unit'] == 'percent'
        check(f'AP {label}', ok, f'{len(table["labels"])} labels, {len(table["series"])} series, '
                                  f'{len(present)}/{len(values)} numbers, weeks {weeks[0] if weeks else "-"}..'
                                  f'{weeks[-1] if weeks else "-"}, {took:.2f}s')
people = []
for c, spec in specs:
    if c['type'] == 'tile' and spec['measures'][0].split('.')[0] in ('new_members', 'baptismal_date_friends', 'high_potentials'):
        status, answer, _ = post('/internal/presentations/chart-data', ap, {'spec': spec})
        last = answer['table']['series'][0]['values'][-1] if status == 200 and answer['table']['series'] else None
        people.append(last or 0)
print(f'note: {len(people)} covenant-path tiles, last finished week total {sum(people)} on this copy '
      f'(test people of the template; live had 0 on 28 Sep 2026)', flush=True)
times.sort()
check('each chart answers in under a second', times[-1] < 1.0, f'median {times[len(times) // 2]:.2f}s, slowest {times[-1]:.2f}s')

# ---- refused for everyone else ----------------------------------------------------------------------------------------
viewers = [('a DL', dl, None), ('a ZL', zl, None), ('an STL (stand-in)', dl, 'STL'), ('Office (stand-in)', dl, 'OFFICE'),
           ('a missionary (stand-in)', dl, 'MISSIONARY')]
for who, uid, role in viewers:
    statuses = set()
    for _, spec in specs:
        for body in ({'spec': spec}, {'spec': spec, 'deck': DECK, 'pinned': True}, {'spec': spec, 'deck': DECK, 'pinned': False}):
            status, _, _ = post('/internal/presentations/chart-data', uid, body, role)
            statuses.add(status)
    check(f'{who} is refused every chart of the deck, pinned or not', statuses == {403}, sorted(statuses))

for who, uid, role in [('an AP', ap, None)] + viewers[:3]:
    status, answer, _ = post('/internal/presentations/check', uid, {'deck_slugs': [DECK]}, role)
    if uid == ap:
        check('an AP may manage (and so open) the deck', status == 200 and answer['can_manage'] is True, status)
    else:
        check(f'the deck is not offered to {who}', status == 200 and answer['can_manage'] is False
              and DECK not in answer['allowed_slugs'] and answer['role'] in ('DL', 'ZL', 'STL'), (status, answer and answer.get('role')))

passed = sum(results)
print(f'\n{passed} of {len(results)} checks passed', flush=True)
sys.exit(0 if passed == len(results) else 1)
