"""A person's weekly answers start from last time (migration 042) against a THROWAWAY database copy like live.

Everything runs inside one transaction that is rolled back at the end, with made-up people:
- when a week's plan starts (fill_current_week_plans, the same code a missionary opening the portal runs), a New Member and
  a friend with a baptismal date get the answers of their latest EARLIER row, also when that row is in another area
  (a transfer); only that latest row counts;
- "discussed in Gemiko" is never carried forward; the Gemiko support plan is;
- nothing typed is overwritten, and an answer cleared on purpose is not refilled the next time the plan is started again;
- the prefill function itself fills only empty answers, and refuses a signed-in person who may not edit the plan.
Prints counts only. Refuses unless DATABASE_URL names a database containing "test" and PREFILL_TEST_THROWAWAY=yes. Run:
  docker run --rm -e PREFILL_TEST_THROWAWAY=yes -e DATABASE_URL=postgresql://supabase_admin:...@<test db>:5432/postgres \
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/prefill_answers_db.py
"""
import os
import sys

if os.environ.get('PREFILL_TEST_THROWAWAY') != 'yes' or 'test' not in os.environ.get('DATABASE_URL', ''):
    sys.exit('Refusing to run: this test writes people and plans and needs a throwaway *test* database.')

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()
failures = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else f'  -> {detail}'))
    if not ok:
        failures.append(name)


def one(query, params=()):
    cur.execute(query, params)
    return cur.fetchone()


