"""Unit checks for Call-ins (callins.py) without a database: who opens which scope, drill-down refusals, what each
viewer may change, saves running as the user, database refusals as plain answers, bad weeks, and the time limit.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_callins.py
pytest works too: python -m pytest portal-api/tests/test_callins.py
"""
import base64
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import app  # noqa: E402
import callins  # noqa: E402

M = {'mission_id': 1}
CONTEXTS = {
    'ap': dict(M, app_role='AP', leadership_role='AP', zone_id=6, district_id=61, area_id=611),
    'president': dict(M, app_role='PRESIDENT', leadership_role=None, zone_id=6, district_id=61, area_id=611),
    'data_admin': dict(M, app_role='DATA_ADMIN', leadership_role=None, zone_id=6, district_id=61, area_id=611),
    'zl': dict(M, app_role='MISSIONARY', leadership_role='ZL', leadership_zone_id=5, zone_id=5, district_id=51, area_id=511),
    'dl': dict(M, app_role='MISSIONARY', leadership_role='DL', leadership_district_id=51, zone_id=5, district_id=51, area_id=512),
    'dl_da': dict(M, app_role='MISSIONARY', leadership_role='DL', leadership_district_id=51, zone_id=5, district_id=51,
                  area_id=512, additional_roles=['DATA_ADMIN']),
    'zl_office': dict(M, app_role='MISSIONARY', leadership_role='ZL', leadership_zone_id=5, zone_id=5, additional_roles=['OFFICE']),
    'stl': dict(M, app_role='MISSIONARY', leadership_role='STL', leadership_zone_id=5, zone_id=5, district_id=52, area_id=521),
    'stl_da': dict(M, app_role='MISSIONARY', leadership_role='STL', leadership_zone_id=5, zone_id=5, additional_roles=['DATA_ADMIN']),
    'missionary_da': dict(M, app_role='MISSIONARY', leadership_role=None, zone_id=5, district_id=52, area_id=521,
                          additional_roles=['DATA_ADMIN']),
    'office_da': dict(M, app_role='OFFICE', leadership_role=None, zone_id=6, area_id=611, additional_roles=['DATA_ADMIN']),
    'office': dict(M, app_role='OFFICE', leadership_role=None, zone_id=6, area_id=611),
    'missionary': dict(M, app_role='MISSIONARY', leadership_role=None, zone_id=5, district_id=51, area_id=511),
}
# The structure of a small mission 1, plus zone 9 of another mission.
ZONES = {5: 1, 6: 1, 9: 2}
DISTRICTS = {51: 5, 52: 5, 61: 6, 91: 9}
AREAS = {511: 51, 512: 51, 521: 52, 611: 61, 911: 91}
WEEKS = [(12, date(2026, 9, 20)), (11, date(2026, 9, 13))]


def metrics(n):
    row = {}
    for key, _ in callins.METRICS:
        row.update({key + '_actual': n, key + '_goal': n + 1})
        if key != 'follow_up_lessons':
            row[key + '_previous_goal'] = n + 2
    return row


