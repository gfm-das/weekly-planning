"""The Vollzogen list for the Office and the managers: the people who were baptized and confirmed. Read-only.

What it is: one route, GET /api/vollzogen. It lists the rows of public.vollzogen_records (migration 051, filled from DA
Management > Data uploads > Vollzogen) of the viewer's mission, newest baptism first, with the columns of the office's
sheet: name, date the baptismal date was set, baptism date, how they were found, the missionaries who worked with them,
unit, stake, zone, confirmed, country, gender and preferred language. Filters: ?week= (the Sunday that names the week of
the baptism, as dashboards.vollzogen_week does), ?zone= (the zone as written in the list) and ?q= (a text search).
Who uses it: portal/vollzogen.html, for the Office and the managers (AP, President, Data Analyst).
How it fits: roles.can_view_vollzogen decides (a viewing right; Office stays a non-manager). The table has no policy and no
rights for the portal's database roles, so the query runs on the service connection AFTER that check, with the viewer's
mission in the WHERE clause and a fixed list of columns (never the FC number, the record key or the link to a person).
Nothing here writes: PUT, POST and DELETE answer 405 because only GET is registered.
"""
import re
from datetime import datetime

from flask import Blueprint, abort, g, jsonify, request

import roles
from helpers import fetch_rows, json_ready

vollzogen_bp = Blueprint('vollzogen', __name__)

LIMIT = 500
WEEKS_SHOWN = 104
TEXT_LIMIT = 100
NOT_FOR_YOU = 'The Vollzogen list is for the office and mission leaders.'
BAD_WEEK = 'Choose a week as a date like 2026-09-20.'
# The Sunday that names the week of a baptism (the same rule as dashboards.vollzogen_week in migration 051).
SUNDAY = '(v.baptism_date + (7 - extract(isodow FROM v.baptism_date)::int))'
COLUMNS = ('full_name', 'baptismal_date_set_on', 'baptism_date', 'found_how', 'workers', 'unit', 'stake', 'zone',
           'confirmed', 'country', 'gender', 'preferred_language')


def _app():
    import app  # imported here: app.py registers this blueprint while it is still loading
    return app


def parse_week(value):
    """The ?week= filter as a date, or None when not given. Anything else is a 400, not a 500."""
    if value is None or value == '':
        return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        abort(400, BAD_WEEK)
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        abort(400, BAD_WEEK)


def parse_text(value, name, limit):
    """A text filter, trimmed; None when empty. Too long is a 400."""
    value = (value or '').strip()
    if not value:
        return None
    if len(value) > limit:
        abort(400, f'The {name} is too long.')
    return value


def like_pattern(text):
    """The text as a 'contains' pattern with the LIKE wildcards of the text itself switched off."""
    return '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


@vollzogen_bp.get('/api/vollzogen')
def vollzogen_list():
    c = g.context
    if not roles.can_view_vollzogen(c):
        abort(403, NOT_FOR_YOU)
    mission_id = c.get('mission_id')
    week = parse_week(request.args.get('week'))
    zone = parse_text(request.args.get('zone'), 'zone', 200)
    search = parse_text(request.args.get('q'), 'search text', TEXT_LIMIT)
    pattern = like_pattern(search) if search else None
    with _app().db() as conn:
        weeks = fetch_rows(conn, f'''SELECT DISTINCT {SUNDAY} AS sunday FROM public.vollzogen_records v
            WHERE v.mission_id=%s ORDER BY sunday DESC LIMIT %s''', (mission_id, WEEKS_SHOWN))
        zones = fetch_rows(conn, '''SELECT DISTINCT v.zone FROM public.vollzogen_records v
            WHERE v.mission_id=%s AND v.zone IS NOT NULL AND v.zone<>'' ORDER BY v.zone''', (mission_id,))
        found = fetch_rows(conn, f'''SELECT {', '.join('v.' + col for col in COLUMNS)}
            FROM public.vollzogen_records v
            WHERE v.mission_id=%s
              AND (%s::date IS NULL OR {SUNDAY}=%s)
              AND (%s::text IS NULL OR v.zone=%s)
              AND (%s::text IS NULL OR v.full_name ILIKE %s OR v.found_how ILIKE %s OR v.workers ILIKE %s
                   OR v.unit ILIKE %s OR v.stake ILIKE %s OR v.zone ILIKE %s)
            ORDER BY v.baptism_date DESC, v.full_name LIMIT %s''',
                          (mission_id, week, week, zone, zone, pattern, pattern, pattern, pattern, pattern, pattern,
                           pattern, LIMIT + 1))
    return jsonify(json_ready({
        'read_only': True, 'roles_label': roles.describe(c),
        'weeks': [w['sunday'] for w in weeks], 'zones': [z['zone'] for z in zones],
        'filter': {'week': week, 'zone': zone, 'q': search},
        'items': found[:LIMIT], 'truncated': len(found) > LIMIT}))
