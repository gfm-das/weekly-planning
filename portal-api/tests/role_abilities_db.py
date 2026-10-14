"""public.role_has_ability() and the role-abilities tables against a THROWAWAY database copy that has migration 055.

It runs everything inside one transaction that is rolled back at the end (nothing is kept). It refuses unless DATABASE_URL names a
database containing "test" and ABIL_TEST_THROWAWAY=yes. NOT run in the round-13 session (no Docker or Postgres): run it on a
throw-away copy first, then re-run 019_restrict_public_functions.sql.

Run inside a temporary portal-api container (same way as vollzogen_view_db.py):
  ABIL_TEST_THROWAWAY=yes python tests/role_abilities_db.py
Checks: the seed is today's matrix; the function answers for the signed-in person from their roles (any role may give the right,
managers always have it, nobody signed in or an unknown person has none, an unknown ability is no); the function follows a switch;
anon cannot run it; the portal API's reader returns the rows.
"""
import json
import os
import sys
import uuid
from urllib.parse import urlparse

import psycopg2

sys.path.insert(0, '/app')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('ABIL_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test needs a throwaway *test* database.')

import roles  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail and not ok else ''), flush=True)


conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
try:
    cur.execute('SELECT role,ability,allowed FROM public.role_abilities')
    table = {(r, a): v for r, a, v in cur.fetchall()}
    check('40 rows, equal to the built-in matrix', table == roles.DEFAULT_ABILITIES, len(table))
    check('the portal API reader shape is accepted by roles.py', roles.parse_ability_rows([{'role': r, 'ability': a, 'allowed': v} for (r, a), v in table.items()]) == table)

    # Invented accounts: a user_profiles row cannot be invented without auth.users, so use real rows by role when there are any.
    cur.execute("SELECT id, app_role FROM public.user_profiles WHERE active AND app_role IN ('PRESIDENT','DATA_ADMIN','OFFICE') LIMIT 10")
    people = cur.fetchall()
    cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({'sub': str(uuid.uuid4()), 'role': 'authenticated'}),))
    cur.execute('SET LOCAL ROLE authenticated')
    cur.execute("SELECT public.role_has_ability('calendar.edit')")
    check('an unknown person has no ability', cur.fetchone()[0] is False)
    for who in people:
        cur.execute('RESET ROLE')
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({'sub': str(who[0]), 'role': 'authenticated'}),))
        cur.execute('SET LOCAL ROLE authenticated')
        for ability in roles.ABILITIES:
            cur.execute('SELECT public.role_has_ability(%s)', (ability,))
            got = cur.fetchone()[0]
            if who[1] in ('PRESIDENT', 'DATA_ADMIN'):
                check(f'{who[1]} has {ability}', got is True)
            else:
                check(f'OFFICE has {ability} as built in', got is roles.DEFAULT_ABILITIES[('OFFICE', ability)], got)
    cur.execute("SELECT public.role_has_ability('management')")
    check('an unknown ability is no', cur.fetchone()[0] is False)

    cur.execute('RESET ROLE')
    for office in [p for p in people if p[1] == 'OFFICE'][:1]:
        cur.execute("SELECT set_config('gfm.change_batch', %s, true)", (str(uuid.uuid4()),))
        cur.execute("UPDATE public.role_abilities SET allowed=false, changed_by_name='test' WHERE role='OFFICE' AND ability='vollzogen.view'")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({'sub': str(office[0]), 'role': 'authenticated'}),))
        cur.execute('SET LOCAL ROLE authenticated')
        cur.execute("SELECT public.role_has_ability('vollzogen.view'), public.role_has_ability('calendar.edit')")
        check('the function follows a switch, and only that one', cur.fetchone() == (False, True))
        cur.execute('RESET ROLE')

    cur.execute("SELECT has_function_privilege('anon','public.role_has_ability(text)','EXECUTE'), has_function_privilege('public','public.role_has_ability(text)','EXECUTE')")
    check('anon and PUBLIC cannot run it', cur.fetchone() == (False, False))
finally:
    conn.rollback()
    conn.close()

print(f'{sum(results)}/{len(results)} passed')
sys.exit(0 if all(results) else 1)
