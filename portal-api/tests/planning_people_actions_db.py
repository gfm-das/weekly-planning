"""Managing people on a plan (migration 023 + the portal-api actions), against a THROWAWAY database copy.

Covers every action (Edit details, Transfer, End follow-up, Drop, Baptized, Delete), their refusals (another
area, a submitted plan, a person no longer on the plan or in the area, bad reasons and units, deleting someone
who was on a submitted plan, also after a leader unlocked that earlier plan), the submit check for unanswered
person questions, the transfer choices, the carry-over of the two baptismal dates, Beta's two-argument transfer
and reactivation, and who may run the people functions.

It commits rows, so it refuses to run unless DATABASE_URL points at a database whose name contains "test" and
PEOPLE_TEST_THROWAWAY=yes. Migration 023 must be applied. Identity lookups are replaced in-process (as in
planning_people_db.py); database roles, RLS, triggers, SECURITY DEFINER functions and area checks are real.

Run inside a temporary portal-api container:  python tests/planning_people_actions_db.py
"""
import base64
import json
import os
import sys
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('PEOPLE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import psycopg2  # noqa: E402

import app as api  # noqa: E402
import planning  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    if callable(ok):  # evaluated here, so a missing key in a reply counts as a failed check
        try:
            ok = ok()
        except Exception as error:  # noqa: BLE001
            ok, detail = False, f'{type(error).__name__}: {error} {detail}'
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {detail}' if detail != '' and not ok else ''))


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 600}) + '.fixture'


def call(user, method, path, body=None):
    response = client.open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def as_role(role, user_id, query, args=()):
    """Run one statement as a signed-in user (role authenticated) or as anon, like PostgREST would."""
    with api.db() as conn:
        claims = json.dumps({'sub': str(user_id), 'role': role}) if user_id else json.dumps({'role': role})
        api.rows(conn, "SELECT set_config('request.jwt.claims',%s,true)", (claims,))
        api.rows(conn, f'SET LOCAL ROLE {role}')
        return api.rows(conn, query, args)


def error_of(callable_):
    try:
        callable_()
    except psycopg2.Error as error:
        return error
    return None


# ---------- Fixture: two companionships in different areas ----------
users = sql('''SELECT c.user_id, c.area_id FROM public.current_user_context c
               WHERE c.user_active AND c.area_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM public.area_units au JOIN public.units u ON u.id=au.unit_id
                             WHERE au.area_id=c.area_id AND au.active AND u.active)
               ORDER BY c.area_id, c.user_id''')
first = users[0]
other = next(u for u in users if u['area_id'] != first['area_id'])
A, B = first['user_id'], other['user_id']
# Someone without any access to A's area (can_access_area false), for the database's own refusals. B may be a
# leader (then the people functions let B act on A's area; only the portal limits a plan to its companionship).
outsider = next((u['user_id'] for u in users if u['area_id'] != first['area_id']
                 and not as_role('authenticated', u['user_id'], 'SELECT public.can_access_area(%s) AS ok', (first['area_id'],))[0]['ok']), None)
print(f"fixture: testing area {first['area_id']} vs {other['area_id']}; outsider found: {outsider is not None}")

status, form = call(A, 'GET', '/api/planning/form')
report_id, unit_id, area_id = form['report']['report_id'], form['report']['unit_id'], first['area_id']
sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL, submitted_by=NULL WHERE id=%s", (report_id,))
status, form_b = call(B, 'GET', '/api/planning/form')
report_b, unit_b = form_b['report']['report_id'], form_b['report']['unit_id']
sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL, submitted_by=NULL WHERE id=%s", (report_b,))
base = f'/api/planning/reports/{report_id}/people'

NM = {'last_name': 'Testperson', 'baptismal_date_extended': '2026-09-01', 'baptism_date': '2026-09-20',
      'confirmation_date': '2026-09-26', 'date_of_birth': '1995-03-04', 'age_range': '31-45', 'finding_source': 'Member/Member',
      'gender': 'Female', 'living_situation': 'Student', 'marital_status': 'Single',
      'mission_language_competency': 'Conversational/basic', 'native_language': 'Italian', 'country_of_origin': 'Italy',
      'child_dependents': '0', 'conversion_success_notes': 'The ward council helped.'}


