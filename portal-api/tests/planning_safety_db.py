"""Two companions editing one shared plan at once, against a THROWAWAY database copy.

Proves that saves keep each other's answers and people: concurrent edits of different
answers and person fields, a friend added by the companion, a cleared friend name, a friend
the companion removed, hidden sacrament follow-ups, saves that touch the same rows in opposite
order (no deadlock), person-card work counting as activity for the Sunday reminder, a number out
of range refused with the person's name, the order of new friends after removals, a page from an
old portal version, and the Sunday rollover.

Saves are sent the way the current planning page sends them: only the changes, marked
"changes_only": true.

It commits rows and briefly moves public.current_reporting_sunday() a week ahead (restored at the end),
so it refuses to run unless DATABASE_URL points at a database whose name contains "test"
and PEOPLE_TEST_THROWAWAY=yes. Identity lookups are replaced in-process (as in
planning_people_db.py); database roles, RLS, triggers and area checks are the real ones.

Run inside a temporary portal-api container:  python tests/planning_safety_db.py
"""
import base64
import json
import os
import sys
import threading
import time
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('PEOPLE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402
import reminders  # noqa: E402

LAST_WEEK = "This plan is for last week. Reload to open this week's plan."
RELOAD = "This page was updated. Reload to keep saving."


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
results = []


def check(name, ok, detail=''):
    if callable(ok):  # evaluated here, so a missing key in a reply counts as a failed check
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
    # A new test client per call, so the two companions can run in parallel threads.
    response = api.app.test_client().open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True)


def save_answers(user, values, report=None):
    return call(user, 'PUT', f'/api/planning/reports/{report or report_id}/answers', {'answers': {'changes_only': True, **values}})


def save_people(user, groups):
    return call(user, 'PUT', people_url, {'people': {'changes_only': True, **groups}})


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def friends():
    return {r['id']: r for r in sql('SELECT id, name, notes, at_church_this_sunday, display_order FROM public.weekly_high_potential_friends WHERE weekly_area_report_id=%s', (report_id,))}


def answer_numbers(keys):
    return {r['question_key']: int(r['answer_number']) for r in sql(
        'SELECT question_key, answer_number FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s AND question_key=ANY(%s)', (report_id, list(keys)))}


users = sql('''SELECT c.area_id, array_agg(DISTINCT c.user_id::text ORDER BY c.user_id::text) AS ids
               FROM public.current_user_context c
               WHERE c.user_active AND c.area_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM public.area_units au WHERE au.area_id=c.area_id)
               GROUP BY c.area_id HAVING count(DISTINCT c.user_id) >= 2 ORDER BY c.area_id''')
area_id, (a, b) = users[0]['area_id'], users[0]['ids'][:2]
outsider = sql('SELECT user_id FROM public.current_user_context WHERE user_active AND area_id IS DISTINCT FROM %s LIMIT 1', (area_id,))
print(f'fixture: area {area_id}, companions A and B (two sign-ins of the same area)')

status, form_a = call(a, 'GET', '/api/planning/form')
status_b, form_b = call(b, 'GET', '/api/planning/form?unit_id=%d' % form_a['report']['unit_id'])
report_id = form_a['report']['report_id']
check('both companions open the same shared plan', status == 200 and status_b == 200 and form_b['report']['report_id'] == report_id,
      (status, status_b, report_id))
if form_a['report']['status'] != 'DRAFT':
    sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL WHERE id=%s", (report_id,))
answers_url, people_url = f'/api/planning/reports/{report_id}/answers', f'/api/planning/reports/{report_id}/people'
conditional = {'sacrament_first_time', 'sacrament_first_time_first_week', 'sacrament_attendance_actual'}
numbers = [q['question_key'] for q in form_a['questions'] if q['question_type'] == 'NUMBER' and q['question_key'] not in conditional][:6]
texts = [q['question_key'] for q in form_a['questions'] if q['question_type'] == 'LONG_TEXT'][:2]

# 1. Both companions type into different answers at the same time; each page sends only what it changed.
errors = []


