"""The mission glimpse: the numbers at the top of the managers' Overview.

What it is: mission_dashboard() reads the six key indicators by finished week and zone; parse_weeks() checks the
?weeks= number. GET /api/dashboard in app.py calls them (asking areas_open_to first; read fresh on every visit).
Who uses it: the AP, the President and Data Analysts on the Overview (portal/glimpse.js in home.html).
How it fits:
- Finished weeks only, and only weeks that have plans. The week still being reported (public.current_reporting_sunday()) is left out, as in the
  Dashboards deck, so a week that has only just started does not pull every number down.
- Each week's result is measured against the goal set the week before ("previous_goal"), as in Call-ins and the
  deck: the total of the goals the plans set in the previous reporting week, per zone and for the mission (the
  dashboards.kpi_zone_week and kpi_mission_week views of migration 018 pair them the same way).
- The labels are the Overview's (planning.KEY_INDICATORS), in the deck's order: "New people being taught", the key
  indicator, first.
- Like Call-ins, every plan in a week counts, drafts too.

Access (who sees which plans): the same rule as row-level security, asked once per area instead of once per row.
1. areas_open_to() runs on the caller's own connection (app.user_db: role authenticated with their sign-in claims) and
   asks public.can_access_area for every area of their mission. That is the very question row-level security asks
   for every weekly plan and every planning answer (the whole mission for the President, the APs and the Data
   Analysts; a DL only their district).
2. mission_dashboard() then reads the numbers on the service's connection (app.db), for exactly those areas.
Row-level security would give the same rows, but it asks the question again for every plan and twice for every
answer: after a few weeks of planning answers that took many seconds (round 9, docs/handoff/round9/api.md). Only the
weeks shown are read (12 by default, at most 26), week by week through the index on reporting_week_id.
"""
from datetime import timedelta

from helpers import fetch_rows, json_ready
from planning import KEY_INDICATORS

# The deck's order; the key indicator first.
ORDER = ('friends_found', 'baptisms_confirmations', 'baptismal_dates',
         'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament')
KEY_INDICATOR = 'friends_found'
# (key, label, column prefix in weekly_area_reports_with_planning_metrics), e.g. members_at_lessons ->
# lessons_with_members_actual / _goal, exactly as the Overview reads them.
INDICATORS = tuple(
    (key, label, actual_column[:-len('_actual')])
    for wanted in ORDER
    for key, label, _answer, _goal_answer, actual_column, *_rest in KEY_INDICATORS
    if key == wanted
)
DEFAULT_WEEKS = 12
MAX_WEEKS = 26
COMPLETE = ['SUBMITTED', 'LOCKED']
WEEKS_MESSAGE = f'Choose between 1 and {MAX_WEEKS} weeks.'
PARTS = ('actual', 'goal', 'previous_goal')


def parse_weeks(value):
    """The number of finished weeks to show: DEFAULT_WEEKS when not given, otherwise 1 to MAX_WEEKS."""
    if value is None or value == '':
        return DEFAULT_WEEKS
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(WEEKS_MESSAGE)
    weeks = int(text)
    if not 1 <= weeks <= MAX_WEEKS:
        raise ValueError(WEEKS_MESSAGE)
    return weeks


def _add(total, value):
    """total + value, where None means "no number" (None + 3 = 3, None + None = None)."""
    if value is None:
        return total
    return value if total is None else total + value


def _cell(row=None):
    """One zone in one week. Without a row (no plans that week): no results, no goals set."""
    return {
        'reports': row['reports'] if row else 0,
        'submitted': row['submitted'] if row else 0,
        'actual': {key: (row[key + '_actual'] if row else None) for key, *_ in INDICATORS},
        'goal': {key: (row[key + '_goal'] if row else None) for key, *_ in INDICATORS},
    }


# ---------------------------------------------------------------------------------------------- reading
def _weeks_to_read(conn, current, weeks, area_ids):
    """The latest finished Sundays that have data (at least one plan in the areas the person may see), newest first. A
    finished week without any plan is left out, so the week list has no empty weeks."""
    return [row['sunday'] for row in fetch_rows(conn, """
        SELECT rw.sunday FROM public.reporting_weeks rw
        WHERE rw.sunday < %s AND EXISTS (SELECT 1 FROM public.weekly_area_reports war
                                         WHERE war.reporting_week_id = rw.id AND war.area_id = ANY(%s))
        ORDER BY rw.sunday DESC LIMIT %s""", (current, area_ids, weeks))]


def areas_open_to(conn, mission_id):
    """The ids of the mission's areas the person may see, asked as the person (conn: their app.user_db connection)
    with row-level security's own question, public.can_access_area."""
    return [row['id'] for row in fetch_rows(conn, """
        SELECT a.id FROM public.areas a
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE z.mission_id = %s AND public.can_access_area(a.id)
        ORDER BY a.id""", (mission_id,))]