def new_member(first_name):
    status, body = call(A, 'POST', f'{base}/new_member', {**NM, 'first_name': first_name})
    assert status == 201, (status, body)
    return body['id']


def friend(first_name, user=A, path=None):
    status, body = call(user, 'POST', path or f'{base}/baptismal',
                        {'first_name': first_name, 'last_name': 'Friend', 'finding_source': 'Media/Referral'})
    assert status == 201, (status, body)
    return body['id']


def on_plan(table, column, person, report=None):
    return bool(sql(f'SELECT 1 FROM public.{table} WHERE weekly_area_report_id=%s AND {column}=%s', (report or report_id, person)))


# ---------- Transfer choices ----------
status, targets = call(A, 'GET', '/api/planning/transfer-targets')
area_b = next((a for a in targets.get('areas', []) if a['area_id'] == other['area_id']), None) if status == 200 else None
check('transfer choices: every area of the mission with zone, district and its wards or branches',
      lambda: status == 200 and targets['current_area_id'] == area_id and area_b and area_b['zone'] and area_b['district']
      and any(u['unit_id'] == unit_b for u in area_b['units']), (status, targets and len(targets.get('areas', []))))
foreign_unit = sql('SELECT u.id FROM public.units u WHERE u.active AND u.id <> ALL(%s) ORDER BY u.id LIMIT 1',
                   ([u['unit_id'] for u in sql('SELECT unit_id FROM public.area_units WHERE area_id=%s', (other['area_id'],))],))[0]['id']

# ---------- New Member: Transfer ----------
nm = new_member('Zz Transfer')
status, body = call(A, 'POST', f'{base}/new_members/{nm}/transfer', {'area_id': other['area_id'], 'unit_id': unit_b})
row = sql('SELECT area_id, unit_id, stake_id FROM public.new_members WHERE id=%s', (nm,))[0]
stake = sql('SELECT stake_id FROM public.units WHERE id=%s', (unit_b,))[0]['stake_id']
assignments = sql('SELECT area_id, unit_id, end_date, transfer_reason FROM public.new_member_area_assignments WHERE new_member_id=%s ORDER BY id', (nm,))
check('transfer New Member: area, ward or branch and stake move; old assignment closed, new one has the unit',
      status == 200 and row == {'area_id': other['area_id'], 'unit_id': unit_b, 'stake_id': stake}
      and len(assignments) == 2 and assignments[0]['end_date'] is not None and assignments[1]['end_date'] is None
      and assignments[1]['unit_id'] == unit_b and assignments[1]['transfer_reason'] == 'transferred_within_mission', (status, body, row, assignments))
check('transfer New Member: leaves this plan in the same step; the reply has the plan without them',
      lambda: not on_plan('weekly_new_members', 'new_member_id', nm)
      and all(p['new_member_id'] != nm for p in body['people']['new_members']) and 'transferred to' in body['message'])
status, form_b = call(B, 'GET', '/api/planning/form')
check('transfer New Member: shows up on the new area\'s plan when it opens (the unit bug is fixed)',
      lambda: status == 200 and any(p['new_member_id'] == nm for p in form_b['people']['new_members']), status)

# ---------- Refusals ----------
nm2 = new_member('Zz Refusals')
status, body = call(B, 'POST', f'{base}/new_members/{nm2}/end', {'reason': 'other'})
check('another area\'s companionship -> 403, nothing changes', status == 403
      and sql("SELECT follow_up_status FROM public.new_members WHERE id=%s", (nm2,))[0]['follow_up_status'] == 'current', (status, body))
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/transfer', {'area_id': area_id, 'unit_id': unit_id})
check('transfer to the same area and ward or branch -> 400 with the field', status == 400 and 'area_id' in (body.get('fields') or {}), body)
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/transfer', {'area_id': other['area_id'], 'unit_id': foreign_unit})
check('transfer to a ward or branch of another area -> 400', status == 400 and 'unit_id' in (body.get('fields') or {}), body)
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/end', {'reason': 'bored'})
check('end follow-up with an unknown reason -> 400', status == 400 and (body.get('fields') or {}).get('reason') == 'Choose a reason.', body)
status, body = call(A, 'POST', f'{base}/new_members/{nm}/end', {'reason': 'other'})
check('a person who is not on this plan -> 400 "no longer on this plan"', status == 400 and 'no longer on this plan' in body['error'], body)
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/drop', {'reason': 'other'})
check('an action of the other group -> 400', status == 400, body)
sql("UPDATE public.weekly_area_reports SET status='SUBMITTED', submitted_at=now() WHERE id=%s", (report_id,))
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/end', {'reason': 'other'})
check('a submitted plan -> 400 "ask a leader", nothing changes', status == 400 and 'unlock' in body['error']
      and sql("SELECT follow_up_status FROM public.new_members WHERE id=%s", (nm2,))[0]['follow_up_status'] == 'current', body)
sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL, submitted_by=NULL WHERE id=%s", (report_id,))
# Moved to another area behind the plan's back (e.g. by a leader in Beta): the row stays but cannot be managed.
sql('''UPDATE public.new_member_area_assignments SET area_id=%s WHERE new_member_id=%s AND end_date IS NULL''', (other['area_id'], nm2))
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/end', {'reason': 'other'})
status2, form_a = call(A, 'GET', '/api/planning/form')
check('a person no longer assigned to the area -> 400; the plan marks the row as not current',
      lambda: status == 400 and 'no longer assigned to your area' in body['error']
      and next(p for p in form_a['people']['new_members'] if p['new_member_id'] == nm2)['is_current'] is False, body)
sql('''UPDATE public.new_member_area_assignments SET area_id=%s WHERE new_member_id=%s AND end_date IS NULL''', (area_id, nm2))

# ---------- New Member: End follow-up, Edit details ----------
status, body = call(A, 'POST', f'{base}/new_members/{nm2}/end', {'reason': 'moved_out_of_mission'})
row = sql('SELECT follow_up_status, follow_up_end_reason, active FROM public.new_members WHERE id=%s', (nm2,))[0]
check('end follow-up: ended with the reason, off this plan', status == 200 and row == {
    'follow_up_status': 'ended', 'follow_up_end_reason': 'moved_out_of_mission', 'active': False}
    and not on_plan('weekly_new_members', 'new_member_id', nm2), (status, body, row))

nm3 = new_member('Zz Edit')
status, body = call(A, 'POST', f'{base}/new_members/{nm3}/edit', {**NM, 'first_name': 'Zz Edited', 'country_of_origin': 'Spain'})
row = sql('SELECT display_name, country_of_origin, confirmation_date::text FROM public.new_members WHERE id=%s', (nm3,))[0]
check('edit details: saved; the person stays on the plan',
      status == 200 and row == {'display_name': 'Zz Edited Testperson', 'country_of_origin': 'Spain', 'confirmation_date': '2026-09-26'}
      and on_plan('weekly_new_members', 'new_member_id', nm3), (status, body, row))
status, body = call(A, 'POST', f'{base}/new_members/{nm3}/edit', {**NM, 'first_name': 'Zz Edited', 'country_of_origin': ''})
check('edit details: a missing required field -> 400 with the field', status == 400 and set(body['fields']) == {'country_of_origin'}, body)
err = error_of(lambda: as_role('authenticated', outsider, "SELECT public.update_new_member_profile(%s,'X',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)", (nm3,)))
check('update_new_member_profile: someone without access to the area is refused by the database too',
      outsider and err is not None and 'permission' in str(err), err)
status, body = call(outsider, 'POST', f'{base}/new_members/{nm3}/edit', {**NM, 'first_name': 'Zz Intruder'})
check('the same person through the portal -> 403', status == 403, (status, body))
err = error_of(lambda: as_role('authenticated', A, "SELECT public.update_new_member_profile(%s,'X',NULL,NULL,'2026-09-20','2026-09-01',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)", (nm3,)))
check('update_new_member_profile: a confirmation before the baptism is refused by the database', err is not None and 'Confirmation cannot be before' in str(err), err)

# ---------- New Member: no Delete (round 12) ----------
nm4 = new_member('Zz Delete')
status, body = call(A, 'POST', f'{base}/new_members/{nm4}/delete')
check('delete a New Member is not available any more -> 400, the record is kept', status == 400
      and 'not available' in body.get('error', '') and sql('SELECT 1 FROM public.new_members WHERE id=%s', (nm4,))
      and on_plan('weekly_new_members', 'new_member_id', nm4), (status, body))
err = error_of(lambda: as_role('authenticated', A, 'SELECT public.delete_new_member_added_by_mistake(%s)', (nm4,)))
check('delete_new_member_added_by_mistake: a signed-in person may not call it either (migration 041)',
      err is not None and err.pgcode == '42501', err)
