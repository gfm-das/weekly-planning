"""The Overview week list (planning._recent_weeks, round 12) against a THROWAWAY database copy like live.

Checks, with made-up plans in three areas (every row it makes is removed at the end):
- a missionary (no stewardship) sees every week their own area has a plan, not only the last four, newest first;
- a leader sees the weeks of their own area AND of everything they may look at (one area's older weeks appear too);
- a manager with no area of their own still gets the list of the whole mission;
- the current week is always there, even without a plan; a future week never is; a week without any plan is left out;
- report_count / submitted_count are for the area shown, scope_plans for everything in sight.
Prints counts only. Refuses unless DATABASE_URL names a database containing "test" and OVERVIEW_TEST_THROWAWAY=yes. Run:
  docker run --rm -e OVERVIEW_TEST_THROWAWAY=yes -e DATABASE_URL=postgresql://supabase_admin:...@<test db>:5432/postgres \
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/overview_weeks_db.py
"""
import os
import sys
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('OVERVIEW_TEST_THROWAWAY') != 'yes' or 'test' not in dbname + os.environ.get('DATABASE_URL', ''):
    sys.exit('Refusing to run: this test writes plans and needs a throwaway *test* database.')
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

import planning  # noqa: E402

conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()
failures = []


def check(name, ok):
    print(('ok   ' if ok else 'FAIL ') + name)
    if not ok:
        failures.append(name)


cur.execute("select public.current_reporting_sunday() s")
today = cur.fetchone()['s']
cur.execute("select id from public.areas where active order by id limit 3")
a1, a2, a3 = [r['id'] for r in cur.fetchall()]
# A1: plans in 7 weeks back (two submitted); A2: only an old week (9 weeks back); A3: only a future week.
weeks_a1 = [today - timedelta(days=7 * n) for n in (1, 2, 3, 4, 5, 6, 7)]
old = today - timedelta(days=7 * 9)
future = today + timedelta(days=14)
made_weeks, made_reports = [], []


def week_id(day):
    cur.execute("select id from public.reporting_weeks where sunday=%s", (day,))
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute("insert into public.reporting_weeks(sunday) values(%s) returning id", (day,))
    made_weeks.append(cur.fetchone()['id'])
    return made_weeks[-1]


def plan(area, day, status='DRAFT'):
    cur.execute("insert into public.weekly_area_reports(area_id,reporting_week_id,status) values(%s,%s,%s) returning id",
                (area, week_id(day), status))
    made_reports.append(cur.fetchone()['id'])


try:
    for n, day in enumerate(weeks_a1):
        plan(a1, day, 'SUBMITTED' if n < 2 else 'DRAFT')
    plan(a2, old)
    plan(a3, future)
    mission_areas = [{'area_id': a} for a in (a1, a2, a3)]

    with patch.object(planning, '_scoped_areas', return_value=(None, [])):
        weeks = planning._recent_weeks(conn, {}, a1)
    days = [w['sunday'] for w in weeks]
    check('missionary: current week first, then every week with a plan, newest first',
          days == [today] + weeks_a1)
    check('missionary: more than four weeks are listed', len(days) > 4)
    check('missionary: the other areas\' weeks are not in the list', old not in days and future not in days)
    first = next(w for w in weeks if w['sunday'] == weeks_a1[0])
    check('counts for the area shown', (first['report_count'], first['submitted_count'], first['scope_plans']) == (1, 1, 1))
    check('the current week has no plan but is listed', next(w for w in weeks if w['sunday'] == today)['scope_plans'] == 0)

    with patch.object(planning, '_scoped_areas', return_value=('zone', [{'area_id': a1}, {'area_id': a2}])):
        weeks = planning._recent_weeks(conn, {}, a1)
    days = [w['sunday'] for w in weeks]
    check('leader: also the weeks of the other areas in sight', old in days and days == sorted(days, reverse=True))
    check('leader: a future plan never opens a week', future not in days)
    check('leader: counts for the shown area stay the same', next(w for w in weeks if w['sunday'] == weeks_a1[0])['report_count'] == 1)
    check('leader: older week counts as a plan in sight', next(w for w in weeks if w['sunday'] == old)['scope_plans'] == 1)

    with patch.object(planning, '_scoped_areas', return_value=('mission', mission_areas)):
        weeks = planning._recent_weeks(conn, {}, None)
    days = [w['sunday'] for w in weeks]
    check('manager without an area: whole mission list', old in days and weeks_a1[-1] in days and today in days)
    check('manager without an area: no count for an area, plans in sight counted',
          next(w for w in weeks if w['sunday'] == weeks_a1[0])['report_count'] == 0
          and next(w for w in weeks if w['sunday'] == weeks_a1[0])['scope_plans'] == 1)
    check('every listed week can be opened (it has a row)', all(w['id'] for w in weeks))
finally:
    conn.rollback()
    for table, column, ids in (('weekly_area_reports', 'id', made_reports), ('reporting_weeks', 'id', made_weeks)):
        if ids:
            cur.execute(f'delete from public.{table} where {column} = any(%s)', (ids,))
    conn.commit()
    conn.close()
sys.exit(1 if failures else 0)
