"""Unit checks for the known-issue fixes of round 2 (no database, no push service).

Attachment names keep letters such as ä; one date of a repeating event can be deleted; reminders keep a device on a
network error and forget it when the push service reports it gone; New Members are archived once a day.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_known_issues.py
"""
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests  # noqa: E402
from pywebpush import WebPushException  # noqa: E402

import app  # noqa: E402
import reminders  # noqa: E402

UTC = timezone.utc
BERLIN = app.ZoneInfo('Europe/Berlin')


# Attachment names ---------------------------------------------------------------------------------------------

def test_attachment_names_keep_unicode_letters():
    assert app.attachment_name('Präsentation Größe ÄÖÜ.pdf') == 'Präsentation Größe ÄÖÜ.pdf'
    assert app.attachment_name('Zeugnis – Łódź, São Paulo, Ñandú.docx') == 'Zeugnis – Łódź, São Paulo, Ñandú.docx'
    assert app.attachment_name('会议记录.pdf') == '会议记录.pdf'
    assert app.attachment_name('Привет мир.txt') == 'Привет мир.txt'


def test_attachment_names_are_nfc():
    # macOS sends "ä" as "a" plus a combining mark; it is stored as one letter.
    decomposed = unicodedata.normalize('NFD', 'Bericht März.pdf')
    assert decomposed != 'Bericht März.pdf'
    assert app.attachment_name(decomposed) == 'Bericht März.pdf'


def test_attachment_names_drop_folders_and_unsafe_characters():
    assert app.attachment_name('../../etc/passwd') == 'passwd'
    assert app.attachment_name('C:\\Users\\Elder\\Plan für Sonntag.xlsx') == 'Plan für Sonntag.xlsx'
    assert app.attachment_name('a"b<c>d:e|f?g*.pdf') == 'a_b_c_d_e_f_g_.pdf'
    assert app.attachment_name('line\nbreak\ttab\x00.txt') == 'line break tab .txt'
    # A right-to-left override could make "report\u202egpj.exe" look like "reportexe.jpg".
    assert app.attachment_name('report\u202egpj.exe') == 'report gpj.exe'
    # Zero-width joiners are part of some scripts' spelling and stay.
    assert app.attachment_name('ف\u200cا.pdf') == 'ف\u200cا.pdf'
    assert app.attachment_name('क्\u200dष.pdf') == 'क्\u200dष.pdf'


def test_attachment_names_are_never_empty_or_reserved():
    for value in ('', None, '   ', '...', '/', '\\\\'):
        assert app.attachment_name(value) == 'attachment', value
    assert app.attachment_name(' .hidden. ') == 'hidden'
    assert app.attachment_name('CON.txt') == '_CON.txt'
    assert app.attachment_name('lpt1') == '_lpt1'
    assert app.attachment_name('Console.txt') == 'Console.txt'


def test_long_attachment_names_keep_their_extension():
    name = app.attachment_name('Ä' * 400 + '.pdf')
    assert len(name) == app.ATTACHMENT_NAME_LIMIT and name.endswith('.pdf') and name.startswith('ÄÄÄ')
    assert len(app.attachment_name('x' * 400)) == app.ATTACHMENT_NAME_LIMIT


def test_download_header_uses_rfc5987_for_unicode_names():
    # The portal-api download sends the stored name through Werkzeug (send_file).
    with app.app.test_request_context():
        response = app.send_file(__file__, as_attachment=True, download_name='Präsentation Größe.pdf')
        header = response.headers['Content-Disposition']
        response.close()
    assert "filename*=UTF-8''Pr%C3%A4sentation%20Gr%C3%B6%C3%9Fe.pdf" in header, header
    assert 'filename="Prasentation Groe.pdf"' in header or 'filename=Prasentation' in header, header


# Deleting one date of a repeating event --------------------------------------------------------------------------

def weekly(skipped=()):
    start = datetime(2026, 10, 11, 10, 0, tzinfo=BERLIN)  # Sundays 10:00 Berlin, across the end of summer time
    return {'id': 'weekly', 'starts_at': start, 'ends_at': start + timedelta(hours=1), 'timezone': 'Europe/Berlin',
            'recurrence': {'frequency': 'weekly', 'interval': 1, 'until': '2026-11-01T23:59:00+01:00'},
            'skipped_dates': list(skipped)}


def local_dates(events):
    return [e['starts_at'].astimezone(BERLIN).date().isoformat() for e in events]


def test_skipped_dates_are_left_out_of_the_calendar():
    start, end = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 30, tzinfo=UTC)
    assert local_dates(app.occurrences(weekly(), start, end)) == ['2026-10-11', '2026-10-18', '2026-10-25', '2026-11-01']
    shown = app.occurrences(weekly([date(2026, 10, 25)]), start, end)
    assert local_dates(shown) == ['2026-10-11', '2026-10-18', '2026-11-01']
    # The other dates keep 10:00 Berlin time, before and after the clocks change.
    assert all(e['starts_at'].astimezone(BERLIN).hour == 10 for e in shown)
    # Without the column (a database before migration 026) nothing is skipped.
    event = weekly()
    del event['skipped_dates']
    assert len(app.occurrences(event, start, end)) == 4


