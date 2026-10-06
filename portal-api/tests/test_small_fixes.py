"""Unit checks for the round-3 "small" fixes (no database; the database side is in small_fixes_db.py).

- A person's dates are checked against today in Berlin, not the server's UTC date.
- An upload whose attachment row is not stored leaves no file behind; after a failed commit the file goes only when
  a new connection shows no row for it (the database may have committed before the connection broke).
- A person action sends back the "Add from database" lists, and the page uses them at once.
- The portal shell waits for portal-enhancements.js before it opens the first page.

Run in the portal-api image (no pytest needed); the page checks read ../portal and are skipped without it:
  docker run --rm -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api \
      python tests/test_small_fixes.py
"""
import io
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import app  # noqa: E402
import planning  # noqa: E402

PORTAL = next((path for path in (Path(__file__).resolve().parents[2] / 'portal', Path('/portal'))
               if (path / 'index.template.html').exists()), None)
NEW_MEMBER = {'first_name': 'Lea', 'last_name': 'Hoffmann', 'baptismal_date_extended': '2026-08-30',
              'baptism_date': '2026-09-20', 'confirmation_date': '2026-09-21', 'date_of_birth': '1995-03-04',
              'age_range': '31-45', 'finding_source': 'Member/Member', 'gender': 'Female',
              'living_situation': 'Student', 'marital_status': 'Single',
              'mission_language_competency': 'Fluent/almost fluent', 'native_language': 'Italian',
              'country_of_origin': 'Italy', 'child_dependents': '0', 'conversion_success_notes': 'Notes.'}


