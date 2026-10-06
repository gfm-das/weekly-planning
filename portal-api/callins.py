"""Call-ins: the weekly check-in of leaders, for the mission, a zone, a district or one area.

What it is: the /api/callins routes. Reading: the numbers, notes and plans of one level (mission > zone > district >
area) for one week, plus the People and GEMIKO tabs. Writing: DL notes, ZL notes, zone notes, area updates, and
Complete / Reopen of a district's call-in.
Who uses it: portal/callins.html, for managers, ZLs and DLs.
How it fits: the numbers come from database functions (migrations 020 and 022). This file checks who may open or
write what, calls those functions as the signed-in person (app.user_db), and shapes the answer for the page.

Who sees what (roles.py decides the roles; stewardship follows the main role):
- Mission managers (AP, President, Data Analyst - also as an additional role) open the mission and may go down
  to any zone, district or area of their mission.
- A ZL opens their zone and may go down to its districts and areas; a DL opens their district and its areas.
- Someone whose manager right comes only from an additional Data Analyst role opens on their DL or ZL home but may
  go up to the mission; without a DL or ZL home they open on the mission (computer-first, like any Data Analyst).
- Everyone else (missionaries, STLs, Office) gets a friendly 403. STLs have no part in Call-ins.

Every read and write runs as the signed-in user after the stewardship check below, so the database rules stay the
final word; a database refusal (SQLSTATE 42501) becomes a plain 403. DL notes, area updates and Complete / Reopen:
the DL of the district and managers. ZL notes and zone notes: the ZL of the zone and managers. A completed district
call-in locks its DL notes and area updates. There is no thank-you feature: call_in_districts.thank_you is never read
or written here.
"""
import re
from datetime import datetime

import psycopg2
from flask import Blueprint, abort, g, jsonify, request

import roles
from helpers import fetch_rows, json_ready

callins_bp = Blueprint('callins', __name__)

# nginx stops waiting for /api/ after 40 s, but without a limit the database kept running a slow Call-ins summary
# (and an API thread kept waiting for it) for many minutes after the page had given up. Stop it in time to say why.
CALLINS_STATEMENT_TIMEOUT = '30s'
NOTE_LIMIT = 12000
LEVELS = ('mission', 'zone', 'district', 'area')
CHILD_LEVEL = {'mission': 'zone', 'zone': 'district', 'district': 'area', 'area': None}
# The seven call-in numbers, in the order the page shows them. Follow-up lessons have no "goal set last week".
METRICS = (
    ('friends_found', 'New people being taught'),
    ('members_at_lessons', 'Members at lessons'),
    ('sacrament_attendance', 'Sacrament attendance'),
    ('baptismal_dates', 'Baptismal dates'),
    ('baptisms_confirmations', 'Baptisms and confirmations'),
    ('nm_sacrament', 'New member sacrament attendance'),
    ('follow_up_lessons', 'Follow-up lessons'),
)
PLAN_KEYS = tuple(key for key, _ in METRICS if key != 'follow_up_lessons')

NOT_FOR_YOU = ('Call-ins are for district leaders, zone leaders and mission leaders. '
               'If you are one of them, ask the office to check your assignment.')
OUTSIDE = 'This part of the mission is outside your stewardship.'
SLOW = 'Loading call-ins took too long, so it was stopped. Please try again later.'
LOCKED = 'This call-in is marked complete. Reopen it to change the DL notes or area updates.'
BAD_WEEK = 'Choose a reporting week as a date like 2026-09-20.'


def _app():
    import app  # imported here: app.py registers this blueprint while it is still loading
    return app


# ---------------------------------------------------------------- who is asking

def viewer(c):
    """The viewer's Call-ins rights, or a 403 for people Call-ins are not for."""
    main = roles.main_role(c)
    manager = roles.is_manager(c)
    zone_id = (c.get('leadership_zone_id') or c.get('zone_id')) if main == 'ZL' else None
    district_id = (c.get('leadership_district_id') or c.get('district_id')) if main == 'DL' else None
    if not manager and not zone_id and not district_id:
        abort(403, NOT_FOR_YOU)
    if main in roles.MANAGER_ROLES:
        home = ('mission', c['mission_id'])
    elif zone_id:
        home = ('zone', zone_id)
    elif district_id:
        home = ('district', district_id)
    else:  # manager only through an additional Data Analyst role, without a DL or ZL home
        home = ('mission', c['mission_id'])
    return {'main': main, 'manager': manager, 'mission_id': c.get('mission_id'), 'zone_id': zone_id,
            'district_id': district_id, 'home': {'level': home[0], 'id': home[1]},
            'layout': layout_for(main, home[0])}