def test_event_rule_lists_every_date_of_the_series():
    assert len(list(app.event_rule(weekly([date(2026, 10, 25)])))) == 4


def test_skipped_dates_get_no_reminder():
    event = dict(weekly([date(2026, 10, 18)]), mission_id=1, roles=[], zone_ids=[], reminder_minutes=30, location='')
    c = {'user_id': 'u', 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': None, 'zone_id': 5,
         'district_id': 51, 'area_id': 511}
    skipped_start = datetime(2026, 10, 18, 10, 0, tzinfo=BERLIN).astimezone(UTC)
    kept_start = datetime(2026, 10, 11, 10, 0, tzinfo=BERLIN).astimezone(UTC)
    assert reminders.due_events([event], c, skipped_start - timedelta(minutes=10)) == []
    assert len(reminders.due_events([event], c, kept_start - timedelta(minutes=10))) == 1


def test_deleting_a_date_locks_the_event_before_reading_it():
    """Two editors deleting two dates at once must not lose one: the row is locked before skipped_dates is read."""
    steps = []
    event = dict(weekly([date(2026, 10, 18)]), id='5b0c3d1e-0000-4000-8000-000000000001')

    def fake_rows(conn, sql, args=()):
        steps.append(' '.join(sql.split()))
        return []

    def fake_item(conn, table, item_id, c):
        steps.append('read the event')
        return event

    from contextlib import contextmanager

    @contextmanager
    def fake_db():
        yield object()

    start = datetime(2026, 10, 25, 10, 0, tzinfo=BERLIN).isoformat()
    with patch.object(app, 'rows', fake_rows), patch.object(app, 'item', fake_item), patch.object(app, 'db', fake_db),             app.app.test_request_context(f'/api/events/{event["id"]}', method='DELETE', query_string={'occurrence': start}):
        app.g.context = {'user_id': 'u-ap', 'app_role': 'AP', 'leadership_role': 'AP', 'additional_roles': []}
        response = app.event_delete(event['id'])
    assert response.get_json() == {'ok': True, 'deleted': 'occurrence', 'date': '2026-10-25'}
    assert steps[0] == 'SELECT id FROM portal.events WHERE id=%s FOR UPDATE', steps
    assert steps[1] == 'read the event', steps
    assert steps[2].startswith('UPDATE portal.events SET skipped_dates='), steps


MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'


def _migration(name):
    """019 stays in migrations/; the older ones are in migrations/history/ (the baseline replaced them)."""
    return MIGRATIONS / name if (MIGRATIONS / name).exists() else MIGRATIONS / 'history' / name


def test_migration_026_refuses_api_callers_inside_the_sync_function():
    """019 (run again after every migration) gives authenticated EXECUTE back, so the check must be in the body."""
    grant_019 = _migration('019_restrict_public_functions.sql').read_text(encoding='utf-8')
    assert 'TO postgres, authenticated, service_role;' in grant_019
    sql = _migration('026_known_issues.sql').read_text(encoding='utf-8')
    body = sql[sql.index('CREATE OR REPLACE FUNCTION public.sync_current_companionships()'):]
    body = body[:body.index('$function$;')]
    check = body.index("if not (caller_role = 'service_role'")
    assert check < body.index('update public.companionships c'), 'the check must come before the first write'
    assert 'SET search_path = public, pg_temp' in body and 'SECURITY DEFINER' in body
    assert "session_user in ('postgres', 'supabase_admin')" in body
    assert 'REVOKE ALL ON FUNCTION public.sync_current_companionships() FROM PUBLIC, anon, authenticated;' in sql
    assert 'GRANT EXECUTE ON FUNCTION public.sync_current_companionships() TO postgres, service_role;' in sql
    rollback = _migration('026_known_issues_rollback.sql').read_text(encoding='utf-8')
    old = rollback[rollback.index('CREATE OR REPLACE FUNCTION public.sync_current_companionships()'):]
    old = old[:old.index('$function$;')]
    assert 'caller_role' not in old and "SET search_path TO 'public'" in old
    # Apart from the check (and search_path), the body is the one from before 026.
    assert body[body.index('    -- Close companionships'):] == old[old.index('    -- Close companionships'):]


# Push reminders per device ---------------------------------------------------------------------------------------

class FakeDB:
    """Stands in for rows(): two devices of one person, and a record of what was written."""

    def __init__(self, delivered_before=False):
        self.deleted, self.delivered, self.delivered_before = [], [], delivered_before

    def rows(self, conn, sql, args=()):
        if 'FROM portal.reminder_deliveries' in sql:
            return [{'?column?': 1}] if self.delivered_before else []
        if sql.startswith('DELETE FROM portal.push_subscriptions'):
            self.deleted.append(args[0])
        elif sql.startswith('SELECT * FROM portal.push_subscriptions'):
            return [{'id': 1, 'endpoint': 'https://fcm.googleapis.com/fcm/send/phone', 'keys': {}},
                    {'id': 2, 'endpoint': 'https://fcm.googleapis.com/fcm/send/laptop', 'keys': {}}]
        elif 'INSERT INTO portal.reminder_deliveries' in sql:
            self.delivered.append(args)
        return []