class FakeError(psycopg2.Error):
    """A database error with a chosen SQLSTATE (psycopg2's own attributes cannot be set)."""
    def __init__(self, code, message):
        super().__init__(message)
        self._code, self._message = code, message

    @property
    def pgcode(self):
        return self._code

    @property
    def diag(self):
        return SimpleNamespace(message_primary=self._message)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self.result = conn, None, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def answer(self, columns, rows):
        self.description = [(c,) for c in columns]
        self.result = [tuple(r[c] for c in columns) for r in rows]

    def execute(self, sql, args=()):
        flat = ' '.join(sql.split())
        self.conn.log.append((flat, args))
        self.description, self.result = None, []
        failure = next((error for text, error in self.conn.fail.items() if text in flat), None)
        if failure:
            raise failure
        if 'call_in_summary_with_planning' in flat and self.conn.slow:
            raise psycopg2.extensions.QueryCanceledError('canceling statement due to statement timeout')
        for level, text in callins.CHAIN_SQL.items():
            if flat == ' '.join(text.split()):
                return self.answer(*self.chain(level, args[0]))
        if 'get_mission_call_in_summary_with_planning' in flat:
            rows = [dict(metrics(2), zone_id=z, zone_name=f'Zone {z}', mission_id=1, district_count=2,
                         completed_district_count=1, all_dl_call_ins_complete=False, all_weekly_reports_submitted=True,
                         area_count=3, zone_notes=f'notes {z}', planning_details=[]) for z in (5, 6)]
            return self.answer(['data'], [{'data': rows}])
        if 'get_zl_call_in_summary_with_planning' in flat:
            rows = [dict(metrics(1), district_id=d, district_name=f'District {d}', zone_id=5, dl_notes=f'dl {d}',
                         thank_you='SECRET-THANKS', zl_notes=f'zl {d}', dl_call_in_complete=d == 51,
                         dl_completed_at='2026-09-21T10:00:00+00:00' if d == 51 else None, dl_completed_by='uuid-x',
                         area_count=2, all_weekly_reports_submitted=True, planning_details=[])
                    for d in (51, 52)]
            return self.answer(['data'], [{'data': rows}])
        if 'get_zl_call_in_area_updates' in flat:
            return self.answer(['district_id', 'area_id', 'area_name', 'missionaries', 'dl_update'],
                               [{'district_id': 51, 'area_id': 511, 'area_name': 'Area 511',
                                 'missionaries': [{'display_name': 'Elder A', 'roster_position_abbr': 'DL', 'first_name': 'x'}],
                                 'dl_update': 'going well'}])
        if 'get_zl_call_in_zone_notes' in flat:
            return self.answer(['zone_notes', 'updated_at'], [{'zone_notes': 'zone words', 'updated_at': None}])
        if 'get_dl_call_in_summary_with_planning' in flat:
            district = args[0]
            rows = [dict(metrics(a % 10), area_id=a, area_name=f'Area {a}', district_id=district, report_count=1,
                         all_reports_submitted=True, dl_update=f'update {a}', friends_found_plan='Plan text',
                         missionaries=[{'display_name': 'Sister B', 'roster_position_abbr': 'STL', 'last_name': 'x'}],
                         planning_details=[]) for a, d in AREAS.items() if d == district]
            return self.answer(['data'], [{'data': rows}])
        if 'FROM public.call_in_districts WHERE district_id' in flat:
            completed = args[0] in self.conn.completed
            return self.answer(['dl_notes', 'zl_notes', 'dl_completed_at', 'updated_at'],
                               [{'dl_notes': 'dl words', 'zl_notes': 'zl words',
                                 'dl_completed_at': '2026-09-21T10:00:00+00:00' if completed else None, 'updated_at': None}])
        if 'get_call_in_people' in flat:
            return self.answer(['data'], [{'data': {'level': args[0], 'id': args[1], 'baptismal_dates': [], 'new_members': [],
                                                   'high_potentials': [], 'counts': {}}}])
        if 'get_dl_call_in_ward_coordination' in flat:
            return self.answer(['area_id', 'area_name', 'unit_id', 'unit_name', 'ward_coordination_held',
                                'ward_coordination_attendance'],
                               [{'area_id': a, 'area_name': f'Area {a}', 'unit_id': 1, 'unit_name': 'Ward',
                                 'ward_coordination_held': True, 'ward_coordination_attendance': {'gemiko_leader': 'yes'}}
                                for a in (511, 512)])
        if 'FROM public.reporting_weeks' in flat:
            if 'sunday=%s' in flat:
                return self.answer(['id', 'sunday'], [{'id': i, 'sunday': s} for i, s in WEEKS if s == args[0]])
            return self.answer(['id', 'sunday'], [{'id': i, 'sunday': s} for i, s in WEEKS])
        if 'current_reporting_sunday() AS sunday' in flat:
            return self.answer(['sunday'], [{'sunday': date(2026, 9, 27)}])
        if 'FROM public.call_in_area_updates' in flat:
            return self.answer(['update_text', 'updated_at'], [{'update_text': 'saved update', 'updated_at': None}])
        if flat.startswith('SELECT'):
            return self.answer(['value'], [{'value': 'ok'}])

    def chain(self, level, scope_id):
        if level == 'mission':
            return ['mission_id', 'mission_name'], ([{'mission_id': scope_id, 'mission_name': 'Mission'}] if scope_id in (1, 2) else [])
        if level == 'zone':
            return ['zone_id', 'zone_name', 'mission_id', 'mission_name'], (
                [{'zone_id': scope_id, 'zone_name': f'Zone {scope_id}', 'mission_id': ZONES[scope_id], 'mission_name': 'Mission'}]
                if scope_id in ZONES else [])
        if level == 'district':
            if scope_id not in DISTRICTS:
                return ['district_id'], []
            zone = DISTRICTS[scope_id]
            return ['district_id', 'district_name', 'zone_id', 'zone_name', 'mission_id', 'mission_name'], [
                {'district_id': scope_id, 'district_name': f'District {scope_id}', 'zone_id': zone, 'zone_name': f'Zone {zone}',
                 'mission_id': ZONES[zone], 'mission_name': 'Mission'}]
        if scope_id not in AREAS:
            return ['area_id'], []
        district = AREAS[scope_id]
        zone = DISTRICTS[district]
        return ['area_id', 'area_name', 'district_id', 'district_name', 'zone_id', 'zone_name', 'mission_id', 'mission_name'], [
            {'area_id': scope_id, 'area_name': f'Area {scope_id}', 'district_id': district, 'district_name': f'District {district}',
             'zone_id': zone, 'zone_name': f'Zone {zone}', 'mission_id': ZONES[zone], 'mission_name': 'Mission'}]

    def fetchall(self):
        if self.conn.cursor_factory:  # connect() uses RealDictCursor; user_db() switches to plain tuples
            return [dict(zip([d[0] for d in self.description], row)) for row in self.result]
        return self.result