nm5 = new_member('Zz Kept')
# An earlier submitted plan of the same area (so the missionary can see it, as in real life).
old_report = sql('''SELECT war.id FROM public.weekly_area_reports war WHERE war.status='SUBMITTED' AND war.id<>%s
                    ORDER BY (war.area_id=%s) DESC, war.id DESC LIMIT 1''', (report_id, area_id))[0]['id']
sql('INSERT INTO public.weekly_new_members (weekly_area_report_id, new_member_id, display_order) VALUES (%s,%s,99)', (old_report, nm5))
status, form_a = call(A, 'GET', '/api/planning/form')
check('the plan tells the page that this person was on a submitted plan',
      lambda: next(p for p in form_a['people']['new_members'] if p['new_member_id'] == nm5)['on_submitted_plan'] is True)

# ---------- Friends with a baptismal date: Drop, Edit details, Transfer, Delete ----------
bd = friend('Zz Drop')
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd}/drop', {'reason': 'no_longer_on_date'})
row = sql('SELECT tracking_status, tracking_end_reason FROM public.baptismal_date_people WHERE id=%s', (bd,))[0]
check('drop: tracking ended with the reason, off this plan', status == 200
      and row == {'tracking_status': 'ended', 'tracking_end_reason': 'no_longer_on_date'}
      and not on_plan('weekly_baptismal_date_friends', 'baptismal_date_person_id', bd), (status, body, row))
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd}/drop', {'reason': 'no_longer_on_date'})
check('drop again (already off the plan) -> 400', status == 400, body)

bd2 = friend('Zz Friend Edit')
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd2}/edit', {'first_name': 'Zz Friend', 'last_name': 'Edited',
                                                                       'finding_source': 'Member/Member'})
person = sql('SELECT display_name, finding_source FROM public.baptismal_date_people WHERE id=%s', (bd2,))[0]
weekly = sql('SELECT finding_source FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s AND baptismal_date_person_id=%s', (report_id, bd2))
check('edit a friend: name and finding source saved; the draft plan\'s copy of the finding source follows',
      status == 200 and person == {'display_name': 'Zz Friend Edited', 'finding_source': 'Member/Member'}
      and weekly == [{'finding_source': 'Member/Member'}], (status, body, person, weekly))
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd2}/edit', {'first_name': 'Zz Friend', 'last_name': ''})
check('edit a friend: last name and finding source are required', status == 400 and set(body['fields']) == {'last_name', 'finding_source'}, body)
row_bd2 = sql('SELECT id FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s AND baptismal_date_person_id=%s',
              (report_id, bd2))[0]['id']
status, body = call(A, 'PUT', base, {'people': {'changes_only': True, 'baptismal_friends': [
    {'id': row_bd2, 'finding_source': 'Visitor\'s Center'}]}})
check('the weekly card can no longer change the finding source', status == 200 and sql(
    'SELECT finding_source FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s AND baptismal_date_person_id=%s',
    (report_id, bd2))[0]['finding_source'] == 'Member/Member', body)

status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd2}/transfer', {'area_id': other['area_id'], 'unit_id': unit_b})
open_assignment = sql('SELECT area_id, unit_id FROM public.baptismal_date_person_area_assignments WHERE baptismal_date_person_id=%s AND end_date IS NULL', (bd2,))
status_b, form_b = call(B, 'GET', '/api/planning/form')
check('transfer a friend: new area and ward or branch, off this plan, on the new area\'s plan',
      lambda: status == 200 and open_assignment == [{'area_id': other['area_id'], 'unit_id': unit_b}]
      and not on_plan('weekly_baptismal_date_friends', 'baptismal_date_person_id', bd2)
      and any(p['baptismal_date_person_id'] == bd2 for p in form_b['people']['baptismal_friends']), (status, body, open_assignment))

bd3 = friend('Zz Friend Delete')
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd3}/delete')
check('delete a friend added by mistake: gone with assignments and weekly rows', status == 200
      and not sql('SELECT 1 FROM public.baptismal_date_people WHERE id=%s', (bd3,))
      and not sql('SELECT 1 FROM public.weekly_baptismal_date_friends WHERE baptismal_date_person_id=%s', (bd3,)), (status, body))