def run_push(outcomes, delivered_before=False):
    """outcomes: endpoint suffix -> None (sent) or an exception to raise."""
    fake = FakeDB(delivered_before)
    sent = []

    def fake_webpush(subscription_info, **kwargs):
        outcome = outcomes[subscription_info['endpoint'].rsplit('/', 1)[1]]
        if outcome is not None:
            raise outcome
        sent.append(subscription_info['endpoint'])

    env = {'VAPID_PRIVATE_KEY': 'unit-test', 'VAPID_SUBJECT': 'mailto:test@example.org'}
    with patch.object(reminders, 'rows', fake.rows), patch.object(reminders, 'webpush', fake_webpush), \
            patch.dict(reminders.os.environ, env), patch.object(reminders.log, 'warning'), \
            patch.object(reminders.log, 'info'):
        result = reminders.push(object(), 'user', 'event', 'e1:2026-10-11', 'Title', 'Body', '/#calendar')
    return result, sent, fake


def gone(status):
    return WebPushException('push failed', response=SimpleNamespace(status_code=status))


def test_every_device_of_a_person_gets_the_reminder():
    result, sent, fake = run_push({'phone': None, 'laptop': None})
    assert result is True and len(sent) == 2 and fake.deleted == [] and len(fake.delivered) == 1


def test_a_network_error_keeps_the_device():
    # This used to delete the subscription: one outage removed everyone's reminders.
    result, sent, fake = run_push({'phone': requests.ConnectionError('offline'), 'laptop': requests.Timeout('slow')})
    assert result is False and fake.deleted == [] and fake.delivered == []


def test_a_device_the_push_service_reports_gone_is_forgotten():
    result, sent, fake = run_push({'phone': gone(410), 'laptop': None})
    assert result is True and fake.deleted == [1] and sent == ['https://fcm.googleapis.com/fcm/send/laptop']
    result, sent, fake = run_push({'phone': gone(404), 'laptop': gone(500)})
    assert result is False and fake.deleted == [1]  # 500 is the push service's problem: keep the laptop


def test_a_reminder_already_delivered_is_not_sent_again():
    result, sent, fake = run_push({'phone': None, 'laptop': None}, delivered_before=True)
    assert result is False and sent == []


# Archiving New Members once a day --------------------------------------------------------------------------------

def berlin(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=BERLIN).astimezone(UTC)


def test_archive_runs_once_a_day_from_three_in_the_morning():
    calls, state = [], {}

    def archive():
        calls.append(1)
        return 2

    with patch.object(reminders.log, 'info') as logged:
        assert reminders.daily_archive(berlin(28, 2, 59), state, archive) is None
        assert reminders.daily_archive(berlin(28, 3, 0), state, archive) == 2
        assert reminders.daily_archive(berlin(28, 3, 1), state, archive) is None
        assert reminders.daily_archive(berlin(28, 23, 59), state, archive) is None
        assert reminders.daily_archive(berlin(29, 1, 0), state, archive) is None
        assert reminders.daily_archive(berlin(29, 3, 0), state, archive) == 2
    assert len(calls) == 2
    # Only the count is logged.
    assert logged.call_args[0] == ('Archived %s New Members baptized a year ago or more', 2)


def test_archive_started_late_runs_at_once():
    state = {}
    assert reminders.daily_archive(berlin(28, 14, 0), state, lambda: 0) == 0
    assert state['done_on'] == date(2026, 9, 28)


def test_a_failed_archive_is_tried_again_an_hour_later():
    state, calls = {}, []

    def broken():
        calls.append(1)
        raise RuntimeError('database unavailable')

    with patch.object(reminders.log, 'exception'):
        assert reminders.daily_archive(berlin(28, 3, 0), state, broken) is None
        assert reminders.daily_archive(berlin(28, 3, 30), state, broken) is None
        assert len(calls) == 1
        assert reminders.daily_archive(berlin(28, 4, 0), state, lambda: 1) == 1
    assert state == {'done_on': date(2026, 9, 28), 'retry_at': None}


def test_archive_calls_the_database_function():
    seen = []

    class Conn:
        pass

    def fake_rows(conn, sql, args=()):
        seen.append(sql)
        return [{'archived': 3}]

    from contextlib import contextmanager

    @contextmanager
    def fake_db():
        yield Conn()

    with patch.object(reminders, 'rows', fake_rows), patch.object(reminders, 'db', fake_db):
        assert reminders.archive_expired_new_members() == 3
    assert seen == ['SELECT public.archive_expired_new_members() AS archived']


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
