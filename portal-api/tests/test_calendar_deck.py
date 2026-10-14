"""Unit checks for the calendar's deck link (round 13, task 20; no database).

An event may link to one of THIS portal's presentation decks: stored as the relative path /p/<deck>/ in portal.events.deck_link
(migration 050). The API accepts a deck name or that path and refuses everything else (web addresses, other paths, odd
characters). The same editors-only rule as before applies.

Run in the portal-api image (no pytest needed):
  docker run --rm --network none -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api \
      python tests/test_calendar_deck.py
"""
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import app  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'
EDITOR = {'user_id': 'u1', 'mission_id': 1, 'main_role': 'AP', 'roles': ['AP']}
EVENT = {'title': 'Monday Morning Meeting', 'starts_at': '2026-10-19T08:00:00+00:00', 'ends_at': '2026-10-19T09:00:00+00:00',
         'timezone': 'Europe/Berlin', 'recurrence': None, 'roles': [], 'zone_ids': [], 'location': '', 'meeting_url': '',
         'reminder_minutes': 30, 'description': ''}


def refused(value):
    try:
        app.clean_deck_link(value)
    except HTTPException as exc:
        return exc.code == 400
    return False


def test_a_deck_name_or_path_becomes_the_relative_path():
    for given in ('mmm', ' mmm ', 'MMM'.lower(), '/p/mmm/', '/p/mmm', 'p/mmm/', 'mmm/'):
        assert app.clean_deck_link(given) == '/p/mmm/', given
    assert app.clean_deck_link('zoko-2026') == '/p/zoko-2026/'
    assert app.clean_deck_link('zone-conference-1') == '/p/zone-conference-1/'


def test_no_deck_is_none():
    for given in (None, '', '   '):
        assert app.clean_deck_link(given) is None, repr(given)


def test_web_addresses_and_other_paths_are_refused():
    for given in ('https://example.org/p/mmm/', 'http://localhost:8089/p/mmm/', '//evil.example/p/mmm/', 'javascript:alert(1)',
                  '/p/mmm/../admin', '/p/mmm/?x=1', '/p/mmm/#a', '/edit/mmm/', '/studio/mmm', '/api/presentations/mmm',
                  '../mmm', 'mmm/slide', 'two words', 'MMM', 'mmm_', '-mmm', 'mmm-', 'mm--m', 'mmm\n\n x', '/p/', '/p//',
                  'a' * 91, "mmm' OR 1=1 --", '<b>mmm</b>', 'mmm%2F..'):
        assert refused(given), repr(given)


@contextmanager
def saving(deck_link=None, put=False):
    """Runs event_save as an editor with the database replaced; yields what would have been stored."""
    seen = {}

    def fake_rows(conn, sql, args=()):
        seen['sql'], seen['args'] = sql, args
        return [{'id': 'e1'}]

    @contextmanager
    def fake_db():
        yield object()

    body = dict(EVENT, deck_link=deck_link)
    with patch.object(app, 'db', fake_db), patch.object(app, 'rows', fake_rows), \
            patch.object(app, 'validate_targets', lambda *a, **k: {'roles': [], 'zone_ids': []}), \
            patch.object(app, 'item', lambda *a, **k: None), \
            patch.object(app.roles, 'can_edit_calendar', lambda c: c is EDITOR):
        with app.app.test_request_context('/api/events', method='PUT' if put else 'POST', json=body):
            app.g.context = EDITOR
            yield seen, (lambda: app.event_save('e1' if put else None))


def placeholders(sql):
    return sql.count('%s')


def test_saving_an_event_stores_the_normalised_deck_link():
    for put in (False, True):
        with saving('mmm', put) as (seen, call):
            call()
            assert '/p/mmm/' in seen['args'], (put, seen['args'])
            assert 'deck_link' in seen['sql']
            assert placeholders(seen['sql']) == len(seen['args']), (put, placeholders(seen['sql']), len(seen['args']))


def test_saving_without_a_deck_stores_null():
    with saving(None) as (seen, call):
        call()
        assert None in seen['args'] and not any(isinstance(a, str) and a.startswith('/p/') for a in seen['args'])


def test_saving_a_web_address_is_refused_and_nothing_is_stored():
    with saving('https://example.org/deck') as (seen, call):
        try:
            call()
        except HTTPException as exc:
            assert exc.code == 400
        else:
            raise AssertionError('a web address was accepted')
        assert 'sql' not in seen


def test_a_person_who_may_not_edit_the_calendar_is_still_refused():
    with saving('mmm') as (seen, call):
        app.g.context = {'user_id': 'u2', 'mission_id': 1, 'main_role': 'DL', 'roles': ['DL']}
        try:
            call()
        except HTTPException as exc:
            assert exc.code == 403
        else:
            raise AssertionError('a non-editor could save an event')
        assert 'sql' not in seen


def test_the_migration_adds_one_nullable_column_with_a_check_and_leaves_security_alone():
    up = (MIGRATIONS / '050_event_deck_link.sql').read_text(encoding='utf-8')
    down = (MIGRATIONS / '050_event_deck_link_rollback.sql').read_text(encoding='utf-8')
    for text in (up, down):
        assert text.count('BEGIN;') == 1 and text.rstrip().endswith('COMMIT;'), 'one transaction'
        assert "session_user NOT IN ('supabase_admin', 'postgres')" in text
    assert 'ADD COLUMN IF NOT EXISTS deck_link text;' in up and 'NOT NULL' not in up.split('ADD COLUMN', 1)[1].split(';', 1)[0]
    assert "'^/p/[a-z0-9]+(-[a-z0-9]+)*/$'" in up
    assert 'DROP COLUMN IF EXISTS deck_link' in down
    code = re.sub(r'--[^\n]*', '', up)  # comments out: nothing may change the rights or policies
    assert not re.search(r'\b(POLICY|GRANT|REVOKE|DISABLE ROW)\b', code), 'rights untouched'


def test_the_next_free_number_is_not_used_twice():
    numbers = [p.name[:3] for p in MIGRATIONS.glob('[0-9][0-9][0-9]_*.sql') if not p.name.endswith('_rollback.sql')]
    assert numbers.count('050') == 1, numbers


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