def layout_for(main, home_level):
    """Computer-first for the AP, President and Data Analyst, phone-first for DLs and ZLs.

    A Data Analyst by additional role only counts as a Data Analyst here when Call-ins opens on the mission for them
    (main role Missionary, Office or STL). A DL or ZL who is also Data Analyst keeps the phone layout of their home.
    """
    return 'desktop' if main in roles.MANAGER_ROLES or home_level == 'mission' else 'phone'


def may_open(v, chain, level):
    """May this viewer open this scope? chain holds mission_id, zone_id, district_id of the scope."""
    if v['manager'] and chain.get('mission_id') == v['mission_id']:
        return True
    if level == 'mission':
        return False
    if v['zone_id'] and chain.get('zone_id') == v['zone_id']:
        return True
    return bool(v['district_id'] and level in ('district', 'area') and chain.get('district_id') == v['district_id'])


def may_write_dl(v, chain):
    """DL notes, area updates, Complete / Reopen of the district in chain."""
    return bool((v['manager'] and chain.get('mission_id') == v['mission_id'])
                or (v['district_id'] and chain.get('district_id') == v['district_id']))


def may_write_zl(v, chain):
    """ZL notes of the districts in chain's zone, and that zone's notes (also who may read them)."""
    return bool((v['manager'] and chain.get('mission_id') == v['mission_id'])
                or (v['zone_id'] and chain.get('zone_id') == v['zone_id']))


# ---------------------------------------------------------------- database helpers

def call(conn, sql, args=(), refused=OUTSIDE):
    """Run a Call-ins query as the user and turn database refusals into plain HTTP answers."""
    try:
        return fetch_rows(conn, sql, args)
    except psycopg2.extensions.QueryCanceledError:
        abort(503, SLOW)
    except psycopg2.Error as error:
        code = getattr(error, 'pgcode', None)
        message = str(getattr(getattr(error, 'diag', None), 'message_primary', '') or error)
        if code == '42501' or (code == 'P0001' and 'permission' in message.lower()):
            abort(403, refused)
        if code == '55000':
            abort(409, LOCKED)
        raise


def parse_week(value):
    """The ?week= / body week as a date, or None when not given. Anything else is a 400, not a 500."""
    if value is None or value == '':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        abort(400, BAD_WEEK)
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        abort(400, BAD_WEEK)


def parse_scope(args, v):
    """(level, id) asked for with ?level=&id=; without them the viewer's home. 400 for anything else."""
    level = args.get('level') or None
    raw_id = args.get('id')
    if level is None and raw_id in (None, ''):
        return v['home']['level'], v['home']['id']
    if level not in LEVELS:
        abort(400, 'Choose a mission, zone, district or area.')
    try:
        scope_id = int(raw_id)
    except (TypeError, ValueError):
        abort(400, 'Choose a mission, zone, district or area.')
    if scope_id <= 0:
        abort(400, 'Choose a mission, zone, district or area.')
    return level, scope_id


def weeks_for(conn, requested):
    """(week, weeks): the last 12 reporting weeks up to the current one, and the one asked for or the latest."""
    # The row for the current Sunday is created when a companionship first opens planning, so it can be
    # missing early in the week. Without ?week= show the latest week that exists instead of failing.
    weeks = fetch_rows(conn, '''SELECT id,sunday FROM public.reporting_weeks
      WHERE sunday<=public.current_reporting_sunday() ORDER BY sunday DESC LIMIT 12''')
    week = fetch_rows(conn, '''SELECT id,sunday FROM public.reporting_weeks
      WHERE sunday=%s AND sunday<=public.current_reporting_sunday()''', (requested,)) if requested else weeks[:1]
    if not week:
        abort(404, 'That reporting week is unavailable.' if requested else 'No reporting weeks are available yet.')
    return week[0], weeks