def companion(user, keys, base, rounds=4):
    for step in range(rounds):
        for key in keys:
            status, body = save_answers(user, {key: base + step})
            if status != 200:
                errors.append((status, body))


threads = [threading.Thread(target=companion, args=(a, numbers[0::2], 100)),
           threading.Thread(target=companion, args=(b, numbers[1::2], 200))]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
saved = answer_numbers(numbers)
expected = {key: (103 if key in numbers[0::2] else 203) for key in numbers}
check(f'concurrent answer edits: all {len(numbers)} answers kept ({len(numbers[0::2])} by A, {len(numbers[1::2])} by B)',
      not errors and saved == expected, (errors[:2], saved))
status, body = save_answers(a, {texts[0]: 'A: visit the Kleins'})
status, body = save_answers(b, {texts[1]: 'B: plan the baptism'})
check("B's save returns A's text answer too, so B's page can show it",
      lambda: status == 200 and body['answers'].get(texts[0]) == 'A: visit the Kleins', status)
status, body = save_answers(a, {texts[0]: ''})
stored = {r['question_key'] for r in sql('SELECT question_key FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s', (report_id,))}
check("A clearing A's own answer deletes only that one; B's answer stays",
      status == 200 and texts[0] not in stored and texts[1] in stored, status)
status, body = save_answers(a, {numbers[0]: 'abc'})
check('a word in a number answer -> 400 with a clear message (was 500)', lambda: status == 400 and body['error'].endswith('must be a number.'), (status, body))

# 1b. Hidden sacrament follow-ups. B fills all three; A's page still shows them empty and A types only the
# attendance. The page now sends the attendance alone, so B's follow-ups stay. When A sets the attendance
# to 0 the page also sends 0 for both follow-ups (they no longer apply), and that is saved.
sacrament = ('sacrament_attendance_actual', 'sacrament_first_time', 'sacrament_first_time_first_week')
if all(any(q['question_key'] == key for q in form_a['questions']) for key in sacrament):
    save_answers(b, dict(zip(sacrament, (5, 2, 1))))
    status, body = save_answers(a, {sacrament[0]: 3})
    check("A changing only the attendance keeps B's '1st Time' and '1st Time 1st Week'",
          lambda: status == 200 and answer_numbers(sacrament) == dict(zip(sacrament, (3, 2, 1))), (status, answer_numbers(sacrament)))
    status, body = save_answers(a, dict(zip(sacrament, (0, 0, 0))))
    check("A setting the attendance to 0 saves 0 for both follow-ups", status == 200 and answer_numbers(sacrament) == dict.fromkeys(sacrament, 0),
          answer_numbers(sacrament))

# 2. Person cards: A and B edit different fields of the same friend (and of the same new member) at once.
created = [call(a, 'POST', f'/api/planning/reports/{report_id}/people/high_potential', {})[1]['id'] for _ in range(2)]
f1, f2 = created
nm_rows = sql('SELECT id FROM public.weekly_new_members WHERE weekly_area_report_id=%s ORDER BY id LIMIT 1', (report_id,))
if not nm_rows:
    # Every field of the New Member form is required except the second language (planning.NEW_MEMBER_REQUIRED).
    status, body = call(a, 'POST', f'/api/planning/reports/{report_id}/people/new_member', {
        'first_name': 'Zz Safety', 'last_name': 'Testperson', 'age_range': '18-30', 'gender': 'Male',
        'living_situation': 'Student', 'marital_status': 'Single', 'mission_language_competency': 'Minimal',
        'baptismal_date_extended': '2026-09-01', 'baptism_date': '2026-09-20', 'confirmation_date': '2026-09-27',
        'date_of_birth': '2000-01-01', 'finding_source': 'Member/Member', 'native_language': 'German',
        'country_of_origin': 'Germany', 'child_dependents': 0, 'conversion_success_notes': 'Test person.'})
    nm_rows = [{'id': body['weekly_id']}]
nm = nm_rows[0]['id']


def edit_people(user, rows, rounds=4):
    for step in range(rounds):
        payload = {'high_potential': [], 'new_members': []}
        for group, row_id, field, value in rows:
            payload[group].append({'id': row_id, field: value(step)})
        status, body = save_people(user, payload)
        if status != 200:
            errors.append((status, body))


