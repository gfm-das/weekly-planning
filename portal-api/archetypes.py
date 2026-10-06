"""Archetypal Health: which parts of the missionary work each area is strong or weak in, compared with similar areas.

What it is: the /api/archetypes routes. They decide who sees what, load the numbers, and save settings and notes.
The calculation itself is in archetype_model.py (no Flask, no database there).
Who uses it: portal/archetypes.html (the zone overview, Go deeper, diagnoses, notes) and
portal/archetype-settings.html (weights, KPIs, peer groups, bands; managers only).
How it fits: the numbers come from the dashboards views of migration 034; settings and notes live in their own
tables, closed to every API role, so only this code reaches them.

Who sees what (checked here on every request; roles.archetype_scope decides):
- Managers (AP, President, Data Analyst, also as an additional role): the whole mission and the settings.
- Everyone else, including ZLs, STLs and DLs: nothing (403).

Leader notes (one per person, area and week): read and written by managers.

Endpoints (all under the portal sign-in, like every /api/ route):
  GET  /api/archetypes?week=YYYY-MM-DD&weeks=1|4|8|12   the page: zones, districts, areas, trends, notes
  PUT  /api/archetypes/notes {area_id, week, body}       save (or with an empty body remove) your own note
  GET  /api/archetypes/settings                           managers: settings, defaults, numbers to choose, history
  PUT  /api/archetypes/settings {settings, version}      managers: save (checked; version stops two saves at once)
  POST /api/archetypes/settings/restore {version}        managers: restore the sheet's defaults

The numbers are read as gfm_dashboard_reader in a READ ONLY transaction (helpers.dashboard_reader, like charts.py).
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, g, jsonify, request
from psycopg2.extras import Json

import archetype_model as model
import mission_time
import roles
from helpers import dashboard_reader

archetypes_bp = Blueprint('archetypes', __name__)

MISSION_TZ = mission_time.ZONE
STATEMENT_TIMEOUT = '10s'
NOTE_LIMIT = 4000
HISTORY_SHOWN = 50
WEEKS_OFFERED = 26

NOT_FOR_YOU = 'Only the assistants, the President and Data Analysts can open Archetypal Health.'
OUTSIDE = 'This is outside your stewardship, so it cannot be opened.'
MANAGERS_ONLY = 'Only the assistants, the President and Data Analysts can change these settings.'
CHANGED = 'Someone changed the settings since you opened the page. Reload the page and try again.'
BAD_WEEK = 'Choose one of the weeks offered.'
BAD_AVERAGE = 'Choose 1, 4, 8 or 12 weeks.'
NO_NOTE = 'Choose an area and write a note.'
NOTE_TOO_LONG = 'A note can have up to 4000 characters.'  # NOTE_LIMIT
RELOAD = 'Reload the page and try again.'


def _app():
    import app  # imported here: app.py registers this blueprint while it is still loading
    return app


def rows(conn, sql, args=()):
    """app.rows: the rows of a query on an app.db() connection."""
    return _app().rows(conn, sql, args)


def today():
    """Today in the mission (its time zone): a week is complete once its Sunday is over there."""
    return datetime.now(MISSION_TZ).date()


# ---------------------------------------------------------------------------------------------------- who is asking

def viewer(c):
    """The viewer's stewardship for this page, or 403."""
    scope = roles.archetype_scope(c)
    zone_id = (c.get('leadership_zone_id') or c.get('zone_id')) if scope == 'zone' else None
    district_id = (c.get('leadership_district_id') or c.get('district_id')) if scope == 'district' else None
    if scope is None or (scope == 'zone' and not zone_id) or (scope == 'district' and not district_id):
        abort(403, NOT_FOR_YOU)
    return {'scope': scope, 'mission_id': c['mission_id'], 'zone_id': zone_id, 'district_id': district_id,
            'settings': roles.is_manager(c)}


def in_scope(v, unit):
    """Is this area, district or zone (a dict with mission_id, zone_id and district_id) inside the stewardship?"""
    if unit.get('mission_id') != v['mission_id']:
        return False
    if v['scope'] == 'zone':
        return unit.get('zone_id') == v['zone_id']
    if v['scope'] == 'district':
        return unit.get('district_id') == v['district_id']
    return True


