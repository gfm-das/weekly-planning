"""An area with two wards/branches on the Overview adds both plans up (planning.planning_overview, round 13) against a
THROWAWAY database copy like live. Nothing is committed: every change is rolled back at the end.

Made-up plans for one area with two units in the current week, with different numbers in each plan. For the Overview
(own-area path as a missionary, and the leader path), Glimpse (dashboard._zone_week_rows) and the dashboard view
(dashboards.kpi_area_total_week) the area total must be the sum of the two plans, each unit shown underneath, in the
cases: both plans; one plan only; a plan with no unit; a unit no longer attached. (Two plans of one unit and week
cannot exist: unique index weekly_area_reports_area_unit_week_uidx.)
Refuses unless DATABASE_URL names a database containing "test" and OVERVIEW_TEST_THROWAWAY=yes. Run:
  docker run --rm -e OVERVIEW_TEST_THROWAWAY=yes -e DATABASE_URL=postgresql://supabase_admin:...@<test db>:5432/postgres \
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/overview_units_db.py
"""
import os
import sys

sys.path.insert(0, '/app')
if os.environ.get('OVERVIEW_TEST_THROWAWAY') != 'yes' or 'test' not in os.environ.get('DATABASE_URL', ''):
    sys.exit('Refusing to run: this test writes plans and needs a throwaway *test* database.')
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

import dashboard  # noqa: E402
import planning  # noqa: E402

conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()
failures = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else '   ' + str(detail)))
    if not ok:
        failures.append(name)


cur.execute("select public.current_reporting_sunday() s")
today = cur.fetchone()['s']
cur.execute("select id from public.reporting_weeks where sunday=%s", (today,))
row = cur.fetchone()
if row is None:
    cur.execute("insert into public.reporting_weeks(sunday) values(%s) returning id", (today,))
    row = cur.fetchone()
week_id = row['id']
# An area with exactly two attached units.
cur.execute("""select au.area_id from public.area_units au join public.units u on u.id=au.unit_id
  join public.areas a on a.id=au.area_id where au.active and u.active and a.active
  group by au.area_id having count(*)=2 order by au.area_id limit 1""")
AREA = cur.fetchone()['area_id']
cur.execute("""select au.unit_id, au.primary_unit from public.area_units au join public.units u on u.id=au.unit_id
  where au.area_id=%s and au.active order by au.primary_unit desc, au.unit_id""", (AREA,))
U1, U2 = [r['unit_id'] for r in cur.fetchall()]
WEEK = {'sunday': today}


def plan(unit, numbers, status='SUBMITTED'):
    cur.execute("insert into public.weekly_area_reports(area_id,reporting_week_id,unit_id,status) values(%s,%s,%s,%s) returning id",
                (AREA, week_id, unit, status))
    rid = cur.fetchone()['id']
    for key, value in numbers.items():
        cur.execute("insert into public.weekly_planning_answers(weekly_area_report_id,question_key,answer_number) values(%s,%s,%s)",
                    (rid, key, value))
    return rid


def reset():
    cur.execute("delete from public.weekly_area_reports where area_id=%s and reporting_week_id=%s", (AREA, week_id))


def overview_numbers(viewing_area):
    """(actual, goal) of Sacrament attendance and the unit rows, as the Overview computes them."""
    units, _, reports = planning._area_details(conn, {}, AREA, viewing_area, WEEK)
    reports = planning._one_plan_per_unit(reports, units, AREA)
    answers, _ = planning._answers_by_report(conn, [r['report_id'] for r in reports if r.get('report_id')])
    kpi = {k['key']: k for k in planning._key_indicator_summaries(reports, answers)}['sacrament_attendance']
    return kpi['actual'], kpi['goal'], [(u['unit'], u['actual'], u['goal']) for u in kpi['units']]


def glimpse_numbers():
    cur.execute("select a.id, d.zone_id from public.areas a join public.districts d on d.id=a.district_id where a.id=%s", (AREA,))
    zone = cur.fetchone()['zone_id']
    cur.execute("select mission_id from public.zones where id=%s", (zone,))
    mission = cur.fetchone()['mission_id']
    rows = dashboard._zone_week_rows(conn, mission, [today], [AREA])
    r = next((x for x in rows if x['zone_id'] == zone), None)
    return (r['sacrament_attendance_actual'], r['sacrament_attendance_goal']) if r else (None, None)


def dashboard_view_numbers():
    cur.execute("select sacrament_attendance_actual a, sacrament_attendance_goal g from dashboards.kpi_area_total_week where area_id=%s and sunday=%s", (AREA, today))
    r = cur.fetchone()
    return (r['a'], r['g']) if r else (None, None)


def all_pages(label, expect_actual, expect_goal, unit_rows=None, viewing=True):
    area_view = {'area_id': AREA}
    actual, goal, rows = overview_numbers(area_view if viewing else None)
    check(f'{label}: Overview total', (actual, goal) == (expect_actual, expect_goal), (actual, goal, rows))
    if unit_rows is not None:
        check(f'{label}: Overview unit rows', [(a, g) for _, a, g in rows] == unit_rows, rows)
    check(f'{label}: Glimpse total', tuple(map(lambda v: None if v is None else float(v), glimpse_numbers())) == (expect_actual, expect_goal), glimpse_numbers())
    check(f'{label}: dashboard view total', tuple(map(lambda v: None if v is None else float(v), dashboard_view_numbers())) == (expect_actual, expect_goal), dashboard_view_numbers())


try:
    reset()
    plan(U1, {'sacrament_attendance_actual': 10, 'sacrament_attendance_goal': 12})
    plan(U2, {'sacrament_attendance_actual': 3, 'sacrament_attendance_goal': 5})
    all_pages('two plans', 13, 17, [(10, 12), (3, 5)])

    reset()
    plan(U2, {'sacrament_attendance_actual': 3, 'sacrament_attendance_goal': 5})
    all_pages('only the second unit has a plan', 3, 5)

    reset()
    plan(U1, {'sacrament_attendance_actual': 10, 'sacrament_attendance_goal': 12})
    plan(None, {'sacrament_attendance_actual': 3, 'sacrament_attendance_goal': 5})
    all_pages('a plan with no unit', 13, 17)

    reset()
    plan(U1, {'sacrament_attendance_actual': 10, 'sacrament_attendance_goal': 12})
    plan(U2, {'sacrament_attendance_actual': 3, 'sacrament_attendance_goal': 5})
    cur.execute("update public.area_units set active=false where area_id=%s and unit_id=%s", (AREA, U2))
    all_pages('a unit no longer attached', 13, 17)
finally:
    conn.rollback()

print('FAILURES: %d' % len(failures))
sys.exit(1 if failures else 0)