threads = [threading.Thread(target=edit_people, args=(a, [('high_potential', f1, 'notes', lambda s: f'A note {s}'),
                                                          ('new_members', nm, 'lessons_actual', lambda s: s + 1)])),
           threading.Thread(target=edit_people, args=(b, [('high_potential', f1, 'at_church_this_sunday', lambda s: s % 2 == 1),
                                                          ('high_potential', f2, 'notes', lambda s: f'B note {s}'),
                                                          ('new_members', nm, 'how_are_they_doing', lambda s: f'B says {s}')]))]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
rows, member = friends(), sql('SELECT lessons_actual, how_are_they_doing FROM public.weekly_new_members WHERE id=%s', (nm,))[0]
check('concurrent person edits: A\'s and B\'s fields on the same friend both kept',
      lambda: not errors and rows[f1]['notes'] == 'A note 3' and rows[f1]['at_church_this_sunday'] is True and rows[f2]['notes'] == 'B note 3',
      (errors[:2], {k: (v['notes'], v['at_church_this_sunday']) for k, v in rows.items() if k in created}))
check('concurrent person edits: A\'s and B\'s fields on the same new member both kept',
      member['lessons_actual'] == 4 and member['how_are_they_doing'] == 'B says 3', member)

# 2b. Saves that touch the same two friends in opposite order at the same moment wait for each other
# (the plan is locked first) instead of deadlocking into a 500.
failures, rounds = [], 60


def opposite(user, order, label):
    for step in range(rounds):
        status, body = save_people(user, {'high_potential': [{'id': row_id, 'notes': f'{label} {step}'} for row_id in order]})
        if status != 200:
            failures.append((status, body and body.get('error')))


deadlocks = lambda: sql('SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()')[0]['deadlocks']
time.sleep(1.2)
deadlocks_before = deadlocks()
threads = [threading.Thread(target=opposite, args=(a, [f1, f2], 'A')), threading.Thread(target=opposite, args=(b, [f2, f1], 'B')),
           threading.Thread(target=opposite, args=(a, [f2, f1], 'A2')), threading.Thread(target=opposite, args=(b, [f1, f2], 'B2'))]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
time.sleep(1.2)  # the statistics are written a moment after each transaction
check(f'{4 * rounds} saves of the same two friends in opposite order: all saved, no deadlock',
      not failures and deadlocks() == deadlocks_before, (len(failures), failures[:2], deadlocks() - deadlocks_before))

# 2c. Work on person cards alone counts as activity. The Sunday planning reminder (reminders.planning_due) and the
# Overview's activity time read the plan's updated_at, which person rows never change on their own.
def reminder_sees_work_since(t0):
    """reminders.planning_due at 18:30 on the plan's Sunday, its 5-minute activity window starting at t0: not due = working."""
    sunday = date.fromisoformat(form_a['report']['sunday'])
    now = datetime(sunday.year, sunday.month, sunday.day, 18, 30, tzinfo=ZoneInfo('Europe/Berlin'))
    with patch.object(reminders, 'timedelta', lambda **_: now - t0), api.db() as conn:
        due, _ = reminders.planning_due(conn, {'area_id': area_id}, now)
    return not due


def since(act):
    t0 = sql('SELECT now() AS t')[0]['t']
    time.sleep(0.05)
    return (*act(), t0)


def worked_on_since(t0):
    return sql('SELECT updated_at > %s AS yes FROM public.weekly_area_reports WHERE id=%s', (t0, report_id))[0]['yes']         and reminder_sees_work_since(t0)