bd4 = friend('Zz Friend Kept')
sql('INSERT INTO public.weekly_baptismal_date_friends (weekly_area_report_id, baptismal_date_person_id, display_order) VALUES (%s,%s,99)', (old_report, bd4))
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd4}/delete')
check('delete a friend who was on a submitted plan -> 409 "use No longer on date", record kept', status == 409
      and 'Use "No longer on date" instead.' in body['error'] and sql('SELECT 1 FROM public.baptismal_date_people WHERE id=%s', (bd4,)), (status, body))

# ---------- Delete after a leader unlocked an earlier week's plan ----------
# Unlock (unsubmit_weekly_report) makes a submitted plan a draft again and clears its submitted time, and an
# earlier week's plan can never be submitted again. Someone on it must still be kept for the mission's reports.
this_sunday = sql('SELECT public.current_reporting_sunday() AS s')[0]['s']
earlier_week = sql('SELECT public.ensure_reporting_week(%s) AS id', (this_sunday - timedelta(days=14),))[0]['id']
earlier = sql('SELECT id FROM public.weekly_area_reports WHERE area_id=%s AND unit_id=%s AND reporting_week_id=%s',
              (area_id, unit_id, earlier_week))
earlier = earlier[0]['id'] if earlier else sql(
    "INSERT INTO public.weekly_area_reports (area_id, unit_id, reporting_week_id, status) VALUES (%s,%s,%s,'DRAFT') RETURNING id",
    (area_id, unit_id, earlier_week))[0]['id']
sql("UPDATE public.weekly_area_reports SET status='SUBMITTED', submitted_at=now() WHERE id=%s", (earlier,))
nm_unlocked, bd_unlocked = new_member('Zz Unlocked'), friend('Zz Friend Unlocked')
sql('INSERT INTO public.weekly_new_members (weekly_area_report_id, new_member_id, display_order) VALUES (%s,%s,97)',
    (earlier, nm_unlocked))
sql('INSERT INTO public.weekly_baptismal_date_friends (weekly_area_report_id, baptismal_date_person_id, display_order) '
    'VALUES (%s,%s,97)', (earlier, bd_unlocked))
candidates = sql('''SELECT c.user_id FROM public.current_user_context c
                    WHERE c.user_active AND c.leadership_role IS NOT NULL
                    ORDER BY (c.district_id = (SELECT district_id FROM public.areas WHERE id=%s)) DESC NULLS LAST,
                             c.user_id LIMIT 40''', (area_id,))
leader = next((u['user_id'] for u in candidates if as_role(
    'authenticated', u['user_id'], 'SELECT public.can_unlock_planning_area(%s) AS ok', (area_id,))[0]['ok']), None)


def unlock(report):
    """A leader's Unlock through the portal (or the SQL it runs, if the copy has no leader for this area)."""
    if leader:
        return call(leader, 'POST', f'/api/planning/reports/{report}/unlock')
    sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_by=NULL, submitted_at=NULL WHERE id=%s", (report,))
    return 200, {'status': 'DRAFT'}


status, body = unlock(earlier)
print('fixture: earlier plan unlocked by ' + ('a leader through the portal' if leader else 'the SQL of unsubmit_weekly_report'))
check('fixture: the earlier week\'s plan is a draft again, its submitted time cleared',
      status == 200 and sql('SELECT status, submitted_at FROM public.weekly_area_reports WHERE id=%s', (earlier,))
      == [{'status': 'DRAFT', 'submitted_at': None}], (status, body))
status, form_a = call(A, 'GET', '/api/planning/form')
check('after the unlock the plan still tells the page not to offer Delete for them',
      lambda: next(p for p in form_a['people']['new_members'] if p['new_member_id'] == nm_unlocked)['on_submitted_plan'] is True
      and next(p for p in form_a['people']['baptismal_friends']
               if p['baptismal_date_person_id'] == bd_unlocked)['on_submitted_plan'] is True)
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd_unlocked}/delete')
check('delete a friend who is on an earlier plan a leader unlocked -> 409 "use No longer on date"; record and old row kept',
      status == 409 and 'Use "No longer on date" instead.' in body['error'] and sql('SELECT 1 FROM public.baptismal_date_people WHERE id=%s', (bd_unlocked,))
      and on_plan('weekly_baptismal_date_friends', 'baptismal_date_person_id', bd_unlocked, earlier), (status, body))
