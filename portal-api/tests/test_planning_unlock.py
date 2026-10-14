"""Unit checks for the scoped, logged unlock of a Weekly Planning plan (planning.unlock_planning_report, roles.may_unlock_plan)
without a database: who may reopen which plan, locked plans for managers only, the note, and the logged database function.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_planning_unlock.py
pytest works too: python -m pytest portal-api/tests/test_planning_unlock.py
"""
import base64
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import planning  # noqa: E402
import roles  # noqa: E402

M = {'mission_id': 1}
CONTEXTS = {
    'ap': dict(M, app_role='AP', leadership_role='AP'),
    'president': dict(M, app_role='PRESIDENT', leadership_role=None),
    'data_admin': dict(M, app_role='DATA_ADMIN', leadership_role=None),
    'zl': dict(M, app_role='MISSIONARY', leadership_role='ZL', leadership_zone_id=5, zone_id=5, district_id=51),
    'dl': dict(M, app_role='MISSIONARY', leadership_role='DL', leadership_district_id=51, zone_id=5, district_id=51),
    'stl': dict(M, app_role='MISSIONARY', leadership_role='STL', leadership_zone_id=5, zone_id=5),
    'office': dict(M, app_role='OFFICE', leadership_role=None),
    'missionary': dict(M, app_role='MISSIONARY', leadership_role=None, zone_id=5, district_id=51, area_id=511),
    'other_mission_ap': dict(mission_id=2, app_role='AP', leadership_role='AP'),
}
# Plans: id -> (status, area, district, zone, mission)
PLANS = {
    1: ('SUBMITTED', 511, 51, 5, 1),   # the DL's and ZL's own
    2: ('SUBMITTED', 521, 52, 5, 1),   # same zone, other district
    3: ('SUBMITTED', 611, 61, 6, 1),   # other zone
    4: ('LOCKED', 511, 51, 5, 1),
    5: ('DRAFT', 511, 51, 5, 1),
    6: ('SUBMITTED', 911, 91, 9, 2),   # another mission
}


class FakeConn:
    def __init__(self):
        self.log = []

    def cursor(self):
        return FakeCursor(self)


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
        self.description, self.result = None, []
        if 'FROM public.weekly_area_reports war JOIN public.areas' in flat:
            plan = PLANS.get(args[0])
            if plan:
                self.description = [(c,) for c in ('id', 'status', 'area_id', 'district_id', 'zone_id', 'mission_id')]
                self.result = [(args[0], plan[0], plan[1], plan[2], plan[3], plan[4])]
        elif 'reopen_weekly_report_logged' in flat:
            self.description = [(c,) for c in ('weekly_report_id', 'status', 'previous_status')]
            self.result = [(args[0], 'DRAFT', PLANS[args[0]][0])]

    def fetchall(self):
        return self.result


def unlock(user, report_id, note=None):
    conn = FakeConn()
    result = planning.unlock_planning_report(conn, CONTEXTS[user], report_id, note)
    return result, conn.log


def refused(user, report_id, note=None, error=PermissionError):
    conn = FakeConn()
    try:
        planning.unlock_planning_report(conn, CONTEXTS[user], report_id, note)
    except error as exc:
        return str(exc), conn.log
    raise AssertionError(f'{user} should have been refused for plan {report_id}')


def logged(log):
    return [entry for entry in log if 'reopen_weekly_report_logged' in entry[0]]


def test_a_dl_unlocks_only_their_district():
    result, log = unlock('dl', 1)
    assert result['status'] == 'DRAFT' and result['previous_status'] == 'SUBMITTED', result
    for plan in (2, 3, 6):
        message, log = refused('dl', plan)
        assert message == 'This plan is outside your stewardship.' and not logged(log), (plan, message)


def test_a_zl_unlocks_only_their_zone():
    assert unlock('zl', 1)[0]['status'] == 'DRAFT' and unlock('zl', 2)[0]['status'] == 'DRAFT'
    for plan in (3, 6):
        message, log = refused('zl', plan)
        assert message == 'This plan is outside your stewardship.' and not logged(log)


def test_managers_unlock_the_whole_mission_but_not_another_mission():
    for user in ('ap', 'president', 'data_admin'):
        for plan in (1, 2, 3):
            assert unlock(user, plan)[0]['status'] == 'DRAFT', (user, plan)
        assert refused(user, 6)[0] == 'This plan is outside your stewardship.'
    assert unlock('other_mission_ap', 6)[0]['status'] == 'DRAFT'
    assert refused('other_mission_ap', 1)[0] == 'This plan is outside your stewardship.'


def test_a_locked_plan_is_for_managers_only():
    for user in ('ap', 'president', 'data_admin'):
        result, log = unlock(user, 4)
        assert result['previous_status'] == 'LOCKED' and len(logged(log)) == 1, (user, result)
    for user in ('dl', 'zl'):
        message, log = refused(user, 4)
        assert message == planning.LOCKED_UNLOCK_MESSAGE and not logged(log), (user, message)


def test_missionaries_stls_and_office_cannot_unlock():
    for user in ('missionary', 'stl', 'office'):
        message, log = refused(user, 1)
        assert message == 'A leader must unlock a submitted plan.' and log == [], (user, message)