def write_week(conn, payload):
    """The reporting week a save is for (the body's "week"); it must exist and not be in the future."""
    requested = parse_week(payload.get('week'))
    if not requested:
        abort(400, 'Choose the reporting week you are saving for.')
    week = fetch_rows(conn, '''SELECT id,sunday FROM public.reporting_weeks
      WHERE sunday=%s AND sunday<=public.current_reporting_sunday()''', (requested,))
    if not week:
        abort(404, 'That reporting week is unavailable.')
    return week[0]


CHAIN_SQL = {
    'mission': '''SELECT m.id AS mission_id, m.name AS mission_name FROM public.missions m WHERE m.id=%s''',
    'zone': '''SELECT z.id AS zone_id, z.name AS zone_name, z.mission_id, m.name AS mission_name
        FROM public.zones z JOIN public.missions m ON m.id=z.mission_id WHERE z.id=%s''',
    'district': '''SELECT d.id AS district_id, d.name AS district_name, z.id AS zone_id, z.name AS zone_name,
        z.mission_id, m.name AS mission_name FROM public.districts d JOIN public.zones z ON z.id=d.zone_id
        JOIN public.missions m ON m.id=z.mission_id WHERE d.id=%s''',
    'area': '''SELECT a.id AS area_id, a.name AS area_name, d.id AS district_id, d.name AS district_name,
        z.id AS zone_id, z.name AS zone_name, z.mission_id, m.name AS mission_name FROM public.areas a
        JOIN public.districts d ON d.id=a.district_id JOIN public.zones z ON z.id=d.zone_id
        JOIN public.missions m ON m.id=z.mission_id WHERE a.id=%s''',
}


def chain_for(conn, level, scope_id):
    """The ids and names of a scope and everything above it (its district, zone and mission); 404 if not found."""
    found = fetch_rows(conn, CHAIN_SQL[level], (scope_id,))
    if not found:
        abort(404, 'That part of the mission was not found.')
    return found[0]


def breadcrumb(v, chain, level):
    """Mission > Zone > District > Area down to this scope, each step marked with whether the viewer may open it."""
    crumbs = []
    for step in LEVELS[:LEVELS.index(level) + 1]:
        step_chain = {key: chain.get(key) for key in ('mission_id', 'zone_id', 'district_id')
                      if LEVELS.index(key[:-3]) <= LEVELS.index(step)}
        crumbs.append({'level': step, 'id': chain.get(step + '_id'), 'name': chain.get(step + '_name'),
                       'allowed': may_open(v, step_chain, step)})
    return crumbs


def statement_limit(conn):
    """Stop any query of this request that runs longer than CALLINS_STATEMENT_TIMEOUT (see there)."""
    fetch_rows(conn, "SELECT set_config('statement_timeout',%s,true)", (CALLINS_STATEMENT_TIMEOUT,))


def open_scope(conn, v, level, scope_id, requested):
    """(week, weeks, chain) for a scope the viewer may open (403 otherwise). From here on, slow queries are stopped."""
    week, weeks = weeks_for(conn, requested)
    chain = chain_for(conn, level, scope_id)
    if not may_open(v, chain, level):
        abort(403, OUTSIDE)
    statement_limit(conn)
    return week, weeks, chain


# ---------------------------------------------------------------- shaping the answer

def metrics_of(item):
    """The seven numbers of one row: the goal set last week, the result and the new goal of each."""
    result = {}
    for key, _ in METRICS:
        result[key] = {'previous_goal': None if key == 'follow_up_lessons' else item.get(key + '_previous_goal'),
                       'actual': item.get(key + '_actual'), 'goal': item.get(key + '_goal')}
    return result


def add_up(children):
    """The totals of the rows shown (a number nobody has stays None)."""
    totals = {key: {'previous_goal': None, 'actual': None, 'goal': None} for key, _ in METRICS}
    for child in children:
        for key, values in child['metrics'].items():
            for part, value in values.items():
                if value is not None:
                    totals[key][part] = (totals[key][part] or 0) + value
    return totals


def missionaries_of(item):
    """Only what the page shows about the missionaries of an area."""
    people = item.get('missionaries') or []
    return [{'name': m.get('display_name'), 'position': m.get('roster_position_abbr')}
            for m in people if isinstance(m, dict)]