for fn, person in (('delete_baptismal_date_person_added_by_mistake', bd_unlocked),):
    err = error_of(lambda: as_role('authenticated', A, f'SELECT public.{fn}(%s)', (person,)))
    check(f'{fn}: the database refuses it too (GF409) for an earlier plan that is a draft again',
          err is not None and err.pgcode == 'GF409', err)
# This week's plan, submitted and then unlocked, is open to be submitted again (the report that counts is the next submit).
sql("UPDATE public.weekly_area_reports SET status='SUBMITTED', submitted_at=now() WHERE id=%s", (report_id,))
status, body = unlock(report_id)
check('fixture: this week plan unlocked again', status == 200, (status, body))

# ---------- Baptized ----------
bd5 = friend('Zz Baptized')
row_id = sql('SELECT id FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s AND baptismal_date_person_id=%s', (report_id, bd5))[0]['id']
call(A, 'PUT', base, {'people': {'changes_only': True, 'baptismal_friends': [
    {'id': row_id, 'baptismal_date_set_on': '2026-08-30', 'current_baptismal_date': '2026-09-20'}]}})
convert = {key: value for key, value in NM.items() if key not in ('last_name', 'finding_source')}
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd5}/baptized', {**convert, 'first_name': 'Ignored'})
created = sql('''SELECT id, display_name, finding_source, baptismal_date_person_id, unit_id, confirmation_date::text, baptism_date
                 FROM public.new_members WHERE baptismal_date_person_id=%s''', (bd5,))
tracking = sql('SELECT tracking_status, tracking_end_reason FROM public.baptismal_date_people WHERE id=%s', (bd5,))[0]
check('baptized: a New Member with the friend\'s name and finding source, not confirmed yet, in this ward or branch',
      status == 200 and len(created) == 1 and created[0]['display_name'] == 'Zz Baptized Friend'
      and created[0]['finding_source'] == 'Media/Referral' and created[0]['unit_id'] == unit_id
      and created[0]['confirmation_date'] == '2026-09-26' and str(created[0]['baptism_date']) == '2026-09-20'
      and tracking == {'tracking_status': 'ended', 'tracking_end_reason': 'baptized'}, (status, body, created, tracking))
check('baptized: moves from Friends with a Baptismal Date to New Members on this week\'s plan',
      lambda: not on_plan('weekly_baptismal_date_friends', 'baptismal_date_person_id', bd5)
      and on_plan('weekly_new_members', 'new_member_id', created[0]['id']) and body['new_member_id'] == created[0]['id']
      and any(p['new_member_id'] == created[0]['id'] for p in body['people']['new_members']))
status, body = call(A, 'POST', f'{base}/baptismal_friends/{bd4}/baptized', {**convert, 'baptism_date': ''})
check('baptized: the New Member questions are required (baptism date here)', status == 400 and 'baptism_date' in body['fields'], body)

# ---------- Last week's baptismal dates carry over ----------
bd6 = friend('Zz Prefill')
week = sql('SELECT public.current_reporting_sunday() AS s')[0]['s']
last_week_id = sql('SELECT public.ensure_reporting_week(%s) AS id', (week - timedelta(days=7),))[0]['id']
last_report = sql('SELECT id FROM public.weekly_area_reports WHERE area_id=%s AND unit_id=%s AND reporting_week_id=%s',
                  (area_id, unit_id, last_week_id))
last_report = last_report[0]['id'] if last_report else sql(
    "INSERT INTO public.weekly_area_reports (area_id, unit_id, reporting_week_id, status) VALUES (%s,%s,%s,'SUBMITTED') RETURNING id",
    (area_id, unit_id, last_week_id))[0]['id']
sql('''INSERT INTO public.weekly_baptismal_date_friends (weekly_area_report_id, baptismal_date_person_id, display_order,
       baptismal_date_set_on, current_baptismal_date) VALUES (%s,%s,98,'2026-09-06','2026-10-11')''', (last_report, bd6))
row_bd6 = sql('SELECT id FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id=%s AND baptismal_date_person_id=%s', (report_id, bd6))[0]['id']
status, form_a = call(A, 'GET', '/api/planning/form')
mine = next((p for p in form_a['people']['baptismal_friends'] if p['id'] == row_bd6), {})
check('carry-over: this week\'s empty dates are filled from the friend\'s latest earlier row when the plan opens',
      status == 200 and mine.get('baptismal_date_set_on') == '2026-09-06' and mine.get('current_baptismal_date') == '2026-10-11', mine)