def require_manager(c):
    """403 unless c is a manager (only they change the settings)."""
    if not roles.is_manager(c):
        abort(403, MANAGERS_ONLY)


# ---------------------------------------------------------------------------------------------------- loading

def load_settings(conn, mission_id):
    """(settings, version, updated_at, updated_by_name). No saved row: the sheet's defaults, version 0."""
    found = rows(conn, '''SELECT settings, version, updated_at, updated_by_name FROM public.archetype_settings
                          WHERE mission_id=%s''', (mission_id,))
    if not found:
        return model.defaults(), 0, None, None
    row = found[0]
    return row['settings'], row['version'], row['updated_at'], row['updated_by_name']


def load_numbers(conn, mission_id):
    """(area-week rows, {area_id: attributes}) of the whole mission, read as gfm_dashboard_reader."""
    with dashboard_reader(conn, STATEMENT_TIMEOUT) as cur:
        cur.execute('SELECT * FROM dashboards.archetype_area_week WHERE mission_id=%s ORDER BY sunday, area_id',
                    (mission_id,))
        numbers = [dict(r) for r in cur.fetchall()]
        cur.execute('SELECT * FROM dashboards.archetype_area_profile WHERE mission_id=%s', (mission_id,))
        attributes = {r['area_id']: dict(r) for r in cur.fetchall()}
    return numbers, attributes


def chosen_week(value, counts, weeks):
    """The week asked for (it must be a complete week with plans), else the default week."""
    if not value:
        return model.default_week(counts, weeks)
    try:
        week = date.fromisoformat(value)
    except ValueError:
        abort(400, BAD_WEEK)
    if week not in weeks:
        abort(400, BAD_WEEK)
    return week


def chosen_average(value, settings):
    """Weeks to average: the one asked for (1, 4, 8 or 12), else the setting."""
    if value in (None, ''):
        return settings['weeks_to_average']
    if not value.isdigit() or int(value) not in model.WEEK_CHOICES:
        abort(400, BAD_AVERAGE)
    return int(value)


# ---------------------------------------------------------------------------------------------------- the page

def rounded(value, digits=1):
    """value rounded for the page; None stays None."""
    return None if value is None else round(value, digits)


def unit_view(result):
    """What the page needs of a scored unit: indices, overall, label."""
    return {'indices': {a: rounded(v) for a, v in result['indices'].items()}, 'overall': rounded(result['overall']),
            'label': result['label']}


def areas_in_scope(v, numbers):
    """{area_id: newest row} for the areas of the viewer's stewardship. The newest row says where an area belongs
    now (its district and zone), so a leader sees today's stewardship also in older weeks."""
    latest = {}
    for row in numbers:  # ordered by week, so later rows replace earlier ones
        latest[row['area_id']] = row
    return {area_id: row for area_id, row in latest.items() if in_scope(v, row)}


def week_counts_for(v, numbers, mine, counts):
    """{sunday: number of areas with a plan} as the viewer may see it: the whole mission for managers, only the areas
    of their zone or district for a ZL, STL or DL (the mission's counts stay on the server; they only pick the
    default week)."""
    if v['scope'] == 'mission':
        return counts
    return model.week_list(row for row in numbers if row['area_id'] in mine)


def trend_weeks(week, weeks):
    """The complete weeks of the mini trend: up to TREND_WEEKS weeks ending with the week shown, oldest first."""
    return sorted(w for w in weeks if w <= week)[-model.TREND_WEEKS:]


def trend_for(area_ids, scored, threshold):
    """[{week, overall}] of a unit: the average of its areas' overall index, week by week."""
    return [{'week': week.isoformat(), 'overall': rounded(model.roll_up(result['areas'], area_ids, threshold)['overall'])}
            for week, result in scored.items()]


def area_view(area_id, where, result, settings, available):
    """One area row: its indices, label, diagnosis, and the numbers behind them (missing ones named)."""
    used = [k for k in model.used_kpis(settings) if k in available]
    view = unit_view(result)
    view.update(id=area_id, name=where['area'], zone_id=where['zone_id'], district_id=where['district_id'],
                peer_group=result['peer_group'], diagnosis=model.diagnosis(result, settings),
                missing=[k for k in used if result['values'].get(k) is None],
                values={k: rounded(result['values'].get(k), 2) for k in used})
    return view