def _zone_week_rows(conn, mission_id, sundays, area_ids):
    """One row per zone and week: plan counts and the sums of each indicator's result and goal, over the plans of
    area_ids only."""
    if not sundays or not area_ids:
        return []
    sums = ','.join(
        f'sum(v.{column}_actual) AS {key}_actual, sum(v.{column}_goal) AS {key}_goal'
        for key, _, column in INDICATORS)
    # One reporting week at a time (LATERAL; OFFSET 0 keeps the planner from merging it into the joins), so only
    # the plans of these weeks are read, through the index on reporting_week_id.
    return fetch_rows(conn, f"""
        SELECT rw.sunday, z.id AS zone_id,
               count(*)::integer AS reports,
               count(*) FILTER (WHERE v.status = ANY(%s))::integer AS submitted,
               {sums}
        FROM public.reporting_weeks rw
        CROSS JOIN LATERAL (
            SELECT * FROM public.weekly_area_reports_with_planning_metrics m
            WHERE m.reporting_week_id = rw.id OFFSET 0) v
        JOIN public.areas a ON a.id = v.area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE rw.sunday = ANY(%s) AND z.mission_id = %s AND a.id = ANY(%s)
        GROUP BY rw.sunday, z.id""", (COMPLETE, sundays, mission_id, area_ids))


# ---------------------------------------------------------------------------------------------- shaping
def _week_entry(sunday, now_rows, before_rows):
    """One week: a cell per zone that had plans this week or the week before, and the mission totals."""
    cells, mission = {}, {'reports': 0, 'submitted': 0, 'actual': {}, 'goal': {}, 'previous_goal': {}}
    for zone_id in sorted(set(now_rows) | set(before_rows)):
        cell = _cell(now_rows.get(zone_id))
        before = before_rows.get(zone_id)
        cell['previous_goal'] = {key: (before[key + '_goal'] if before else None) for key, *_ in INDICATORS}
        cells[zone_id] = cell
        mission['reports'] += cell['reports']
        mission['submitted'] += cell['submitted']
        for part in PARTS:
            for key, *_ in INDICATORS:
                mission[part][key] = _add(mission[part].get(key), cell[part][key])
    for part in PARTS:
        for key, *_ in INDICATORS:
            mission[part].setdefault(key, None)
    return {'sunday': sunday, 'mission': mission, 'zones': cells}


def mission_dashboard(conn, context, weeks, area_ids):
    """The glimpse's numbers for context's mission, counting the plans of area_ids only (areas_open_to), read on conn
    (the service's app.db connection)."""
    current = fetch_rows(conn, 'SELECT public.current_reporting_sunday() AS sunday')[0]['sunday']
    shown = _weeks_to_read(conn, current, weeks, area_ids)  # newest first
    finished = fetch_rows(conn, """
        SELECT count(*)::integer AS n FROM public.reporting_weeks rw
        WHERE rw.sunday < %s AND EXISTS (SELECT 1 FROM public.weekly_area_reports war
                                         WHERE war.reporting_week_id = rw.id AND war.area_id = ANY(%s))""",
                          (current, area_ids))[0]['n']
    # Each shown week is measured against the goals set the Sunday before it, so those weeks are read too.
    before_of = {sunday: sunday - timedelta(days=7) for sunday in shown}
    data = _zone_week_rows(conn, context['mission_id'], sorted(set(shown) | set(before_of.values())), area_ids)
    zones = fetch_rows(conn, """
        SELECT id, name FROM public.zones
        WHERE mission_id = %s AND active ORDER BY name""", (context['mission_id'],))

    by_week = {}
    for row in data:
        by_week.setdefault(row['sunday'], {})[row['zone_id']] = row
    shown = list(reversed(shown))  # oldest first
    # Only open zones are drawn. Old plans follow their area to the zone it is in today (an area moved to another zone
    # takes its numbers along), and the mission totals still add up every plan of the weeks shown.
    result_weeks = [_week_entry(sunday, by_week.get(sunday, {}), by_week.get(before_of[sunday], {}))
                    for sunday in shown]

    return json_ready({
        'mission': context.get('mission'),
        'current_week': current,
        'weeks_shown': weeks,
        'finished_weeks': finished,
        'max_weeks': MAX_WEEKS,
        'indicators': [{'key': key, 'label': label, 'key_indicator': key == KEY_INDICATOR}
                       for key, label, _ in INDICATORS],
        'zones': [{'id': zone['id'], 'name': zone['name']} for zone in zones],
        # Oldest first. Each week has the mission totals and one cell per zone that had plans that week or the week
        # before (a zone with last week's goals but no plans yet still shows what it was measured against).
        'weeks': result_weeks,
    })