class FakeConn:
    def __init__(self, slow=False, fail=None, completed=()):
        self.slow, self.log, self.cursor_factory = slow, [], 'RealDictCursor'
        self.fail, self.completed = fail or {}, set(completed)

    def cursor(self):
        return FakeCursor(self)


def call(user, path, method='GET', body=None, **conn_options):
    conn = FakeConn(**conn_options)

    @contextmanager
    def fake_db():
        yield conn

    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip('=')
    token = enc({'alg': 'none'}) + '.' + enc({'sub': user, 'role': 'authenticated'}) + '.x'
    identity = lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'id': '00000000-0000-0000-0000-000000000001'})
    context = dict(CONTEXTS[user], user_id=user)
    with patch.object(app.requests, 'get', identity), patch.object(app, 'db', fake_db), \
            patch.object(app, 'context_for', lambda c, u: dict(context)):
        response = app.app.test_client().open(path, method=method, json=body,
                                              headers={'Authorization': 'Bearer ' + token})
    return response.status_code, response.get_json(silent=True), [sql for sql, _ in conn.log], conn.log


def get(user, path, **options):
    return call(user, path, **options)


# ---------------------------------------------------------------- weeks and the time limit

def test_bad_week_is_a_400_before_any_query():
    for bad in ('garbage', '2026-02-30', '20260920', "2026-09-20'--"):
        status, body, sql, _ = get('zl', '/api/callins?week=' + bad)
        assert status == 400 and body == {'error': 'Choose a reporting week as a date like 2026-09-20.'}, (bad, status, body)
        assert sql == [], sql


def test_slow_summary_is_stopped_with_a_plain_503():
    status, body, sql, _ = get('ap', '/api/callins', slow=True)
    assert status == 503, (status, body)
    assert body == {'error': 'Loading call-ins took too long, so it was stopped. Please try again later.'}, body
    summary = next(i for i, s in enumerate(sql) if 'get_mission_call_in_summary_with_planning' in s)
    timeout = next(i for i, s in enumerate(sql) if "set_config('statement_timeout'" in s)
    role = next(i for i, s in enumerate(sql) if s == 'SET LOCAL ROLE authenticated')
    # Same connection and transaction, after the role switch (a role's own timeout never applies to SET ROLE).
    assert role < timeout < summary, sql


def test_the_limit_is_set_on_every_read():
    for user, path in (('zl', '/api/callins'), ('dl', '/api/callins/people'), ('dl', '/api/callins/gemiko?level=district&id=51')):
        status, body, sql, log = get(user, path)
        assert status == 200, (path, status, body)
        [args] = [a for s, a in log if "set_config('statement_timeout'" in s]
        assert args == (callins.CALLINS_STATEMENT_TIMEOUT,), args