call(A, 'PUT', base, {'people': {'changes_only': True, 'baptismal_friends': [{'id': row_bd6, 'current_baptismal_date': '2026-10-18'}]}})
status, form_a = call(A, 'GET', '/api/planning/form')
mine = next((p for p in form_a['people']['baptismal_friends'] if p['id'] == row_bd6), {})
check('carry-over: a date entered this week is kept', mine.get('current_baptismal_date') == '2026-10-18', mine)

# ---------- Beta's functions and rights ----------
nm6 = new_member('Zz Beta Transfer')
as_role('authenticated', A, 'SELECT public.transfer_new_member(%s, %s)', (nm6, other['area_id']))
primary = sql('''SELECT au.unit_id FROM public.area_units au JOIN public.units u ON u.id=au.unit_id
                 WHERE au.area_id=%s AND au.active AND u.active ORDER BY au.primary_unit DESC, u.name, u.id LIMIT 1''', (other['area_id'],))[0]['unit_id']
row = sql('SELECT area_id, unit_id FROM public.new_members WHERE id=%s', (nm6,))[0]
check('Beta\'s transfer_new_member(person, area) now also sets the new area\'s main ward or branch',
      row == {'area_id': other['area_id'], 'unit_id': primary}, row)
as_role('authenticated', A, "SELECT public.archive_new_member(%s, 'other')", (new_member('Zz Reactivate'),))
nm7 = sql("SELECT id FROM public.new_members WHERE first_name='Zz Reactivate'")[0]['id']
for signature, args in (('(%s)', (nm7,)), ('(%s, %s)', (nm7, unit_id))):
    err = error_of(lambda: as_role('authenticated', A, f'SELECT public.reactivate_new_member{signature}', args))
    check(f'signed-in users cannot run reactivate_new_member{signature} (no page uses it)',
          err is not None and 'permission denied' in str(err), err)
# service_role with A's claims: the function's own access check still sees A.
as_role('service_role', A, 'SELECT public.reactivate_new_member(%s)', (nm7,))
row = sql('''SELECT nm.follow_up_status, nm.unit_id, a.unit_id AS assignment_unit FROM public.new_members nm
             JOIN public.new_member_area_assignments a ON a.new_member_id=nm.id AND a.end_date IS NULL WHERE nm.id=%s''', (nm7,))
check('reactivate_new_member(person) (service_role): follow-up restored with the ward or branch on the new assignment',
      row == [{'follow_up_status': 'current', 'unit_id': unit_id, 'assignment_unit': unit_id}], row)
err = error_of(lambda: as_role('anon', None, 'SELECT public.get_previous_weekly_new_members(%s)', (unit_id,)))
check('anon cannot run get_previous_weekly_new_members (signed-in users keep it: 019 grants it by name)',
      err is not None and 'permission denied' in str(err)
      and sql("SELECT has_function_privilege('authenticated', 'public.get_previous_weekly_new_members(bigint)', 'EXECUTE') AS ok")[0]['ok'], err)
err = error_of(lambda: as_role('anon', None, 'SELECT public.archive_expired_new_members()'))
check('anon cannot run archive_expired_new_members()', err is not None and 'permission denied' in str(err), err)
err = error_of(lambda: as_role('authenticated', A, 'SELECT public.archive_expired_new_members()'))
check('signed-in users cannot run archive_expired_new_members() either', err is not None and 'permission denied' in str(err), err)
err = error_of(lambda: as_role('anon', None, "SELECT public.create_baptismal_date_person('X','Y',NULL,1)"))
check('anon cannot run the people functions', err is not None and 'permission denied' in str(err), err)
nm8 = new_member('Zz Not Yours')
for fn in ('delete_new_member_added_by_mistake', 'archive_new_member'):
    args = '(%s)' if fn.startswith('delete') else "(%s, 'other')"
    err = error_of(lambda: as_role('authenticated', outsider, f'SELECT public.{fn}{args}', (nm8,)))
    check(f'{fn}: someone without access to the area is refused by the database',
          outsider and err is not None and 'permission' in str(err)
          and sql("SELECT 1 FROM public.new_members WHERE id=%s AND follow_up_status='current'", (nm8,)), err)