def raises(error, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except error as caught:
        return caught
    raise AssertionError(f'{getattr(call, "__name__", call)} did not raise {error.__name__}')


def frozen_at(instant):
    """planning.datetime, frozen at an instant (UTC), answering now(tz) in that time zone."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    return Frozen


# Dates are checked against the Berlin day ---------------------------------------------------------------------

def test_a_baptism_entered_just_after_midnight_in_berlin_is_not_in_the_future():
    # 00:30 on 28 Sep in Berlin (summer time) is still 27 Sep in UTC.
    just_after_midnight = datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)
    with patch.object(planning, 'datetime', frozen_at(just_after_midnight)):
        assert planning._mission_today() == date(2026, 9, 28)
        values = planning.validate_new_person('new_member', {**NEW_MEMBER, 'baptism_date': '2026-09-28',
                                                             'confirmation_date': '2026-09-28'})
        assert values['baptism_date'] == date(2026, 9, 28)
        # The next day is still refused.
        fields = raises(planning.FieldErrors, planning.validate_new_person, 'new_member',
                        {**NEW_MEMBER, 'baptism_date': '2026-09-29', 'confirmation_date': ''}).fields
        assert 'baptism_date' in fields, fields


def test_winter_time_too():
    # 00:30 on 1 Dec in Berlin (winter time, UTC+1) is 23:30 on 30 Nov in UTC.
    with patch.object(planning, 'datetime', frozen_at(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc))):
        assert planning._mission_today() == date(2026, 12, 1)
    with patch.object(planning, 'datetime', frozen_at(datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc))):
        assert planning._mission_today() == date(2026, 11, 30)


# An upload whose row is not stored leaves no file ---------------------------------------------------------------

class UploadConn:
    """The upload's connection. commit_error: the error commit() raises, after storing the row when
    stored_anyway (the database committed, but its answer was lost on the way back)."""

    def __init__(self, commit_error=None, stored_anyway=False):
        self.commit_error, self.stored_anyway, self.committed = commit_error, stored_anyway, False

    def commit(self):
        self.committed = self.commit_error is None or self.stored_anyway
        if self.commit_error:
            raise self.commit_error


def run_upload(folder, fail_insert=False, commit_error=None, stored_anyway=False, check_error=None, log=None):
    """Upload one file to event e-1 with the database faked. The check after a failed commit runs on a second
    connection: it sees the row when the first one committed, or raises check_error. log collects the SQL."""
    real_path = Path
    conn = UploadConn(commit_error, stored_anyway)
    log = [] if log is None else log

    def fake_path(value):
        return real_path(folder) if str(value) == '/data/uploads' else real_path(value)

    def fake_rows(connection, sql, args=()):
        sql = ' '.join(sql.split())
        log.append(sql)
        if 'INSERT INTO portal.attachments' in sql:
            if fail_insert:
                raise app.psycopg2.errors.ForeignKeyViolation('the event was deleted meanwhile')
            conn.storage_name = args[5]
            return [{'id': 'a-new', 'filename': args[4]}]
        if sql == 'SELECT 1 FROM portal.attachments WHERE storage_name=%s':
            assert connection is not conn, 'the check runs on a new connection'
            return [{'?column?': 1}] if conn.committed and args == (conn.storage_name,) else []
        raise AssertionError('unexpected SQL: ' + sql)

    connections = iter([conn])

    @contextmanager
    def fake_db():
        new = next(connections, None)
        if new is None:  # the check after a failed commit
            if check_error:
                raise check_error
            new = object()
        yield new

    parent = {'id': 'e-1', 'mission_id': 2, 'author_id': 'u-office'}
    with patch.object(app, 'Path', fake_path), patch.object(app, 'rows', fake_rows), \
            patch.object(app, 'db', fake_db), patch.object(app, 'item', lambda *a: parent), \
            app.app.test_request_context('/api/events/e-1/attachments', method='POST',
                                         data={'file': (io.BytesIO(b'agenda'), 'Tagesordnung.pdf')},
                                         content_type='multipart/form-data'):
        app.g.context = {'user_id': 'u-office', 'mission_id': 2, 'app_role': 'OFFICE', 'leadership_role': None}
        return app.upload('events', 'e-1'), conn


def checks_made(log):
    return [sql for sql in log if sql.startswith('SELECT 1 FROM portal.attachments')]


def test_a_stored_upload_keeps_its_file():
    with tempfile.TemporaryDirectory() as folder:
        log = []
        response, conn = run_upload(folder, log=log)
        assert response.get_json()['attachment'] == {'id': 'a-new', 'filename': 'Tagesordnung.pdf'}
        stored = list(Path(folder).iterdir())
        assert conn.committed and len(stored) == 1 and stored[0].read_bytes() == b'agenda'
        assert checks_made(log) == [], 'no extra check when the commit worked'


def test_a_failed_insert_removes_the_file():
    with tempfile.TemporaryDirectory() as folder:
        log = []
        raises(app.psycopg2.errors.ForeignKeyViolation, run_upload, folder, fail_insert=True, log=log)
        assert list(Path(folder).iterdir()) == []
        assert checks_made(log) == [], 'a failed insert needs no check: nothing was stored'


def test_a_refused_commit_removes_the_file():
    # The database refused the commit (a deferred check, a serialization failure): no row, so no file either.
    with tempfile.TemporaryDirectory() as folder:
        log = []
        raises(app.psycopg2.errors.SerializationFailure, run_upload, folder, log=log,
               commit_error=app.psycopg2.errors.SerializationFailure('could not serialize access'))
        assert list(Path(folder).iterdir()) == []
        assert len(checks_made(log)) == 1


def test_a_commit_whose_answer_was_lost_keeps_the_file():
    # The connection broke after the database committed: the row is there, so its file must stay.
    with tempfile.TemporaryDirectory() as folder:
        log = []
        raises(app.psycopg2.OperationalError, run_upload, folder, stored_anyway=True, log=log,
               commit_error=app.psycopg2.OperationalError('server closed the connection unexpectedly'))
        stored = list(Path(folder).iterdir())
        assert len(stored) == 1 and stored[0].read_bytes() == b'agenda'
        assert len(checks_made(log)) == 1


def test_a_lost_commit_answer_without_the_row_removes_the_file():
    # The connection broke before the database committed: no row, so the file goes.
    with tempfile.TemporaryDirectory() as folder:
        raises(app.psycopg2.OperationalError, run_upload, folder,
               commit_error=app.psycopg2.OperationalError('server closed the connection unexpectedly'))
        assert list(Path(folder).iterdir()) == []


def test_a_commit_that_cannot_be_checked_keeps_the_file_and_logs_it():
    with tempfile.TemporaryDirectory() as folder, patch.object(app.app.logger, 'warning') as warning:
        raises(app.psycopg2.OperationalError, run_upload, folder,
               commit_error=app.psycopg2.OperationalError('server closed the connection unexpectedly'),
               check_error=app.psycopg2.OperationalError('could not connect to server'))
        stored = list(Path(folder).iterdir())
        assert len(stored) == 1, 'kept: the row may exist'
        assert warning.call_count == 1 and stored[0].name in warning.call_args.args, warning.call_args


# Person actions send back the "Add from database" lists ---------------------------------------------------------

class ActionPlan:
    """A draft report 1 of area 147, unit 5, with friend 9 on it; friend 12 of the area is not on the plan."""

    def __init__(self):
        self.log = []

    def cursor(self):
        plan = self

        class Cursor:
            description = None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args=()):
                self.result = plan.run(' '.join(sql.split()), args)
                self.description = [(key,) for key in (self.result[0] if self.result else {})]

            def fetchall(self):
                return self.result

            def fetchone(self):
                return self.result[0] if self.result else None
        return Cursor()

    def run(self, sql, args):
        self.log.append((sql, args))
        if 'FOR UPDATE OF war' in sql:
            return [{'id': 1, 'area_id': 147, 'unit_id': 5, 'status': 'DRAFT',
                     'sunday': date(2026, 9, 27), 'current_sunday': date(2026, 9, 27)}]
        if sql.startswith('SELECT bdp.display_name'):
            return [{'display_name': 'Mia Klein', 'area_id': 147, 'unit_id': 5}]
        if 'FROM public.area_units au' in sql:
            return [{'area': 'Mainz', 'unit': 'Mainz Branch'}]
        if 'FROM public.current_new_members nm' in sql:
            return [{'id': 31, 'display_name': 'Lena Vogel'}]
        if 'FROM public.current_baptismal_date_people b' in sql:
            return [{'id': 9, 'display_name': 'Mia Klein'}, {'id': 12, 'display_name': 'Noah Weber'}]
        if sql.startswith(('SELECT public.', 'DELETE', 'UPDATE public.weekly_area_reports')):
            return [{'result': None}] if sql.startswith('SELECT') else []
        if ' wnm' in sql or ' wbf' in sql or 'weekly_high_potential_friends' in sql:
            return []
        raise AssertionError('unexpected SQL: ' + sql)


def test_a_person_action_sends_back_the_add_from_database_lists():
    plan = ActionPlan()
    # A move to another ward or branch of the same area: the friend leaves this plan and can be added again.
    result = planning.manage_planning_person(plan, {'area_id': 147}, 1, 'baptismal_friends', 9, 'transfer',
                                             {'area_id': 147, 'unit_id': 6})
    assert result['available_people'] == {'new_members': [{'id': 31, 'display_name': 'Lena Vogel'}],
                                          'baptismal_friends': [{'id': 9, 'display_name': 'Mia Klein'},
                                                                {'id': 12, 'display_name': 'Noah Weber'}]}
    statements = [sql for sql, _ in plan.log]
    lists = [i for i, sql in enumerate(statements) if 'FROM public.current_' in sql]
    delete = statements.index('DELETE FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s '
                              'AND baptismal_date_person_id=%s')
    assert len(lists) == 2 and min(lists) > delete, 'the lists are read after the row left the plan'
    # The plan's own area, ward or branch and report, as when the form opens.
    args = [a for sql, a in plan.log if 'FROM public.current_' in sql]
    assert args == [(147, 5, 1), (147, 1)], args


def test_the_form_and_the_actions_use_the_same_lists():
    source = Path(planning.__file__).read_text(encoding='utf-8')
    form = source[source.index('def planning_form('):source.index('def save_planning_answers(')]
    assert 'available_new_members = _available_new_members(conn, context.get("area_id"), chosen, report["report_id"])' in form
    assert 'available_baptismal = _available_baptismal_friends(conn, context.get("area_id"), report["report_id"])' in form
    assert re.search(r'"available_people": \{"new_members": available_new_members,\s+"baptismal_friends": available_baptismal\}',
                     form), 'the form sends both lists'
    both = source[source.index('def _available_people('):source.index('def planning_form(')]
    assert '_available_new_members(conn, area_id, unit_id, report_id)' in both
    assert '_available_baptismal_friends(conn, area_id, report_id)' in both
    # Each query is written once.
    assert source.count('FROM public.current_new_members nm') == 1
    assert source.count('FROM public.current_baptismal_date_people b\n') == 1


def page(name):
    return (PORTAL / name).read_text(encoding='utf-8') if PORTAL else None


def test_the_page_takes_the_new_counts_right_after_an_action():
    html = page('planning.html')
    if html is None:
        return print('   (skipped: portal/planning.html not found)')
    apply = html[html.index('function applyPeople('):]
    apply = apply[:apply.index('\n      }')]
    assert 'if (available) data.available_people = available;' in apply
    run = html[html.index('async function runPersonAction('):]
    run = run[:run.index('message.textContent = result.message;')]
    assert re.search(r'applyPeople\(\s*result\.people,[\s\S]*result\.available_people,\s*\);', run), run[-400:]
    # The button label counts data.available_people when the page is drawn again.
    assert '+ Add from database${available.length ? " (" + available.length + ")" : ""}' in html or \
        'data.available_people?.[kind]' in html


def test_calendar_new_event_stays_hidden_for_people_who_cannot_create_one():
    html = page('calendar.html')
    if html is None:
        return print('   (skipped: portal/calendar.html not found)')
    assert '<button id="newEvent" hidden style="display: none">New event</button>' in html
    load = html[html.index('async function load()'):html.index('// ---- The editor')]
    assert 'const canEdit = data.can_edit === true;' in load
    assert '$("newEvent").hidden = !canEdit;' in load
    assert '$("newEvent").style.display = canEdit ? "" : "none";' in load


def test_announcement_publish_stays_hidden_for_people_who_cannot_publish():
    html = page('announcements.html')
    if html is None:
        return print('   (skipped: portal/announcements.html not found)')
    assert '<button id="newAnnouncement" hidden style="display: none">Publish update</button>' in html
    load = html[html.index('async function load()'):html.index('// ---- The editor')]
    assert 'const canPublish = data.can_publish === true;' in load
    assert '$("newAnnouncement").hidden = !canPublish;' in load
    assert '$("newAnnouncement").style.display = canPublish ? "" : "none";' in load


# The shell waits for portal-enhancements.js ---------------------------------------------------------------------

def test_the_shell_opens_the_first_page_only_after_the_enhancements_ran():
    html = page('index.template.html')
    if html is None:
        return print('   (skipped: portal/index.template.html not found)')
    show = html[html.index('async function showPortal()'):]
    show = show[:show.index('function showLogin()')]
    order = [show.index(part) for part in ('await loadUserContext()', 'await enhancementsReady;',
                                           'currentUserContext = context;', 'applyRoleNavigation(context);',
                                           'openPage(pageToOpen);')]
    assert order == sorted(order), order
    ready = html[html.index('const enhancementsReady'):html.index('async function showPortal()')]
    assert 'DOMContentLoaded' in ready and 'document.readyState === "loading"' in ready
    # The enhancements come after the inline start-up, whatever their ?v= number is now (it was 14 then).
    enhancements = re.search(r'<script src="/portal-enhancements\.js\?v=\d+"></script>', html)
    assert enhancements and html.index('startPortal();') < enhancements.start()


# The phones' 44px sizes are plain CSS at the end of portal.css (round 9; before, portal-enhancements.js wrote them into
# a <style>). This reads that part with comments removed and spaces squeezed out, so the rules compare as one line.
def phone_css():
    css = page('portal.css')
    if css is None:
        return None
    part = css[css.index('/* ---- Phones: 44px touch targets'):]
    part = re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', part, flags=re.S))
    return re.sub(r'\s*([{}:;>,])\s*', r'\1', part).replace(';}', '}').strip()


def test_phone_header_controls_are_placed_in_one_place():
    js = page('portal-enhancements.js')
    if js is None:
        return print('   (skipped: portal/portal-enhancements.js not found)')
    place = js[js.index('function placeHeaderControls()'):]
    place = place[:place.index('\n    }')]
    assert 'signOut.before(languages, customize)' in place and 'library.after(customize)' in place
    assert "phoneLayout.addEventListener('change', placeHeaderControls);" in js
    assert 'placeReminderSwitches' not in js
    style = phone_css()
    for rule in ('.topbar .mobile-menu{min-width:44px;min-height:44px', '.topbar .portal-actions .portal-action{min-height:44px',
                 '.sidebar .nav-item{min-height:44px}', '.sidebar-bottom .portal-language{', 'font-size:16px',
                 '.portal-customizer .customizer-actions .portal-action{min-height:44px'):
        assert rule in style, rule
    assert style.startswith('@media (max-width:780px){')


def test_phone_header_title_keeps_its_words_whole():
    # 'anywhere' broke "Presentations" into "Presentation" / "s" next to Library and Reload on a 360px phone; the
    # slimmer header gaps give the title room for it (edge_small_fixes.ps1 measures the lines in a browser).
    style = phone_css()
    if style is None:
        return print('   (skipped: portal/portal.css not found)')
    assert 'overflow-wrap:anywhere' not in style
    assert '.topbar .page-title{overflow-wrap:break-word}' in style
    assert '.main>.topbar{gap:10px;padding:0 12px}' in style
    assert 'margin-right:0;' in style[style.index('.topbar .mobile-menu{'):]


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