def test_latest_week_by_default_and_unknown_week_is_404():
    status, body, _, _ = get('zl', '/api/callins')
    assert body['week'] == {'id': 12, 'sunday': '2026-09-20'} and body['current_sunday'] == '2026-09-27', body['week']
    assert [w['sunday'] for w in body['weeks']] == ['2026-09-20', '2026-09-13']
    status, body, _, _ = get('zl', '/api/callins?week=2026-09-13')
    assert status == 200 and body['week']['id'] == 11
    status, body, _, _ = get('zl', '/api/callins?week=2026-09-19')
    assert status == 404 and body == {'error': 'That reporting week is unavailable.'}, (status, body)


def test_the_limit_ends_before_nginx_gives_up():
    seconds = int(callins.CALLINS_STATEMENT_TIMEOUT.rstrip('s'))
    conf = Path(__file__).resolve().parents[2] / 'portal' / 'nginx.conf'
    if not conf.exists():  # only portal-api is mounted: compare with the value known on 27 Sep 2026
        nginx = 40
    else:
        block = re.search(r'location /api/ \{(.*?)\}', conf.read_text(), re.S).group(1)
        nginx = int(re.search(r'proxy_read_timeout (\d+)s;', block).group(1))
    # Sign-in check (up to 8 s) and the small queries run before the summary; leave them room.
    assert seconds + 8 <= nginx, (seconds, nginx)


# ---------------------------------------------------------------- who opens what

def test_home_scopes():
    expected = {'ap': ('mission', 1, 'desktop'), 'president': ('mission', 1, 'desktop'), 'data_admin': ('mission', 1, 'desktop'),
                'zl': ('zone', 5, 'phone'), 'dl': ('district', 51, 'phone'), 'dl_da': ('district', 51, 'phone'),
                'zl_office': ('zone', 5, 'phone'), 'stl_da': ('mission', 1, 'desktop'),
                # Data Analyst as an additional role without a DL or ZL home: the mission, computer-first.
                'missionary_da': ('mission', 1, 'desktop'), 'office_da': ('mission', 1, 'desktop')}
    for user, (level, scope_id, layout) in expected.items():
        status, body, _, _ = get(user, '/api/callins')
        assert status == 200, (user, status, body)
        assert (body['scope']['level'], body['scope']['id'], body['layout']) == (level, scope_id, layout), (user, body['scope'], body['layout'])
        assert body['home'] == {'level': level, 'id': scope_id}, (user, body['home'])


def test_layout_follows_the_main_role_or_the_mission_home():
    # Computer-first: AP, President and Data Analyst by main role, and anyone who opens on the mission.
    for main in ('AP', 'PRESIDENT', 'DATA_ADMIN'):
        for home in ('mission', 'zone', 'district'):
            assert callins.layout_for(main, home) == 'desktop', (main, home)
    for main in ('MISSIONARY', 'OFFICE', 'STL'):
        assert callins.layout_for(main, 'mission') == 'desktop', main
    # Phone-first: DLs and ZLs, also when they are Data Analyst as well (they open on their district or zone).
    assert callins.layout_for('DL', 'district') == 'phone' and callins.layout_for('ZL', 'zone') == 'phone'
    # The layout goes with the viewer, not the page: a DL + Data Analyst keeps the phone layout on the mission page.
    status, body, _, _ = get('dl_da', '/api/callins?level=mission&id=1')
    assert status == 200 and body['layout'] == 'phone', (status, body.get('layout'))
    status, body, _, _ = get('office_da', '/api/callins?level=district&id=52')
    assert status == 200 and body['layout'] == 'desktop', (status, body.get('layout'))


def test_call_ins_are_not_for_missionaries_stls_or_office():
    for user in ('missionary', 'stl', 'office'):
        for path in ('/api/callins', '/api/callins?level=zone&id=5', '/api/callins/people', '/api/callins/gemiko?level=district&id=52'):
            status, body, sql, _ = get(user, path)
            assert status == 403 and body['error'] == callins.NOT_FOR_YOU, (user, path, status, body)
            assert not any('call_in' in s for s in sql), (user, sql)