def test_a_draft_cannot_be_reopened():
    message, log = refused('ap', 5, error=ValueError)
    assert message == 'Only a submitted plan can be reopened.' and not logged(log)


def test_unknown_plan_is_outside_stewardship():
    assert refused('ap', 999)[0] == 'This plan is outside your stewardship.'


def test_the_unlock_goes_through_the_logged_function_with_the_note():
    result, log = unlock('dl', 1, '  Fix the goal  ')
    assert logged(log) == [('SELECT * FROM public.reopen_weekly_report_logged(%s, %s)', (1, 'Fix the goal'))], log
    assert not any('unsubmit_weekly_report' in sql for sql, _ in log)
    assert unlock('dl', 1, '   ')[1][-1][1] == (1, None)
    assert unlock('dl', 1)[1][-1][1] == (1, None)


def test_the_note_is_short_text():
    assert refused('dl', 1, 'x' * 501, ValueError)[0] == planning.UNLOCK_NOTE_MESSAGE
    assert refused('dl', 1, 12, ValueError)[0] == planning.UNLOCK_NOTE_MESSAGE
    assert unlock('dl', 1, 'x' * 500)[0]['status'] == 'DRAFT'


def test_may_unlock_plan_rules():
    where = {'mission_id': 1, 'zone_id': 5, 'district_id': 51}
    assert roles.may_unlock_plan(CONTEXTS['dl'], where) and roles.may_unlock_plan(CONTEXTS['zl'], where)
    assert roles.may_unlock_plan(CONTEXTS['ap'], where)
    assert not roles.may_unlock_plan(CONTEXTS['stl'], where) and not roles.may_unlock_plan(CONTEXTS['office'], where)
    assert not roles.may_unlock_plan(CONTEXTS['missionary'], where)
    # A DL who is also Data Analyst unlocks across the mission; Office adds nothing.
    dl_da = dict(CONTEXTS['dl'], additional_roles=['DATA_ADMIN'])
    assert roles.may_unlock_plan(dl_da, {'mission_id': 1, 'zone_id': 6, 'district_id': 61})
    dl_office = dict(CONTEXTS['dl'], additional_roles=['OFFICE'])
    assert not roles.may_unlock_plan(dl_office, {'mission_id': 1, 'zone_id': 6, 'district_id': 61})
    assert not roles.may_unlock_plan(CONTEXTS['dl'], {'mission_id': 1, 'zone_id': 5, 'district_id': None})


def test_the_route_passes_the_note_and_reports_refusals():
    import app
    conn = FakeConn()

    @contextmanager
    def fake_user_db():
        yield conn

    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip('=')
    token = enc({'alg': 'none'}) + '.' + enc({'sub': 'u', 'role': 'authenticated'}) + '.x'
    identity = lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'id': '00000000-0000-0000-0000-000000000001'})

    def post(user, report_id, body):
        conn.log.clear()
        with patch.object(app.requests, 'get', identity), patch.object(app, 'user_db', fake_user_db), \
                patch.object(app, 'db', fake_user_db), patch.object(app, 'context_for', lambda c, u: dict(CONTEXTS[user])):
            response = app.app.test_client().post(f'/api/planning/reports/{report_id}/unlock', json=body,
                                                  headers={'Authorization': 'Bearer ' + token})
        return response.status_code, response.get_json(silent=True)

    status, body = post('dl', 1, {'note': 'because'})
    assert status == 200 and body['status'] == 'DRAFT' and conn.log[-1][1] == (1, 'because'), (status, body, conn.log)
    assert post('dl', 1, None)[0] == 200 and conn.log[-1][1] == (1, None)
    assert post('dl', 3, {})[0] == 403
    assert post('dl', 4, {})[0] == 403
    assert post('ap', 4, {})[0] == 200
    assert post('dl', 1, {'note': 'x' * 600})[0] == 400


def test_the_migration_logs_in_the_same_transaction_and_locks_the_table_down():
    sql = (Path(__file__).resolve().parents[1] / 'migrations' / '049_planning_unlock_log.sql').read_text(encoding='utf-8')
    assert sql.count('BEGIN;') == 1 and sql.rstrip().endswith('COMMIT;')
    assert 'PERFORM public.reopen_weekly_report(target_report_id)' in sql, 'the existing stewardship check does the unlock'
    assert sql.index('PERFORM public.reopen_weekly_report') < sql.index('INSERT INTO public.planning_unlock_log')
    assert 'SECURITY DEFINER' in sql and 'REVOKE EXECUTE ON FUNCTION public.reopen_weekly_report_logged(bigint, text) FROM PUBLIC' in sql
    assert 'ENABLE ROW LEVEL SECURITY' in sql and 'REVOKE ALL ON public.planning_unlock_log FROM PUBLIC, anon, authenticated' in sql
    down = (Path(__file__).resolve().parents[1] / 'migrations' / '049_planning_unlock_log_rollback.sql').read_text(encoding='utf-8')
    assert 'DROP FUNCTION IF EXISTS public.reopen_weekly_report_logged' in down and 'DROP TABLE IF EXISTS public.planning_unlock_log' in down


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