def plans_of(item):
    """The six action plans of an area (the text of all its wards' and branches' plans together)."""
    return {key: item.get(key + '_plan') for key in PLAN_KEYS}


def zone_child(v, item):
    """One zone row of the mission page (zone notes only for its ZLs and managers)."""
    chain = {'mission_id': item.get('mission_id'), 'zone_id': item.get('zone_id')}
    return {'level': 'zone', 'id': item.get('zone_id'), 'name': item.get('zone_name'),
            'allowed': may_open(v, chain, 'zone'), 'metrics': metrics_of(item),
            'status': {'district_count': item.get('district_count'),
                       'completed_district_count': item.get('completed_district_count'),
                       'all_dl_call_ins_complete': item.get('all_dl_call_ins_complete'),
                       'all_reports_submitted': item.get('all_weekly_reports_submitted'),
                       'area_count': item.get('area_count')},
            'notes': {'zone_notes': item.get('zone_notes')} if may_write_zl(v, chain) else {},
            'planning_details': item.get('planning_details') or []}


def district_child(v, item, chain, updates):
    """One district row of a zone page: numbers, call-in status, DL and ZL notes (for who may read them) and
    area updates."""
    child_chain = dict(chain, district_id=item.get('district_id'))
    notes = {}
    if may_write_dl(v, child_chain) or may_write_zl(v, child_chain):
        notes['dl_notes'] = item.get('dl_notes')
    if may_write_zl(v, child_chain):
        notes['zl_notes'] = item.get('zl_notes')
    return {'level': 'district', 'id': item.get('district_id'), 'name': item.get('district_name'),
            'allowed': may_open(v, child_chain, 'district'), 'metrics': metrics_of(item),
            'status': {'dl_call_in_complete': bool(item.get('dl_call_in_complete')),
                       'dl_completed_at': item.get('dl_completed_at'),
                       'all_reports_submitted': item.get('all_weekly_reports_submitted'),
                       'area_count': item.get('area_count')},
            'notes': notes,
            'can': {'zl_notes': may_write_zl(v, child_chain)},
            'area_updates': updates.get(item.get('district_id'), []),
            'planning_details': item.get('planning_details') or []}


def area_child(v, item, chain):
    """One area row of a district page: numbers, plans, missionaries and the DL's area update."""
    child_chain = dict(chain, area_id=item.get('area_id'))
    return {'level': 'area', 'id': item.get('area_id'), 'name': item.get('area_name'),
            'allowed': may_open(v, child_chain, 'area'), 'metrics': metrics_of(item),
            'status': {'report_count': item.get('report_count'),
                       'all_reports_submitted': item.get('all_reports_submitted')},
            'missionaries': missionaries_of(item), 'area_update': item.get('dl_update'),
            'plans': plans_of(item), 'planning_details': item.get('planning_details') or []}


def mission_bundle(conn, v, chain, week):
    """The mission page: one row per zone."""
    items = call(conn, 'SELECT public.get_mission_call_in_summary_with_planning(%s,%s) AS data',
                 (chain['mission_id'], week['id']))[0]['data'] or []
    children = [zone_child(v, item) for item in items]
    status = {'district_count': sum(c['status']['district_count'] or 0 for c in children),
              'completed_district_count': sum(c['status']['completed_district_count'] or 0 for c in children),
              'zones_with_all_reports': sum(1 for c in children if c['status']['all_reports_submitted']),
              'zone_count': len(children)}
    return {'children': children, 'status': status, 'notes': {}, 'can': {}}


