"""Unit checks for the read-only Vollzogen list (vollzogen.py, GET /api/vollzogen) without a database: who may ask, that
nothing can be written, the filters, the fixed columns, and the page. The database side is in vollzogen_view_db.py.

Run in the portal-api image (no pytest needed):
  docker run --rm --network none -v <repo>/portal-api:/app -v <repo>/portal:/portal -w /app gfm-portal-portal-api python tests/test_vollzogen_view.py
pytest works too: python -m pytest portal-api/tests/test_vollzogen_view.py
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import app  # noqa: E402
import roles  # noqa: E402
import vollzogen  # noqa: E402

M = {'mission_id': 1}
CONTEXTS = {
    'office': dict(M, app_role='OFFICE', leadership_role=None),
    'office_extra': dict(M, app_role='MISSIONARY', leadership_role=None, additional_roles=['OFFICE']),
    'data_admin': dict(M, app_role='DATA_ADMIN', leadership_role=None),
    'ap': dict(M, app_role='AP', leadership_role='AP'),
    'president': dict(M, app_role='PRESIDENT', leadership_role=None),
    'dl_da': dict(M, app_role='MISSIONARY', leadership_role='DL', leadership_district_id=51, additional_roles=['DATA_ADMIN']),
    'dl': dict(M, app_role='MISSIONARY', leadership_role='DL', leadership_district_id=51),
    'zl': dict(M, app_role='MISSIONARY', leadership_role='ZL', leadership_zone_id=5),
    'stl': dict(M, app_role='MISSIONARY', leadership_role='STL', leadership_zone_id=5),
    'missionary': dict(M, app_role='MISSIONARY', leadership_role=None),
    'ap_without_assignment': dict(M, app_role='AP', leadership_role=None),
}
ALLOWED = ('office', 'office_extra', 'data_admin', 'ap', 'president', 'dl_da')
REFUSED = ('dl', 'zl', 'stl', 'missionary', 'ap_without_assignment')
# Invented people only.
PEOPLE = [
    {'full_name': 'Test Person One', 'baptismal_date_set_on': date(2026, 9, 1), 'baptism_date': date(2026, 9, 20), 'found_how': 'Street',
     'workers': 'Elder A, Elder B', 'unit': 'Sample Ward', 'stake': 'Sample Stake', 'zone': 'Zone 5', 'confirmed': True,
     'country': 'Testland', 'gender': 'F', 'preferred_language': 'English'},
    {'full_name': 'Test Person Two', 'baptismal_date_set_on': None, 'baptism_date': date(2026, 9, 13), 'found_how': None,
     'workers': 'Sister C', 'unit': 'South Ward', 'stake': 'Sample Stake', 'zone': 'Zone 6', 'confirmed': False,
     'country': None, 'gender': 'M', 'preferred_language': 'German'},
]


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self.result = conn, None, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        flat = ' '.join(sql.split())
        self.conn.log.append((flat, args))
        if 'SELECT DISTINCT (v.baptism_date' in flat:
            self.description, self.result = [('sunday',)], [(date(2026, 9, 20),), (date(2026, 9, 13),)]
        elif 'SELECT DISTINCT to_char(v.baptism_date' in flat:
            self.description, self.result = [('month',)], [('2026-09',), ('2025-12',)]
        elif 'SELECT DISTINCT v.zone' in flat:
            self.description, self.result = [('zone',)], [('Zone 5',), ('Zone 6',)]
        elif 'FROM public.vollzogen_records v' in flat:
            mission, week, _, zone = args[0], args[1], args[2], args[3]
            rows = [p for p in PEOPLE if mission == 1 and (zone is None or p['zone'] == zone)]
            columns = vollzogen.COLUMNS
            self.description = [(c,) for c in columns]
            self.result = [tuple(r[c] for c in columns) for r in rows]
        else:
            raise AssertionError('unexpected SQL: ' + flat)

    def fetchall(self):
        return self.result


class FakeConn:
    def __init__(self):
        self.log = []

    def cursor(self):
        return FakeCursor(self)


def call(user, path, method='GET', body=None):
    conn = FakeConn()

    @contextmanager
    def fake_db():
        yield conn

    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip('=')
    token = enc({'alg': 'none'}) + '.' + enc({'sub': user, 'role': 'authenticated'}) + '.x'
    identity = lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'id': '00000000-0000-0000-0000-000000000001'})
    context = dict(CONTEXTS[user], user_id=user)
    with patch.object(app.requests, 'get', identity), patch.object(app, 'db', fake_db), \
            patch.object(app, 'context_for', lambda c, u: dict(context)):
        response = app.app.test_client().open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token})
    return response.status_code, response.get_json(silent=True), [sql for sql, _ in conn.log], conn.log


def test_office_and_managers_get_the_list_read_only():
    for user in ALLOWED:
        status, body, sql, _ = call(user, '/api/vollzogen')
        assert status == 200 and body['read_only'] is True, (user, status, body)
        assert [i['full_name'] for i in body['items']] == ['Test Person One', 'Test Person Two'], (user, body['items'])
        assert body['weeks'] == ['2026-09-20', '2026-09-13'] and body['zones'] == ['Zone 5', 'Zone 6']
        assert not any(s.startswith(('UPDATE', 'INSERT', 'DELETE')) for s in sql), sql


def test_nobody_else_gets_it_and_no_query_runs():
    for user in REFUSED:
        status, body, sql, _ = call(user, '/api/vollzogen')
        assert status == 403 and body['error'] == vollzogen.NOT_FOR_YOU, (user, status, body)
        assert sql == [], sql


def test_only_get_exists():
    for user in ('office', 'data_admin', 'dl'):
        for method in ('PUT', 'POST', 'DELETE', 'PATCH'):
            status, _, sql, _ = call(user, '/api/vollzogen', method=method, body={})
            assert status == 405 and sql == [], (user, method, status)


def test_only_the_fixed_columns_are_returned_never_the_fc_number_or_the_link():
    status, body, _, log = call('office', '/api/vollzogen')
    assert set(body['items'][0]) == set(vollzogen.COLUMNS)
    select = next(sql for sql, _ in log if 'FROM public.vollzogen_records v' in sql and 'v.full_name,' in sql)
    for hidden in ('fc_number', 'record_key', 'new_member_id', 'matched_how', 'updated_by'):
        assert hidden not in select, hidden


def test_the_query_is_limited_to_the_viewers_mission_and_uses_parameters():
    status, body, _, log = call('office', '/api/vollzogen?q=%27%3B%20DROP%20TABLE%20x%3B--&zone=Zone%205&week=2026-09-20')
    assert status == 200, body
    sql, args = next((s, a) for s, a in log if 'v.full_name,' in s)
    assert 'v.mission_id=%s' in sql and args[0] == 1
    assert "DROP" not in sql and any('DROP TABLE' in str(a) for a in args)  # the text travels as a value only
    assert body['filter'] == {'week': '2026-09-20', 'zone': 'Zone 5', 'q': "'; DROP TABLE x;--"}


def test_filters_by_zone_and_checks_the_input():
    status, body, _, _ = call('office', '/api/vollzogen?zone=Zone%206')
    assert status == 200 and [i['zone'] for i in body['items']] == ['Zone 6']
    assert call('office', '/api/vollzogen?week=garbage')[0] == 400
    assert call('office', '/api/vollzogen?week=2026-02-30')[0] == 400
    assert call('office', '/api/vollzogen?q=' + 'x' * 101)[0] == 400
    assert call('office', '/api/vollzogen?zone=' + 'z' * 201)[0] == 400
    assert vollzogen.like_pattern('50%_a\\b') == '%50\\%\\_a\\\\b%'


def test_roles_office_is_not_a_manager():
    assert roles.can_view_vollzogen(CONTEXTS['office']) and not roles.is_manager(CONTEXTS['office'])
    assert not roles.can_view_vollzogen(CONTEXTS['dl']) and not roles.can_view_vollzogen(CONTEXTS['zl'])
    caps = roles.capabilities(CONTEXTS['office'])
    assert caps['vollzogen_view'] is True and caps['manager'] is False and caps['dashboards'] is False and caps['callins'] is False
    assert roles.capabilities(CONTEXTS['dl'])['vollzogen_view'] is False
    assert roles.capabilities(CONTEXTS['dl_da'])['vollzogen_view'] is True
    assert not hasattr(roles, 'can_view_completed_callins')


def test_the_old_completed_call_ins_route_is_gone():
    status, _, sql, _ = call('office', '/api/callins/completed')
    assert status in (403, 404) and sql == [], status
    assert not (Path(__file__).resolve().parents[2] / 'portal' / 'callins-completed.html').exists()


def test_the_page_has_no_edit_controls_and_uses_the_list_route():
    page = (Path(__file__).resolve().parents[2] / 'portal' / 'vollzogen.html').read_text(encoding='utf-8')
    assert 'vollzogen' in page and 'portalAPI' in page
    assert not re.search(r'<(textarea|button)\b|method:\s*["\'](PUT|POST|DELETE)', page, re.I), 'read-only page'
    assert not re.search(r'fc_number|record_key', page)
    assert page.count('<input') == 1  # only the search box



def test_the_period_filter_months_years_and_this_week():
    with patch.object(vollzogen, 'today', lambda: date(2026, 10, 17)):  # a Saturday
        status, body, _, log = call('office', '/api/vollzogen')
        assert status == 200 and body['period'] == 'all'
        assert body['months'] == ['2026-10', '2026-09', '2025-12']  # this month is always offered
        assert body['years'] == ['2026', '2025']
        assert body['this_month'] == '2026-10'
        assert body['this_week'] == {'sunday': '2026-10-11', 'saturday': '2026-10-17'}  # the portal's Sunday-to-Saturday week
        args = next(a for s, a in log if 'v.full_name,' in s)
        assert args[-4:-1] == (None, None, None)  # no period: no date limit
        for asked, period, start, end in (('month', '2026-10', date(2026, 10, 1), date(2026, 11, 1)),
                                          ('2026-12', '2026-12', date(2026, 12, 1), date(2027, 1, 1)),
                                          ('2025', '2025', date(2025, 1, 1), date(2026, 1, 1))):
            status, body, _, log = call('office', '/api/vollzogen?period=' + asked)
            assert status == 200 and body['period'] == period, (asked, body)
            args = next(a for s, a in log if 'v.full_name,' in s)
            assert args[-4:-1] == (start, start, end), (asked, args)
            weeks = next(a for s, a in log if 'SELECT DISTINCT (v.baptism_date' in s)
            assert weeks[1:4] == (start, start, end), weeks  # the week list only holds weeks of the period
        for bad in ('garbage', '2026-13', '2026-1', '26', '2026-10-01'):
            assert call('office', '/api/vollzogen?period=' + bad)[0] == 400, bad
    assert vollzogen.this_week(date(2026, 10, 11)) == {'sunday': date(2026, 10, 11), 'saturday': date(2026, 10, 17)}
    assert vollzogen.this_week(date(2026, 10, 12))['sunday'] == date(2026, 10, 11)


def test_the_page_chooses_a_period_and_marks_this_week():
    page = (Path(__file__).resolve().parents[2] / 'portal' / 'vollzogen.html').read_text(encoding='utf-8')
    assert re.search(r'<select id="period">\s*<option value="month">', page)  # this month is the default
    assert 'period=' in page and 'this_week' in page and 'class="this-week-badge"' in page

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
