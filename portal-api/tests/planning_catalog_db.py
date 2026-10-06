"""Weekly Planning built from the question list, against a THROWAWAY database copy with migration 024 applied.

Proves, through the real API, roles, row-level security and triggers:
- the form carries each question's choices, grid rows, show/hide rules, limits, last week's answer and the
  catalogue version; every question type is saved as Beta stores it; a grid save merges rows;
- a page whose questions changed in DA Management keeps saving (retired questions are dropped with a note and the
  new questions come back; a grid or tick-box answer loses only its retired rows or choices), and a change committed
  while the form or a save reads the questions is noticed by the next save;
- signed-in users (Beta) do not read a rule whose parent question or its section is retired, like the portal;
- submit refuses unanswered required questions by key (hidden ones are skipped) and accepts a complete plan;
- signed-in users (Beta) can read the rules but nobody but the owner can change the catalogue, and the 024
  triggers refuse every forbidden change even for postgres (like Supabase Studio).

It commits rows (a test section with questions, answers on one plan) and submits and reopens that plan, so it
refuses to run unless DATABASE_URL names a database whose name contains "test" and PEOPLE_TEST_THROWAWAY=yes.
Identity lookups are replaced in-process (as in planning_safety_db.py).

Run inside a temporary portal-api container on the test network:  python tests/planning_catalog_db.py
"""
import base64
import json
import os
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg2

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('PEOPLE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
results = []
RUN = uuid.uuid4().hex[:6]


def check(name, ok, detail=''):
    if callable(ok):
        try:
            ok = ok()
        except Exception as error:  # noqa: BLE001
            ok, detail = False, f'{type(error).__name__}: {error} {detail}'
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail != '' else ''))


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 600}) + '.fixture'


def call(user, method, path, body=None):
    response = api.app.test_client().open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def refused(query, args=()):
    """The database error message of a statement run as postgres, or '' if it was allowed (and then undone)."""
    conn = api.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, args)
        return ''
    except psycopg2.Error as error:
        return error.diag.message_primary or str(error)
    finally:
        conn.rollback()
        conn.close()


def as_role(role, query, args=(), claims=None):
    """Run one statement as anon/authenticated (like PostgREST); returns rows or the error message."""
    conn = api.connect()
    try:
        with conn.cursor() as cur:
            if claims:
                cur.execute("SELECT set_config('request.jwt.claims',%s,true)", (json.dumps(claims),))
            cur.execute(f'SET LOCAL ROLE {role}')
            cur.execute(query, args)
            return [dict(r) for r in cur.fetchall()] if cur.description else []
    except psycopg2.Error as error:
        return 'ERROR: ' + (error.diag.message_primary or str(error))
    finally:
        conn.rollback()
        conn.close()


def stored(key):
    rows = sql('SELECT answer_text,answer_number,answer_boolean,answer_json FROM public.weekly_planning_answers '
               'WHERE weekly_area_report_id=%s AND question_key=%s', (report_id, key))
    return rows[0] if rows else None


users = sql('''SELECT c.area_id, array_agg(DISTINCT c.user_id::text ORDER BY c.user_id::text) AS ids
               FROM public.current_user_context c
               WHERE c.user_active AND c.area_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM public.area_units au WHERE au.area_id=c.area_id)
               GROUP BY c.area_id ORDER BY c.area_id''')
area_id, user = users[0]['area_id'], users[0]['ids'][0]
claims = {'sub': user, 'role': 'authenticated'}

# 0. A test section with one question of each type the live list does not use yet.
section = sql('''INSERT INTO public.planning_question_sections(section_key,section_title,description,display_order)
                 VALUES(%s,'Catalogue test','Throwaway',990) RETURNING id''', (f'zz_catalog_{RUN}',))[0]['id']
