"""Migration 037 (the access checks in plpgsql) against a THROWAWAY database copy like live.

The promise of 037: every "may this person see this area?" answer stays exactly the same, only faster. This test
asks the database the same questions before 037, after it, after its rollback and after it once more, for many kinds
of people, and compares every answer:
- can_access_area and is_mission_manager_for_area for every area (and for no area / an unknown one);
- the checks built on them (zone, district and mission access, planning edit and unlock, Call-ins edit and read);
- how many rows row-level security lets the person read in the tables guarded by can_access_area.
The people: the six accounts of the copy as they are, and changed versions of them inside a transaction that is
rolled back (a President with and without a missionary link, a Data Analyst by additional role, Office staff, a staff
account of another mission, a released AP, a future AP, an inactive AP, an STL, a released ZL, a DL without an area,
a missionary who moved). It also checks that 037 and its rollback keep owner, SECURITY DEFINER, STABLE, search_path
and rights, that the rollback brings back the exact SQL texts of 013 and 032, and that 037 refuses to run over an
access check it does not know. Prints counts and booleans only, no names.

It refuses unless both URLs name the same database containing "test" and ACCESS_TEST_THROWAWAY=yes. Run inside a
temporary portal-api container on the test network, with portal-api mounted at /app:
  DATABASE_URL=postgresql://postgres:...@host/gfm_test_x  ADMIN_DATABASE_URL=postgresql://supabase_admin:...@host/gfm_test_x
  ACCESS_TEST_THROWAWAY=yes python tests/access_checks_db.py
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

HERE = Path(__file__).resolve().parent.parent / 'migrations'

def migration_file(name):
    """A migration file: 019 stays in migrations/, every older one is in migrations/history/ (the baseline replaced them)."""
    return HERE / name if (HERE / name).exists() else HERE / 'history' / name

FORWARD, BACK, CLOSE = '037_faster_access_checks.sql', '037_faster_access_checks_rollback.sql', \
    '019_restrict_public_functions.sql'
CHECKS = ('public.can_access_area(bigint)', 'public.is_mission_manager_for_area(bigint)')
SQL_TEXTS = {'can_access_area': '12d62d4109a13f3c07d1bd4b77cb198a',
             'is_mission_manager_for_area': 'b3d5c725c02a16125618451f8721754e'}
GUARDED = ('weekly_area_reports', 'weekly_planning_answers', 'missionaries', 'missionary_assignments', 'companionships',
           'companionship_members', 'new_members', 'new_member_area_assignments', 'baptismal_date_people',
           'baptismal_date_person_area_assignments', 'weekly_new_members', 'weekly_baptismal_date_friends',
           'weekly_high_potential_friends')

url, admin_url = os.environ.get('DATABASE_URL', ''), os.environ.get('ADMIN_DATABASE_URL', '')
dbname, admin_dbname = urlparse(url).path.lstrip('/'), urlparse(admin_url).path.lstrip('/')
if os.environ.get('ACCESS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname or dbname != admin_dbname:
    sys.exit('Refusing to run: this test runs migrations and needs one throwaway *test* database in both URLs.')

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' else ''), flush=True)


admin = psycopg2.connect(admin_url)  # supabase_admin, as the files run on the live database
admin.autocommit = True


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


def one(sql, args=()):
    with admin.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def facts():
    """Language, owner, SECURITY DEFINER, volatility, settings and rights of the two checks."""
    return one("""SELECT p.proname, l.lanname, pg_get_userbyid(p.proowner), p.prosecdef, p.provolatile, p.proconfig,
                         p.proacl::text, md5(replace(p.prosrc, E'\\r', ''))
                  FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang
                  WHERE p.oid = ANY(%s::regprocedure[]) ORDER BY 1""", (list(CHECKS),))


USERS = {row[0]: row[1] for row in one('SELECT id::text, missionary_id FROM public.user_profiles ORDER BY id')}
AREAS = [row[0] for row in one('SELECT id FROM public.areas ORDER BY id')] + [None, 0]
ZONES = [row[0] for row in one('SELECT id FROM public.zones ORDER BY id')]
DISTRICTS = [row[0] for row in one('SELECT id FROM public.districts ORDER BY id')]
MISSIONS = [row[0] for row in one('SELECT id FROM public.missions ORDER BY id')]
AP, ZL, DL, MISSIONARY, FREE = ('ffa4f36b-ec04-4a0c-9a34-2307e49a1307', '5f4f3146-12bc-4626-8324-03f4d65099cf',
                                '666a414d-0490-47cb-b3bc-2fa179122755', 'c360d13c-ec26-4ebe-ba8d-a6bc9c9a8ad8',
                                'e0c86dcf-6e7f-4642-9aa4-46aafa8426f6')
if not {AP, ZL, DL, MISSIONARY, FREE} <= set(USERS):
    sys.exit('This copy does not have the accounts of gfm_test_r3_template; build it as portal-api/README.md says.')
YESTERDAY = "CURRENT_DATE - 1"

# (name, the person asking, changes made first inside the transaction)
SCENARIOS = [(f'account {n + 1} as it is', user, []) for n, user in enumerate(USERS)] + [
    ('President with a missionary link', MISSIONARY,
     ["UPDATE public.user_profiles SET app_role = 'PRESIDENT' WHERE id = %(user)s"]),
    ('President staff account (home mission)', FREE,
     ["UPDATE public.user_profiles SET app_role = 'PRESIDENT', home_mission_id = %(mission)s WHERE id = %(user)s"]),
    ('Data Analyst by additional role (staff)', FREE,
     ["UPDATE public.user_profiles SET app_role = 'OFFICE', additional_roles = '{DATA_ADMIN}', "
      "home_mission_id = %(mission)s WHERE id = %(user)s"]),
    ('Office staff account', FREE,
     ["UPDATE public.user_profiles SET app_role = 'OFFICE', home_mission_id = %(mission)s WHERE id = %(user)s"]),
    ('President staff account of another mission', FREE,
     ["INSERT INTO public.missions (name) VALUES ('Access check test mission')",
      "UPDATE public.user_profiles SET app_role = 'PRESIDENT', home_mission_id = (SELECT id FROM public.missions "
      "WHERE name = 'Access check test mission') WHERE id = %(user)s"]),
    ('released AP (app_role still AP)', AP,
     [f"UPDATE public.leadership_assignments SET start_date = least(start_date, CURRENT_DATE - 30), "
      f"end_date = {YESTERDAY} WHERE missionary_id = %(missionary)s AND role = 'AP'"]),
    ('AP who starts tomorrow', AP,
     ["UPDATE public.leadership_assignments SET start_date = CURRENT_DATE + 1, end_date = NULL "
      "WHERE missionary_id = %(missionary)s AND role = 'AP'"]),
    ('inactive AP', AP, ["UPDATE public.user_profiles SET active = false WHERE id = %(user)s"]),
    ('STL', ZL, ["UPDATE public.leadership_assignments SET role = 'STL' WHERE missionary_id = %(missionary)s "
                 "AND role = 'ZL'"]),
    ('released ZL', ZL,
     [f"UPDATE public.leadership_assignments SET start_date = least(start_date, CURRENT_DATE - 30), "
      f"end_date = {YESTERDAY} WHERE missionary_id = %(missionary)s AND role = 'ZL'"]),
    ('DL without a current area', DL,
     [f"UPDATE public.missionary_assignments SET start_date = least(start_date, CURRENT_DATE - 30), "
      f"end_date = {YESTERDAY} WHERE missionary_id = %(missionary)s"]),
    ('missionary who moved to another area', MISSIONARY,
     ["UPDATE public.missionary_assignments SET area_id = (SELECT min(id) FROM public.areas WHERE id <> area_id) "
      "WHERE missionary_id = %(missionary)s"]),
    ('Data Analyst with a missionary link', ZL,
     ["UPDATE public.user_profiles SET app_role = 'DATA_ADMIN' WHERE id = %(user)s"]),
]


def answers(user, changes):
    """Every answer for one person, as one comparable structure (the transaction is rolled back afterwards)."""
    found = {}
    with admin.cursor() as cur:
        cur.execute('BEGIN')
        try:
            for change in changes:
                cur.execute(change, {'user': user, 'missionary': USERS[user], 'mission': MISSIONS[0]})
            cur.execute("SELECT set_config('request.jwt.claims', %s, true)",
                        (json.dumps({'sub': user, 'role': 'authenticated'}),))
            cur.execute('SET LOCAL ROLE authenticated')
            for name in ('can_access_area', 'is_mission_manager_for_area', 'can_edit_planning_area',
                         'can_unlock_planning_area'):
                cur.execute(f'SELECT public.{name}(x) FROM unnest(%s::bigint[]) WITH ORDINALITY AS t(x, n) ORDER BY n',
                            (AREAS,))
                found[name] = [row[0] for row in cur.fetchall()]
            for name, ids in (('can_access_zone', ZONES), ('can_access_district', DISTRICTS),
                              ('can_edit_dl_call_in', DISTRICTS), ('can_edit_zl_call_in', DISTRICTS),
                              ('can_edit_zl_zone_call_in', ZONES), ('can_access_mission', MISSIONS)):
                cur.execute(f'SELECT public.{name}(x) FROM unnest(%s::bigint[]) WITH ORDINALITY AS t(x, n) ORDER BY n',
                            (ids,))
                found[name] = [row[0] for row in cur.fetchall()]
            for level, ids in (('mission', MISSIONS), ('zone', ZONES), ('district', DISTRICTS)):
                cur.execute('SELECT public.can_view_call_in(%s, x) FROM unnest(%s::bigint[]) WITH ORDINALITY '
                            'AS t(x, n) ORDER BY n', (level, ids))
                found['can_view_call_in ' + level] = [row[0] for row in cur.fetchall()]
            for table in GUARDED:
                cur.execute(f'SELECT count(*) FROM public.{table}')
                found['rows ' + table] = cur.fetchone()[0]
        finally:
            cur.execute('ROLLBACK')
    return found


def everything():
    return {name: answers(user, changes) for name, user, changes in SCENARIOS}


def timed_read():
    """Seconds for the AP to count every plan (one access check per plan)."""
    started = time.perf_counter()
    answers(AP, [])
    return time.perf_counter() - started


def same(label, now, before):
    differing = [name for name in before if now.get(name) != before[name]]
    check(f'{label}: every answer is the same for all {len(before)} people', not differing, differing)


before_facts = facts()
check('start: both checks are the SQL texts of 013 and 032',
      all(row[1] == 'sql' and row[7] == SQL_TEXTS[row[0]] for row in before_facts), before_facts)
started = time.perf_counter()
reference = everything()
sql_seconds = time.perf_counter() - started
seen = {name: sum(1 for v in found['can_access_area'] if v) for name, found in reference.items()}
check('the people differ: some see every area, some a few, some none',
      max(seen.values()) == len(AREAS) - 2 and 0 in seen.values() and any(0 < v < len(AREAS) - 2 for v in seen.values()),
      sorted(seen.values()))
sql_read = timed_read()

for step in (FORWARD, FORWARD, CLOSE):
    ok, error = run_file(step)
    check(f'{step} runs', ok, error)
after_facts = facts()
check('after 037: both checks run in plpgsql', all(row[1] == 'plpgsql' for row in after_facts), after_facts)
check('after 037: owner, SECURITY DEFINER, STABLE, search_path and rights as before',
      [row[2:7] for row in after_facts] == [row[2:7] for row in before_facts], after_facts)
started = time.perf_counter()
same('after 037', everything(), reference)
plpgsql_seconds = time.perf_counter() - started
plpgsql_read = timed_read()
print(f'  all questions: {sql_seconds:.1f} s in SQL, {plpgsql_seconds:.1f} s after 037; '
      f'the AP reading every guarded table: {sql_read:.2f} s in SQL, {plpgsql_read:.2f} s after 037', flush=True)

for step in (BACK, BACK, CLOSE):
    ok, error = run_file(step)
    check(f'{step} runs', ok, error)
check('after the rollback: the exact SQL texts of 013 and 032, owner, settings and rights as before',
      facts() == before_facts, facts())
same('after the rollback', everything(), reference)

for step in (FORWARD, CLOSE):
    ok, error = run_file(step)
    check(f'{step} runs again', ok, error)
check('037 again: plpgsql, same owner, settings and rights',
      [row[1:7] for row in facts()] == [('plpgsql',) + tuple(row[2:7]) for row in before_facts], facts())
same('037 again', everything(), reference)

# 037 refuses to write over an access check it does not know (someone changed it after 032).
for step in (BACK,):
    ok, error = run_file(step)
    check('the rollback runs before the refusal check', ok, error)
with admin.cursor() as cur:
    cur.execute("SELECT pg_get_functiondef('public.can_access_area(bigint)'::regprocedure)")
    changed = cur.fetchone()[0].replace('SELECT public.is_mission_manager_for_area', '-- changed by hand\n    SELECT '
                                                                                  'public.is_mission_manager_for_area')
    cur.execute('SET ROLE postgres')
    cur.execute(changed)
    cur.execute('RESET ROLE')
ok, error = run_file(FORWARD)
check('037 refuses an access check it does not know', not ok and 'not the 013 / 032 version' in error, error)
check('... and changes nothing', all(row[1] == 'sql' for row in facts()), facts())
for step in (BACK, FORWARD, CLOSE):
    ok, error = run_file(step)
    check(f'{step} runs to finish', ok, error)
check('finished with 037 in place', all(row[1] == 'plpgsql' for row in facts()), facts())
same('finished', everything(), reference)

print(f'{sum(results)}/{len(results)} passed')
sys.exit(0 if all(results) else 1)