def test_drill_down():
    cases = [
        ('dl', 'district', 52, 403), ('dl', 'zone', 5, 403), ('dl', 'mission', 1, 403), ('dl', 'area', 521, 403),
        ('dl', 'area', 511, 200), ('dl', 'district', 51, 200),
        ('zl', 'zone', 6, 403), ('zl', 'mission', 1, 403), ('zl', 'district', 61, 403), ('zl', 'area', 611, 403),
        ('zl', 'district', 51, 200), ('zl', 'area', 512, 200), ('zl', 'zone', 5, 200),
        ('ap', 'zone', 9, 403), ('ap', 'district', 91, 403), ('ap', 'mission', 2, 403),
        ('ap', 'zone', 6, 200), ('ap', 'district', 52, 200), ('ap', 'area', 521, 200),
        ('dl_da', 'mission', 1, 200), ('dl_da', 'zone', 6, 200), ('stl_da', 'district', 52, 200),
    ]
    for user, level, scope_id, expected in cases:
        status, body, sql, _ = get(user, f'/api/callins?level={level}&id={scope_id}')
        assert status == expected, (user, level, scope_id, status, body)
        if expected == 403:
            assert body['error'] == callins.OUTSIDE, body
            assert not any('summary_with_planning' in s for s in sql), sql
    for user, level, scope_id in (('dl', 'zone', 5), ('zl', 'zone', 6), ('stl', 'zone', 5)):
        status, _, sql, _ = get(user, f'/api/callins/people?level={level}&id={scope_id}')
        assert status == 403 and not any('get_call_in_people' in s for s in sql), (user, level, status)


def test_unknown_or_bad_scope():
    assert get('ap', '/api/callins?level=zone&id=77')[0] == 404
    assert get('ap', '/api/callins?level=region&id=5')[0] == 400
    assert get('ap', '/api/callins?level=zone&id=abc')[0] == 400
    assert get('ap', '/api/callins?level=zone')[0] == 400
    assert get('dl', '/api/callins/gemiko?level=zone&id=5')[0] == 400


def test_breadcrumb_marks_levels_the_viewer_may_open():
    _, body, _, _ = get('dl', '/api/callins?level=area&id=511')
    crumbs = [(c['level'], c['id'], c['allowed']) for c in body['scope']['breadcrumb']]
    assert crumbs == [('mission', 1, False), ('zone', 5, False), ('district', 51, True), ('area', 511, True)], crumbs
    _, body, _, _ = get('zl', '/api/callins?level=district&id=52')
    assert [c['allowed'] for c in body['scope']['breadcrumb']] == [False, True, True]
    _, body, _, _ = get('dl_da', '/api/callins')
    assert [c['allowed'] for c in body['scope']['breadcrumb']] == [True, True, True]
    _, body, _, _ = get('zl', '/api/callins')
    assert [c['allowed'] for c in body['children']] == [True, True] and body['scope']['child_level'] == 'district'


# ---------------------------------------------------------------- what each viewer may change and read

def test_can_flags_and_notes_by_viewer():
    _, body, _, _ = get('dl', '/api/callins')
    assert body['can'] == {'dl_notes': True, 'area_updates': True, 'complete': True, 'reopen': False, 'zl_notes': False}, body['can']
    assert set(body['notes']) == {'dl_notes'}, body['notes']  # the DL does not see the ZL's notes
    _, body, _, _ = get('zl', '/api/callins?level=district&id=51')
    assert body['can'] == {'dl_notes': False, 'area_updates': False, 'complete': False, 'reopen': False, 'zl_notes': True}, body['can']
    assert set(body['notes']) == {'dl_notes', 'zl_notes'}
    _, body, _, _ = get('ap', '/api/callins?level=district&id=51')
    assert all(body['can'][k] for k in ('dl_notes', 'area_updates', 'complete', 'zl_notes')), body['can']
    _, body, _, _ = get('zl', '/api/callins')
    assert body['can'] == {'zone_notes': True, 'zl_notes': True} and body['notes'] == {'zone_notes': 'zone words'}, body
    assert all(c['can'] == {'zl_notes': True} and set(c['notes']) == {'dl_notes', 'zl_notes'} for c in body['children'])


def test_completed_call_in_locks_dl_notes_and_area_updates():
    _, body, _, _ = get('dl', '/api/callins', completed={51})
    assert body['can'] == {'dl_notes': False, 'area_updates': False, 'complete': False, 'reopen': True, 'zl_notes': False}, body['can']
    assert body['status']['dl_call_in_complete'] is True
    _, body, _, _ = get('dl', '/api/callins?level=area&id=511', completed={51})
    assert body['can']['area_updates'] is False and body['can']['reopen'] is True and body['children'] == []
    assert body['detail']['id'] == 511 and body['status']['dl_call_in_complete'] is True
    _, body, _, _ = get('zl', '/api/callins?level=district&id=51', completed={51})
    assert body['can']['zl_notes'] is True and body['can']['reopen'] is False  # ZL notes are never locked


