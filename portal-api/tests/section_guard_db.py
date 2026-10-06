"""Migration 036 (the section guard's sentence without Beta) against a THROWAWAY database copy like live.

Runs the real files as supabase_admin, like on Beta: 036, 036 again, 019, then tries to retire the key indicator
section as postgres (DA Management's login) and reads the refusal; then the rollback (the 024 sentence comes back),
the rollback again, and 036 once more. Each time it also checks that the other rules of the guard still hold (a
section is never deleted, its key never changes) and that the function kept its owner, SECURITY DEFINER, search_path
and rights. Every refused change is rolled back, so the catalogue is left as it was. Prints sentences and booleans
only.

It refuses unless both URLs name the same database containing "test" and GUARD_TEST_THROWAWAY=yes. Run inside a
temporary portal-api container on the test network, with portal-api mounted at /app:
  DATABASE_URL=postgresql://postgres:...@host/gfm_test_x  ADMIN_DATABASE_URL=postgresql://supabase_admin:...@host/gfm_test_x
  GUARD_TEST_THROWAWAY=yes python tests/section_guard_db.py
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

HERE = Path(__file__).resolve().parent.parent / 'migrations'

def migration_file(name):
    """A migration file: 019 stays in migrations/, every older one is in migrations/history/ (the baseline replaced them)."""
    return HERE / name if (HERE / name).exists() else HERE / 'history' / name

NEW = ('The section "{}" stays active: it holds the key indicators that Dashboards, Call-ins and Presentations '
       'read every week.')
OLD = 'The section "{}" stays active: the Key Indicators and Beta depend on it.'

url, admin_url = os.environ.get('DATABASE_URL', ''), os.environ.get('ADMIN_DATABASE_URL', '')
dbname, admin_dbname = urlparse(url).path.lstrip('/'), urlparse(admin_url).path.lstrip('/')
if os.environ.get('GUARD_TEST_THROWAWAY') != 'yes' or 'test' not in dbname or dbname != admin_dbname:
    sys.exit('Refusing to run: this test runs migrations and needs one throwaway *test* database in both URLs.')

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' else ''), flush=True)


def connect(target):
    conn = psycopg2.connect(target)
    conn.autocommit = True
    return conn


admin, api = connect(admin_url), connect(url)  # supabase_admin (as the files run on Beta), postgres (DA Management)


def run_file(name):
    """Run a migration file as psql would (one batch with its own BEGIN/COMMIT). Returns (ok, error)."""
    try:
        with admin.cursor() as cur:
            cur.execute(migration_file(name).read_text(encoding='utf-8'))
        return True, ''
    except psycopg2.Error as error:
        with admin.cursor() as cur:
            cur.execute('ROLLBACK')
        return False, str(error).strip().splitlines()[0]


def refusal(statement, args=()):
    """The database's message for a change DA Management's login tries; None when it was allowed (then undone)."""
    with api.cursor() as cur:
        cur.execute('BEGIN')
        try:
            cur.execute(statement, args)
            return None
        except psycopg2.Error as error:
            return error.diag.message_primary
        finally:
            cur.execute('ROLLBACK')


def guard_facts():
    with admin.cursor() as cur:
        cur.execute("""SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig, p.proacl::text
                       FROM pg_proc p WHERE p.oid = 'public.planning_question_sections_guard()'::regprocedure""")
        return cur.fetchone()


with admin.cursor() as cur:
    cur.execute("SELECT id, section_title FROM public.planning_question_sections WHERE section_key = 'key_indicators_conversion'")
    section_id, title = cur.fetchone()
facts_before = guard_facts()
RETIRE = 'UPDATE public.planning_question_sections SET active = false WHERE id = %s'


def rules_still_hold(when):
    check(f'{when}: retiring the key indicator section is refused', refusal(RETIRE, (section_id,)) is not None)
    deleted = refusal('DELETE FROM public.planning_question_sections WHERE id = %s', (section_id,))
    check(f'{when}: a section is never deleted', deleted and deleted.startswith('Sections are never deleted'), deleted)
    renamed = refusal("UPDATE public.planning_question_sections SET section_key = section_key || '_x' WHERE id = %s",
                      (section_id,))
    check(f'{when}: a section key never changes', renamed and renamed.startswith('The key of a section never changes'),
          renamed)
    check(f'{when}: owner, SECURITY DEFINER, search_path and rights as before', guard_facts() == facts_before,
          guard_facts())


check('start: the copy has the 024 sentence', refusal(RETIRE, (section_id,)) == OLD.format(title))
for step in ('036_section_guard_wording.sql', '036_section_guard_wording.sql', '019_restrict_public_functions.sql'):
    ok, error = run_file(step)
    check(f'{step} runs', ok, error)
message = refusal(RETIRE, (section_id,))
check('after 036: the new sentence', message == NEW.format(title), message)
check('after 036: no Beta in it', 'Beta' not in (message or ''), message)
rules_still_hold('after 036')

for step in ('036_section_guard_wording_rollback.sql', '036_section_guard_wording_rollback.sql',
             '019_restrict_public_functions.sql'):
    ok, error = run_file(step)
    check(f'{step} runs', ok, error)
message = refusal(RETIRE, (section_id,))
check('after the rollback: the 024 sentence again', message == OLD.format(title), message)
rules_still_hold('after the rollback')

for step in ('036_section_guard_wording.sql', '019_restrict_public_functions.sql'):
    ok, error = run_file(step)
    check(f'{step} runs again', ok, error)
check('036 again: the new sentence', refusal(RETIRE, (section_id,)) == NEW.format(title))
with admin.cursor() as cur:
    cur.execute('SELECT active FROM public.planning_question_sections WHERE id = %s', (section_id,))
    check('the key indicator section is still active', cur.fetchone()[0] is True)

print(f'{sum(results)}/{len(results)} passed')
sys.exit(0 if all(results) else 1)