def zone_bundle(conn, v, chain, week):
    """A zone page: one row per district, with each district's area updates, and the zone notes."""
    items = call(conn, 'SELECT public.get_zl_call_in_summary_with_planning(%s,%s) AS data',
                 (chain['zone_id'], week['id']))[0]['data'] or []
    updates = {}
    for row in call(conn, '''SELECT district_id, area_id, area_name, missionaries, dl_update
                             FROM public.get_zl_call_in_area_updates(%s,%s) ORDER BY district_name, area_name''',
                    (chain['zone_id'], week['id'])):
        updates.setdefault(row['district_id'], []).append(
            {'area_id': row['area_id'], 'area_name': row['area_name'], 'missionaries': missionaries_of(row),
             'text': row['dl_update']})
    notes, can = {}, {'zone_notes': may_write_zl(v, chain), 'zl_notes': may_write_zl(v, chain)}
    if can['zone_notes']:
        found = call(conn, 'SELECT zone_notes FROM public.get_zl_call_in_zone_notes(%s,%s)', (chain['zone_id'], week['id']))
        notes['zone_notes'] = found[0]['zone_notes'] if found else None
    children = [district_child(v, item, chain, updates) for item in items]
    status = {'district_count': len(children),
              'completed_district_count': sum(1 for c in children if c['status']['dl_call_in_complete']),
              'all_reports_submitted': bool(children) and all(c['status']['all_reports_submitted'] for c in children)}
    return {'children': children, 'status': status, 'notes': notes, 'can': can}


def district_record(conn, district_id, week_id):
    """This week's call_in_districts row (read as the user, under row-level security), without thank_you."""
    found = fetch_rows(conn, '''SELECT dl_notes, zl_notes, dl_completed_at, updated_at FROM public.call_in_districts
                           WHERE district_id=%s AND reporting_week_id=%s''', (district_id, week_id))
    return found[0] if found else {}


def district_bundle(conn, v, chain, week, area_id=None):
    """A district page (one row per area, DL and ZL notes, Complete / Reopen), or with area_id one area of it."""
    items = call(conn, 'SELECT public.get_dl_call_in_summary_with_planning(%s,%s) AS data',
                 (chain['district_id'], week['id']))[0]['data'] or []
    record = district_record(conn, chain['district_id'], week['id'])
    completed = record.get('dl_completed_at')
    dl, zl = may_write_dl(v, chain), may_write_zl(v, chain)
    can = {'dl_notes': dl and not completed, 'area_updates': dl and not completed,
           'complete': dl and not completed, 'reopen': dl and bool(completed), 'zl_notes': zl}
    notes = {}
    if dl or zl:
        notes['dl_notes'] = record.get('dl_notes')
    if zl:
        notes['zl_notes'] = record.get('zl_notes')
    children = [area_child(v, item, chain) for item in items]
    status = {'dl_call_in_complete': bool(completed), 'dl_completed_at': completed,
              'area_count': len(children), 'report_count': sum(c['status']['report_count'] or 0 for c in children),
              'all_reports_submitted': bool(children) and all(c['status']['all_reports_submitted'] for c in children)}
    if area_id is None:
        return {'children': children, 'status': status, 'notes': notes, 'can': can}
    detail = next((c for c in children if c['id'] == area_id), None)
    if detail is None:  # an inactive area has no summary row
        abort(404, 'This area has no call-in for that week.')
    area_status = dict(detail['status'], dl_call_in_complete=bool(completed), dl_completed_at=completed)
    # Complete / Reopen stay on the district page; the flags tell the area page whether this viewer could.
    area_can = {'area_updates': can['area_updates'], 'complete': can['complete'], 'reopen': can['reopen'],
                'dl_notes': False, 'zl_notes': False}
    return {'children': [], 'detail': detail, 'status': area_status, 'notes': {}, 'can': area_can}


# ---------------------------------------------------------------- routes