def test_no_thank_you_anywhere():
    for user, path in (('zl', '/api/callins'), ('dl', '/api/callins'), ('ap', '/api/callins?level=zone&id=5')):
        status, body, _, _ = get(user, path)
        text = json.dumps(body)
        assert status == 200 and 'thank_you' not in text and 'SECRET-THANKS' not in text, (user, path)


def test_totals_seven_numbers_and_follow_up():
    _, body, _, _ = get('dl', '/api/callins')
    assert [m['key'] for m in body['metrics']] == [k for k, _ in callins.METRICS] and len(body['metrics']) == 7
    # Areas 511 and 512: actual 1 and 2, goals 2 and 3, previous goals 3 and 4.
    assert body['totals']['friends_found'] == {'previous_goal': 7, 'actual': 3, 'goal': 5}, body['totals']['friends_found']
    assert body['totals']['follow_up_lessons'] == {'previous_goal': None, 'actual': 3, 'goal': 5}
    area = body['children'][0]
    assert area['plans']['friends_found'] == 'Plan text' and area['area_update'] == 'update 511'
    assert area['missionaries'] == [{'name': 'Sister B', 'position': 'STL'}], area['missionaries']  # no other personal fields
    _, body, _, _ = get('dl', '/api/callins?level=area&id=512')
    assert body['totals']['friends_found'] == {'previous_goal': 4, 'actual': 2, 'goal': 3}
    _, body, _, _ = get('zl', '/api/callins')
    assert body['children'][0]['area_updates'] == [{'area_id': 511, 'area_name': 'Area 511', 'missionaries': [
        {'name': 'Elder A', 'position': 'DL'}], 'text': 'going well'}]
    assert body['status'] == {'district_count': 2, 'completed_district_count': 1, 'all_reports_submitted': True}


def test_gemiko_for_one_area_is_filtered():
    status, body, _, log = get('dl', '/api/callins/gemiko?level=area&id=512')
    assert status == 200 and [u['area_id'] for u in body['units']] == [512], body
    assert [a for s, a in log if 'ward_coordination' in s] == [(51, 12)]


# ---------------------------------------------------------------- saves

WEEK = {'week': '2026-09-20'}


def saves(sql):
    return [s for s in sql if re.search(r'save_|complete_dl|reopen_dl|INSERT INTO', s)]


def test_writes_refused_before_the_database():
    cases = [
        ('dl', 'PUT', '/api/callins/zones/5', {'zone_notes': 'x'}),
        ('dl', 'PUT', '/api/callins/districts/51/zl-notes', {'zl_notes': 'x'}),
        ('dl', 'PUT', '/api/callins/districts/52/dl-notes', {'dl_notes': 'x'}),
        ('dl', 'PUT', '/api/callins/areas/521/update', {'update_text': 'x'}),
        ('dl', 'POST', '/api/callins/districts/52/complete', {}),
        ('zl', 'PUT', '/api/callins/districts/51/dl-notes', {'dl_notes': 'x'}),
        ('zl', 'PUT', '/api/callins/areas/511/update', {'update_text': 'x'}),
        ('zl', 'POST', '/api/callins/districts/51/complete', {}),
        ('zl', 'POST', '/api/callins/districts/51/reopen', {}),
        ('zl', 'PUT', '/api/callins/zones/6', {'zone_notes': 'x'}),
        ('zl', 'PUT', '/api/callins/districts/61/zl-notes', {'zl_notes': 'x'}),
        ('ap', 'PUT', '/api/callins/zones/9', {'zone_notes': 'x'}),
        ('ap', 'PUT', '/api/callins/districts/91/dl-notes', {'dl_notes': 'x'}),
    ]
    for user, method, path, body in cases:
        status, answer, sql, _ = call(user, path, method, dict(WEEK, **body))
        assert status == 403, (user, path, status, answer)
        assert saves(sql) == [], (user, path, sql)
    for user in ('stl', 'missionary', 'office'):
        status, answer, sql, _ = call(user, '/api/callins/zones/5', 'PUT', dict(WEEK, zone_notes='x'))
        assert status == 403 and answer['error'] == callins.NOT_FOR_YOU and saves(sql) == [], (user, status, sql)