def group_view(kind, unit_id, name, area_ids, scored, week, threshold):
    """A zone, district or mission row: the average of its areas this week, with a mini trend."""
    rolled = model.roll_up(scored[week]['areas'], area_ids, threshold)
    view = unit_view(rolled)
    view.update(id=unit_id, name=name, kind=kind, areas_scored=rolled['areas_scored'],
                trend=trend_for(area_ids, scored, threshold))
    return view


def grouped(mine, key):
    """{district_id or zone_id: [area ids]}."""
    groups = {}
    for area_id, row in mine.items():
        groups.setdefault(row[key], []).append(area_id)
    return groups


def notes_for(conn, area_ids, week, user_id):
    """The leader notes of these areas for the week, oldest first; your own note is marked editable."""
    if not area_ids:
        return {}
    found = rows(conn, '''SELECT id, area_id, author_id, author_name, author_role, body, updated_at
                          FROM public.archetype_notes WHERE sunday=%s AND area_id = ANY(%s)
                          ORDER BY updated_at''', (week, list(area_ids)))
    notes = {}
    for note in found:
        notes.setdefault(note['area_id'], []).append({
            'id': note['id'], 'author': note['author_name'], 'role': note['author_role'], 'body': note['body'],
            'updated_at': note['updated_at'].isoformat(), 'mine': str(note['author_id']) == str(user_id)})
    return notes


def build_page(conn, c, week_value, average_value):
    """Everything the Archetypal Health page shows for one week: the rows of the viewer's stewardship only."""
    v = viewer(c)
    settings, version, _, _ = load_settings(conn, v['mission_id'])
    numbers, attributes = load_numbers(conn, v['mission_id'])
    counts = model.week_list(numbers)
    weeks = model.complete_weeks(counts, today())
    week = chosen_week(week_value, counts, weeks)
    average = chosen_average(average_value, settings)
    mine = areas_in_scope(v, numbers)
    base = page_basics(v, settings, version, weeks, average, week_counts_for(v, numbers, mine, counts))
    if week is None:
        return dict(base, week=None, zones=[], districts=[], areas=[], skipped=[], mission=None)

    # The week shown and the weeks of the mini trends, each scored for the whole mission.
    scored = {w: model.score_week(numbers, attributes, settings, w, average) for w in trend_weeks(week, weeks)}
    shown = scored[week]
    return dict(base, week=week.isoformat(), skipped=shown['skipped'],
                areas=area_rows(conn, c, mine, shown, settings, week),
                **group_rows(v, c, mine, scored, week, settings['balance_threshold']),
                home={'scope': v['scope'], 'zone_id': v['zone_id'], 'district_id': v['district_id']})


def page_basics(v, settings, version, weeks, average, week_counts):
    """What the page shows for any week: who is looking, the bands, the week list and the labels of the numbers."""
    return {'viewer': {'scope': v['scope'], 'settings': v['settings']}, 'bands': settings['bands'],
            'weeks_choices': list(model.WEEK_CHOICES), 'weeks_to_average': average,
            'weeks': [{'week': w.isoformat(), 'areas': week_counts.get(w, 0)} for w in weeks[:WEEKS_OFFERED]],
            'newest_week': weeks[0].isoformat() if weeks else None, 'settings_version': version,
            'kpi_labels': {key: label for key, (label, _) in model.SOURCES.items()}}


def area_rows(conn, c, mine, shown, settings, week):
    """One row per area of the stewardship that has a score this week, each with its leader notes."""
    available = set(model.used_kpis(settings)) - set(shown['skipped'])
    notes = notes_for(conn, [a for a in mine if a in shown['areas']], week, c['user_id'])
    areas = []
    for area_id, where in mine.items():
        if area_id in shown['areas']:
            view = area_view(area_id, where, shown['areas'][area_id], settings, available)
            areas.append(dict(view, notes=notes.get(area_id, [])))
    return areas