status, body, t0 = since(lambda: (None, None))
check('control: with no work since then, the Sunday reminder would be sent', not reminder_sees_work_since(t0))
status, body, t0 = since(lambda: save_people(a, {'high_potential': [{'id': f1, 'notes': 'activity check'}]}))
check("a save of a friend's notes alone marks the plan as worked on, so no reminder is sent", status == 200 and worked_on_since(t0), status)
status, body, t0 = since(lambda: save_people(b, {'new_members': [{'id': nm, 'reading': True}]}))
check('a save of a new member field alone marks the plan as worked on', status == 200 and worked_on_since(t0), status)
status, body, t0 = since(lambda: call(a, 'POST', f'/api/planning/reports/{report_id}/people/high_potential', {}))
extra = body and body.get('id')
check('"+ Add friend" marks the plan as worked on', status == 201 and worked_on_since(t0), status)
status, body, t0 = since(lambda: save_people(a, {'high_potential': [{'id': extra, 'removed': True}]}))
check('removing a friend marks the plan as worked on', status == 200 and extra not in friends() and worked_on_since(t0), status)

# 2d. A number out of range is refused with the person's name, and nothing of that save is written.
nm_name = sql('''SELECT COALESCE(n.display_name,'New member') AS name FROM public.weekly_new_members w
                 LEFT JOIN public.new_members n ON n.id=w.new_member_id WHERE w.id=%s''', (nm,))[0]['name']
notes_before = friends()[f2]['notes']
status, body = save_people(a, {'high_potential': [{'id': f2, 'notes': 'must not be saved'}],
                               'new_members': [{'id': nm, 'pmg_lessons_percentage': 150}]})
check("PMG 150 % -> 400 naming the new member; the other card's change in that save is not written either",
      lambda: status == 400 and body['error'] == nm_name + ': Preach My Gospel lessons taught (%) must be a number from 0 to 100.'
      and friends()[f2]['notes'] == notes_before, (status, body and body.get('error', '').replace(nm_name, '<name>')))

# 3. B adds a friend after A's page loaded; A's next save must not delete it.
status, body = call(b, 'POST', f'/api/planning/reports/{report_id}/people/high_potential', {})
f3 = body['id']
status, body = save_people(a, {'high_potential': [{'id': f1, 'notes': 'A edits after B added one'}]})
check("A's save keeps the friend B added meanwhile, and returns it to A's page",
      lambda: status == 200 and f3 in friends() and f3 in [r['id'] for r in body['people']['high_potential']], (status, sorted(friends())))

# 4. Clearing a friend's name must not delete the friend or break later saves.
status, body = save_people(a, {'high_potential': [{'id': f1, 'name': ''}]})
name_after = friends().get(f1, {}).get('name')
check('clearing a friend name keeps the friend and the saved name', status == 200 and name_after == 'New High Potential', (status, name_after))
status, body = save_people(a, {'high_potential': [{'id': f1, 'name': 'Anna', 'notes': 'after a blank name'}]})
check('saving that friend afterwards still works (was 403 on every save)', lambda: status == 200 and friends()[f1]['name'] == 'Anna', (status, body and body.get('error')))

# 5. B removes a friend with the Remove button; A's stale page still edits it.
status, body = save_people(b, {'high_potential': [{'id': f2, 'removed': True}]})
check("B's explicit removal deletes exactly that friend", status == 200 and f2 not in friends() and {f1, f3} <= set(friends()), sorted(friends()))
status, body = save_people(a, {'high_potential': [{'id': f2, 'notes': 'stale page'}, {'id': f1, 'notes': 'still saved'}]})
check("A's edit of the removed friend is reported once, A's other edit still saves",
      lambda: status == 200 and body['missing'] == [{'group': 'high_potential', 'id': f2}] and friends()[f1]['notes'] == 'still saved', (status, body and body.get('missing', body.get('error'))))
status, body = save_people(a, {'high_potential': [{'id': f1, 'at_church_this_sunday': False}]})
check("A's next save works normally", lambda: status == 200 and body['missing'] == [], (status, body and body.get('error')))

# 5b. After removals, "+ Add friend" puts the new friend after every other one (was count+1: in the middle).
status, body = call(a, 'POST', f'/api/planning/reports/{report_id}/people/high_potential', {})
f4, rows = body['id'], friends()
check('a friend added after removals comes last in the list',
      lambda: status == 201 and rows[f4]['display_order'] > max(r['display_order'] for k, r in rows.items() if k != f4),
      sorted((r['display_order'], k) for k, r in rows.items()))