def test_writes_run_as_the_user_with_their_own_function():
    cases = [
        ('dl', 'PUT', '/api/callins/districts/51/dl-notes', {'dl_notes': '  Talked about faith. '},
         'SELECT public.save_dl_call_in_notes(%s,%s,%s,NULL)', (51, 12, 'Talked about faith.')),
        ('dl', 'PUT', '/api/callins/areas/512/update', {'update_text': 'Two lessons'},
         'SELECT public.save_call_in_area_update(%s,%s,%s,%s)', (51, 12, 512, 'Two lessons')),
        ('dl', 'POST', '/api/callins/districts/51/complete', {}, 'SELECT public.complete_dl_call_in(%s,%s)', (51, 12)),
        ('dl', 'POST', '/api/callins/districts/51/reopen', {}, 'SELECT public.reopen_dl_call_in(%s,%s)', (51, 12)),
        ('zl', 'PUT', '/api/callins/districts/52/zl-notes', {'zl_notes': 'Follow up'},
         'SELECT public.save_zl_call_in_notes(%s,%s,%s)', (52, 12, 'Follow up')),
        ('zl', 'PUT', '/api/callins/zones/5', {'zone_notes': ''}, 'SELECT public.save_zl_zone_call_in_notes(%s,%s,%s)', (5, 12, None)),
        ('ap', 'PUT', '/api/callins/districts/61/dl-notes', {'dl_notes': 'x'}, 'SELECT public.save_dl_call_in_notes(%s,%s,%s,NULL)', (61, 12, 'x')),
        ('ap', 'PUT', '/api/callins/districts/61/zl-notes', {'zl_notes': 'x'}, 'SELECT public.save_zl_call_in_notes(%s,%s,%s)', (61, 12, 'x')),
        ('ap', 'PUT', '/api/callins/zones/6', {'zone_notes': 'x'}, 'SELECT public.save_zl_zone_call_in_notes(%s,%s,%s)', (6, 12, 'x')),
        ('dl_da', 'PUT', '/api/callins/areas/611/update', {'update_text': 'x'}, 'SELECT public.save_call_in_area_update(%s,%s,%s,%s)', (61, 12, 611, 'x')),
    ]
    for user, method, path, body, expected_sql, expected_args in cases:
        status, answer, sql, log = call(user, path, method, dict(WEEK, **body))
        assert status == 200 and answer['ok'] is True, (user, path, status, answer)
        [args] = [a for s, a in log if s == expected_sql]
        assert args == expected_args, (path, args)
        assert sql.index('SET LOCAL ROLE authenticated') < sql.index(expected_sql), sql
        assert not any('INSERT INTO' in s for s in sql), sql  # never a direct server write any more
        assert 'thank_you' not in json.dumps(answer)


def test_save_needs_a_week_and_short_text():
    status, body, sql, _ = call('dl', '/api/callins/districts/51/dl-notes', 'PUT', {'dl_notes': 'x'})
    assert status == 400 and body == {'error': 'Choose the reporting week you are saving for.'} and saves(sql) == []
    status, body, sql, _ = call('dl', '/api/callins/districts/51/dl-notes', 'PUT', dict(WEEK, dl_notes='x' * 12001))
    assert status == 400 and '12,000' in body['error'] and saves(sql) == []
    status, body, _, _ = call('dl', '/api/callins/districts/51/dl-notes', 'PUT', dict(WEEK, dl_notes=5))
    assert status == 400 and body == {'error': 'DL notes must be text.'}
    status, body, _, _ = call('dl', '/api/callins/districts/51/dl-notes', 'PUT', {'week': '2026-09-19', 'dl_notes': 'x'})
    assert status == 404
    status, _, _, _ = call('dl', '/api/callins/districts/51/finish', 'POST', WEEK)
    assert status == 404