def group_rows(v, c, mine, scored, week, threshold):
    """{'districts', 'zones', 'mission'}: the summary rows above the areas (only those with a scored area)."""
    districts = [dict(group_view('district', d, mine[ids[0]]['district'], ids, scored, week, threshold),
                      zone_id=mine[ids[0]]['zone_id']) for d, ids in grouped(mine, 'district_id').items()]
    zones = []
    if v['scope'] != 'district':  # a DL sees only part of the zone, so a row named after the zone would mislead
        zones = [group_view('zone', z, mine[ids[0]]['zone'], ids, scored, week, threshold)
                 for z, ids in grouped(mine, 'zone_id').items()]
    mission = None
    if v['scope'] == 'mission':
        mission = group_view('mission', v['mission_id'], c.get('mission') or '', list(mine), scored, week, threshold)
    return {'districts': [d for d in districts if d['areas_scored']], 'zones': [z for z in zones if z['areas_scored']],
            'mission': mission}


@archetypes_bp.get('/api/archetypes')
def archetypes_page():
    """The page for one week (?week=) averaged over ?weeks= weeks."""
    with _app().db() as conn:
        return jsonify(build_page(conn, g.context, request.args.get('week'), request.args.get('weeks')))


# ---------------------------------------------------------------------------------------------------- notes

def area_chain(conn, area_id):
    """mission_id, zone_id and district_id of an area (None if there is no such area)."""
    found = rows(conn, '''SELECT z.mission_id, d.zone_id, a.district_id FROM public.areas a
                          JOIN public.districts d ON d.id = a.district_id JOIN public.zones z ON z.id = d.zone_id
                          WHERE a.id=%s''', (area_id,))
    return found[0] if found else None


def note_request(body):
    """(area_id, week, text) of a note save; 400 unless the week is a past Sunday and the note fits NOTE_LIMIT."""
    area_id, text = body.get('area_id'), body.get('body')
    try:
        week = date.fromisoformat(str(body.get('week')))
    except ValueError:
        abort(400, BAD_WEEK)
    if not isinstance(area_id, int) or isinstance(area_id, bool) or not isinstance(text, str):
        abort(400, NO_NOTE)
    if week.isoweekday() != 7 or week >= today():
        abort(400, BAD_WEEK)
    if len(text.strip()) > NOTE_LIMIT:
        abort(400, NOTE_TOO_LONG)
    return area_id, week, text


@archetypes_bp.put('/api/archetypes/notes')
def save_note():
    """Save your own note on an area for a week; an empty note removes it."""
    c = g.context
    v = viewer(c)
    area_id, week, text = note_request(request.get_json(silent=True) or {})
    with _app().db() as conn:
        chain = area_chain(conn, area_id)
        if not chain or not in_scope(v, chain):
            abort(403, OUTSIDE)
        if not text.strip():
            rows(conn, 'DELETE FROM public.archetype_notes WHERE area_id=%s AND sunday=%s AND author_id=%s',
                 (area_id, week, c['user_id']))
            return jsonify(saved=False, removed=True)
        saved = rows(conn, '''INSERT INTO public.archetype_notes (area_id, sunday, author_id, author_name, author_role, body)
                              VALUES (%s, %s, %s, %s, %s, %s)
                              ON CONFLICT (area_id, sunday, author_id) DO UPDATE
                              SET body = EXCLUDED.body, author_name = EXCLUDED.author_name,
                                  author_role = EXCLUDED.author_role, updated_at = now()
                              RETURNING id, updated_at''',
                     (area_id, week, c['user_id'], c.get('display_name'), roles.describe(c), text.strip()))
        return jsonify(saved=True, id=saved[0]['id'], updated_at=saved[0]['updated_at'].isoformat())


# ---------------------------------------------------------------------------------------------------- settings

def extra_attributes(attributes):
    """The names of the free area attributes typed in DA Management (for the peer-group choice)."""
    return sorted({name for area in attributes.values() for name in (area.get('extra') or {})})


def history(conn, mission_id):
    """The latest settings changes, newest first (the Change history on the settings page)."""
    found = rows(conn, '''SELECT version, action, summary, changed_at, changed_by_name
                          FROM public.archetype_settings_history WHERE mission_id=%s
                          ORDER BY changed_at DESC, id DESC LIMIT %s''', (mission_id, HISTORY_SHOWN))
    return [dict(r, changed_at=r['changed_at'].isoformat()) for r in found]