@callins_bp.get('/api/callins')
def callins_bundle():
    """One Call-ins page: a scope (?level=&id=, default the viewer's home) for one week (?week=, default the latest)."""
    c = g.context
    v = viewer(c)
    level, scope_id = parse_scope(request.args, v)
    requested = parse_week(request.args.get('week'))
    with _app().user_db() as conn:
        week, weeks, chain = open_scope(conn, v, level, scope_id, requested)
        if level == 'mission':
            bundle = mission_bundle(conn, v, chain, week)
        elif level == 'zone':
            bundle = zone_bundle(conn, v, chain, week)
        else:
            bundle = district_bundle(conn, v, chain, week, scope_id if level == 'area' else None)
        current = fetch_rows(conn, 'SELECT public.current_reporting_sunday() AS sunday')[0]['sunday']
    detail = bundle.get('detail')
    totals = detail['metrics'] if detail else add_up(bundle['children'])
    scope = {'level': level, 'id': scope_id, 'name': chain.get(level + '_name'), 'child_level': CHILD_LEVEL[level],
             'breadcrumb': breadcrumb(v, chain, level),
             'mission_id': chain.get('mission_id'), 'zone_id': chain.get('zone_id'),
             'district_id': chain.get('district_id'), 'area_id': chain.get('area_id')}
    # ISO dates (YYYY-MM-DD) so the page can label weeks and send them back unchanged. current_sunday tells the
    # page when the week shown is older than the current reporting week.
    return jsonify(json_ready({
        'role': v['main'], 'roles': roles.roles(c), 'roles_label': roles.describe(c), 'layout': v['layout'],
        'home': v['home'], 'week': week, 'weeks': [{'sunday': w['sunday']} for w in weeks], 'current_sunday': current,
        'scope': scope, 'metrics': [{'key': key, 'label': label} for key, label in METRICS],
        'can': bundle['can'], 'totals': totals, 'status': bundle['status'], 'notes': bundle['notes'],
        'children': bundle['children'], 'detail': detail}))


@callins_bp.get('/api/callins/people')
def callins_people():
    """Baptismal-date friends, new members and high potentials of the scope (the People tab, loaded when opened)."""
    v = viewer(g.context)
    level, scope_id = parse_scope(request.args, v)
    requested = parse_week(request.args.get('week'))
    with _app().user_db() as conn:
        week, _, _ = open_scope(conn, v, level, scope_id, requested)
        data = call(conn, 'SELECT public.get_call_in_people(%s,%s,%s) AS data', (level, scope_id, week['id']))[0]['data']
    return jsonify(json_ready(dict(data or {}, week=week)))


@callins_bp.get('/api/callins/gemiko')
def callins_gemiko():
    """Ward coordination (GEMIKO) of a district or one area for the week, loaded when first opened."""
    v = viewer(g.context)
    level, scope_id = parse_scope(request.args, v)
    if level not in ('district', 'area'):
        abort(400, 'GEMIKO is shown for a district or an area.')
    requested = parse_week(request.args.get('week'))
    with _app().user_db() as conn:
        week, _, chain = open_scope(conn, v, level, scope_id, requested)
        found = call(conn, '''SELECT area_id, area_name, unit_id, unit_name, ward_coordination_held,
                                     ward_coordination_attendance
                              FROM public.get_dl_call_in_ward_coordination(%s,%s)''', (chain['district_id'], week['id']))
    if level == 'area':
        found = [row for row in found if row['area_id'] == scope_id]
    units = [{'area_id': row['area_id'], 'area_name': row['area_name'], 'unit_id': row['unit_id'],
              'unit_name': row['unit_name'], 'held': row['ward_coordination_held'],
              'attendance': row['ward_coordination_attendance']} for row in found]
    return jsonify(json_ready({'level': level, 'id': scope_id, 'week': week, 'units': units}))


def _payload():
    """The request body; 400 unless it is a JSON object."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, 'Send the call-in as a JSON object.')
    return payload


def _note(payload, key, label):
    """A note from the body: text of at most NOTE_LIMIT characters, trimmed; None when empty."""
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        abort(400, f'{label} must be text.')
    value = (value or '').strip()
    if len(value) > NOTE_LIMIT:
        abort(400, f'{label} must be 12,000 characters or fewer.')
    return value or None


def _write(level, scope_id, rule, refused, action):
    """Shared steps of every save: stewardship, week, then the database function as the user."""
    v = viewer(g.context)
    payload = _payload()
    with _app().user_db() as conn:
        chain = chain_for(conn, level, scope_id)
        if not rule(v, chain):
            abort(403, refused)
        week = write_week(conn, payload)
        saved = action(conn, chain, week, payload)
    return jsonify(json_ready({'ok': True, 'week': week, 'saved': saved}))


@callins_bp.put('/api/callins/districts/<int:district_id>/dl-notes')
def save_dl_notes(district_id):
    """Save a district's DL notes for the week (its DL and managers; not after Complete)."""
    refused = 'Only the district leader of this district or a mission leader can save its DL notes.'

    def action(conn, chain, week, payload):
        notes = _note(payload, 'dl_notes', 'DL notes')
        call(conn, 'SELECT public.save_dl_call_in_notes(%s,%s,%s,NULL)', (district_id, week['id'], notes), refused)
        record = district_record(conn, district_id, week['id'])
        return {'district_id': district_id, 'dl_notes': record.get('dl_notes'), 'updated_at': record.get('updated_at')}
    return _write('district', district_id, may_write_dl, refused, action)


