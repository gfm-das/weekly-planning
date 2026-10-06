"""Migration 028 (New People Being Taught, Preach My Gospel wording) against a THROWAWAY database.

Runs the real files as supabase_admin, like on Beta: 028, 028 again, 019, the rollback, the rollback again, 028
again. It also plays DA Management edits made before and after 028 (a label worded a little differently, a section
description someone already rewrote) and checks they are respected: renamed or kept, never overwritten, and always
named in the change history. The copy ends with 028 applied and the catalogue texts as 028 writes them; only extra
history rows are left behind. It prints only labels, keys, booleans and counts (catalogue texts, no names).

It refuses to run unless both URLs name the same database containing "test" and NEWPEOPLE_TEST_THROWAWAY=yes.
Run inside a temporary portal-api container, on a copy of Beta with 024 applied:
  DATABASE_URL=postgresql://postgres:...@host/gfm_test_x  ADMIN_DATABASE_URL=postgresql://supabase_admin:...@host/gfm_test_x
  NEWPEOPLE_TEST_THROWAWAY=yes python tests/new_people_labels_db.py
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras

HERE = Path(__file__).resolve().parent.parent / 'migrations'

def migration_file(name):
    """A migration file: 019 stays in migrations/, every older one is in migrations/history/ (the baseline replaced them)."""
    return HERE / name if (HERE / name).exists() else HERE / 'history' / name

MIGRATION, ROLLBACK = '028_new_people_being_taught.sql', '028_new_people_being_taught_rollback.sql'
EM = ' — '
KEYS = ('friends_found_actual', 'friends_found_goal', 'friends_found_plan')
OLD = {'friends_found_actual': f'Friends Found{EM}Actual', 'friends_found_goal': f'Friends Found{EM}Goal',
       'friends_found_plan': f'Friends Found{EM}Action Plan'}
NEW = {'friends_found_actual': f'New People Being Taught{EM}Actual', 'friends_found_goal': f'New People Being Taught{EM}Goal',
       'friends_found_plan': f'New People Being Taught{EM}Action Plan'}
PLAN_HELP = 'What will you do, with whom, and when? Include how members can help.'
PLANS = ('nm_sacrament_attendance_plan', 'baptisms_confirmations_plan', 'baptismal_dates_plan', 'sacrament_attendance_plan',
         'members_at_lessons_plan', 'friends_found_plan', 'social_media_plan', 'weekly_action_plan')  # guide 3.3: all *_plan

url, admin_url = os.environ.get('DATABASE_URL', ''), os.environ.get('ADMIN_DATABASE_URL', '')
dbname, admin_dbname = urlparse(url).path.lstrip('/'), urlparse(admin_url).path.lstrip('/')
if os.environ.get('NEWPEOPLE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname or dbname != admin_dbname:
    sys.exit('Refusing to run: this test runs migrations and needs one throwaway *test* database in both URLs.')

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' else ''), flush=True)


def connect(target):
    conn = psycopg2.connect(target, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    return conn


admin, api = connect(admin_url), connect(url)  # supabase_admin (as the files run on Beta), postgres (as DA Management)


def sql(query, args=(), conn=None):
    with (conn or admin).cursor() as cur:
        cur.execute(query, args)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def run_file(name, conn=None):
    """Run a migration file as psql would (one batch with its own BEGIN/COMMIT). Returns (ok, error, notices)."""
    conn = conn or admin
    del conn.notices[:]
    try:
        with conn.cursor() as cur:
            cur.execute(migration_file(name).read_text(encoding='utf-8'))
        return True, '', [n.strip() for n in conn.notices]
    except psycopg2.Error as error:
        with conn.cursor() as cur:
            cur.execute('ROLLBACK')
        return False, str(error).strip().splitlines()[0], [n.strip() for n in conn.notices]


def labels():
    return {r['question_key']: r['question_label'] for r in sql(
        'SELECT question_key, question_label FROM public.planning_questions WHERE question_key = ANY(%s)', (list(KEYS),))}


def texts():
    """Every catalogue text 028 may touch, as one comparable snapshot."""
    rows = sql("""SELECT 'q:' || question_key AS k, question_label || ' | ' || coalesce(help_text, '<null>') AS v
                  FROM public.planning_questions
                  UNION ALL SELECT 's:' || section_key, section_title || ' | ' || coalesce(description, '<null>')
                  FROM public.planning_question_sections""")
    return {r['k']: r['v'] for r in rows}


def history(actor):
    return sql('SELECT id, table_name, row_key, before_row, after_row FROM public.planning_catalog_changes '
               'WHERE actor = %s ORDER BY id', (actor,))


def edit(query, args=()):
    """A change as DA Management makes it: as postgres (the page also writes a history row; not needed here)."""
    sql(query, args, conn=api)


# Start from the state before 028 (the copy may already have it).
if any('New People Being Taught' in v for v in labels().values()):
    ok, error, _ = run_file(ROLLBACK)
    check('start: rollback of an earlier 028 run', ok, error)
before = texts()
check('start: the three labels are the old ones', labels() == OLD, labels())
check('start: the keys, types and protection', len(sql("""SELECT 1 FROM public.planning_questions WHERE question_key = ANY(%s)
      AND protected AND active""", (list(KEYS),))) == 3)
version_before = sql('SELECT version FROM public.planning_catalog_version')[0]['version']
written_before = len(history('Migration 028'))

# 028 refuses to run as postgres (it must run as supabase_admin, like 024).
ok, error, _ = run_file(MIGRATION, conn=api)
check('028 as postgres is refused', not ok and 'supabase_admin' in error, error)
check('... and changed nothing', texts() == before)

# DA Management edits made before 028: a label worded a little differently and a section description rewritten.
edit("UPDATE public.planning_questions SET question_label = %s WHERE question_key = 'friends_found_goal'",
     (f'Friends found{EM}Goal for next week',))
edit("UPDATE public.planning_question_sections SET description = 'Our own words.' WHERE section_key = 'youth_service'")

ok, error, notices = run_file(MIGRATION)
check('028 applies', ok, error)
now = labels()
check('actual and action plan renamed exactly', now['friends_found_actual'] == NEW['friends_found_actual']
      and now['friends_found_plan'] == NEW['friends_found_plan'], now)
check('a differently worded label is renamed too, the rest of it kept',
      now['friends_found_goal'] == f'New People Being Taught{EM}Goal for next week', now['friends_found_goal'])
check('keys, protection, type and required unchanged', len(sql("""SELECT 1 FROM public.planning_questions
      WHERE question_key = ANY(%s) AND protected AND active AND required""", (list(KEYS),))) == 3)
check('the Facebook question keeps its label', sql("""SELECT question_label FROM public.planning_questions
      WHERE question_key = 'facebook_friends_found'""")[0]['question_label'] == before['q:facebook_friends_found'].split(' | ')[0])
check('no label, help text or section text says Friends Found (except the Facebook question)', not sql("""
      SELECT 1 FROM public.planning_questions WHERE question_key <> 'facebook_friends_found'
        AND (question_label ~* 'friends\\s+found' OR coalesce(help_text, '') ~* 'friends\\s+found')
      UNION ALL SELECT 1 FROM public.planning_question_sections WHERE section_title ~* 'friends\\s+found'
        OR coalesce(description, '') ~* 'friends\\s+found'"""))
names = sql("""SELECT question_key, btrim(regexp_replace(regexp_replace(question_label, '^Optional: ', ''),
               '\\s*' || chr(8212) || '.*$', '')) AS name FROM public.planning_questions WHERE question_key = ANY(%s)""",
            (list(KEYS),))
check('Call-ins and planning.py derive the name New People Being Taught',
      {r['name'] for r in names} == {'New People Being Taught'}, names)
check('the section someone rewrote is kept', sql("""SELECT description FROM public.planning_question_sections
      WHERE section_key = 'youth_service'""")[0]['description'] == 'Our own words.')
check('... and named in a NOTICE', any('youth_service' in n for n in notices), notices)
sections = {r['section_key']: r['description'] for r in sql('SELECT section_key, description FROM public.planning_question_sections')}
check('the other five section descriptions use the new wording',
      sections['ward_coordination'].startswith('Your GEMIKO (ward mission coordination) meeting')
      and sections['key_indicators_conversion'].startswith('How the people you are teaching progressed'), sections)
helps = {r['question_key']: r['help_text'] for r in sql(
    'SELECT question_key, help_text FROM public.planning_questions WHERE question_key = ANY(%s)', (list(PLANS),))}
check('every action plan has the invite-help-follow-up help text (weekly_action_plan too)',
      len(helps) == len(PLANS) and set(helps.values()) == {PLAN_HELP}, helps)
info = sql("SELECT question_label, help_text, required FROM public.planning_questions WHERE question_key = 'information_up_chain'")[0]
check('Information for leaders (optional), still optional', info['question_label'] == 'Information for leaders (optional)'
      and info['help_text'].startswith('Anything your district leader') and not info['required'], info)
rows = history('Migration 028')[written_before:]
label_rows = [r for r in rows if 'question_label' in (r['after_row'] or {}) and r['row_key'].get('question_key') in KEYS]
check('the history has one row per renamed label, before and after',
      sorted(r['row_key']['question_key'] for r in label_rows) == sorted(KEYS)
      and all(r['before_row']['question_label'] != r['after_row']['question_label'] for r in label_rows), len(label_rows))
check('the history has no row for the section someone rewrote',
      not [r for r in rows if r['row_key'].get('section_key') == 'youth_service'])
check('the catalogue version went up (open plans reload their questions)',
      sql('SELECT version FROM public.planning_catalog_version')[0]['version'] > version_before)
first = texts()
count = len(history('Migration 028'))

ok, error, _ = run_file(MIGRATION)
check('028 again: applies, changes nothing, writes no history', ok and texts() == first and len(history('Migration 028')) == count, error)
ok, error, _ = run_file('019_restrict_public_functions.sql')
check('019 passes afterwards', ok, error)

# A DA Management edit after 028, then the rollback: that text stays, everything else goes back.
edit("UPDATE public.planning_questions SET help_text = 'Our own help.' WHERE question_key = 'social_media_plan'")
put_back_before = len(history('Migration 028 rollback'))
ok, error, notices = run_file(ROLLBACK)
check('rollback applies', ok, error)
after_rollback = texts()
expected = dict(before)
expected['q:friends_found_goal'] = f'Friends found{EM}Goal for next week | <null>'  # the DA wording from before 028
expected['s:youth_service'] = 'Youth/Service | Our own words.'  # 028 never touched it
expected['q:social_media_plan'] = before['q:social_media_plan'].split(' | ')[0] + ' | Our own help.'  # changed after 028
diff = {k: (expected.get(k), after_rollback.get(k)) for k in set(expected) | set(after_rollback) if expected.get(k) != after_rollback.get(k)}
check('rollback puts back exactly what 028 changed, keeps later edits', not diff, diff)
check('... and names the kept text', any('social_media_plan' in n for n in notices), notices)
check('... and records each text it put back (all but the one kept)',
      len(history('Migration 028 rollback')) - put_back_before == sum(len(r['after_row']) for r in rows) - 1,
      sum(len(r['after_row']) for r in rows))  # one row per text; the information_up_chain row of 028 holds two
back_count = len(history('Migration 028 rollback'))
ok, error, notices = run_file(ROLLBACK)
check('rollback again: applies and puts nothing back', ok and texts() == after_rollback
      and len(history('Migration 028 rollback')) == back_count, error)
ok, error, _ = run_file('019_restrict_public_functions.sql')
check('019 passes after the rollback', ok, error)

# Put the copy back as it was (the DA edits undone), then 028 again: the result equals the first run.
edit("UPDATE public.planning_questions SET question_label = %s WHERE question_key = 'friends_found_goal'", (OLD['friends_found_goal'],))
edit("UPDATE public.planning_question_sections SET description = %s WHERE section_key = 'youth_service'",
     (before['s:youth_service'].split(' | ', 1)[1],))
edit("UPDATE public.planning_questions SET help_text = NULL WHERE question_key = 'social_media_plan'")
check('copy back at the state before 028', texts() == before)
ok, error, _ = run_file(MIGRATION)
final = texts()
check('028 once more: the labels are the new ones and no text is left over', ok and labels() == NEW
      and final['s:youth_service'].endswith('in your ward or branch.') and final['q:social_media_plan'].endswith(PLAN_HELP), error)
ok, error, _ = run_file('019_restrict_public_functions.sql')
check('019 passes at the end', ok, error)

print(f'{sum(results)}/{len(results)} checks passed')
sys.exit(0 if all(results) else 1)