keys = {kind: f'zz_{kind.lower()}_{RUN}' for kind in ('TEXT', 'DATE', 'SELECT', 'RADIO', 'CHECKBOX', 'NUMBER')}
for order, (kind, key) in enumerate(keys.items()):
    sql('''INSERT INTO public.planning_questions(section_id,question_key,question_label,question_type,required,display_order,
               min_value,max_value,integer_only,placeholder)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (section, key, f'Test {kind.lower()}', kind, kind == 'SELECT', order * 10,
         2 if kind == 'NUMBER' else None, 9 if kind == 'NUMBER' else None, kind != 'NUMBER', 'Type here' if kind == 'TEXT' else None))
for kind in ('SELECT', 'RADIO', 'CHECKBOX'):
    qid = sql('SELECT id FROM public.planning_questions WHERE question_key=%s', (keys[kind],))[0]['id']
    for order, (value, label) in enumerate((('red', 'Red'), ('blue', 'Blue'), ('green', 'Green'))):
        sql('INSERT INTO public.planning_question_options(question_id,option_value,option_label,display_order) VALUES(%s,%s,%s,%s)',
            (qid, value, label, order))
sql("INSERT INTO public.planning_question_visibility_rules(child_question_key,parent_question_key,operator,comparison_value) VALUES(%s,%s,'equals','blue')",
    (keys['RADIO'], keys['SELECT']))

# 1. The form.
status, form = call(user, 'GET', '/api/planning/form')
report_id, unit_id = form['report']['report_id'], form['report']['unit_id']
if form['report']['status'] != 'DRAFT':
    sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL WHERE id=%s", (report_id,))
    status, form = call(user, 'GET', '/api/planning/form')
questions = {q['question_key']: q for q in form['questions']}
version = form.get('catalog_version')
check('form: 200 with a catalogue version and no invented grid choices', status == 200 and isinstance(version, int) and 'grid_options' not in form,
      (status, version))
grid = questions.get('ward_coordination_attendance', {})
check('form: the ward coordination grid has its 8 rows and 3 choices from the database',
      len(grid.get('rows', [])) == 8 and [o['value'] for o in grid.get('options', [])] == ['yes', 'no', 'dont_have_one'], grid.get('rows'))
check('form: "1st Time 1st Week" has both rules and saves 0 when hidden',
      lambda: sorted(r['parent'] for r in questions['sacrament_first_time_first_week']['rules']) == ['sacrament_attendance_actual', 'sacrament_first_time']
      and questions['sacrament_first_time_first_week']['value_when_hidden'] == '0')
check('form: limits, placeholder and every question carry "previous" (last week)',
      lambda: questions[keys['NUMBER']]['min_value'] == 2 and questions[keys['NUMBER']]['max_value'] == 9
      and questions[keys['TEXT']]['placeholder'] == 'Type here' and all('previous' in q for q in form['questions']))
check('form: the test questions of every type are there, in order', lambda: [k for k in questions if k.endswith(RUN)] == list(keys.values()))


def save(values, page_version=None):
    return call(user, 'PUT', f'/api/planning/reports/{report_id}/answers',
                {'answers': {'changes_only': True, 'catalog_version': version if page_version is None else page_version, **values}})


# 2. Every type saved like Beta.
status, body = save({keys['TEXT']: '  short note ', keys['DATE']: '2026-10-04', keys['SELECT']: 'blue', keys['RADIO']: 'green',
                     keys['CHECKBOX']: ['green', 'red'], keys['NUMBER']: 5, 'ward_coordination_held': True,
                     'ward_coordination_attendance': {'elders_quorum_representative': 'yes'}, 'weekly_action_plan': 'Catalogue test plan'})
check('save: all types -> 200', status == 200 and body.get('catalog_version') == version, (status, body and body.get('error')))
check('save: text, date, choice and radio are stored as text', lambda: (stored(keys['TEXT'])['answer_text'], stored(keys['DATE'])['answer_text'],
      stored(keys['SELECT'])['answer_text'], stored(keys['RADIO'])['answer_text']) == ('short note', '2026-10-04', 'blue', 'green'))
check('save: tick boxes as a list of codes (in choice order), yes/no as a boolean, a number as a number',
      lambda: stored(keys['CHECKBOX'])['answer_json'] == ['red', 'green'] and stored('ward_coordination_held')['answer_boolean'] is True
      and int(stored(keys['NUMBER'])['answer_number']) == 5)
status, body = save({'ward_coordination_attendance': {'relief_society_representative': 'no'}})
check('save: a grid row saved by a companion is kept (rows are merged)',
      lambda: stored('ward_coordination_attendance')['answer_json'] == {'elders_quorum_representative': 'yes', 'relief_society_representative': 'no'})
status, body = save({keys['NUMBER']: 12})
check('save: a number above its limit -> 400 naming the question', lambda: status == 400 and body['error'] == 'Test number must be a number from 2 to 9.', body)
status, body = save({keys['SELECT']: 'purple'})
check('save: a choice that is not offered -> 400', lambda: status == 400 and 'choose one of the listed answers' in body['error'], body)
# A "value saved while hidden" that does not fit its question (only Studio can set one now) never blocks a save.
sql("UPDATE public.planning_questions SET value_when_hidden='-1' WHERE question_key='sacrament_first_time'")
status, body = save({'sacrament_attendance_actual': 0, 'sacrament_first_time': -1, 'sacrament_first_time_first_week': 0,
                     'weekly_action_plan': 'Saved with a bad hidden value'},
                    page_version=sql('SELECT version FROM public.planning_catalog_version')[0]['version'])
check('save: a bad value when hidden is skipped and the rest is saved -> 200',
      lambda: status == 200 and 'dropped' not in body and stored('weekly_action_plan')['answer_text'] == 'Saved with a bad hidden value'
      and int(stored('sacrament_attendance_actual')['answer_number']) == 0
      and (stored('sacrament_first_time') or {}).get('answer_number') != -1, (status, body and body.get('error')))
sql("UPDATE public.planning_questions SET value_when_hidden='0' WHERE question_key='sacrament_first_time'")

# 3. The questions change in DA Management while the page is open.
sql('UPDATE public.planning_questions SET question_label=%s WHERE question_key=%s', ('Test text (renamed)', keys['TEXT']))
sql('UPDATE public.planning_questions SET active=false WHERE question_key=%s', (keys['DATE'],))
new_version = sql('SELECT version FROM public.planning_catalog_version')[0]['version']
check('catalogue version went up with the changes', new_version > version, (version, new_version))
status, body = save({keys['DATE']: '2026-10-05', keys['TEXT']: 'typed on the old page'})
check('stale page: 200, the text is saved, the retired date is dropped with a note',
      lambda: status == 200 and stored(keys['TEXT'])['answer_text'] == 'typed on the old page'
      and stored(keys['DATE'])['answer_text'] == '2026-10-04' and body['dropped'] == [keys['DATE']] and body['note'], (status, body and body.get('error')))
check('stale page: the new questions come back (renamed label, retired one gone) with the new version',
      lambda: body['catalog_changed'] is True and body['catalog_version'] == new_version
      and {q['question_key']: q['question_label'] for q in body['questions']}[keys['TEXT']] == 'Test text (renamed)'
      and keys['DATE'] not in {q['question_key'] for q in body['questions']})
status, body = save({keys['TEXT']: 'again'}, page_version=new_version)
check('page with the new version: a normal save', lambda: status == 200 and 'catalog_changed' not in body, body)
version = new_version
current_version = lambda: sql('SELECT version FROM public.planning_catalog_version')[0]['version']

# 3b. A stale page keeps the rest of a grid or tick-box answer when one row or choice was retired meanwhile
# (review: the whole answer was dropped, so a row still asked lost its change).
grid_key = f'zz_grid_{RUN}'
grid_qid = sql("""INSERT INTO public.planning_questions(section_id,question_key,question_label,question_type,display_order)
                  VALUES(%s,%s,'Test grid','GRID',95) RETURNING id""", (section, grid_key))[0]['id']
for order, (value, label) in enumerate((('yes', 'Yes'), ('no', 'No'))):
    sql('INSERT INTO public.planning_question_options(question_id,option_value,option_label,display_order) VALUES(%s,%s,%s,%s)', (grid_qid, value, label, order))
for order, row in enumerate(('first', 'second', 'third')):
    sql('INSERT INTO public.planning_question_grid_rows(question_id,row_key,row_label,display_order) VALUES(%s,%s,%s,%s)', (grid_qid, row, row.title(), order))
loaded = current_version()  # the page shows the grid and the tick boxes from here on
sql("UPDATE public.planning_question_grid_rows SET active=false WHERE question_id=%s AND row_key='second'", (grid_qid,))
sql("UPDATE public.planning_question_options o SET active=false FROM public.planning_questions q WHERE q.id=o.question_id AND q.question_key=%s AND o.option_value='green'",
    (keys['CHECKBOX'],))
status, body = save({grid_key: {'first': 'yes', 'second': 'no'}, keys['CHECKBOX']: ['red', 'green']}, page_version=loaded)
check('stale page: a grid keeps its rows still asked and tick boxes their choices still offered; only the rest is listed',
      lambda: status == 200 and stored(grid_key)['answer_json'] == {'first': 'yes'} and stored(keys['CHECKBOX'])['answer_json'] == ['red']
      and body['dropped_parts'] == {grid_key: ['second'], keys['CHECKBOX']: ['green']} and body['dropped'] == [] and body['catalog_changed'] is True,
      (status, body and (body.get('error'), body.get('dropped'), body.get('dropped_parts'))))

# 3c. A DA Management change committed while the form or a save reads the questions (review: the form read the
# version after the questions, so the page could keep the old questions with the new version for good).
import planning as planning_module  # noqa: E402  (the module the API uses)


def change_committed_after(read):
    def wrapped(*args):
        result = read(*args)
        sql('UPDATE public.planning_questions SET help_text=help_text WHERE question_key=%s', (keys['TEXT'],))  # bumps the version
        return result
    return wrapped


with patch.object(planning_module, '_form_questions', side_effect=change_committed_after(planning_module._form_questions)):
    status, raced = call(user, 'GET', '/api/planning/form')
status, body = save({keys['TEXT']: 'after a raced form'}, page_version=raced['catalog_version'])
check('form: a change committed while the questions are read makes the next save refresh them',
      lambda: body['catalog_changed'] is True and body['catalog_version'] == current_version() > raced['catalog_version'], (raced.get('catalog_version'), body.get('catalog_version')))
before = current_version()
with patch.object(planning_module, '_catalog_questions', side_effect=change_committed_after(planning_module._catalog_questions)):
    status, first = save({keys['TEXT']: 'a raced save'}, page_version=before)
status, second = save({}, page_version=first['catalog_version'])
check('save: a change committed while a save reads the questions is noticed by the next save',
      lambda: first['catalog_version'] == before and 'catalog_changed' not in first and second['catalog_changed'] is True, (before, first.get('catalog_version')))
version = current_version()

# 4. Submit checks the required questions by key; hidden ones are skipped.
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/submit')
fields = (body or {}).get('fields') or {}
check('submit with required questions unanswered -> 400 listing their keys', status == 400 and fields and all(k in questions for k in fields),
      (status, list(fields)[:5]))
check('submit: a hidden follow-up is not listed while its parent is unanswered',
      'sacrament_first_time_first_week' not in fields and 'sacrament_first_time' not in fields, list(fields))
answers = {}
for key, q in questions.items():
    if not q['required'] or key in {keys['DATE']}:
        continue
    kind = q['question_type']
    answers[key] = {'NUMBER': 0, 'BOOLEAN': False, 'LONG_TEXT': 'Test', 'TEXT': 'Test', 'DATE': '2026-10-01',
                    'SELECT': q['options'][0]['value'] if q['options'] else None, 'RADIO': q['options'][0]['value'] if q['options'] else None,
                    'CHECKBOX': [q['options'][0]['value']] if q['options'] else None,
                    'GRID': {row['key']: q['options'][0]['value'] for row in q['rows']}}[kind]
answers['ward_coordination_held'] = True  # the grid is then shown and required
answers['ward_coordination_attendance'] = {row['key']: 'no' for row in grid['rows'][:-1]}  # one row left open
answers['sacrament_attendance_actual'] = 0  # both follow-ups hidden and saved as 0 by the page
answers['sacrament_first_time'] = answers['sacrament_first_time_first_week'] = 0
status, body = save(answers)
check('filling in the required answers -> 200', status == 200, body and body.get('error'))
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/submit')
check('submit with one grid row unanswered -> 400 naming only the grid',
      lambda: status == 400 and list(body['fields']) == ['ward_coordination_attendance'], (status, body))
save({'ward_coordination_attendance': {grid['rows'][-1]['key']: 'dont_have_one'}})
sql("UPDATE public.planning_questions SET required=true WHERE question_key=%s", (keys['RADIO'],))  # hidden unless the choice is blue
save({keys['SELECT']: 'red'}, page_version=sql('SELECT version FROM public.planning_catalog_version')[0]['version'])
status, body = call(user, 'POST', f'/api/planning/reports/{report_id}/submit')
check('submit of a complete plan (a required question hidden by its rule is skipped) -> 200 SUBMITTED',
      lambda: status == 200 and body['status'] == 'SUBMITTED', (status, body))
sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL WHERE id=%s", (report_id,))

# 5. Who may read and change the catalogue (PostgREST roles: Beta reads as authenticated).
check('signed-in users read the active rules (Beta)', lambda: len(as_role('authenticated', 'SELECT * FROM public.planning_question_visibility_rules', claims=claims)) >= 4)
sql("INSERT INTO public.planning_question_visibility_rules(child_question_key,parent_question_key,operator,comparison_value,active) VALUES(%s,%s,'equals','1',false)",
    (keys['TEXT'], keys['NUMBER']))
check('signed-in users do not see turned-off rules', lambda: all(r['active'] for r in as_role('authenticated', 'SELECT * FROM public.planning_question_visibility_rules', claims=claims)))
# Row-level security gives anon no rows (024). 029 keeps anon's SELECT on the five catalogue tables (024's rollback
# checks for it) and takes every other right in public from anon.
check('anon sees no rules any more', lambda: as_role('anon', 'SELECT * FROM public.planning_question_visibility_rules') == [])
# Beta ignores a rule whose parent question is not on the form, as the portal does (review: Beta kept the child
# hidden, while the portal showed and required it). The rule itself stays and applies again when the parent is back.
seen = lambda: as_role('authenticated', 'SELECT child_question_key FROM public.planning_question_visibility_rules WHERE parent_question_key=%s',
                       (keys['SELECT'],), claims=claims)
portal_rules = lambda: next(q for q in call(user, 'GET', '/api/planning/form')[1]['questions'] if q['question_key'] == keys['RADIO'])['rules']
check('Beta reads the rule whose parent question is on the form', lambda: seen() == [{'child_question_key': keys['RADIO']}] and len(portal_rules()) == 1)
sql('UPDATE public.planning_questions SET active=false WHERE question_key=%s', (keys['SELECT'],))
check('parent question retired: neither Beta nor the portal gets its rule', lambda: seen() == [] and portal_rules() == [])
sql('UPDATE public.planning_questions SET active=true WHERE question_key=%s', (keys['SELECT'],))
check('parent question restored: the rule is back for both', lambda: len(seen()) == 1 and len(portal_rules()) == 1)
sql('UPDATE public.planning_question_sections SET active=false WHERE id=%s', (section,))
check("parent question's section retired: Beta does not get the rule", lambda: seen() == [])
sql('UPDATE public.planning_question_sections SET active=true WHERE id=%s', (section,))
check('the rule itself stayed active throughout', lambda: sql('SELECT bool_and(active) AS on FROM public.planning_question_visibility_rules WHERE parent_question_key=%s',
                                                             (keys['SELECT'],))[0]['on'] is True)
check('saved answers have an index by question key (DA Management counts them)',
      lambda: sql("SELECT to_regclass('public.weekly_planning_answers_question_key_idx')::text AS idx")[0]['idx'] == 'weekly_planning_answers_question_key_idx')
for role in ('anon', 'authenticated'):
    for statement in ("DELETE FROM public.planning_question_visibility_rules",
                      "UPDATE public.planning_questions SET question_label='x'",
                      "INSERT INTO public.planning_question_options(question_id,option_value,option_label) VALUES(1,'x','x')",
                      "TRUNCATE public.planning_question_grid_rows",
                      "UPDATE public.planning_catalog_version SET version=1",
                      "SELECT * FROM public.planning_catalog_changes"):
        outcome = as_role(role, statement, claims=claims if role == 'authenticated' else None)
        check(f'{role} may not: {statement[:48]}', isinstance(outcome, str) and 'permission denied' in outcome, outcome)
# planning_option_used runs with the caller's rights and only its owner (the triggers, DA Management) runs it:
# signed-in users cannot ask it whether any plan in the mission holds a given text.
for role in ('anon', 'authenticated', 'service_role'):
    outcome = as_role(role, "SELECT public.planning_option_used('weekly_action_plan', 'Catalogue test plan')",
                      claims=claims if role == 'authenticated' else None)
    check(f'{role} may not run planning_option_used', isinstance(outcome, str) and 'permission denied' in outcome, outcome)
check('planning_option_used is not SECURITY DEFINER and still answers for postgres',
      lambda: sql("SELECT p.prosecdef, public.planning_option_used(%s, 'red') AS used "
                  "FROM pg_proc p WHERE p.oid = 'public.planning_option_used(text,text)'::regprocedure", (keys['SELECT'],))[0]
      == {'prosecdef': False, 'used': True})
check('signed-in users read the catalogue version', lambda: as_role('authenticated', 'SELECT version FROM public.planning_catalog_version', claims=claims)[0]['version']
      == sql('SELECT version FROM public.planning_catalog_version')[0]['version'])
check('Beta reads last week through get_previous_planning_answers as before',
      lambda: isinstance(as_role('authenticated', 'SELECT * FROM public.get_previous_planning_answers(%s)', (unit_id,), claims=claims), list))

# 6. The 024 protections hold for postgres too (Supabase Studio, DA Management).
forbidden = {
    'rename a question key': ("UPDATE public.planning_questions SET question_key=question_key||'_x' WHERE question_key=%s", (keys['NUMBER'],)),
    'delete a question': ('DELETE FROM public.planning_questions WHERE question_key=%s', (keys['NUMBER'],)),
    'change the type of an answered question': ("UPDATE public.planning_questions SET question_type='TEXT' WHERE question_key=%s", (keys['NUMBER'],)),
    'retire a protected question': ("UPDATE public.planning_questions SET active=false WHERE question_key='friends_found_goal'", ()),
    'make a protected required question optional': ("UPDATE public.planning_questions SET required=false WHERE question_key='weekly_action_plan'", ()),
    're-type a protected unanswered question': ("UPDATE public.planning_questions SET question_type='TEXT' WHERE question_key='baptismal_dates_goal'", ()),
    'unprotect without the setting': ("UPDATE public.planning_questions SET protected=false WHERE question_key='friends_found_goal'", ()),
    'move a protected question to a retired section': (
        "UPDATE public.planning_questions SET section_id=(SELECT id FROM public.planning_question_sections WHERE section_key=%s) WHERE question_key='facebook_finding_days'",
        (f'zz_retired_{RUN}',)),
    'rename a section key': ("UPDATE public.planning_question_sections SET section_key='x_'||section_key WHERE id=%s", (section,)),
    'delete a section': ('DELETE FROM public.planning_question_sections WHERE id=%s', (section,)),
    'retire the Key Indicators section': ("UPDATE public.planning_question_sections SET active=false WHERE section_key='key_indicators_conversion'", ()),
    'retire a section with protected questions': ("UPDATE public.planning_question_sections SET active=false WHERE section_key='ward_coordination'", ()),
    'change a choice code used in a plan': ("UPDATE public.planning_question_options o SET option_value='navy' FROM public.planning_questions q WHERE q.id=o.question_id AND q.question_key=%s AND o.option_value='red'", (keys['SELECT'],)),
    'delete a tick-box choice used in a plan': ("DELETE FROM public.planning_question_options o USING public.planning_questions q WHERE q.id=o.question_id AND q.question_key=%s AND o.option_value='red'", (keys['CHECKBOX'],)),
    'delete a grid choice used in a plan': ("DELETE FROM public.planning_question_options o USING public.planning_questions q WHERE q.id=o.question_id AND q.question_key='ward_coordination_attendance' AND o.option_value='no'", ()),
    'rename a grid row used in a plan': ("UPDATE public.planning_question_grid_rows r SET row_key='eq' FROM public.planning_questions q WHERE q.id=r.question_id AND r.row_key='elders_quorum_representative'", ()),
    'retire a row of a protected grid': ("UPDATE public.planning_question_grid_rows r SET active=false FROM public.planning_questions q WHERE q.id=r.question_id AND q.question_key='ward_coordination_attendance' AND r.row_key='gemiko_leader'", ()),
    'a rule on itself': ("INSERT INTO public.planning_question_visibility_rules(child_question_key,parent_question_key,operator,comparison_value) VALUES(%s,%s,'equals','1')", (keys['TEXT'], keys['TEXT'])),
    'a circle of rules': ("INSERT INTO public.planning_question_visibility_rules(child_question_key,parent_question_key,operator,comparison_value) VALUES(%s,%s,'equals','x')", (keys['SELECT'], keys['RADIO'])),
    'empty the questions': ('TRUNCATE public.planning_question_options', ()),
    'a key with capitals': ("INSERT INTO public.planning_questions(section_id,question_key,question_label,question_type) VALUES(%s,'Bad_Key','x','TEXT')", (section,)),
    'a half-number lowest limit on a whole-number question': ("UPDATE public.planning_questions SET integer_only=true, min_value=0.5 WHERE question_key=%s", (f'zz_spare_{RUN}',)),
    'a half-number highest limit on a whole-number question': ("UPDATE public.planning_questions SET integer_only=true, max_value=9.5 WHERE question_key=%s", (f'zz_spare_{RUN}',)),
}
sql("INSERT INTO public.planning_question_sections(section_key,section_title,active) VALUES(%s,'Retired test section',false)", (f'zz_retired_{RUN}',))
sql("INSERT INTO public.planning_questions(section_id,question_key,question_label,question_type) VALUES(%s,%s,'Never answered','NUMBER')", (section, f'zz_spare_{RUN}'))
for name, (statement, args) in forbidden.items():
    message = refused(statement, args)
    check(f'refused: {name}', message != '', message)
# A protected question's choices, rows and rules stay exactly as they are, and nothing is saved for it while hidden
# (a rule could otherwise hide a Key Indicator, which then is neither asked nor required).
ward_rule = sql("SELECT id FROM public.planning_question_visibility_rules WHERE child_question_key='ward_coordination_attendance'")[0]['id']
fixed = {
    'add a choice to the protected grid': (
        "INSERT INTO public.planning_question_options(question_id,option_value,option_label) SELECT id,'maybe','Maybe' FROM public.planning_questions WHERE question_key='ward_coordination_attendance'",
        (), 'no choice can be added'),
    'add a row to the protected grid': (
        "INSERT INTO public.planning_question_grid_rows(question_id,row_key,row_label) SELECT id,'bishop','Bishop' FROM public.planning_questions WHERE question_key='ward_coordination_attendance'",
        (), 'no row can be added'),
    'a rule that hides a Key Indicator': (
        "INSERT INTO public.planning_question_visibility_rules(child_question_key,parent_question_key,operator,comparison_value) VALUES('friends_found_goal','ward_coordination_held','equals','true')",
        (), 'no rule can be added'),
    'turn off the rule of a protected question': ('UPDATE public.planning_question_visibility_rules SET active=false WHERE id=%s', (ward_rule,), 'cannot be changed or turned off'),
    'change the rule of a protected question': ("UPDATE public.planning_question_visibility_rules SET comparison_value='false' WHERE id=%s", (ward_rule,), 'cannot be changed'),
    'delete the rule of a protected question': ('DELETE FROM public.planning_question_visibility_rules WHERE id=%s', (ward_rule,), 'cannot be deleted'),
    'move a rule onto a protected question': ("UPDATE public.planning_question_visibility_rules SET child_question_key='friends_found_goal' WHERE child_question_key=%s", (keys['RADIO'],), 'no rule can be moved'),
    'a value saved while hidden on a protected question': ("UPDATE public.planning_questions SET value_when_hidden='0' WHERE question_key='friends_found_goal'", (), 'nothing is saved for it while hidden'),
    'protect a question that has a value saved while hidden': ("UPDATE public.planning_questions SET protected=true WHERE question_key='sacrament_first_time'", (), 'Clear "value saved while hidden" first'),
    'empty the rules': ('TRUNCATE public.planning_question_visibility_rules', (), 'cannot be emptied'),
}
for name, (statement, args, why) in fixed.items():
    message = refused(statement, args)
    check(f'refused: {name}', why in message, message)
allowed = {
    'relabel a protected question': ("UPDATE public.planning_questions SET question_label=question_label||' ' WHERE question_key='friends_found_goal'", ()),
    'change the type of an unanswered question': ("UPDATE public.planning_questions SET question_type='LONG_TEXT' WHERE question_key=%s", (f'zz_spare_{RUN}',)),
    'retire an unprotected question': ('UPDATE public.planning_questions SET active=false WHERE question_key=%s', (keys['TEXT'],)),
    'delete an unused choice': ("DELETE FROM public.planning_question_options o USING public.planning_questions q WHERE q.id=o.question_id AND q.question_key=%s AND o.option_value='green'", (keys['SELECT'],)),
    'change an unused choice code': ("UPDATE public.planning_question_options o SET option_value='lime' FROM public.planning_questions q WHERE q.id=o.question_id AND q.question_key=%s AND o.option_value='green'", (keys['SELECT'],)),
    'retire a used choice': ("UPDATE public.planning_question_options o SET active=false FROM public.planning_questions q WHERE q.id=o.question_id AND q.question_key=%s AND o.option_value='blue'", (keys['SELECT'],)),
    'unprotect on purpose with the setting': ("SELECT set_config('planning_catalog.unprotect','on',true); UPDATE public.planning_questions SET protected=false WHERE question_key='long_term_service'", ()),
    'change a protected grid on purpose (unprotect, add a row, protect again)': (
        "SELECT set_config('planning_catalog.unprotect','on',true); "
        "UPDATE public.planning_questions SET protected=false WHERE question_key='ward_coordination_attendance'; "
        "INSERT INTO public.planning_question_grid_rows(question_id,row_key,row_label) SELECT id,'bishop','Bishop' FROM public.planning_questions WHERE question_key='ward_coordination_attendance'; "
        "UPDATE public.planning_questions SET protected=true WHERE question_key='ward_coordination_attendance'", ()),
    'relabel a choice of the protected grid': ("UPDATE public.planning_question_options o SET option_label=option_label||' ' FROM public.planning_questions q WHERE q.id=o.question_id AND q.question_key='ward_coordination_attendance' AND o.option_value='yes'", ()),
    'a rule whose parent is a protected question': ("UPDATE public.planning_question_visibility_rules SET parent_question_key='ward_coordination_held', comparison_value='true' WHERE child_question_key=%s", (keys['RADIO'],)),
    'retire a section without protected questions': ('UPDATE public.planning_question_sections SET active=false WHERE id=%s', (section,)),
    'a half-number limit when decimals are allowed': ("UPDATE public.planning_questions SET integer_only=false, min_value=0.5, max_value=9.5 WHERE question_key=%s", (f'zz_spare_{RUN}',)),
}
for name, (statement, args) in allowed.items():
    message = refused(statement, args)
    check(f'allowed: {name}', message == '', message)
check('updated_at is kept by the trigger', lambda: sql('SELECT updated_at > created_at AS moved FROM public.planning_questions WHERE question_key=%s', (keys['TEXT'],))[0]['moved'])

# Clean up what the plan got (questions and sections are never deleted; the test ones are retired).
sql('DELETE FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s AND question_key LIKE %s', (report_id, f'zz_%_{RUN}'))
sql('UPDATE public.planning_questions SET active=false WHERE section_id=%s', (section,))
sql('UPDATE public.planning_question_sections SET active=false WHERE id=%s', (section,))
print(f'\n{sum(results)}/{len(results)} passed (throwaway database {dbname})')
sys.exit(0 if all(results) else 1)