@callins_bp.put('/api/callins/districts/<int:district_id>/zl-notes')
def save_zl_notes(district_id):
    """Save the ZL notes about one district for the week (the zone leaders and managers)."""
    refused = "Only the zone leaders of this district's zone or a mission leader can save its ZL notes."

    def action(conn, chain, week, payload):
        notes = _note(payload, 'zl_notes', 'ZL notes')
        call(conn, 'SELECT public.save_zl_call_in_notes(%s,%s,%s)', (district_id, week['id'], notes), refused)
        record = district_record(conn, district_id, week['id'])
        return {'district_id': district_id, 'zl_notes': record.get('zl_notes'), 'updated_at': record.get('updated_at')}
    return _write('district', district_id, may_write_zl, refused, action)


@callins_bp.put('/api/callins/zones/<int:zone_id>')
def save_zone_notes(zone_id):
    """Save a zone's own notes for the week (its zone leaders and managers)."""
    refused = 'Only the zone leaders of this zone or a mission leader can save its zone notes.'

    def action(conn, chain, week, payload):
        notes = _note(payload, 'zone_notes', 'Zone notes')
        call(conn, 'SELECT public.save_zl_zone_call_in_notes(%s,%s,%s)', (zone_id, week['id'], notes), refused)
        found = call(conn, '''SELECT z.zone_notes, c.updated_at FROM public.get_zl_call_in_zone_notes(%s,%s) z
                              LEFT JOIN public.call_in_zones c ON c.zone_id=z.zone_id AND c.reporting_week_id=z.reporting_week_id''',
                     (zone_id, week['id']), refused)
        return {'zone_id': zone_id, 'zone_notes': found[0]['zone_notes'] if found else notes,
                'updated_at': found[0]['updated_at'] if found else None}
    return _write('zone', zone_id, may_write_zl, refused, action)


@callins_bp.put('/api/callins/areas/<int:area_id>/update')
def save_area_update(area_id):
    """Save the DL's update about one area for the week (the area's DL and managers; not after Complete)."""
    refused = 'Only the district leader of this area or a mission leader can save its area update.'

    def action(conn, chain, week, payload):
        text = _note(payload, 'update_text', 'The area update')
        call(conn, 'SELECT public.save_call_in_area_update(%s,%s,%s,%s)',
             (chain['district_id'], week['id'], area_id, text), refused)
        found = fetch_rows(conn, '''SELECT u.update_text, u.updated_at FROM public.call_in_area_updates u
            JOIN public.call_in_districts d ON d.id=u.district_call_in_id
            WHERE d.district_id=%s AND d.reporting_week_id=%s AND u.area_id=%s''', (chain['district_id'], week['id'], area_id))
        return {'area_id': area_id, 'update_text': found[0]['update_text'] if found else text,
                'updated_at': found[0]['updated_at'] if found else None}
    return _write('area', area_id, may_write_dl, refused, action)


@callins_bp.post('/api/callins/districts/<int:district_id>/<action_name>')
def complete_or_reopen(district_id, action_name):
    """Mark a district's call-in complete (locks its DL notes and area updates), or reopen it."""
    if action_name not in ('complete', 'reopen'):
        abort(404)
    refused = 'Only the district leader of this district or a mission leader can complete or reopen its call-in.'
    function = 'complete_dl_call_in' if action_name == 'complete' else 'reopen_dl_call_in'

    def action(conn, chain, week, payload):
        call(conn, f'SELECT public.{function}(%s,%s)', (district_id, week['id']), refused)
        record = district_record(conn, district_id, week['id'])
        return {'district_id': district_id, 'dl_call_in_complete': bool(record.get('dl_completed_at')),
                'dl_completed_at': record.get('dl_completed_at'), 'updated_at': record.get('updated_at')}
    return _write('district', district_id, may_write_dl, refused, action)
