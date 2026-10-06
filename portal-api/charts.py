"""Database charts for slides: the numbers behind <MissionChart :query='{...}'> and the chart builder in /studio.

What it is: two routes the presentation manager calls, and the code that turns a chart's settings (the "spec") into a
table of numbers: normalize_spec (check the settings), stewardship_units (whose numbers), data_query (the SQL),
build_table (rows into labels and series).
Who uses it: the Slidev presentation manager (slidev/manager/server.mjs /api/charts/*), for managers, ZLs, STLs and
DLs with a shared deck. Never the browser directly.
How it fits: the manager asks with the service key and the person's id; this file checks what that person may see
and reads only the dashboards views, as a read-only reader role.

POST /internal/presentations/chart-catalog {user_id}
    What a chart can show: measures, levels, zones, districts, areas and recent weeks. Managers get the mission; a ZL
    or STL who makes their zone's presentations gets only their own zone, its districts and areas (round 7).
POST /internal/presentations/chart-data {user_id, spec, deck?, pinned?}
    One chart's table {labels, series:[{name, values, role?}]} and meta.

Both are reached only from the Slidev manager (server.mjs /api/charts/*) and are authenticated exactly like
/internal/presentations/kpis: app.internal_context (the X-Service-Key header, then the person's current context),
then the presentations role check.

Who may ask for what:
- Managers (roles.is_manager: AP, President, Data Analyst, also as an additional role) may ask for any spec that
  passes validation: every measure, level and filter comes from the whitelist below.
- ZL and STL get specs "pinned" in a deck they may open. The manager checks that the spec's canonical hash
  (spec_hash) appears in the deck's slides.md and says so with pinned=true; this endpoint then checks the deck's
  access rule again (app.deck_allowed). Round 7: a ZL or STL also edits their own zone's decks, so for those decks
  (app.deck_editable) any spec is answered, pinned or not (the builder's preview). That is safe because of the rule
  below: they always get only their own zone's numbers. DLs and missionaries have no Presentations.

Who sees which numbers (round 6, 28 Sep 2026: "ZL can't do other zones and mission"):
- Managers see the chart as written: the whole mission.
- Everyone else (DL, ZL, STL) sees only their own stewardship (app.scope_areas: DL = district, ZL/STL = zone), for
  EVERY chart. When the chart's level is wider than the viewer's stewardship (a mission chart for a ZL, a zone chart
  for a DL), the chart shows the viewer's own units one level down instead (the ZL's zone, the DL's district), never
  a partial total under the mission's or the zone's name. A chart limited to other zones or districts shows them
  nothing ("There are no numbers for your stewardship in this chart.").
- The spec's 'audience' ('deck' or 'stewardship') is still accepted and still part of the canonical form and the
  pinned hash, so every chart already written in a deck keeps working, but it no longer changes who sees what. The
  old 'deck' audience showed every viewer the same mission-wide numbers; it is retired.
- Round 8: a chart in a zone's presentation (a deck with an owner zone, migration 035) shows at most that zone, for
  everyone who opens it, managers too (deck_units). Its slides are page code that zone's leaders wrote, and since
  round 8 managers see zone decks; the deck's code then never gets more numbers than its own authors may see.

Queries: built only from the whitelist, names through psycopg2.sql.Identifier, values as parameters, run in one
READ ONLY transaction as gfm_dashboard_reader (SET LOCAL ROLE; migration 025 lets postgres do that) with a short
statement timeout, and at most MAX_ROWS rows per query. The reader can read the dashboards views only: key
indicators (018, 025) and count-only people views (025), where area numbers below 3 are already hidden.
No names, notes or person ids ever reach a chart.

The spec (canonical form, the same in slidev/manager/gfm-addon/lib/chart-spec.mjs; test vectors in
slidev/tests/fixtures/chart-spec-vectors.json):
    {"v":1, "measures":["friends_found.actual","friends_found.previous_goal"], "level":"zone", "by":"week",
     "filter":{"zones":[3,5]}, "weeks":{"last":12}, "includeCurrent":true, "transform":"none",
     "sort":"none", "top":0, "audience":"deck"}
The same stewardship rule gives leaders their own totals instead of the mission's in /internal/presentations/kpis
(app.presentation_kpis, through leader_units and stewardship_kpis below).
"""
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone

from flask import Blueprint, abort, jsonify, request
from psycopg2 import errors as pg_errors, sql

import roles
from helpers import dashboard_reader

charts_bp = Blueprint('charts', __name__)


def _app():
    import app  # imported here: app.py registers this blueprint while it is still loading
    return app


LEVELS = ('mission', 'zone', 'district', 'area')
BYS = ('week', 'unit')
TRANSFORMS = ('none', 'pct_of_goal', 'cumulative', 'rolling4', 'per_area')
SORTS = ('none', 'desc', 'asc')
AUDIENCES = ('deck', 'stewardship')
FILTER_KEYS = ('zones', 'districts', 'areas')
LEVEL_FILTERS = {'mission': (), 'zone': ('zones',), 'district': ('zones', 'districts'),
                 'area': ('zones', 'districts', 'areas')}