# 6. A page from before this fix sends every box and every card (and leaves out removed ones). It could overwrite or
# delete the companion's work, so it is told to reload and nothing is written.
before_friends, before_answers = friends(), sql('SELECT question_key, answer_text, answer_number FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s ORDER BY 1', (report_id,))
legacy_people = [{'id': r['id'], 'name': r['name'], 'notes': 'stale', 'at_church_this_sunday': r['at_church_this_sunday']}
                 for r in before_friends.values() if r['id'] != f3]
legacy_answers = {key: '' for key in numbers} | {texts[1]: 'stale copy'}
replies = [call(a, 'PUT', people_url, {'people': {'high_potential': legacy_people, 'new_members': [], 'baptismal_friends': []}}),
           call(a, 'PUT', answers_url, {'answers': legacy_answers})]
check('an old page is told to reload (answers and people -> 400), and nothing is changed or deleted',
      all(s == 400 and r.get('error') == RELOAD for s, r in replies) and friends() == before_friends
      and sql('SELECT question_key, answer_text, answer_number FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s ORDER BY 1', (report_id,)) == before_answers,
      [(s, r.get('error')) for s, r in replies])

# 7. Other areas and submitted plans are still refused.
if outsider:
    status, body = call(outsider[0]['user_id'], 'PUT', people_url, {'people': {'changes_only': True, 'high_potential': [{'id': f1, 'notes': 'intruder'}]}})
    check('a user from another area -> 403, nothing written', lambda: status == 403 and friends()[f1]['notes'] == 'still saved', status)
sql("UPDATE public.weekly_area_reports SET status='SUBMITTED', submitted_at=now() WHERE id=%s", (report_id,))
status, body = save_people(a, {'high_potential': [{'id': f1, 'notes': 'late'}]})
check('submitted plan: people save refused with the submitted message', lambda: status == 400 and 'submitted' in body['error'], body)
sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL WHERE id=%s", (report_id,))

# 8. The Sunday rollover: the page still points at last week's plan.
original = sql("SELECT pg_get_functiondef('public.current_reporting_sunday'::regproc) AS d")[0]['d']
try:
    # The database now believes it is next week: the page's plan is last week's.
    sql('''CREATE OR REPLACE FUNCTION public.current_reporting_sunday() RETURNS date LANGUAGE sql STABLE AS $f$
             SELECT current_date - extract(dow from current_date)::integer + 7 $f$''')
    counts = lambda: (len(friends()), sql('SELECT count(*) AS n FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s', (report_id,))[0]['n'])
    before = counts()
    replies = [save_answers(a, {numbers[0]: 1}),
               save_people(a, {'high_potential': [{'id': f1, 'notes': 'next week'}]}),
               call(a, 'POST', f'/api/planning/reports/{report_id}/people/high_potential', {}),
               call(a, 'POST', f'/api/planning/reports/{report_id}/people/baptismal', {'first_name': 'Zz Rollover'})]
    check('after the rollover, answers / people / add friend / add person on last week\'s plan -> 400 "for last week"',
          all(s == 400 and r.get('error') == LAST_WEEK for s, r in replies), [(s, r.get('error')) for s, r in replies])
    check('after the rollover, nothing was written to last week\'s plan', counts() == before
          and not sql("SELECT 1 FROM public.baptismal_date_people WHERE first_name='Zz Rollover'"), (before, counts()))
    status, new_form = call(a, 'GET', '/api/planning/form?unit_id=%d' % form_a['report']['unit_id'])
    new_id = new_form['report']['report_id']
    status2, body = save_answers(a, {numbers[0]: 5}, report=new_id)
    check("reloading opens this week's plan, and saving there works", new_id != report_id and status2 == 200, (new_id, status2))
finally:
    sql(original)
check('reporting week function restored', str(sql('SELECT public.current_reporting_sunday() AS d')[0]['d']) == form_a['report']['sunday'])

print(f'\n{sum(results)}/{len(results)} passed (throwaway database {dbname})')
sys.exit(0 if all(results) else 1)