def test_database_refusals_become_plain_answers():
    locked = FakeError('55000', 'This call-in is marked complete. Reopen it to change the DL notes or area updates.')
    status, body, _, _ = call('dl', '/api/callins/districts/51/dl-notes', 'PUT', dict(WEEK, dl_notes='x'),
                              fail={'save_dl_call_in_notes': locked})
    assert status == 409 and body == {'error': callins.LOCKED}, (status, body)
    refused = FakeError('42501', 'You do not have permission to edit this district call-in.')
    status, body, _, _ = call('dl', '/api/callins/districts/51/dl-notes', 'PUT', dict(WEEK, dl_notes='x'),
                              fail={'save_dl_call_in_notes': refused})
    assert status == 403 and 'district leader' in body['error'], (status, body)
    legacy = FakeError('P0001', 'You do not have permission to view this district.')
    status, body, _, _ = get('zl', '/api/callins', fail={'get_zl_call_in_area_updates': legacy})
    assert status == 403 and body == {'error': callins.OUTSIDE}, (status, body)
    outside = FakeError('42501', 'This zone is outside your stewardship.')
    status, body, _, _ = get('zl', '/api/callins', fail={'get_zl_call_in_summary_with_planning': outside})
    assert status == 403 and body == {'error': callins.OUTSIDE}
    other = FakeError('XX000', 'internal')
    status, body, _, _ = get('zl', '/api/callins', fail={'get_zl_call_in_summary_with_planning': other})
    assert status == 500 and body == {'error': 'The request could not be completed. Please retry.'}


# ---------------------------------------------------------------- the page (static checks; the behaviour is checked in Edge)

PAGE = Path(__file__).resolve().parents[2] / 'portal' / 'callins.html'


def page_css():
    return re.search(r'<style>(.*?)</style>', PAGE.read_text(encoding='utf-8'), re.S).group(1)


def test_page_touch_targets_are_44px():
    if not PAGE.exists():  # only portal-api is mounted (mount the portal folder at /portal to include this check)
        print('  (skipped: portal/callins.html is not mounted)')
        return
    small = []
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', page_css(), flags=re.S)):
        tappable = any(word in selectors for word in ('button', 'summary', 'select', '.go'))
        for value in re.findall(r'min-height:\s*(\d+)px', body):
            if tappable and int(value) < 44:
                small.append((' '.join(selectors.split()), value))
    assert small == [], small
    inputs = re.search(r'textarea,\s*select,\s*input\s*\{([^}]*)\}', page_css()).group(1)
    assert 'font-size: 16px' in inputs, inputs  # no zoom-in on phones


def test_page_keeps_text_when_a_save_finds_the_call_in_completed():
    if not PAGE.exists():
        print('  (skipped: portal/callins.html is not mounted)')
        return
    script = PAGE.read_text(encoding='utf-8')
    save = re.search(r'async function saveField\(id\) \{(.*?)\n      \}\n', script, re.S).group(1)
    locked = save[save.index('error.status === 409'):]
    # The typed text is kept (and shown again), and nothing reloads the page on a timer behind the leader's back.
    assert 'kept: true' in locked.split('return "locked"')[0], locked[:400]
    assert 'setTimeout' not in save and 'drafts.delete' not in locked.split('return "locked"')[0]


# ---------------------------------------------------------------- the rules themselves

def test_rule_helpers():
    v = lambda user: callins.viewer(dict(CONTEXTS[user]))
    chain = {'mission_id': 1, 'zone_id': 5, 'district_id': 51}
    assert callins.may_write_dl(v('dl'), chain) and not callins.may_write_zl(v('dl'), chain)
    assert callins.may_write_zl(v('zl'), chain) and not callins.may_write_dl(v('zl'), chain)
    assert callins.may_write_dl(v('ap'), chain) and callins.may_write_zl(v('ap'), chain)
    assert not callins.may_write_dl(v('ap'), {'mission_id': 2, 'zone_id': 9, 'district_id': 91})
    assert callins.may_write_dl(v('dl_da'), {'mission_id': 1, 'zone_id': 6, 'district_id': 61})  # Data Analyst: whole mission
    assert not callins.may_write_zl(v('zl_office'), {'mission_id': 1, 'zone_id': 6})  # Office gives no Call-ins rights
    assert v('zl_office')['manager'] is False


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_') and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print('ok', test.__name__)
        except Exception as exc:  # keep going so a run shows every failing check
            failed += 1
            print('FAIL', test.__name__, '-', type(exc).__name__, str(exc)[:600])
    print(f'{len(tests) - failed} of {len(tests)} tests passed')
    sys.exit(1 if failed else 0)