FILTER_COLUMNS = {'zones': 'zone_id', 'districts': 'district_id', 'areas': 'area_id'}
SPEC_KEYS = ('v', 'measures', 'level', 'by', 'filter', 'weeks', 'includeCurrent', 'transform', 'sort', 'top', 'audience')
MEASURE_ID = re.compile(r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
MAX_MEASURES = 8
MAX_MEASURE_ENTRIES = 32  # entries in the measures list before repeats are dropped (chart-spec.mjs has the same)
MAX_WEEKS = 104
MAX_TOP = 50
MAX_FILTER = 200
MAX_ID = 2 ** 31 - 1
MAX_ROWS = 20000
MAX_SERIES = 40
MAX_CELLS = 6000
STATEMENT_TIMEOUT = '5s'
ROLLING = 4

NOT_PINNED = 'This chart is not part of a presentation you may open.'
SLOW = 'These numbers took too long to load. Choose fewer weeks or units, or try again later.'
TOO_MANY = 'This chart would show too many numbers. Choose fewer weeks, units or numbers.'

# ---- the whitelist -----------------------------------------------------------------------------------------------

KPI_VIEWS = {'mission': 'kpi_mission_week', 'zone': 'kpi_zone_week', 'district': 'kpi_district_week',
             'area': 'kpi_area_total_week'}
PEOPLE_VIEWS = {'mission': 'people_mission_week', 'zone': 'people_zone_week', 'district': 'people_district_week',
                'area': 'people_area_week'}
UNIT_COLUMNS = {'mission': ('mission_id', None), 'zone': ('zone_id', 'zone'), 'district': ('district_id', 'district'),
                'area': ('area_id', 'area')}
LEVEL_WORDS = {'mission': 'Mission', 'zone': 'Zone', 'district': 'District', 'area': 'Area'}

GROUPS = (
    ('kpi', 'Key indicators'),
    ('lessons', 'Lessons'),
    ('plans', 'Weekly plans'),
    ('new_members', 'New members'),
    ('baptismal_date_friends', 'Friends with a baptismal date'),
    ('high_potentials', 'High-potential friends'),
)

# The six key indicators have "goal set the week before" (previous_goal, what Call-ins compares with) and "next
# week's goal" (goal: the goal a plan sets for the week after it, migration 018); the lesson counts only the latter.
# Labels are what people see (chart legends, the builder). They are not part of a chart's spec, so changing one
# never changes a pinned chart's hash; the ids (friends_found, ...) must stay as they are.
KPIS = (
    # Preach My Gospel's name for the indicator the plans still call friends_found.
    ('friends_found', 'New people being taught', 'kpi', ('actual', 'goal', 'previous_goal')),
    ('baptisms_confirmations', 'Baptisms and confirmations', 'kpi', ('actual', 'goal', 'previous_goal')),
    ('baptismal_dates', 'Baptismal dates', 'kpi', ('actual', 'goal', 'previous_goal')),
    ('sacrament_attendance', 'Sacrament attendance', 'kpi', ('actual', 'goal', 'previous_goal')),
    ('members_at_lessons', 'Members at lessons', 'kpi', ('actual', 'goal', 'previous_goal')),
    ('new_member_sacrament', 'New member sacrament attendance', 'kpi', ('actual', 'goal', 'previous_goal')),
    ('first_time_sacrament', 'First time at sacrament meeting', 'lessons', ('actual',)),
    ('lessons_with_friends', 'Lessons with friends', 'lessons', ('actual', 'goal')),
    ('follow_up_lessons', 'Follow-up lessons', 'lessons', ('actual', 'goal')),
)
GOAL_WORDS = {'previous_goal': 'goal set the week before', 'goal': "next week's goal"}
GOAL_SHORT = {'previous_goal': 'Goal set the week before', 'goal': "Next week's goal"}

PEOPLE = (
    ('new_members', 'New members', (
        ('total', 'new_members', 'New members', 'New members'),
        ('at_church', 'new_members_at_church', 'New members at church', 'At church'),
        ('temple_recommend', 'new_members_temple_recommend', 'New members with a temple recommend', 'Temple recommend'),
        ('calling', 'new_members_calling', 'New members with a calling', 'Calling'),
        ('aaronic_priesthood', 'new_members_aaronic_priesthood', 'New members with the Aaronic Priesthood',
         'Aaronic Priesthood'),
        ('melchizedek_priesthood', 'new_members_melchizedek_priesthood', 'New members with the Melchizedek Priesthood',
         'Melchizedek Priesthood'),
        ('ministering', 'new_members_ministering', 'New members with a ministering assignment',
         'Ministering assignment'),
        ('with_minister', 'new_members_with_minister', 'New members with ministering brothers or sisters',
         'Ministering brothers or sisters'),
        ('visited_temple', 'new_members_visited_temple', 'New members who have been to the temple for baptisms',
         'Temple baptisms'),
        ('reading', 'new_members_reading', 'New members reading', 'Reading'),
        ('praying', 'new_members_praying', 'New members praying', 'Praying'),
        ('member_involvement', 'new_members_member_involvement', 'New members with member involvement',
         'Member involvement'),
        ('discussed_in_gemiko', 'new_members_discussed_in_gemiko', 'New members discussed in GEMIKO',
         'Discussed in GEMIKO'),
    )),
    ('baptismal_date_friends', 'Friends with a baptismal date', (
        ('total', 'baptismal_date_friends', 'Friends with a baptismal date', 'Friends with a date'),
        ('next_4_weeks', 'baptismal_date_friends_next_4_weeks', 'Baptismal dates in the next 4 weeks',
         'Date in the next 4 weeks'),
        ('at_church', 'baptismal_date_friends_at_church', 'Friends with a date at church', 'At church'),
        ('reading', 'baptismal_date_friends_reading', 'Friends with a date reading', 'Reading'),
        ('praying', 'baptismal_date_friends_praying', 'Friends with a date praying', 'Praying'),
        ('keeping_commandments', 'baptismal_date_friends_keeping_commandments',
         'Friends with a date keeping the commandments', 'Keeping the commandments'),
        ('member_involvement', 'baptismal_date_friends_member_involvement', 'Friends with a date with member involvement',
         'Member involvement'),
    )),
    ('high_potentials', 'High-potential friends', (
        ('total', 'high_potentials', 'High-potential friends', 'High-potential friends'),
        ('at_church', 'high_potentials_at_church', 'High-potential friends at church', 'At church'),
    )),
)


def _measures():
    """Every measure a chart may show, by id ('friends_found.actual'), built from KPIS, the plan counts and PEOPLE."""
    out = {}
    for key, name, group, fields in KPIS:
        for field in fields:
            goal = field in GOAL_WORDS
            out[f'{key}.{field}'] = {
                'id': f'{key}.{field}', 'source': 'kpi', 'column': f'{key}_{field}', 'group': group, 'topic': key,
                'field': field, 'kind': 'goal' if goal else 'actual',
                'label': f'{name}: {GOAL_WORDS[field]}' if goal else name,
                'short': GOAL_SHORT[field] if goal else name,
                'goals': {g: f'{key}.{g}' for g in fields if g in GOAL_WORDS} if not goal else {},
            }
    for field, column, label in (('started', 'reports', 'Plans started'), ('submitted', 'submitted_reports', 'Plans submitted')):
        out[f'plans.{field}'] = {'id': f'plans.{field}', 'source': 'kpi', 'column': column, 'group': 'plans',
                                 'topic': 'plans', 'field': field, 'kind': 'count', 'label': label, 'short': label,
                                 'goals': {}}
    for group, _, fields in PEOPLE:
        for field, column, label, short in fields:
            out[f'{group}.{field}'] = {'id': f'{group}.{field}', 'source': 'people', 'column': column, 'group': group,
                                       'topic': group, 'field': field, 'kind': 'count', 'label': label,
                                       'short': short, 'goals': {}}
    return out


MEASURES = _measures()

# ---- the spec ------------------------------------------------------------------------------------------------------


def _integer(value):
    """A whole number from JSON (12 or 12.0), else None. Booleans are not numbers here."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _choice(spec, key, options, default):
    """spec[key] (or the default) when it is one of the options, else a ValueError naming them."""
    value = spec.get(key, default)
    if value not in options:
        raise ValueError(f'Choose one of {", ".join(options)} for {key}.')
    return value


def normalize_spec(raw, whitelist=True):
    """The canonical spec, with every default filled in, or ValueError with a sentence for the writer.

    Mirrors normalizeSpec() in chart-spec.mjs exactly (same rules, same defaults, same order of checks), so both
    sides compute the same canonical JSON and hash. `whitelist` also checks the measure names and the combinations
    that need to know them (% of goal); the Slidev manager cannot, so it leaves that to this side.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError('The chart settings are not valid JSON.') from None
    if not isinstance(raw, dict):
        raise ValueError('The chart settings must be a list of settings in { }.')
    unknown = sorted(set(raw) - set(SPEC_KEYS))
    if unknown:
        raise ValueError(f'Unknown chart setting: {unknown[0]}.')
    version = _integer(raw.get('v', 1))
    if version != 1:
        raise ValueError('This chart was made for a newer version of Presentations.')

    measures = raw.get('measures')
    if not isinstance(measures, list) or not measures:
        raise ValueError('Choose at least one number to show.')
    # A long list is refused before it is read; repeats within the limit are dropped (first one kept).
    if len(measures) > MAX_MEASURE_ENTRIES:
        raise ValueError(f'Choose at most {MAX_MEASURES} numbers for one chart.')
    seen = {}
    for m in measures:
        if not isinstance(m, str) or not MEASURE_ID.fullmatch(m):  # fullmatch: '$' alone lets a final newline through
            raise ValueError('A number in this chart is not written like "friends_found.actual".')
        seen.setdefault(m, None)
    seen = list(seen)
    if len(seen) > MAX_MEASURES:
        raise ValueError(f'Choose at most {MAX_MEASURES} numbers for one chart.')

    level = _choice(raw, 'level', LEVELS, 'mission')
    by = _choice(raw, 'by', BYS, 'week')

    given = raw.get('filter', {})
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise ValueError('Choose the zones, districts or areas as lists of numbers.')
    filt = {}
    for key in sorted(given):
        if key not in FILTER_KEYS:
            raise ValueError(f'Unknown chart setting: filter.{key}.')
        values = given[key]
        if values is None:
            values = []
        if not isinstance(values, list):
            raise ValueError(f'Choose {key} as a list of numbers.')
        ids = [_integer(v) for v in values]
        if any(i is None or i < 1 or i > MAX_ID for i in ids):
            raise ValueError(f'Choose {key} as a list of numbers.')
        ids = sorted(set(ids))
        if len(ids) > MAX_FILTER:
            raise ValueError(f'Choose at most {MAX_FILTER} {key}.')
        if not ids:
            continue
        if key not in LEVEL_FILTERS[level]:
            raise ValueError(f'A {level} chart cannot be limited to {key}.')
        filt[key] = ids

    weeks = raw.get('weeks', 12)
    if isinstance(weeks, dict):
        extra = sorted(set(weeks) - {'last'})
        if extra:
            raise ValueError(f'Unknown chart setting: weeks.{extra[0]}.')
        weeks = weeks.get('last', 12)
    last = _integer(weeks)
    if last is None or not 1 <= last <= MAX_WEEKS:
        raise ValueError(f'Choose between 1 and {MAX_WEEKS} weeks.')

    include_current = raw.get('includeCurrent', True)
    if not isinstance(include_current, bool):
        raise ValueError('includeCurrent must be true or false.')

    transform = _choice(raw, 'transform', TRANSFORMS, 'none')
    if transform in ('cumulative', 'rolling4') and by != 'week':
        raise ValueError('A running total or 4-week average needs the chart grouped by week.')

    sort = _choice(raw, 'sort', SORTS, 'none')
    top = _integer(raw.get('top', 0))
    if top is None or not 0 <= top <= MAX_TOP:
        raise ValueError(f'Choose a top number between 0 and {MAX_TOP}.')
    if by == 'week' and (sort != 'none' or top):
        raise ValueError('Sorting and "top" work when the chart is grouped by zone, district or area.')

    audience = _choice(raw, 'audience', AUDIENCES, 'deck' if level in ('mission', 'zone') else 'stewardship')

    spec = {'v': 1, 'measures': seen, 'level': level, 'by': by, 'filter': filt, 'weeks': {'last': last},
            'includeCurrent': include_current, 'transform': transform, 'sort': sort, 'top': top, 'audience': audience}
    if whitelist:
        check_whitelist(spec)
    return spec


def check_whitelist(spec):
    """Every measure must be a known one, and '% of goal' needs a goal for each number."""
    for m in spec['measures']:
        if m not in MEASURES:
            raise ValueError(f'Unknown number: {m}.')
    if spec['transform'] == 'pct_of_goal':
        goal_pairs(spec['measures'])


def goal_pairs(measures):
    """For '% of goal': each actual with the goal it is measured against (goal set last week first)."""
    chosen = set(measures)
    pairs = []
    for m in measures:
        info = MEASURES[m]
        if info['kind'] == 'goal':
            continue
        if not info['goals']:
            raise ValueError(f'"% of goal" works only for numbers with a goal; {info["label"]} has none.')
        goal = next((g for f, g in sorted(info['goals'].items(), key=lambda x: x[0] != 'previous_goal') if g in chosen),
                    None)
        if not goal:
            raise ValueError(f'To show "% of goal", also choose a goal to compare {info["label"]} with.')
        pairs.append((m, goal))
    if not pairs:
        raise ValueError('To show "% of goal", choose a number and its goal.')
    return pairs


def canonical_json(spec):
    """The spec as one fixed text (sorted keys, no spaces): the same text the Slidev manager makes."""
    return json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def spec_hash(spec):
    """SHA-256 of the canonical JSON: what the Slidev manager looks for in a deck's slides.md (pinning)."""
    return hashlib.sha256(canonical_json(spec).encode('utf-8')).hexdigest()

# ---- who sees which units ----------------------------------------------------------------------------------------


def covered_units(level, all_areas, mine):
    """Units at `level` whose areas all lie in `mine` (a set of area ids). all_areas: [{id, district_id, zone_id}]."""
    if level == 'area':
        return {a['id'] for a in all_areas if a['id'] in mine}
    if level == 'mission':
        return {'mission'} if all_areas and all(a['id'] in mine for a in all_areas) else set()
    key = 'zone_id' if level == 'zone' else 'district_id'
    units = {}
    for a in all_areas:
        units.setdefault(a[key], []).append(a['id'] in mine)
    return {unit for unit, inside in units.items() if all(inside)}


def stewardship_units(level, all_areas, mine):
    """(effective level, unit ids or None for "no restriction") for an audience='stewardship' chart.

    The whole mission in scope (managers): the chart as written. Otherwise the units at the chart's level that lie
    wholly inside the viewer's stewardship; when there are none (a zone chart for a DL), one level down, and so on.
    """
    if all_areas and all(a['id'] in mine for a in all_areas):
        return level, None
    for candidate in LEVELS[LEVELS.index(level):]:
        units = covered_units(candidate, all_areas, mine)
        if units and candidate != 'mission':
            return candidate, units
    return 'area', set()

# ---- queries -------------------------------------------------------------------------------------------------------


def week_query(mission_id, current, last, include_current):
    """The last `last` reporting Sundays that have plans, up to the current one (or before it).

    people_mission_week has a row for exactly the weeks with plans, like kpi_mission_week, but is about ten times
    cheaper to read (it does not rebuild every report's key indicators)."""
    compare = sql.SQL('<=') if include_current else sql.SQL('<')
    query = sql.SQL('SELECT sunday FROM {view} WHERE mission_id = %s AND sunday {cmp} %s ORDER BY sunday DESC LIMIT %s').format(
        view=sql.Identifier('dashboards', 'people_mission_week'), cmp=compare)
    return query, [mission_id, current, last]


def data_query(source, level, measures, mission_id, sundays, filt, units):
    """One source's rows (kpi or people) for the chosen weeks, as a whitelisted SELECT."""
    view = (KPI_VIEWS if source == 'kpi' else PEOPLE_VIEWS)[level]
    unit_id, unit_name = UNIT_COLUMNS[level]
    columns = ['sunday', unit_id] + ([unit_name] if unit_name else [])
    columns.append('reports' if source == 'kpi' and level == 'area' else 'areas_reporting')
    for m in measures:
        column = MEASURES[m]['column']
        if MEASURES[m]['source'] == source and column not in columns:
            columns.append(column)
    where = [sql.SQL('mission_id = %s'), sql.SQL('sunday = ANY(%s::date[])')]
    args = [mission_id, list(sundays)]
    for key in FILTER_KEYS:
        if filt.get(key):
            where.append(sql.SQL('{} = ANY(%s::bigint[])').format(sql.Identifier(FILTER_COLUMNS[key])))
            args.append(list(filt[key]))
    if units is not None:
        where.append(sql.SQL('{} = ANY(%s::bigint[])').format(sql.Identifier(unit_id)))
        args.append(sorted(units))
    query = sql.SQL('SELECT {cols} FROM {view} WHERE {where} ORDER BY sunday, {unit} LIMIT {cap}').format(
        cols=sql.SQL(', ').join(sql.Identifier(c) for c in columns),
        view=sql.Identifier('dashboards', view),
        where=sql.SQL(' AND ').join(where),
        unit=sql.Identifier(unit_id),
        cap=sql.Literal(MAX_ROWS + 1))
    return query, args, columns


def fetch(cur, query, args):
    """The rows of a chart query; refused with TOO_MANY when a query hits the MAX_ROWS limit."""
    cur.execute(query, args)
    got = cur.fetchall()
    if len(got) > MAX_ROWS:
        raise ValueError(TOO_MANY)
    return [dict(r) for r in got]

# ---- from rows to a chart table ----------------------------------------------------------------------------------


def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def _number(value):
    if value is None:
        return None
    n = float(value)
    return int(n) if n.is_integer() else n


def _round(value, digits):
    return None if value is None else _number(round(value, digits))


def series_name(info, measures, unit=None, many_units=False):
    """The legend name of one line or bar: the short label when every measure has the same topic, the unit's name
    when the chart shows one measure per unit."""
    same_topic = len({MEASURES[m]['topic'] for m in measures}) == 1
    label = info['short'] if same_topic else info['label']
    if unit is None:
        return label
    if len(measures) == 1:
        return unit
    return f'{unit} · {label}' if many_units else label


def pivot(measures, level, rows_by_source):
    """The rows as three lookups: cells {(week, unit): {measure: value}}, names {unit: name} and
    areas {(week, unit): number of areas reporting} (for the per-area transform)."""
    unit_id, unit_name = UNIT_COLUMNS[level]
    cells, names, areas = {}, {}, {}
    for source, source_rows in rows_by_source.items():
        for r in source_rows:
            week, unit = _iso(r['sunday']), r[unit_id]
            names[unit] = (r.get(unit_name) or LEVEL_WORDS[level]) if unit_name else 'Mission'
            cell = cells.setdefault((week, unit), {})
            for m in measures:
                if MEASURES[m]['source'] == source:
                    value = _number(r.get(MEASURES[m]['column']))
                    # The totals count a goal nobody set as 0: leave it out of the goal line, as <MissionKpiChart> does.
                    cell[m] = None if value == 0 and MEASURES[m]['kind'] == 'goal' else value
            if source == 'kpi' and level == 'area':
                count = r.get('reports')
                areas.setdefault((week, unit), 1 if count else None)
            elif r.get('areas_reporting') is not None:
                areas[(week, unit)] = _number(r['areas_reporting'])
    return cells, names, areas


class ChartNumbers:
    """The pivoted numbers of one chart, read through the chart's transform.

    poisoned: measures whose empty values mean "hidden" (people counts per area), so sums and averages over them
    stay empty instead of showing a smaller number."""

    def __init__(self, cells, areas, transform, poisoned):
        self.cells, self.areas, self.transform, self.poisoned = cells, areas, transform, poisoned

    def value(self, week, unit, m):
        """One number; divided by the areas reporting for the per-area transform."""
        v = self.cells.get((week, unit), {}).get(m)
        if v is not None and self.transform == 'per_area':
            d = self.areas.get((week, unit))
            v = v / d if d else None
        return v

    def over_weeks(self, unit, m, weeks_used):
        """By unit: the measure added up over the weeks (None when a hidden number is among them)."""
        values = [self.value(w, unit, m) for w in weeks_used]
        if m in self.poisoned and any(v is None for v in values):
            return None
        present = [v for v in values if v is not None]
        return sum(present) if present else None

    def pct_over_weeks(self, unit, m, goal, weeks_used):
        """By unit, '% of goal': actual and goal added up only over the weeks that have both a number and a goal,
        the same weeks the week-by-week chart shows. A week without a goal would otherwise add its number but no
        goal and overstate the percentage."""
        actual_sum = goal_sum = 0
        for w in weeks_used:
            a, g = self.value(w, unit, m), self.value(w, unit, goal)
            if a is not None and g:
                actual_sum += a
                goal_sum += g
        return _round(actual_sum / goal_sum * 100, 1) if goal_sum else None

    def weekly(self, unit, m, weeks):
        """Week by week, with the running total or the 4-week average applied (the average needs ROLLING-1 extra
        weeks at the start, which it uses up)."""
        values = [self.value(w, unit, m) for w in weeks]
        if self.transform == 'cumulative':
            return running_total(values, m in self.poisoned)
        if self.transform == 'rolling4':
            return rolling_average(values, m in self.poisoned)
        return values


def running_total(values, poisoned):
    """The running total week by week; empty before the first number, and from a hidden number on (poisoned)."""
    out, total, started, hidden = [], 0, False, False
    for v in values:
        if v is None and poisoned and started:
            hidden = True
        if v is not None:
            total += v
            started = True
        out.append(None if hidden or not started else total)
    return out


def rolling_average(values, poisoned):
    """The average of each week and the ROLLING-1 weeks before it (so ROLLING-1 fewer values come out). A window
    with a hidden number (poisoned) stays empty."""
    out = []
    for i in range(ROLLING - 1, len(values)):
        window = values[i - ROLLING + 1:i + 1]
        present = [v for v in window if v is not None]
        hidden = poisoned and len(present) < ROLLING
        out.append(None if hidden or not present else sum(present) / len(present))
    return out


def _series_entry(info, name, values, transform):
    entry = {'name': name, 'values': values}
    if info['kind'] == 'goal' and transform != 'pct_of_goal':
        entry['role'] = 'goal'  # drawn as a goal line
    return entry


def _table_by_unit(spec, numbers, pairs, units, names, shown_weeks):
    """One bar per unit: each measure added up over the weeks shown; then sorted and cut to the top N."""
    labels = [names[u] for u in units]
    series = []
    for m, goal in pairs:
        info = MEASURES[m]
        if goal:
            vals = [numbers.pct_over_weeks(u, m, goal, shown_weeks) for u in units]
        else:
            vals = [_round(numbers.over_weeks(u, m, shown_weeks), 2) for u in units]
        series.append(_series_entry(info, series_name(info, [p[0] for p in pairs]), vals, spec['transform']))
    if series and (spec['sort'] != 'none' or spec['top']):
        direction = spec['sort'] if spec['sort'] != 'none' else 'desc'
        first = series[0]['values']
        order = sorted(range(len(labels)),
                       key=lambda i: (first[i] is None, -(first[i] or 0) if direction == 'desc' else (first[i] or 0)))
        if spec['top']:
            order = order[:spec['top']]
        labels = [labels[i] for i in order]
        for s in series:
            s['values'] = [s['values'][i] for i in order]
    return labels, series


def _table_by_week(spec, level, numbers, pairs, units, names, weeks, shown_weeks):
    """One line per unit and measure, week by week (at most MAX_SERIES lines)."""
    many_units = level != 'mission' and len(units) > 1
    lines = len(units) * len(pairs)
    if lines > MAX_SERIES:
        plural = {'zone': 'zones', 'district': 'districts', 'area': 'areas'}.get(level, 'units')
        raise ValueError(f'Week by week this chart would draw {lines} lines. Choose some {plural} (at most '
                         f'{max(1, MAX_SERIES // len(pairs))}), or show one bar per {level}.')
    series = []
    for u in units:
        unit_label = names[u] if level != 'mission' else None
        for m, goal in pairs:
            info = MEASURES[m]
            if goal:
                a, g = numbers.weekly(u, m, weeks), numbers.weekly(u, goal, weeks)
                vals = [_round(x / y * 100, 1) if x is not None and y else None for x, y in zip(a, g)]
            else:
                vals = [_round(v, 2) for v in numbers.weekly(u, m, weeks)]
            name = series_name(info, [p[0] for p in pairs], unit_label, many_units)
            series.append(_series_entry(info, name, vals, spec['transform']))
    return list(shown_weeks), series


def build_table(spec, level, weeks, rows_by_source, poisoned):
    """Pivots the rows into {labels, series} and applies the transform. Returns (table, number of units).

    weeks: ascending ISO Sundays, including ROLLING-1 extra leading weeks for rolling4. poisoned: measures whose
    empty values mean "hidden" (people counts per area), so sums and averages over them stay empty.
    """
    measures = spec['measures']
    cells, names, areas = pivot(measures, level, rows_by_source)
    units = sorted(names, key=lambda u: (str(names[u]).casefold(), str(u)))
    transform = spec['transform']
    numbers = ChartNumbers(cells, areas, transform, poisoned)
    pairs = goal_pairs(measures) if transform == 'pct_of_goal' else [(m, None) for m in measures]
    shown_weeks = weeks[ROLLING - 1:] if transform == 'rolling4' else weeks
    if spec['by'] == 'unit':
        labels, series = _table_by_unit(spec, numbers, pairs, units, names, shown_weeks)
    else:
        labels, series = _table_by_week(spec, level, numbers, pairs, units, names, weeks, shown_weeks)
    if len(labels) * max(1, len(series)) > MAX_CELLS:
        raise ValueError(TOO_MANY)
    return {'labels': labels, 'series': series}, len(units)


def run_chart(conn, c, spec, deck_units=None):
    """The chart for context c. deck_units: None for a manager (the chart as written); for anyone else the
    (level, units) of their stewardship from leader_units()."""
    level = spec['level']
    units = None
    if deck_units is not None:
        level, units = deck_units
    current = _app().rows(conn, 'SELECT public.current_reporting_sunday() AS sunday')[0]['sunday']
    extra = ROLLING - 1 if spec['transform'] == 'rolling4' else 0
    sources = [source for source in ('kpi', 'people') if any(MEASURES[m]['source'] == source for m in spec['measures'])]
    rows_by_source = {}
    with dashboard_reader(conn, STATEMENT_TIMEOUT) as cur:
        wq, wargs = week_query(c['mission_id'], current, spec['weeks']['last'] + extra, spec['includeCurrent'])
        weeks = sorted(_iso(r['sunday']) for r in fetch(cur, wq, wargs))
        if units is None or units:
            for source in sources:
                query, args, _ = data_query(source, level, spec['measures'], c['mission_id'], weeks, spec['filter'], units)
                rows_by_source[source] = fetch(cur, query, args)
    poisoned = {m for m in spec['measures'] if MEASURES[m]['source'] == 'people' and level == 'area'}
    table, unit_count = build_table(spec, level, weeks, rows_by_source, poisoned)
    # A people count per area that exists but is empty was hidden (fewer than 3, see migration 025).
    suppressed = any(r.get(MEASURES[m]['column']) is None for r in rows_by_source.get('people', []) for m in poisoned)
    value_kind = {'pct_of_goal': 'percent', 'per_area': 'per_area'}.get(spec['transform'], 'count')
    return {
        'table': table,
        'meta': {
            'level': level, 'by': spec['by'], 'audience': spec['audience'], 'transform': spec['transform'],
            'unit': value_kind, 'weeks': weeks[extra:] if extra else weeks, 'current_week': _iso(current),
            'units': unit_count, 'suppressed': suppressed, 'stewardship': units is not None,
            'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
    }

# ---- whose numbers: a leader's own stewardship, a zone deck's zone --------------------------------------------------


def leader_units(conn, c, level):
    """None for a manager (the whole mission). For anyone else the (effective level, unit ids) of their own
    stewardship for a chart at `level` (stewardship_units); the unit ids are an empty set when they have none."""
    if roles.is_manager(c):
        return None
    api = _app()
    mine = {a['id'] for a in api.scope_areas(conn, c)}
    return stewardship_units(level, mission_areas(conn, c['mission_id']), mine)


def deck_units(conn, c, level, rule):
    """The units a chart in this deck shows to c (round 8). rule: the deck's access rule (app.deck_rules) or None.
    A mission deck (no owner zone): leader_units, as before. A zone's deck: at most that zone, for everyone who opens
    it (managers too), and for a leader also at most their own stewardship (a DL of the zone: their district)."""
    zone = (rule or {}).get('owner_zone_id')
    if not zone:
        return leader_units(conn, c, level)
    all_areas = mission_areas(conn, c['mission_id'])
    mine = {a['id'] for a in all_areas if a['zone_id'] == zone}
    if not roles.is_manager(c):
        mine &= {a['id'] for a in _app().scope_areas(conn, c)}
    return stewardship_units(level, all_areas, mine)


def stewardship_kpis(conn, mission_id, level, units, weeks, keys):
    """Week by week totals of the key indicators over a leader's own units (newest first, at most `weeks`), with
    the same columns as dashboards.kpi_mission_week: {key}_actual and {key}_previous_goal. units: a non-empty set of
    ids at `level` (zone, district or area), from leader_units."""
    unit_id = UNIT_COLUMNS[level][0]
    sums = sql.SQL(', ').join(sql.SQL('sum({c}) AS {c}').format(c=sql.Identifier(f'{k}_{f}'))
                              for k in keys for f in ('actual', 'previous_goal'))
    query = sql.SQL('SELECT sunday, {sums} FROM {view} WHERE mission_id = %s AND {unit} = ANY(%s::bigint[]) '
                    'AND sunday <= public.current_reporting_sunday() GROUP BY sunday ORDER BY sunday DESC LIMIT %s').format(
        sums=sums, view=sql.Identifier('dashboards', KPI_VIEWS[level]), unit=sql.Identifier(unit_id))
    with conn.cursor() as cur:
        cur.execute(query, [mission_id, sorted(units), weeks])
        return [dict(r) for r in cur.fetchall()]


def own_units(my_areas, zones, districts, areas):
    """The zones, districts and areas (lists of rows with an id) that hold at least one of my_areas (app.scope_areas),
    so the chart builder offers a ZL or STL only their own zone."""
    area_ids = {a['id'] for a in my_areas}
    district_ids = {a['district_id'] for a in my_areas}
    zone_ids = {a['zone_id'] for a in my_areas}
    return ([z for z in zones if z['id'] in zone_ids], [d for d in districts if d['id'] in district_ids],
            [a for a in areas if a['id'] in area_ids])


def mission_areas(conn, mission_id):
    """Every area of the mission with its district and zone: [{id, district_id, zone_id}]."""
    return _app().rows(conn, '''SELECT a.id, a.district_id, d.zone_id FROM public.areas a
        JOIN public.districts d ON d.id = a.district_id JOIN public.zones z ON z.id = d.zone_id
        WHERE z.mission_id = %s ORDER BY a.id''', (mission_id,))


# ---- endpoints -----------------------------------------------------------------------------------------------------


@charts_bp.post('/internal/presentations/chart-data')
def chart_data():
    """One chart's numbers for a person (see the top of this file for who may ask for which chart)."""
    api = _app()
    body = request.json or {}
    with api.db() as conn:
        c = api.internal_context(conn)
        if not roles.can_use_presentations(c):
            abort(403, 'Presentations are available to assigned leaders.')
        spec = normalize_spec(body.get('spec'))
        deck = str(body.get('deck') or '')
        rule = api.deck_rules(conn, c, [deck]).get(deck) if deck else None
        if not roles.is_manager(c):
            # A zone deck's own ZL and STL may try any chart while they build it (the builder's preview); anyone
            # else only a chart written in a deck they may open. Either way deck_units below narrows the numbers
            # to their own zone.
            building = bool(deck) and api.deck_editable(rule, c)
            pinned = bool(deck) and body.get('pinned') is True and api.deck_allowed(rule, c)
            if not (building or pinned):
                abort(403, NOT_PINNED)
        # Managers: the chart as written. Everyone else: their own stewardship, whatever the spec's audience says.
        # Round 8: in a zone's deck, at most that zone for everyone (deck_units).
        steward = deck_units(conn, c, spec['level'], rule)
        try:
            result = run_chart(conn, c, spec, steward)
        except pg_errors.QueryCanceled:
            abort(503, SLOW)
    result['meta']['hash'] = spec_hash(spec)
    return jsonify(result)


@charts_bp.post('/internal/presentations/chart-catalog')
def chart_catalog():
    """Everything the chart builder offers: org units and week dates, no people. Managers get the whole mission. A ZL
    or STL who makes their zone's presentations gets only their own zone, its districts and areas, and no mission
    level (round 7: "zl and stl should not see other zones when building graphs and presentations")."""
    api = _app()
    with api.db() as conn:
        c = api.internal_context(conn)
        manager = roles.is_manager(c)
        if not manager and not roles.presentation_zone(c):
            abort(403, 'The chart builder is for mission leaders who manage presentations.')
        mission = c['mission_id']
        zones = api.rows(conn, 'SELECT id, name FROM public.zones WHERE mission_id=%s ORDER BY name, id', (mission,))
        districts = api.rows(conn, '''SELECT d.id, d.name, d.zone_id FROM public.districts d
            JOIN public.zones z ON z.id = d.zone_id WHERE z.mission_id=%s ORDER BY d.name, d.id''', (mission,))
        areas = api.rows(conn, '''SELECT a.id, a.name, a.district_id, d.zone_id FROM public.areas a
            JOIN public.districts d ON d.id = a.district_id JOIN public.zones z ON z.id = d.zone_id
            WHERE z.mission_id=%s ORDER BY a.name, a.id''', (mission,))
        levels = LEVELS
        if not manager:
            zones, districts, areas = own_units(api.scope_areas(conn, c), zones, districts, areas)
            levels = LEVELS[1:]  # no "The mission"
        current = api.rows(conn, 'SELECT public.current_reporting_sunday() AS sunday')[0]['sunday']
        with dashboard_reader(conn, STATEMENT_TIMEOUT) as cur:
            query, args = week_query(mission, current, MAX_WEEKS, True)
            weeks = [_iso(r['sunday']) for r in fetch(cur, query, args)]
    measures = [{k: v for k, v in info.items() if k != 'column'} for info in MEASURES.values()]
    return jsonify({
        'measures': measures,
        'groups': [{'id': g, 'label': label} for g, label in GROUPS],
        'levels': [{'id': lv, 'label': LEVEL_WORDS[lv]} for lv in levels],
        'scope': 'mission' if manager else 'zone',
        'zones': zones, 'districts': districts, 'areas': areas,
        'weeks': {'current': _iso(current), 'available': weeks},
        'limits': {'weeks': MAX_WEEKS, 'measures': MAX_MEASURES, 'top': MAX_TOP, 'filter': MAX_FILTER,
                   'series': MAX_SERIES},
        'transforms': list(TRANSFORMS), 'audiences': list(AUDIENCES),
    })