bd7 = friend('Zz Friend Not Yours')
for fn, args in (('delete_baptismal_date_person_added_by_mistake', '(%s)'), ('update_baptismal_date_person', "(%s,'X','Y',NULL)"),
                 ('archive_baptismal_date_person', "(%s,'other')")):
    err = error_of(lambda: as_role('authenticated', outsider, f'SELECT public.{fn}{args}', (bd7,)))
    check(f'{fn}: someone without access to the area is refused by the database',
          outsider and err is not None and 'permission' in str(err)
          and sql("SELECT 1 FROM public.baptismal_date_people WHERE id=%s AND tracking_status='current'", (bd7,)), err)

# ---------- Submit: every current person's questions answered ----------
# Only the person check is tested here. Where the planning-question check exists (migration 024 and its
# planning.py), it runs first and has its own test (planning_catalog_db.py); it is switched off for this part so a
# required planning question left empty by this test cannot stop the submit before the person check.
if hasattr(planning, '_check_required_answers'):
    patch.object(planning, '_check_required_answers', lambda conn, report_id: None).start()
status, form_a = call(A, 'GET', '/api/planning/form')
status, body = call(A, 'POST', f'/api/planning/reports/{report_id}/submit')
listed = (body.get('fields') or {}).get('people') or []
check('submit with unanswered person questions -> 400 listing each person, group, row and fields; not submitted',
      status == 400 and listed and all({'group', 'id', 'name', 'fields'} <= set(p) for p in listed)
      and sql('SELECT status FROM public.weekly_area_reports WHERE id=%s', (report_id,))[0]['status'] == 'DRAFT', (status, body))
answers = {
    'new_members': {'lessons_actual': 1, 'lessons_goal': 2, 'pmg_lessons_percentage': 40, 'how_are_they_doing': 'Well',
                    'at_church_this_sunday': True, 'reading': True, 'praying': False, 'member_involvement': True,
                    'discussed_in_gemiko': True, 'gemiko_support_plan': 'Ministering visit', 'next_ordinance': 'TB',
                    'has_calling': 'no', 'has_aaronic_priesthood': 'not_applicable', 'has_melchizedek_priesthood': 'not_applicable',
                    'ministers_to_someone': 'no', 'ministered_to_by_someone': True, 'has_active_temple_recommend': 'yes',
                    'visited_temple_for_baptisms': 'yes'},
    'baptismal_friends': {'baptismal_date_set_on': '2026-09-01', 'current_baptismal_date': '2026-10-04', 'reading': True,
                          'praying': True, 'at_church_this_sunday': False, 'keeping_commandments': True, 'member_involvement': False},
    'high_potential': {'name': 'Zz High Potential', 'at_church_this_sunday': False}}
people = {group: [{'id': p['id'], **values} for p in form_a['people'][group]] for group, values in answers.items()}
people['new_members'][-1:] = [dict(people['new_members'][-1], discussed_in_gemiko=True, gemiko_support_plan='')] if people['new_members'] else []
status, body = call(A, 'PUT', base, {'people': {'changes_only': True, **people}})
status, body = call(A, 'POST', f'/api/planning/reports/{report_id}/submit')
gemiko = (body.get('fields') or {}).get('people') or []
check('"How will GEMIKO support them?" is required when they were discussed in GEMIKO',
      lambda: status == 400 and [p['fields'] for p in gemiko] == [['gemiko_support_plan']], (status, body))
people['new_members'] = [{'id': p['id'], 'gemiko_support_plan': 'Ministering visit'} for p in people['new_members']]
call(A, 'PUT', base, {'people': {'changes_only': True, 'new_members': people['new_members']}})
status, body = call(A, 'POST', f'/api/planning/reports/{report_id}/submit')
check('submit once every current person is answered -> 200 SUBMITTED', status == 200 and body.get('status') == 'SUBMITTED', (status, body))
status, body = call(A, 'POST', f'{base}/new_members/{nm5}/end', {'reason': 'other'})
check('after submitting, managing people is refused until a leader unlocks the plan', status == 400 and 'unlock' in body['error'], body)

print(f'\n{sum(results)}/{len(results)} passed (throwaway database {dbname})')
sys.exit(0 if all(results) else 1)
