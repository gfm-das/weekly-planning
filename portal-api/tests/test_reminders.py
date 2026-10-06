"""Unit checks for calendar reminder timing and audience (no database, no push service).

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_reminders.py
pytest works too: python -m pytest portal-api/tests/test_reminders.py
"""
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.exceptions import Forbidden  # noqa: E402

import app  # noqa: E402
import reminders  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)  # a Wednesday, 19:00 in Berlin
MINUTE = timedelta(minutes=1)
MISSION = 1


def person(user_id, app_role='MISSIONARY', leadership_role=None, zone=None, district=None, area=None, additional=()):
    return {'user_id': user_id, 'app_role': app_role, 'leadership_role': leadership_role, 'mission_id': MISSION,
            'zone_id': zone, 'district_id': district, 'area_id': area, 'additional_roles': list(additional)}


ZL = person('zl', leadership_role='ZL', zone=5, district=51, area=511)
COMPANION = person('companion', zone=5, district=52, area=521)
OTHER_ZONE = person('other', zone=6, district=61, area=611)
AP = person('ap', app_role='AP', leadership_role='AP', zone=6, district=61, area=612)
OFFICE = person('office', app_role='OFFICE')          # no area
PRESIDENT = person('president', app_role='PRESIDENT')  # no area
DATA_ADMIN = person('da', app_role='DATA_ADMIN')      # no area
# Additional roles (migration 021): a DL who also works in the office, and a missionary who is the Data Analyst.
DL_OFFICE = person('dl-office', leadership_role='DL', zone=5, district=52, area=522, additional=['OFFICE'])
ANALYST = person('analyst', zone=6, district=61, area=613, additional=['DATA_ADMIN'])


def event(key, start, minutes, reminder=30, roles=(), zones=(), recurrence=None, mission=MISSION, location=''):
    return {'id': key, 'mission_id': mission, 'author_id': 'ap', 'title': key, 'description': '',
            'starts_at': start, 'ends_at': start + timedelta(minutes=minutes), 'timezone': 'Europe/Berlin',
            'recurrence': recurrence, 'roles': list(roles), 'zone_ids': list(zones), 'location': location,
            'meeting_url': '', 'reminder_minutes': reminder}


def due_ids(events, c, now=NOW):
    return sorted(e['id'] for e in reminders.due_events(events, c, now))


def test_at_start_reminder_is_due_at_and_shortly_after_the_start_only():
    start = NOW
    assert not reminders.reminder_due(start, 0, start - MINUTE)
    assert reminders.reminder_due(start, 0, start)
    assert reminders.reminder_due(start, 0, start + 4 * MINUTE)
    assert not reminders.reminder_due(start, 0, start + reminders.REMINDER_GRACE)


def test_earlier_reminders_keep_their_window_before_the_start():
    start = NOW + 30 * MINUTE
    assert not reminders.reminder_due(start, 30, NOW - MINUTE)
    assert reminders.reminder_due(start, 30, NOW)
    assert reminders.reminder_due(start, 30, start - MINUTE)
    assert not reminders.reminder_due(start, 30, start)
    # A one-minute reminder is not lost between two runs of the once-a-minute loop.
    assert reminders.reminder_due(NOW, 1, NOW + 3 * MINUTE)
    assert not reminders.reminder_due(NOW, 1, NOW + 4 * MINUTE)


def test_at_start_event_occurrences():
    started = event('started-2-min-ago', NOW - 2 * MINUTE, 60, reminder=0)
    later = event('starts-in-10-min', NOW + 10 * MINUTE, 60, reminder=0)
    old = event('started-10-min-ago', NOW - 10 * MINUTE, 60, reminder=0)
    short = event('already-over', NOW - 3 * MINUTE, 2, reminder=0)
    assert due_ids([started, later, old, short], COMPANION) == ['started-2-min-ago']
    # A weekly "At start" meeting is due on today's occurrence even though the series began weeks ago.
    weekly = event('weekly', NOW - timedelta(days=21), 60, reminder=0,
                   recurrence={'frequency': 'weekly', 'interval': 1, 'until': (NOW + timedelta(days=60)).isoformat()})
    [occurrence] = reminders.due_events([weekly], COMPANION, NOW + MINUTE)
    assert occurrence['starts_at'] == NOW


def test_only_the_event_audience_is_reminded():
    zone5 = event('zone-5-council', NOW + 10 * MINUTE, 60, zones=[5])
    office = event('office-only', NOW + 10 * MINUTE, 60, roles=['OFFICE'])
    leaders = event('zone-leaders', NOW + 10 * MINUTE, 60, roles=['ZL'], zones=[5])
    everyone = event('mission-wide', NOW + 10 * MINUTE, 60)
    elsewhere = event('other-mission', NOW + 10 * MINUTE, 60, mission=2)
    events = [zone5, office, leaders, everyone, elsewhere]
    assert due_ids(events, ZL) == ['mission-wide', 'zone-5-council', 'zone-leaders']
    assert due_ids(events, COMPANION) == ['mission-wide', 'zone-5-council']
    assert due_ids(events, OTHER_ZONE) == ['mission-wide']
    # Managers and the office may see or edit every event, but are reminded only when it targets them.
    assert due_ids(events, AP) == ['mission-wide']
    assert due_ids(events, OFFICE) == ['mission-wide', 'office-only']
    assert due_ids(events, PRESIDENT) == ['mission-wide']