@archetypes_bp.get('/api/archetypes/settings')
def get_settings():
    """The settings page: the settings, the sheet's defaults, every number to choose from, the change history."""
    c = g.context
    require_manager(c)
    with _app().db() as conn:
        settings, version, updated_at, updated_by = load_settings(conn, c['mission_id'])
        entries = history(conn, c['mission_id'])
        numbers, attributes = load_numbers(conn, c['mission_id'])
    with_data = {k for row in numbers for k in model.SOURCES if row.get(k) is not None}
    # An archived number is listed only while these settings still weight it (so its weight keeps its label); the
    # page offers none of them for adding (archived: true).
    in_use = model.archived_used(settings)
    sources = [dict({'key': k, 'label': label, 'group': group, 'has_data': k in with_data},
                    **({'archived': True} if k in model.ARCHIVED_SOURCES else {}))
               for k, (label, group) in model.SOURCES.items()
               if k not in model.ARCHIVED_SOURCES or k in in_use]
    return jsonify(settings=settings, version=version, defaults=model.defaults(), sources=sources,
                   archetypes=list(model.ARCHETYPES), patterns=list(model.PATTERNS),
                   attributes=list(model.PEER_ATTRIBUTES) + ['extra:' + n for n in extra_attributes(attributes)],
                   week_choices=list(model.WEEK_CHOICES), history=entries,
                   updated_at=updated_at.isoformat() if updated_at else None, updated_by=updated_by)


def store(conn, c, settings, version, action):
    """Save the settings as version + 1 and add a history row. 409 when someone saved in between."""
    current, current_version, _, _ = load_settings(conn, c['mission_id'])
    if version != current_version:
        abort(409, CHANGED)
    summary = ('Restored the sheet\'s defaults' if action == 'restore_defaults'
               else model.change_summary(current, settings))
    new_version = current_version + 1
    who = (c.get('display_name') or '')[:200]
    rows(conn, '''INSERT INTO public.archetype_settings (mission_id, settings, version, updated_at, updated_by, updated_by_name)
                  VALUES (%s, %s, %s, now(), %s, %s)
                  ON CONFLICT (mission_id) DO UPDATE SET settings = EXCLUDED.settings, version = EXCLUDED.version,
                      updated_at = now(), updated_by = EXCLUDED.updated_by, updated_by_name = EXCLUDED.updated_by_name
                  WHERE public.archetype_settings.version = %s''',
         (c['mission_id'], Json(settings), new_version, c['user_id'], who, current_version))
    rows(conn, '''INSERT INTO public.archetype_settings_history
                  (mission_id, version, action, summary, settings, changed_by, changed_by_name)
                  VALUES (%s, %s, %s, %s, %s, %s, %s)''',
         (c['mission_id'], new_version, action, summary, Json(settings), c['user_id'], who))
    return new_version, summary


def lock_settings(conn, mission_id):
    """One save at a time per mission (a transaction-level lock, released at commit)."""
    rows(conn, 'SELECT pg_advisory_xact_lock(hashtext(%s), %s)', ('archetype_settings', mission_id))


def asked_version(body):
    """The settings version the page was showing; 400 (reload) when it is not a whole number."""
    version = body.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        abort(400, RELOAD)
    return version


@archetypes_bp.put('/api/archetypes/settings')
def put_settings():
    """Save the settings (checked; 409 when someone else saved since the page was opened)."""
    c = g.context
    require_manager(c)
    body = request.get_json(silent=True) or {}
    version = asked_version(body)
    try:
        settings = model.validate_settings(body.get('settings'))
    except model.SettingsError as error:
        return jsonify(error=str(error), fields=error.fields), 400
    with _app().db() as conn:
        lock_settings(conn, c['mission_id'])
        problems = model.archived_added(load_settings(conn, c['mission_id'])[0], settings)
        if problems:
            return jsonify(error=str(model.SettingsError(problems)), fields=problems), 400
        new_version, summary = store(conn, c, settings, version, 'save')
    return jsonify(settings=settings, version=new_version, summary=summary)


@archetypes_bp.post('/api/archetypes/settings/restore')
def restore_settings():
    """Go back to the owner's sheet's default settings (a new version, kept in the history)."""
    c = g.context
    require_manager(c)
    version = asked_version(request.get_json(silent=True) or {})
    settings = model.defaults()
    with _app().db() as conn:
        lock_settings(conn, c['mission_id'])
        new_version, summary = store(conn, c, settings, version, 'restore_defaults')
    return jsonify(settings=settings, version=new_version, summary=summary)
