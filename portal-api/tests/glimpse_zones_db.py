"""The Glimpse shows only open zones and only weeks with plans (dashboard.mission_dashboard, round 12) against a
THROWAWAY database copy like live. Nothing is committed: every change is rolled back at the end.

Made-up plans in two zones and four Sundays, one of them with no plan at all (a gap):
- the week list has only weeks with a plan in the areas the person may see (no gap week, no empty week);
- a zone that is closed (active = false) is not in the zone list, even though it has plans in the weeks read, and it
  comes back as soon as it is open again;
- the mission total of a week still counts every plan, also those of a closed zone;
- an area moved to another zone takes its old numbers to that zone;
- a week after a gap is measured against nothing (the Sunday before it has no goals); finished_weeks counts the weeks
  with data only; a person who may see no area gets no weeks.
Prints counts only. Refuses unless DATABASE_URL names a database containing "test" and GLIMPSE_TEST_THROWAWAY=yes. Run:
  docker run --rm -e GLIMPSE_TEST_THROWAWAY=yes -e DATABASE_URL=postgresql://supabase_admin:...@<test db>:5432/postgres \
      -v <repo>/portal-api:/app:ro -w /app gfm-portal-portal-api python tests/glimpse_zones_db.py
"""
import os
import sys
from datetime import timedelta
from urllib.parse import urlparse

sys.path.insert(0, '/app')
if os.environ.get('GLIMPSE_TEST_THROWAWAY') != 'yes' or 'test' not in os.environ.get('DATABASE_URL', ''):
    sys.exit('Refusing to run: this test writes plans and needs a throwaway *test* database.')
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

import dashboard  # noqa: E402

conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()
failures = []


def check(name, ok):
    print(('ok   ' if ok else 'FAIL ') + name)
    if not ok:
        failures.append(name)


def glimpse(area_ids, weeks=12):
    return dashboard.mission_dashboard(conn, {'mission_id': 2, 'mission': 'test'}, weeks, area_ids)


cur.execute("select public.current_reporting_sunday() s")
today = cur.fetchone()['s']
cur.execute("""select a.id area_id, z.id zone_id from public.areas a join public.districts d on d.id=a.district_id
  join public.zones z on z.id=d.zone_id where z.mission_id=2 and a.active and z.active order by z.id, a.id""")
rows = cur.fetchall()
a1 = rows[0]
a2 = next(r for r in rows if r['zone_id'] != a1['zone_id'])
all_areas = [r['area_id'] for r in rows]
w1, w2, gap, w4 = (today - timedelta(days=7 * n) for n in (5, 4, 3, 2))
S = lambda d: d.isoformat()  # the answer carries dates as text  # w1, w2, (gap), w4; the week after the gap is w4


def week_id(day):
    cur.execute("select id from public.reporting_weeks where sunday=%s", (day,))
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute("insert into public.reporting_weeks(sunday) values(%s) returning id", (day,))
    return cur.fetchone()['id']


def plan(area, day):
    cur.execute("insert into public.weekly_area_reports(area_id,reporting_week_id,status) values(%s,%s,'SUBMITTED')", (area, week_id(day)))


try:
    cur.execute("delete from public.weekly_area_reports where area_id = any(%s)", ([a1['area_id'], a2['area_id']],))
    week_id(gap)  # a reporting week row exists for the gap, but nobody has a plan in it
    for day in (w1, w2, w4):
        plan(a1['area_id'], day)
        plan(a2['area_id'], day)
    base_weeks = {w['sunday'] for w in glimpse(all_areas)['weeks']}

    body = glimpse(all_areas)
    days = [w['sunday'] for w in body['weeks']]
    mine = [d for d in days if d in map(S, (w1, w2, gap, w4))]
    check('only weeks with a plan are listed, oldest first', mine == [S(w1), S(w2), S(w4)] and S(gap) not in days
          and days == sorted(days))
    check('every listed week has plans', all(w['mission']['reports'] > 0 for w in body['weeks']))
    check('finished_weeks counts weeks with data', body['finished_weeks'] == len(base_weeks))
    week4 = next(w for w in body['weeks'] if w['sunday'] == S(w4))
    check('the week after a gap is measured against nothing', all(v is None for v in week4['mission']['previous_goal'].values()))
    check('both zones are drawn while open', {a1['zone_id'], a2['zone_id']} <= {z['id'] for z in body['zones']})

    cur.execute("update public.zones set active=false where id=%s", (a2['zone_id'],))
    closed = glimpse(all_areas)
    check('a closed zone is not drawn, although it has plans in the weeks read', a2['zone_id'] not in {z['id'] for z in closed['zones']})
    check('the open zone is still drawn', a1['zone_id'] in {z['id'] for z in closed['zones']})
    check('the mission total still counts the closed zone\'s plans',
          next(w for w in closed['weeks'] if w['sunday'] == S(w2))['mission']['reports'] == 2)
    cur.execute("update public.zones set active=true where id=%s", (a2['zone_id'],))
    check('reopened: drawn again', a2['zone_id'] in {z['id'] for z in glimpse(all_areas)['zones']})

    cur.execute("""update public.areas set district_id=(select d.id from public.districts d where d.zone_id=%s limit 1)
      where id=%s""", (a1['zone_id'], a2['area_id']))
    moved = glimpse(all_areas)
    cell = next(w for w in moved['weeks'] if w['sunday'] == S(w2))['zones']
    check('an area moved to another zone takes its numbers along', cell[a1['zone_id']]['reports'] == 2
          and (a2['zone_id'] not in cell or cell[a2['zone_id']]['reports'] == 0))

    nobody = glimpse([])
    check('someone who may see no area gets no weeks', nobody['weeks'] == [] and nobody['finished_weeks'] == 0)
finally:
    conn.rollback()
    conn.close()
sys.exit(1 if failures else 0)