def test_additional_roles_join_the_audience():
    office = event('office-only', NOW + 10 * MINUTE, 60, roles=['OFFICE'])
    dls = event('district-leaders', NOW + 10 * MINUTE, 60, roles=['DL'])
    analysts = event('data-analysts', NOW + 10 * MINUTE, 60, roles=['DATA_ADMIN'])
    zone6 = event('zone-6-council', NOW + 10 * MINUTE, 60, zones=[6])
    events = [office, dls, analysts, zone6]
    # An event for the office reaches a DL who also works in the office, and one for DLs too.
    assert due_ids(events, DL_OFFICE) == ['district-leaders', 'office-only']
    assert due_ids(events, ANALYST) == ['data-analysts', 'zone-6-council']
    assert due_ids(events, OFFICE) == ['office-only']
    # Managers and calendar editors see every event of the mission, whatever its audience.
    for c in (DL_OFFICE, ANALYST):
        assert all(app.visible(e, c, event=True) for e in events)
    assert not app.visible(analysts, ZL, event=True)


def test_message_says_now_for_at_start_reminders():
    assert reminders.event_message(event('a', NOW, 60, reminder=0)) == 'Your mission meeting starts now.'
    assert reminders.event_message(event('a', NOW, 60, reminder=15)) == 'Your mission meeting starts soon.'
    assert reminders.event_message(event('a', NOW, 60, reminder=0, location='Chapel')) == 'Chapel'


# One reminder cycle with a stand-in database: which reminders go to whom.
CYCLE_EVENTS = [
    event('zone-5-at-start', NOW - 2 * MINUTE, 60, reminder=0, zones=[5]),
    event('zone-5-in-15-min', NOW + 15 * MINUTE, 60, reminder=30, zones=[5]),
    event('mission-devotional', NOW + 20 * MINUTE, 60, reminder=30),
    event('office-at-start-later', NOW + 10 * MINUTE, 60, reminder=0, roles=['OFFICE']),
]
CONTEXTS = {c['user_id']: c for c in (ZL, AP, OFFICE, PRESIDENT, DATA_ADMIN)}


def fake_rows(conn, sql, args=()):
    if 'pg_try_advisory_xact_lock' in sql:
        return [{'locked': True}]
    if 'FROM public.current_user_context' in sql:
        users = list(CONTEXTS.values()) + [{'user_id': 'no-mission', 'area_id': None}]
        if 'area_id IS NOT NULL' in sql:
            users = [u for u in users if u.get('area_id')]
        return [{'user_id': u['user_id']} for u in users]
    if 'FROM portal.events' in sql:
        return [dict(e) for e in CYCLE_EVENTS]
    return []  # savepoints, attachments


def fake_context(conn, user_id):
    # The office, president and data-office accounts here are given a mission although they have no area. Real
    # context_for finds a mission only through an area or an AP assignment, so on Beta today such accounts are
    # refused like 'no-mission' below (by the portal as well). This checks that reminders.py itself does not
    # leave them out once they have a mission.
    if user_id not in CONTEXTS:
        raise Forbidden('A mission assignment is required.')
    return dict(CONTEXTS[user_id], mission_id=MISSION)


@contextmanager
def fake_db():
    yield object()


def run_cycle():
    sent, planning_checked = [], []

    def fake_push(conn, user_id, kind, reference, title, body, url):
        sent.append((user_id, kind, reference.split(':')[0]))
        return True

    def fake_planning(conn, c, now):
        planning_checked.append(c['user_id'])
        return False, None

    with patch.object(reminders, 'rows', fake_rows), patch.object(app, 'rows', fake_rows), \
            patch.object(reminders, 'db', fake_db), patch.object(reminders, 'context_for', fake_context), \
            patch.object(reminders, 'push', fake_push), patch.object(reminders, 'planning_due', fake_planning), \
            patch.object(reminders.log, 'exception') as logged:
        result = reminders.run_once(NOW)
    return result, sorted(sent), sorted(planning_checked), logged.call_count


def test_one_cycle_sends_to_the_audience_including_area_less_accounts_that_have_a_mission():
    result, sent, planning_checked, errors = run_cycle()
    assert sent == [('ap', 'event', 'mission-devotional'),
                    ('da', 'event', 'mission-devotional'),
                    ('office', 'event', 'mission-devotional'),
                    ('president', 'event', 'mission-devotional'),
                    ('zl', 'event', 'mission-devotional'),
                    ('zl', 'event', 'zone-5-at-start'),
                    ('zl', 'event', 'zone-5-in-15-min')], sent
    assert result == {'planning_due': 0, 'event_due': 7, 'sent': 7}
    # Weekly Planning is only checked for accounts with an area; an account without a mission is skipped quietly.
    assert planning_checked == ['ap', 'zl'] and errors == 0


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_') and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print('ok', test.__name__)
        except Exception as exc:  # keep going so a run shows every failing check
            failed += 1
            print('FAIL', test.__name__, '-', type(exc).__name__, str(exc)[:300])
    print(f'{len(tests) - failed} of {len(tests)} tests passed')
    sys.exit(1 if failed else 0)
