"""The Vollzogen list for the Office and the managers: the people who were baptized and confirmed. Read-only.

What it is: one route, GET /api/vollzogen. It lists the rows of public.vollzogen_records (migration 051, filled from DA
Management > Data uploads > Vollzogen) of the viewer's mission, newest baptism first, with the columns of the office's
sheet: name, date the baptismal date was set, baptism date, how they were found, the missionaries who worked with them,
unit, stake, zone, confirmed, country, gender and preferred language. Filters: ?week= (the Sunday that names the week of
the baptism, as dashboards.vollzogen_week does), ?zone= (the zone as written in the list), ?q= (a text search) and
?period= (round 21: a month 2026-10, a year 2026, "month" for this month in the mission's time zone, or nothing/"all" for all
time). The answer also lists the months that have baptisms ("months", this month always included), the years ("years"), the
period asked for ("period"), this month ("this_month") and this reporting week ("this_week": its Sunday and Saturday, the portal's week, as
public.current_reporting_sunday counts it) so the page can mark the people baptized this week. The week list only holds
weeks of the chosen period.
Who uses it: portal/vollzogen.html, for the Office and the managers (AP, President, Data Analyst).
How it fits: roles.can_view_vollzogen decides (a viewing right; Office stays a non-manager). The table has no policy and no
rights for the portal's database roles, so the query runs on the service connection AFTER that check, with the viewer's
mission in the WHERE clause and a fixed list of columns (never the FC number, the record key or the link to a person).
Nothing here writes: PUT, POST and DELETE answer 405 because only GET is registered.
"""
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, g, jsonify, request

import mission_time
import roles
from helpers import fetch_rows, json_ready

vollzogen_bp = Blueprint('vollzogen', __name__)

LIMIT = 500
WEEKS_SHOWN = 104
TEXT_LIMIT = 100
NOT_FOR_YOU = 'The Vollzogen list is for the office and mission leaders.'
BAD_WEEK = 'Choose a week as a date like 2026-09-20.'
BAD_PERIOD = 'Choose a period as a month like 2026-10 or a year like 2026.'
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


def today():
    """Today in the mission's time zone (GFM_TIME_ZONE, default Europe/Berlin)."""
    return datetime.now(mission_time.ZONE).date()


def parse_period(value, now):
    """?period= as (name, first day, day after the last), or ('all', None, None). Anything else is a 400."""
    value = (value or '').strip()
    if value in ('', 'all'):
        return 'all', None, None
    if value == 'month':
        value = now.strftime('%Y-%m')
    found = re.fullmatch(r'(\d{4})(?:-(\d{2}))?', value)
    if not found or not 1900 < int(found[1]) < 3000 or (found[2] and not 1 <= int(found[2]) <= 12):
        abort(400, BAD_PERIOD)
    year, month = int(found[1]), int(found[2] or 0)
    if not month:
        return value, date(year, 1, 1), date(year + 1, 1, 1)
    return value, date(year, month, 1), date(year + month // 12, month % 12 + 1, 1)


def this_week(now):
    """The portal's reporting week of `now`: Sunday to Saturday (public.reporting_sunday_at)."""
    sunday = now - timedelta(days=now.isoweekday() % 7)
    return {'sunday': sunday, 'saturday': sunday + timedelta(days=6)}


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
    now = today()
    period, start, end = parse_period(request.args.get('period'), now)
    with _app().db() as conn:
        weeks = fetch_rows(conn, f'''SELECT DISTINCT {SUNDAY} AS sunday FROM public.vollzogen_records v
            WHERE v.mission_id=%s AND (%s::date IS NULL OR (v.baptism_date>=%s AND v.baptism_date<%s))
            ORDER BY sunday DESC LIMIT %s''', (mission_id, start, start, end, WEEKS_SHOWN))
        months = fetch_rows(conn, '''SELECT DISTINCT to_char(v.baptism_date, 'YYYY-MM') AS month FROM public.vollzogen_records v
            WHERE v.mission_id=%s AND v.baptism_date IS NOT NULL ORDER BY month DESC''', (mission_id,))
        zones = fetch_rows(conn, '''SELECT DISTINCT v.zone FROM public.vollzogen_records v
            WHERE v.mission_id=%s AND v.zone IS NOT NULL AND v.zone<>'' ORDER BY v.zone''', (mission_id,))
        found = fetch_rows(conn, f'''SELECT {', '.join('v.' + col for col in COLUMNS)}
            FROM public.vollzogen_records v
            WHERE v.mission_id=%s
              AND (%s::date IS NULL OR {SUNDAY}=%s)
              AND (%s::text IS NULL OR v.zone=%s)
              AND (%s::text IS NULL OR v.full_name ILIKE %s OR v.found_how ILIKE %s OR v.workers ILIKE %s
                   OR v.unit ILIKE %s OR v.stake ILIKE %s OR v.zone ILIKE %s)
              AND (%s::date IS NULL OR (v.baptism_date>=%s AND v.baptism_date<%s))
            ORDER BY v.baptism_date DESC, v.full_name LIMIT %s''',
                          (mission_id, week, week, zone, zone, pattern, pattern, pattern, pattern, pattern, pattern,
                           pattern, start, start, end, LIMIT + 1))
    months = sorted({m['month'] for m in months} | {now.strftime('%Y-%m')}, reverse=True)
    return jsonify(json_ready({
        'read_only': True, 'roles_label': roles.describe(c),
        'weeks': [w['sunday'] for w in weeks], 'zones': [z['zone'] for z in zones],
        'filter': {'week': week, 'zone': zone, 'q': search},
        'period': period, 'this_month': now.strftime('%Y-%m'), 'months': months, 'years': sorted({m[:4] for m in months}, reverse=True), 'this_week': this_week(now),
        'items': found[:LIMIT], 'truncated': len(found) > LIMIT}))