try:
    sunday = one('select public.current_reporting_sunday() s')['s']
    cur.execute("""select au.area_id, au.unit_id from public.area_units au join public.areas a on a.id = au.area_id and a.active
      where au.active order by au.area_id limit 2""")
    (a1, u1), (a2, u2) = [(r['area_id'], r['unit_id']) for r in cur.fetchall()]
    day = lambda back: f"public.ensure_reporting_week('{sunday}'::date - {7 * back})"

    def report(area, unit, back, status='SUBMITTED'):
        week = one(f'select {day(back)} id')['id']
        found = one('select id from public.weekly_area_reports where area_id=%s and unit_id=%s and reporting_week_id=%s', (area, unit, week))
        if found:  # the copy of live may already have a plan there: use it
            return found['id']
        return one('insert into public.weekly_area_reports(area_id,unit_id,reporting_week_id,status) values(%s,%s,%s,%s) returning id',
                   (area, unit, week, status))['id']

    nm = one("""insert into public.new_members(area_id,unit_id,first_name,last_name,baptism_date,follow_up_status,active)
      values(%s,%s,'Zz','Prefill',current_date - 30,'current',true) returning id""", (a1, u1))['id']
    cur.execute('insert into public.new_member_area_assignments(new_member_id,area_id,unit_id,start_date) values(%s,%s,%s,current_date - 30)', (nm, a1, u1))
    friend = one("insert into public.baptismal_date_people(first_name,last_name) values('Zz','Friend') returning id")['id']
    cur.execute('insert into public.baptismal_date_person_area_assignments(baptismal_date_person_id,area_id,unit_id,start_date) values(%s,%s,%s,current_date - 30)', (friend, a1, u1))

    # Two weeks back, in ANOTHER area (the person transferred since): older answers that must not be used, because a later row exists.
    old_report = report(a2, u2, 2)
    cur.execute("""insert into public.weekly_new_members(weekly_area_report_id,new_member_id,display_order,lessons_goal,next_ordinance)
      values(%s,%s,1,9,'Old ordinance')""", (old_report, nm))
    # Last week, in this area: the latest earlier row.
    last_report = report(a1, u1, 1)
    cur.execute("""insert into public.weekly_new_members(weekly_area_report_id,new_member_id,display_order,lessons_actual,pmg_lessons_percentage,
      how_are_they_doing,discussed_in_gemiko,gemiko_support_plan,at_church_this_sunday,has_calling,reading,praying,member_involvement,next_ordinance)
      values(%s,%s,1,3,66.5,'Doing well',true,'Ward will visit',true,'yes',true,false,true,'Confirmation')""", (last_report, nm))
    cur.execute("""insert into public.weekly_baptismal_date_friends(weekly_area_report_id,baptismal_date_person_id,display_order,baptismal_date_set_on,
      current_baptismal_date,reading,praying,at_church_this_sunday,keeping_commandments,member_involvement)
      values(%s,%s,1,current_date - 20,current_date + 14,true,true,true,false,true)""", (last_report, friend))

    made = one('select public.fill_current_week_plans() n')['n']
    row = one("""select w.* from public.weekly_new_members w join public.weekly_area_reports r on r.id = w.weekly_area_report_id
      where w.new_member_id = %s and r.reporting_week_id = %s""", (nm, one(f'select {day(0)} id')['id']))
    check('the plan of the current week was started', made >= 1 and row is not None, (made, row))
    wanted = {'lessons_actual': 3, 'how_are_they_doing': 'Doing well', 'gemiko_support_plan': 'Ward will visit', 'at_church_this_sunday': True,
              'has_calling': 'yes', 'reading': True, 'praying': False, 'member_involvement': True, 'next_ordinance': 'Confirmation'}
    got = {k: row[k] for k in wanted}
    check('a New Member starts with the answers of the latest earlier row', got == wanted, got)
    check('...the percentage too', float(row['pmg_lessons_percentage']) == 66.5, row['pmg_lessons_percentage'])
    check('...but "discussed in Gemiko" is not carried forward', row['discussed_in_gemiko'] is None, row['discussed_in_gemiko'])
    check('only the latest row counts (an older row\'s other answers are not mixed in)', row['lessons_goal'] is None, row['lessons_goal'])

    frow = one("""select w.* from public.weekly_baptismal_date_friends w join public.weekly_area_reports r on r.id = w.weekly_area_report_id
      where w.baptismal_date_person_id = %s and r.reporting_week_id = %s""", (friend, one(f'select {day(0)} id')['id']))
    fgot = {k: frow[k] for k in ('reading', 'praying', 'at_church_this_sunday', 'keeping_commandments', 'member_involvement')}
    check('a friend with a baptismal date starts with the latest earlier answers',
          fgot == {'reading': True, 'praying': True, 'at_church_this_sunday': True, 'keeping_commandments': False, 'member_involvement': True}, fgot)
    check('...and both dates', frow['baptismal_date_set_on'] is not None and frow['current_baptismal_date'] is not None, frow)

    # Typed answers stay; an answer cleared on purpose is not refilled when the plan is started again.
    cur.execute('update public.weekly_new_members set lessons_actual = 7, reading = NULL where id = %s', (row['id'],))
    one('select public.fill_current_week_plans() n')
    again = one('select lessons_actual, reading from public.weekly_new_members where id = %s', (row['id'],))
    check('what was typed stays and a cleared answer stays cleared', again == {'lessons_actual': 7, 'reading': None}, again)

    # The function itself: fills empty answers only.
    cur.execute('update public.weekly_new_members set how_are_they_doing = NULL, lessons_actual = 8 where id = %s', (row['id'],))
    cur.execute('select public.prefill_weekly_new_members(ARRAY[%s]::bigint[])', (row['id'],))
    third = one('select lessons_actual, how_are_they_doing, reading from public.weekly_new_members where id = %s', (row['id'],))
    check('the prefill function fills empty answers and leaves typed ones', third == {'lessons_actual': 8, 'how_are_they_doing': 'Doing well', 'reading': True}, third)

    # A person who is not allowed to edit this plan is refused (signed in as someone else).
    cur.execute('select id from public.user_profiles where active order by id limit 40')
    refused = None
    for profile in cur.fetchall():
        cur.execute('savepoint probe')
        cur.execute("select set_config('request.jwt.claims', %s, true), set_config('request.jwt.claim.sub', %s, true)",
                    ('{"sub":"%s","role":"authenticated"}' % profile['id'], str(profile['id'])))
        cur.execute('set local role authenticated')
        try:
            cur.execute('select public.can_edit_planning_area(%s) ok', (a1,))
            may = cur.fetchone()['ok']
            if not may:
                try:
                    cur.execute('select public.prefill_weekly_new_members(ARRAY[%s]::bigint[])', (row['id'],))
                    refused = False
                except psycopg2.errors.InsufficientPrivilege:
                    refused = True
        finally:
            cur.execute('rollback to savepoint probe')
            cur.execute('reset role')
        if refused is not None:
            break
    check('a signed-in person who may not edit the plan is refused', refused is True, refused)
finally:
    conn.rollback()
    conn.close()
sys.exit(1 if failures else 0)
