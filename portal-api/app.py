"""The portal's API: the front door for every page of the mission portal.

What it is: a small Flask web service (gunicorn runs it in the portal-api container, port 8091). nginx hands every
/api/ request of the portal to it. Each request first proves who is asking (the portal sign-in), then this file or
one of its helper files answers with JSON.
Who uses it: the pages in portal/ (Overview, Weekly Planning, Call-ins, calendar, announcements, Archetypal Health,
Whiteboard, the Dashboards sign-in) and, under /internal/, the Presentations (Slidev) manager.
How it fits: everything is stored in the Supabase Postgres database. Most routes read and write through db(), the
service's own database account. Weekly Planning, Call-ins and the mission glimpse use user_db(), which acts as the
signed-in person, so the database's own row-level security rules decide as well. roles.py says what each role may do.

The parts of this file, in order:
   1. Database connections       connect, db, rows, user_db
   2. Who is asking              authenticate (runs before every request), context_for, internal_context
   3. Errors and health          error_response, /health
   4. Stewardship and targets    which areas someone may reach, who sees an event or announcement, /api/options
   5. Calendar                   /api/events: repeating events, attendance, deleting one date
   6. Announcements              /api/announcements and their read receipts
   7. Attachments                files added to events and announcements
   8. Overview                   /api/overview, the mission glimpse (/api/dashboard), mission focus, languages
   9. Weekly Planning            /api/planning/... (planning.py does the work)
  10. Push reminders             which browsers get reminders (reminders.py sends them)
  11. Presentations              /internal/presentations/...: who may open or change a deck, key numbers for slides
  12. The other files            Call-ins, Dashboards sign-in, charts, Whiteboard, Archetypal Health, wiki edit
"""
import base64
import hmac
import json
import os
import re
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg2
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from dateutil.rrule import DAILY, MONTHLY, WEEKLY, rrule
from flask import Flask, abort, g, jsonify, request, send_file
from psycopg2.extras import Json, RealDictCursor, register_uuid
from werkzeug.exceptions import HTTPException

import charts
import church_links
import dashboard
import origin_guard
import planning
import mission_time
import roles
from archetypes import archetypes_bp
from callins import callins_bp
from charts import charts_bp
from dataease_auth import dataease_bp
from helpers import json_ready
from whiteboards import whiteboards_bp
from wiki_edit import wiki_bp

app = Flask(__name__, static_folder=None)  # only JSON answers: no /static/ files (nginx serves the portal's files)
register_uuid()  # uuid columns come back as uuid.UUID
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # the largest request accepted (an attachment, for example)

UTC = timezone.utc
MISSION_TZ = mission_time.ZONE  # the mission's time zone (GFM_TIME_ZONE, default Europe/Berlin)
# Audience targets for events and announcements (a record reaches anyone holding one of its roles).
ROLES = ['MISSIONARY', 'DL', 'ZL', 'STL', 'OFFICE', 'AP', 'PRESIDENT', 'DATA_ADMIN']
# Areas offered for targeting, by purpose (see roles.target_scope).
SCOPE_PURPOSES = {'announcements', 'calendar', 'presentations'}
# Attachment files live in this folder (a Docker volume), each under a random name (portal.attachments.storage_name).
UPLOAD_FOLDER = '/data/uploads'


# ============================================================================================== 1. database connections

def connect():
    """A new connection to the portal database as the service's own account; rows come back as dicts."""
    return psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor, connect_timeout=8)


@contextmanager
def db():
    """One transaction as the service's own account: saved (committed) at the end, undone on an error, then closed."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def rows(conn, sql, args=()):
    """Run one query and return its rows as a list of dicts (an empty list for a statement without rows)."""
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


@contextmanager
def user_db():
    """Like db(), but acting as the signed-in person (database role 'authenticated' with their sign-in claims), so
    row-level security decides what they may read and write. Its cursors return plain rows, not dicts; the code that
    uses it reads them with helpers.fetch_rows."""
    with db() as conn:
        rows(conn, "SELECT set_config('request.jwt.claims',%s,true)", (json.dumps(g.claims),))
        rows(conn, 'SET LOCAL ROLE authenticated')
        conn.cursor_factory = None
        yield conn


# ===================================================================================================== 2. who is asking

@app.before_request
def authenticate():
    """Runs before every request: the caller must be signed in to the portal. Sets g.context (who they are and
    their assignment, see context_for) and g.claims (their sign-in token's contents, used by user_db).
    /health needs no sign-in; /internal/ routes check the service key themselves (internal_context)."""
    if request.path in {'/health', '/api/health'} or request.path.startswith('/internal/'):
        return
    # Never a request from a presentation page or another address (origin_guard.py, round 8).
    refused = origin_guard.refusal(request.path, request.headers, origin_guard.deck_port(os.environ))
    if refused:
        abort(403, refused)
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        abort(401, 'Sign in through the mission portal.')
    user_id, claims = signed_in_user(header)
    with db() as conn:
        g.context = context_for(conn, user_id)
    g.claims = claims


def signed_in_user(header):
    """(user id, token claims) for an 'Authorization: Bearer <token>' header. Supabase checks the token: 401 when
    it has expired, 503 when the sign-in service cannot be reached."""
    token = header[7:]
    try:
        answer = requests.get(os.environ['SUPABASE_URL'] + '/auth/v1/user', headers={
            'apikey': os.environ['SUPABASE_SERVICE_ROLE_KEY'], 'Authorization': header}, timeout=8)
        if answer.status_code != 200:
            abort(401, 'Your session expired. Sign in again.')
        user_id = str(uuid.UUID(answer.json()['id']))
        # The token's middle part holds its claims. Supabase has just accepted the token, so they can be used.
        claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))
    except HTTPException:
        raise
    except Exception:
        abort(503, 'The sign-in service is unavailable. Please retry.')
    return user_id, claims


def context_for(conn, user_id):
    """Who this person is: their account, main role, all roles, area, district, zone and mission (a dict, called
    c or g.context everywhere). 403 when the account is inactive or has no mission.

    c.* includes additional_roles once migration 021 is applied (roles.py treats a missing column as empty). The
    highest current leadership row decides the main role, in the order of roles.LEADER_ORDER."""
    found = rows(conn, '''SELECT c.*,s.leadership_district_id,s.leadership_zone_id,
        s.leadership_mission_id FROM public.current_user_context c
        JOIN public.current_user_scope s ON s.user_id=c.user_id
          AND s.area_id IS NOT DISTINCT FROM c.area_id
          AND s.leadership_role IS NOT DISTINCT FROM c.leadership_role
        WHERE c.user_id=%s ORDER BY array_position(%s::text[],c.leadership_role) NULLS LAST,
          c.assignment_start_date DESC NULLS LAST LIMIT 1''', (user_id, list(roles.LEADER_ORDER)))
    if not found or not found[0].get('user_active'):
        abort(403, 'Your account is inactive or has no current assignment.')
    c = with_home_mission(conn, found[0])
    c['mission_id'] = c.get('leadership_mission_id') or c.get('mission_id')
    c['role'] = roles.main_role(c)
    c['roles'] = roles.roles(c)
    c['is_manager'] = roles.is_manager(c)
    if not c['mission_id']:
        abort(403, 'A mission assignment is required.')
    return c


def with_home_mission(conn, c):
    """Staff accounts (President, Office or Data Analyst with no missionary link, migration 027) have no area or
    leadership assignment. Their mission is the home mission set in DA Management (current_user_context.
    home_mission_id). A missionary's mission always comes from their assignments, never from a home mission."""
    home = c.get('home_mission_id')
    if home and not c.get('missionary_id') and not c.get('mission_id') and not c.get('leadership_mission_id'):
        c['mission_id'] = home
        found = rows(conn, 'SELECT name FROM public.missions WHERE id=%s', (home,))
        c['mission'] = found[0]['name'] if found else None
    return c


def internal_context(conn):
    """For /internal/ routes (the Presentations manager): checks the shared service key, then returns the context
    of the person the manager asks for (user_id in the body). 403 without the right key."""
    supplied = request.headers.get('X-Service-Key', '')
    if not supplied or not hmac.compare_digest(supplied, os.environ['PORTAL_SERVICE_KEY']):
        abort(403)
    return context_for(conn, str(uuid.UUID(request.json['user_id'])))


# ================================================================================================= 3. errors and health

@app.errorhandler(Exception)
def error_response(error):
    """Every error becomes JSON {"error": "..."}: the page shows the text. Bad input (ValueError, TypeError,
    KeyError) is a 400, PermissionError a 403, anything unexpected a logged 500 with a general message."""
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code
    if isinstance(error, ValueError) and isinstance(getattr(error, 'fields', None), dict):
        return jsonify(error=str(error), fields=error.fields), 400  # also names the form fields to mark
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return jsonify(error=str(error)), 400
    if isinstance(error, PermissionError):
        return jsonify(error=str(error)), 403
    app.logger.exception('Portal request failed')
    return jsonify(error='The request could not be completed. Please retry.'), 500


@app.get('/health')
@app.get('/api/health')
def health():
    """Docker's health check: the service runs and reaches the database."""
    with db() as conn:
        rows(conn, 'SELECT 1')
    return jsonify(ok=True)


# =========================================================================================== 4. stewardship and targets

def scope_areas(conn, c, purpose='announcements'):
    """Areas someone may target for this purpose (roles.target_scope): the whole mission for managers, and for
    Office on calendars and announcements; otherwise the main role's district, zone or area."""
    sql = '''SELECT a.id,a.name,a.district_id,d.zone_id FROM public.areas a
             JOIN public.districts d ON d.id=a.district_id JOIN public.zones z ON z.id=d.zone_id
             WHERE z.mission_id=%s'''
    args = [c['mission_id']]
    scope = roles.target_scope(c, purpose)
    if scope == 'district':
        sql += ''' AND d.id IN (SELECT leadership_district_id FROM public.current_user_scope
                   WHERE user_id=%s AND leadership_role='DL')'''
        args.append(c['user_id'])
    elif scope == 'zone':
        sql += ''' AND z.id IN (SELECT leadership_zone_id FROM public.current_user_scope
                   WHERE user_id=%s AND leadership_role=%s)'''
        args.extend([c['user_id'], roles.main_role(c)])
    elif scope == 'area':
        sql += ' AND a.id=%s'
        args.append(c['area_id'])
    return rows(conn, sql + ' ORDER BY a.name', args)


def visible(record, c, event=False, allow_admin=True):
    """Does this calendar event or announcement reach c? Managers (and calendar editors, for events) see every
    record of the mission, authors their own announcements. Everyone else needs one of the record's roles (if it
    names any) and one of its zones, districts, areas or people (if it names any).
    allow_admin=False asks only "is c in the audience?" (attendance lists and reminders)."""
    if int(record['mission_id']) != int(c['mission_id']):
        return False
    if allow_admin and (roles.is_manager(c) or (event and roles.can_edit_calendar(c))):
        return True
    if allow_admin and not event and str(record.get('author_id')) == str(c['user_id']):
        return True
    # The audience: any of the person's roles (main or additional) among the record's roles.
    if record.get('roles') and not set(roles.roles(c)) & set(record['roles']):
        return False
    zones, districts, areas, users = (record.get('zone_ids', []), record.get('district_ids', []),
                                      record.get('area_ids', []), record.get('user_ids', []))
    if not any((zones, districts, areas, users)):
        return True
    return (c.get('zone_id') in zones or c.get('district_id') in districts
            or c.get('area_id') in areas or str(c['user_id']) in [str(x) for x in users])


def item(conn, table, item_id, c):
    """One event or announcement that c may see; 404 when it is missing or not for them."""
    if table not in {'events', 'announcements'}:
        abort(400)
    found = rows(conn, f'SELECT * FROM portal.{table} WHERE id=%s', (str(uuid.UUID(item_id)),))
    if not found or not visible(found[0], c, event=table == 'events'):
        abort(404, 'This item is not available to your assignment.')
    return found[0]


def validate_targets(conn, c, data, announcement=False, purpose=None):
    """The audience of an event, announcement or deck access rule, checked against c's stewardship.

    Returns {'roles', 'zone_ids', 'district_ids', 'area_ids', 'user_ids'}: 400 for an unknown role, 403 for a target
    outside the stewardship. A leader's announcement without any target goes to their own district (DL) or zone
    (ZL, STL), never to the whole mission."""
    audience = list(dict.fromkeys(data.get('roles') or []))
    if any(r not in ROLES for r in audience):
        abort(400, 'Select valid roles.')
    areas = scope_areas(conn, c, purpose or ('announcements' if announcement else 'calendar'))
    allowed = allowed_targets(c, areas, announcement)
    clean = {'roles': audience}
    for key in ('zone_ids', 'district_ids', 'area_ids'):
        values = list(dict.fromkeys(int(v) for v in (data.get(key) or [])))
        if not set(values).issubset(allowed[key]):
            abort(403, 'A target is outside your stewardship.')
        clean[key] = values
    clean['user_ids'] = allowed_user_ids(conn, data, areas)
    if announcement and roles.target_scope(c, 'announcements') != 'mission':
        keep_leader_announcement_inside(c, clean, allowed)
    return clean


def allowed_targets(c, areas, announcement):
    """The zones, districts and areas c may name. A DL's announcement may not name a whole zone."""
    allowed = {'zone_ids': {a['zone_id'] for a in areas}, 'district_ids': {a['district_id'] for a in areas},
               'area_ids': {a['id'] for a in areas}}
    if (announcement and roles.target_scope(c, 'announcements') != 'mission'
            and roles.main_role(c) == 'DL'):
        allowed['zone_ids'] = set()
    return allowed


def allowed_user_ids(conn, data, areas):
    """The people named in data['user_ids']; 403 when one of them is not an active account in these areas."""
    user_ids = [str(uuid.UUID(v)) for v in (data.get('user_ids') or [])]
    if user_ids:
        allowed = {str(u['user_id']) for u in rows(conn, '''SELECT user_id FROM public.current_user_context
            WHERE area_id=ANY(%s) AND user_active''', ([a['id'] for a in areas],))}
        if not set(user_ids).issubset(allowed):
            abort(403, 'An account is outside your stewardship.')
    return user_ids


def keep_leader_announcement_inside(c, clean, allowed):
    """A leader cannot publish to the entire mission by leaving targets blank or using a larger zone: without any
    target, a DL's announcement goes to their district and a ZL's or STL's to their zone. Non-leaders get 403."""
    main = roles.main_role(c)
    if main not in roles.LEADER_ROLES:
        abort(403)
    if not any(clean[k] for k in ('zone_ids', 'district_ids', 'area_ids', 'user_ids')):
        if main == 'DL':
            clean['district_ids'] = sorted(allowed['district_ids'])
        else:
            clean['zone_ids'] = sorted(allowed['zone_ids'])


def iso(value):
    """A date and time sent by a page ('2026-09-27T18:00:00+02:00'); 400 when it has no time zone."""
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        abort(400, 'Times must include a timezone.')
    return moment


def safe_url(value):
    """A web link typed by a person: empty, or http(s) of at most 2000 characters (400 otherwise)."""
    if not value:
        return ''
    if urlparse(value).scheme not in {'https', 'http'} or len(value) > 2000:
        abort(400, 'Use an http or https meeting link.')
    return value


@app.get('/api/options')
def options():
    """Targets for the calendar (?purpose=calendar), announcements (default) or presentations, and what this person
    may do (their roles, capabilities, whether they may edit the calendar or publish)."""
    c = g.context
    purpose = request.args.get('purpose') or 'announcements'
    if purpose not in SCOPE_PURPOSES:
        abort(400, 'Choose calendar or announcements.')
    with db() as conn:
        areas = scope_areas(conn, c, purpose)
        districts = rows(conn, 'SELECT id,name,zone_id FROM public.districts WHERE id=ANY(%s) ORDER BY name',
                         (list({a['district_id'] for a in areas}),))
        zones = rows(conn, 'SELECT id,name FROM public.zones WHERE id=ANY(%s) ORDER BY name',
                     (list({a['zone_id'] for a in areas}),))
        users = rows(conn, '''SELECT DISTINCT user_id,display_name AS name,area_id FROM public.current_user_context
            WHERE user_active AND area_id=ANY(%s) ORDER BY name''', ([a['id'] for a in areas],))
    # roles: the audience targets; my_roles and role_label: this person's own roles, main role first.
    return jsonify(roles=ROLES, role_labels={r: roles.ROLE_LABELS[r] for r in ROLES}, areas=areas, zones=zones,
                   districts=districts, users=users, purpose=purpose, role=roles.main_role(c), my_roles=roles.roles(c),
                   role_label=roles.describe(c), capabilities=roles.capabilities(c),
                   can_edit_calendar=roles.can_edit_calendar(c), can_publish=roles.can_publish(c))


# ========================================================================================================== 5. calendar

def event_rule(event):
    """Every start of a repeating event, in the event's time zone (deleted dates included)."""
    recurrence = event['recurrence']
    zone = ZoneInfo(event['timezone'])
    freq = {'daily': DAILY, 'weekly': WEEKLY, 'monthly': MONTHLY}[recurrence['frequency']]
    return rrule(freq, dtstart=event['starts_at'].astimezone(zone), interval=recurrence.get('interval', 1),
                 until=iso(recurrence['until']).astimezone(zone))


def occurrences(event, start, end):
    """The dates of an event that touch the time from start to end (at most 500), each a copy of the event with its
    own starts_at and ends_at. The series' own times stay in series_starts_at and series_ends_at."""
    begins = event['starts_at']
    duration = event['ends_at'] - begins
    if not event.get('recurrence'):
        starts = [begins] if begins <= end and begins + duration >= start else []
    else:
        zone = ZoneInfo(event['timezone'])
        # Dates deleted one by one (migration 026), as local dates in the event's time zone.
        skipped = set(event.get('skipped_dates') or [])
        starts = [s for s in event_rule(event).between((start - duration).astimezone(zone), end.astimezone(zone),
                                                       inc=True)
                  if s.date() not in skipped][:500]
    return [dict(event, occurrence=s.isoformat(), series_starts_at=begins,
                 series_ends_at=event['ends_at'], starts_at=s, ends_at=s + duration) for s in starts]


def occurrence_at(event, when):
    """The event's date that starts exactly at `when`, or None when the event has no such date."""
    return next((e for e in occurrences(event, when, when) if e['starts_at'].timestamp() == when.timestamp()), None)


def event_list(conn, c, start, end):
    """Every date between start and end of the events c may see, with their attachments, earliest first."""
    found = rows(conn, 'SELECT * FROM portal.events WHERE mission_id=%s AND starts_at<=%s ORDER BY starts_at',
                 (c['mission_id'], end))
    found = attachment_info(conn, 'events', [event for event in found if visible(event, c, True)])
    expanded = [o for event in found for o in occurrences(event, start, end)]
    return sorted(expanded, key=lambda e: e['starts_at'])


@app.get('/api/events')
def events_get():
    """The calendar: the dates from ?start to ?end (default: a week ago to 90 days later; at most one year)."""
    start = iso(request.args['start']) if 'start' in request.args else datetime.now(UTC) - timedelta(days=7)
    end = iso(request.args['end']) if 'end' in request.args else start + timedelta(days=90)
    if end <= start or end - start > timedelta(days=366):
        abort(400, 'Select a calendar range of at most one year.')
    with db() as conn:
        return jsonify(events=event_list(conn, g.context, start, end), can_edit=roles.can_edit_calendar(g.context))


def clean_event(data):
    """(title, start, end, time zone, repeat rule) of an event as the calendar page sent it, checked (400)."""
    title = str(data['title']).strip()
    if not 1 <= len(title) <= 180:
        abort(400, 'Enter a title of at most 180 characters.')
    start, end = iso(data['starts_at']), iso(data['ends_at'])
    if end <= start:
        abort(400, 'The end must follow the start.')
    tz = data.get('timezone', mission_time.NAME)
    ZoneInfo(tz)  # an unknown time zone stops the save here
    return title, start, end, tz, clean_recurrence(data.get('recurrence'), start)


def clean_recurrence(recurrence, start):
    """A repeat rule: daily, weekly or monthly, every 1 to 52, ending within two years of the start. An empty rule
    (a one-off event) is kept as it came."""
    if not recurrence:
        return recurrence
    if recurrence.get('frequency') not in {'daily', 'weekly', 'monthly'}:
        abort(400, 'Select a supported repeat interval.')
    recurrence = {'frequency': recurrence['frequency'], 'interval': int(recurrence.get('interval', 1)),
                  'until': iso(recurrence['until']).isoformat()}
    if not 1 <= recurrence['interval'] <= 52 or not start <= iso(recurrence['until']) <= start + timedelta(days=730):
        abort(400, 'Recurring events must end within two years.')
    return recurrence


@app.route('/api/events', methods=['POST'])
@app.route('/api/events/<item_id>', methods=['PUT'])
def event_save(item_id=None):
    """Add an event (POST) or change one (PUT). Calendar editors only."""
    c = g.context
    if not roles.can_edit_calendar(c):
        abort(403, 'Calendar editing is available to the office, APs, president, and data analysts.')
    data = request.get_json()
    title, start, end, tz, recurrence = clean_event(data)
    with db() as conn:
        targets = validate_targets(conn, c, data, purpose='calendar')
        values = (title, str(data.get('description', ''))[:20000], start, end, tz, Json(recurrence), targets['roles'],
                  targets['zone_ids'], str(data.get('location', ''))[:500], safe_url(data.get('meeting_url', '')),
                  int(data.get('reminder_minutes', 30)))
        if item_id:
            item(conn, 'events', item_id, c)
            record = rows(conn, '''UPDATE portal.events SET title=%s,description=%s,starts_at=%s,ends_at=%s,timezone=%s,
                recurrence=%s,roles=%s,zone_ids=%s,location=%s,meeting_url=%s,reminder_minutes=%s,updated_at=now()
                WHERE id=%s RETURNING *''', values + (item_id,))[0]
        else:
            record = rows(conn, '''INSERT INTO portal.events(title,description,starts_at,ends_at,timezone,recurrence,
                roles,zone_ids,location,meeting_url,reminder_minutes,mission_id,author_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''', values + (c['mission_id'], c['user_id']))[0]
    return jsonify(event=record)


@app.route('/api/events/<item_id>/attendance', methods=['GET', 'POST'])
def attendance(item_id):
    """GET: the event's audience and who attended one date (?occurrence=<its start>). POST: record who attended,
    after the meeting has ended. Calendar editors only."""
    if not roles.can_edit_calendar(g.context):
        abort(403, 'Only calendar editors may record attendance.')
    occurrence = iso(request.args['occurrence'] if request.method == 'GET' else request.json['occurrence'])
    with db() as conn:
        event = item(conn, 'events', item_id, g.context)
        matched = occurrence_at(event, occurrence)
        if matched is None:
            abort(400, 'Select an actual event occurrence.')
        if request.method == 'POST':
            record_attendance(conn, item_id, event, matched, occurrence, request.json.get('attendance', []))
        return jsonify(users=event_audience(conn, event), attendance=rows(conn, '''SELECT a.*,(SELECT c.display_name
            FROM public.current_user_context c WHERE c.user_id=a.user_id LIMIT 1) AS display_name
            FROM portal.attendance a WHERE event_id=%s AND occurrence=%s''', (item_id, occurrence)))


def record_attendance(conn, item_id, event, matched, occurrence, entries):
    """Save [{user_id, attended}] for one date of the event; only people of its audience, only after it ended."""
    if datetime.now(UTC) < matched['ends_at'].astimezone(UTC):
        abort(400, 'Attendance can be recorded after the meeting ends.')
    for entry in entries:
        user = str(uuid.UUID(entry['user_id']))
        if not visible(event, context_for(conn, user), True, False):
            abort(403, 'This account is outside the event audience.')
        rows(conn, '''INSERT INTO portal.attendance(event_id,occurrence,user_id,attended,recorded_by)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(event_id,occurrence,user_id)
            DO UPDATE SET attended=excluded.attended,recorded_by=excluded.recorded_by,recorded_at=now()''',
             (item_id, occurrence, user, bool(entry['attended']), g.context['user_id']))


def event_audience(conn, event):
    """Everyone in the event's audience, once each, sorted by name.

    Staff accounts (President, Office or Data Analyst without an area, migration 027) belong to their home mission,
    as in context_for. Someone with two current leadership rows has two context rows: the highest counts, as in
    context_for. to_jsonb(c) gives additional_roles and home_mission_id, or nothing on a database without migration
    021 or 027."""
    people = rows(conn, '''SELECT DISTINCT ON (user_id) user_id,display_name,app_role,leadership_role,
        coalesce(mission_id,(to_jsonb(c)->>'home_mission_id')::bigint) AS mission_id,
        area_id,district_id,zone_id,to_jsonb(c)->'additional_roles' AS additional_roles
        FROM public.current_user_context c
        WHERE user_active AND coalesce(mission_id,(to_jsonb(c)->>'home_mission_id')::bigint)=%s
        ORDER BY user_id,array_position(%s::text[],leadership_role) NULLS LAST,assignment_start_date DESC NULLS LAST''',
        (g.context['mission_id'], list(roles.LEADER_ORDER)))
    return sorted(({'user_id': p['user_id'], 'name': p['display_name']} for p in people
                   if visible(event, p, True, False)), key=lambda p: str(p['name'] or '').casefold())


@app.delete('/api/events/<item_id>')
def event_delete(item_id):
    """Deletes an event with its attachments and attendance, or with ?occurrence=<start> one date of a repeating
    event (kept in portal.events.skipped_dates, migration 026). Deleting the last date left deletes the event."""
    c = g.context
    if not roles.can_edit_calendar(c):
        abort(403, 'Only calendar editors (the office, APs, the president and data analysts) may delete events.')
    occurrence = request.args.get('occurrence')
    with db() as conn:
        # Lock the event before reading skipped_dates: when two editors delete different dates at the same moment,
        # the second waits for the first and then reads its change, so both dates stay deleted.
        rows(conn, 'SELECT id FROM portal.events WHERE id=%s FOR UPDATE', (str(uuid.UUID(item_id)),))
        event = item(conn, 'events', item_id, c)
        if occurrence and event.get('recurrence'):
            day = delete_one_date(conn, event, iso(occurrence))
            if day:
                return jsonify(ok=True, deleted='occurrence', date=day.isoformat())
            # That was the last date left: delete the whole event.
        files = rows(conn, 'SELECT storage_name FROM portal.attachments WHERE event_id=%s', (event['id'],))
        rows(conn, 'DELETE FROM portal.events WHERE id=%s', (event['id'],))
    remove_stored_files(files)
    return jsonify(ok=True, deleted='event')


def delete_one_date(conn, event, when):
    """Deletes one date of a repeating event, with its attendance. Returns that date (also when another editor
    deleted it a moment ago), or None when it was the last date left (the caller then deletes the whole event)."""
    day = when.astimezone(ZoneInfo(event['timezone'])).date()
    skipped = set(event.get('skipped_dates') or [])
    if day in skipped:
        return day
    matched = occurrence_at(event, when)
    if matched is None:
        abort(400, 'This date is not part of the event any more. Reload the calendar and try again.')
    skipped.add(day)
    if not any(s.date() not in skipped for s in event_rule(event)):
        return None
    rows(conn, 'UPDATE portal.events SET skipped_dates=%s::date[],updated_at=now() WHERE id=%s',
         (sorted(skipped), event['id']))
    rows(conn, 'DELETE FROM portal.attendance WHERE event_id=%s AND occurrence=%s', (event['id'], matched['starts_at']))
    return day


# ===================================================================================================== 6. announcements

def announcement_list(conn, c):
    """The announcements c may see that have not expired: pinned first, then urgent, then newest; with whether c
    has read each one and may edit it, and its attachments."""
    found = rows(conn, '''SELECT a.*,r.read_at FROM portal.announcements a LEFT JOIN portal.announcement_reads r
        ON r.announcement_id=a.id AND r.user_id=%s WHERE a.mission_id=%s
        AND (a.expires_at IS NULL OR a.expires_at>now()) ORDER BY pinned DESC,urgent DESC,created_at DESC''',
                 (c['user_id'], c['mission_id']))
    found = [record for record in found if visible(record, c)]
    for record in found:
        record['can_edit'] = roles.is_manager(c) or str(record['author_id']) == str(c['user_id'])
    return attachment_info(conn, 'announcements', found)


@app.get('/api/announcements')
def announcements_get():
    """The announcements page: every announcement for this person, and whether they may publish."""
    with db() as conn:
        return jsonify(announcements=announcement_list(conn, g.context), can_publish=roles.can_publish(g.context))


@app.route('/api/announcements', methods=['POST'])
@app.route('/api/announcements/<item_id>', methods=['PUT'])
def announcement_save(item_id=None):
    """Publish an announcement (POST) or change one (PUT: the author or a manager), inside the allowed scope."""
    c = g.context
    if not roles.can_publish(c):
        abort(403, 'Leadership may publish within their stewardship.')
    data = request.json
    title, body = str(data['title']).strip(), str(data['body']).strip()
    if not 1 <= len(title) <= 180 or not 1 <= len(body) <= 20000:
        abort(400, 'Enter a title and announcement text.')
    with db() as conn:
        if item_id:
            old = item(conn, 'announcements', item_id, c)
            if str(old['author_id']) != str(c['user_id']) and not roles.is_manager(c):
                abort(403, 'You may edit your own announcements.')
        t = validate_targets(conn, c, data, True)
        values = (title, body, t['roles'], t['zone_ids'], t['district_ids'], t['area_ids'], t['user_ids'],
                  bool(data.get('pinned')), bool(data.get('urgent')),
                  iso(data['expires_at']) if data.get('expires_at') else None)
        if item_id:
            record = rows(conn, '''UPDATE portal.announcements SET title=%s,body=%s,roles=%s,zone_ids=%s,
                district_ids=%s,area_ids=%s,user_ids=%s::uuid[],pinned=%s,urgent=%s,expires_at=%s,updated_at=now()
                WHERE id=%s RETURNING *''', values + (item_id,))[0]
        else:
            record = rows(conn, '''INSERT INTO portal.announcements(title,body,roles,zone_ids,district_ids,area_ids,
                user_ids,pinned,urgent,expires_at,mission_id,author_id) VALUES(%s,%s,%s,%s,%s,%s,%s::uuid[],%s,%s,%s,%s,%s)
                RETURNING *''', values + (c['mission_id'], c['user_id']))[0]
    return jsonify(announcement=record)


@app.delete('/api/announcements/<item_id>')
def announcement_delete(item_id):
    """Delete an announcement (the author or a manager) with its read receipts and attachments."""
    c = g.context
    with db() as conn:
        record = item(conn, 'announcements', item_id, c)
        if str(record['author_id']) != str(c['user_id']) and not roles.is_manager(c):
            abort(403, 'You may delete only your own announcements.')
        # Foreign-key cascades remove read receipts and attachment rows; their stored files go after the commit.
        files = rows(conn, 'SELECT storage_name FROM portal.attachments WHERE announcement_id=%s', (item_id,))
        rows(conn, 'DELETE FROM portal.announcements WHERE id=%s', (item_id,))
    remove_stored_files(files)
    return jsonify(ok=True)


@app.post('/api/announcements/<item_id>/read')
def announcement_read(item_id):
    """Mark an announcement as read by this person."""
    with db() as conn:
        item(conn, 'announcements', item_id, g.context)
        rows(conn, '''INSERT INTO portal.announcement_reads(announcement_id,user_id) VALUES(%s,%s)
            ON CONFLICT DO NOTHING''', (item_id, g.context['user_id']))
    return jsonify(ok=True)


@app.get('/api/announcements/<item_id>/receipts')
def announcement_receipts(item_id):
    """Who has read an announcement, and when (the author or a manager)."""
    with db() as conn:
        record = item(conn, 'announcements', item_id, g.context)
        if not roles.is_manager(g.context) and str(record['author_id']) != str(g.context['user_id']):
            abort(403)
        return jsonify(reads=rows(conn, '''SELECT r.read_at,c.display_name FROM portal.announcement_reads r
            JOIN public.current_user_context c ON c.user_id=r.user_id WHERE announcement_id=%s ORDER BY read_at''',
                                  (item_id,)))


# ======================================================================================================= 7. attachments

# Attachment names. Files are stored under a random name (storage_name), so the name people see only has to be
# safe to show, to save on Windows, macOS or a phone, and to send back in Content-Disposition.
WINDOWS_RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                          *(f'LPT{i}' for i in range(1, 10))}
ATTACHMENT_NAME_LIMIT = 150


def attachment_info(conn, table, records):
    """Adds each record's attachments (id, filename, mime_type, bytes; oldest first) as record['attachments']."""
    key = 'event_id' if table == 'events' else 'announcement_id'
    for record in records:
        record['attachments'] = rows(conn, f'''SELECT id,filename,mime_type,bytes FROM portal.attachments
            WHERE {key}=%s ORDER BY created_at''', (record['id'],))
    return records


def attachment_name(value):
    """The uploaded file's own name, keeping letters such as ä, ß, é, ł or 会 (secure_filename dropped them).

    Removes folders, control and bidirectional-override characters and the characters Windows does not allow in
    file names, and keeps at most 150 characters with the extension. Never empty."""
    name = unicodedata.normalize('NFC', str(value or ''))
    name = re.split(r'[\\/]', name)[-1]
    name = ''.join(' ' if unicodedata.category(ch) in {'Cc', 'Cs', 'Co', 'Cn'}
                   # Keep the zero-width non-joiner and joiner: Persian, Arabic and Indic names need them.
                   or (unicodedata.category(ch) == 'Cf' and ch not in '\u200c\u200d') else ch for ch in name)
    name = re.sub(r'[<>:"|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip(' .')
    if name.split('.')[0].strip().upper() in WINDOWS_RESERVED_NAMES:
        name = '_' + name
    if len(name) > ATTACHMENT_NAME_LIMIT:
        stem, dot, ext = name.rpartition('.')
        suffix = '.' + ext if dot and stem and 0 < len(ext) <= 16 else ''
        body = name[:len(name) - len(suffix)]
        name = body[:ATTACHMENT_NAME_LIMIT - len(suffix)].rstrip(' .') + suffix
    return name or 'attachment'


def stored_file(storage_name):
    """Where an attachment's file is kept."""
    return Path(UPLOAD_FOLDER) / storage_name


def remove_stored_files(records):
    """Deletes the stored files of attachment rows that are already gone (call after the commit)."""
    for record in records:
        try:
            stored_file(record['storage_name']).unlink(missing_ok=True)
        except OSError:
            app.logger.warning('A stored attachment file could not be deleted.')


def attachment_stored(storage_name):
    """Whether an attachment row points to this stored file, read on a new connection; None when that cannot be
    read either. Then the file is kept and logged: an attachment without its file is worse than a stray file."""
    try:
        with db() as conn:
            return bool(rows(conn, 'SELECT 1 FROM portal.attachments WHERE storage_name=%s', (storage_name,)))
    except Exception:
        app.logger.warning('Kept the attachment file %s: its commit failed and could not be checked.', storage_name)
        return None


def may_change_attachments(table, parent, c):
    """Who may add or remove files: calendar editors on events; the author or a manager on announcements."""
    if table == 'events':
        return roles.can_edit_calendar(c)
    return roles.is_manager(c) or str(parent['author_id']) == str(c['user_id'])


@app.post('/api/<table>/<item_id>/attachments')
def upload(table, item_id):
    """Add a file to an event or announcement. The file is saved first, then its row; if the row cannot be
    stored, the file is removed again, so no file is left without a row."""
    if table not in {'events', 'announcements'}:
        abort(404)
    with db() as conn:
        parent = item(conn, table, item_id, g.context)
        if not may_change_attachments(table, parent, g.context):
            abort(403)
        file = request.files.get('file')
        if not file or not file.filename:
            abort(400, 'Choose an attachment.')
        filename = attachment_name(file.filename)
        storage = str(uuid.uuid4())
        path = stored_file(storage)
        try:
            file.save(path)
            record = rows(conn, '''INSERT INTO portal.attachments(mission_id,uploader_id,event_id,announcement_id,
                filename,storage_name,mime_type,bytes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,filename''',
                          (g.context['mission_id'], g.context['user_id'], item_id if table == 'events' else None,
                           item_id if table == 'announcements' else None, filename, storage,
                           file.mimetype or 'application/octet-stream', path.stat().st_size))[0]
        except BaseException:
            # No attachment row was stored (the insert failed or the upload broke off): the file, or the part of
            # it already written, would be left behind with nothing pointing to it.
            remove_stored_files([{'storage_name': storage}])
            raise
        try:
            conn.commit()  # here, so that a failed commit can be handled below
        except BaseException:
            # The row may be stored all the same (the connection broke after the database committed): remove the
            # file only when a new connection shows that no row points to it.
            if attachment_stored(storage) is False:
                remove_stored_files([{'storage_name': storage}])
            raise
    return jsonify(attachment=record)


@app.get('/api/attachments/<attachment_id>')
def download(attachment_id):
    """Download a file of an event or announcement this person may see."""
    with db() as conn:
        found = rows(conn, 'SELECT * FROM portal.attachments WHERE id=%s', (str(uuid.UUID(attachment_id)),))
        if not found:
            abort(404)
        a = found[0]
        item(conn, 'events' if a['event_id'] else 'announcements', str(a['event_id'] or a['announcement_id']),
             g.context)
    path = stored_file(a['storage_name'])
    if not path.is_file():
        abort(404, 'This attachment is no longer available. Ask the person who added it to add it again.')
    # Werkzeug adds filename*=UTF-8''... (RFC 5987) for names with letters such as ä or é.
    return send_file(path, as_attachment=True, download_name=a['filename'], mimetype=a['mime_type'])


@app.delete('/api/attachments/<attachment_id>')
def attachment_delete(attachment_id):
    """Remove one file from an event (calendar editors) or announcement (its author or a manager)."""
    c = g.context
    with db() as conn:
        found = rows(conn, 'SELECT * FROM portal.attachments WHERE id=%s', (str(uuid.UUID(attachment_id)),))
        if not found:
            abort(404, 'This attachment was already removed. Reload the page.')
        a = found[0]
        table = 'events' if a['event_id'] else 'announcements'
        parent = item(conn, table, str(a['event_id'] or a['announcement_id']), c)
        if not may_change_attachments(table, parent, c):
            abort(403, 'Only calendar editors may remove files from events.' if table == 'events'
                  else 'You may remove files only from your own announcements.')
        rows(conn, 'DELETE FROM portal.attachments WHERE id=%s', (a['id'],))
    remove_stored_files([a])
    return jsonify(ok=True)


# ========================================================================================================== 8. overview

@app.get('/api/overview')
def overview():
    """The Overview page: this week's planning (planning.py), the next events and newest announcements, the
    mission focus or a short thought, and whether the mission glimpse is shown (managers)."""
    with user_db() as conn:
        payload = planning.planning_overview(conn, g.context, request.args.get('area_id', type=int),
                                             request.args.get('week'))
    now = datetime.now(UTC)
    with db() as conn:
        payload.update(events=event_list(conn, g.context, now, now + timedelta(days=30))[:5],
                       announcements=announcement_list(conn, g.context)[:5])
        focus = mission_focus_payload(conn, g.context)
    payload['mission_focus'] = focus
    payload['inspiration'] = focus['focus'] or inspiration()
    # The managers' Overview starts with the mission glimpse (home.html asks GET /api/dashboard for its numbers).
    payload['glimpse'] = roles.shows_glimpse(g.context)
    return jsonify(payload)


# The mission glimpse at the top of the managers' Overview (portal/glimpse.js). It is read fresh on every visit
# (a few tenths of a second, see dashboard.py); until round 9 it took seconds and each answer was kept for 10 minutes.
@app.get('/api/dashboard')
def mission_dashboard_view():
    """The six key indicators by finished week and zone for the mission glimpse, mission-wide. Managers only (AP,
    President, Data Analyst: roles.shows_glimpse). Row-level security's own question decides which areas count: it is
    asked as the caller through user_db(), once per area (dashboard.areas_open_to)."""
    if not roles.shows_glimpse(g.context):
        abort(403, 'The mission glimpse is for the mission president, the assistants to the president '
                   'and the data analysts.')
    weeks = dashboard.parse_weeks(request.args.get('weeks'))
    with user_db() as conn:  # as the person: which areas may they see?
        area_ids = dashboard.areas_open_to(conn, g.context['mission_id'])
    with db() as conn:  # then the numbers of exactly those areas
        payload = dashboard.mission_dashboard(conn, g.context, weeks, area_ids)
    payload['read_at'] = datetime.now(UTC).isoformat()
    return jsonify(payload)


# The thought of the day on the Overview when no mission focus is set. Brief excerpts verified against the official
# Church scripture text. Never use Song of Solomon. The page shows them in the reader's language (portal catalogs
# overview.almaText, overview.dcText). Keep 'text':'...' with no space for those two: portal/tests/i18n-check.cjs
# looks for exactly that, and the updater installs nothing while that check fails.
INSPIRATIONS = [
    {'reference': 'Alma 37:6', 'text':'By small and simple things are great things brought to pass.',
     'url': 'https://www.churchofjesuschrist.org/study/scriptures/bofm/alma/37?lang=eng&id=p6'},
    {'reference': 'Doctrine and Covenants 64:33', 'text':'Be not weary in well-doing.',
     'url': 'https://www.churchofjesuschrist.org/study/scriptures/dc-testament/dc/64?lang=eng&id=p33'},
    {'reference': 'Preach My Gospel · Chapter 8',
     'text': 'Plan your week prayerfully, set meaningful goals, and work together as companions.',
     'paraphrase': True,
     'url': 'https://www.churchofjesuschrist.org/study/manual/preach-my-gospel-2023/16-chapter-8?lang=eng'},
    # Our own words, labelled "Mission thought", so nothing is attributed to Preach My Gospel that it does not say.
    {'source': 'Mission thought', 'text': 'Plan around people: who needs you this week, and what is their next step?'},
    {'source': 'Mission thought', 'text': 'Counsel together as companions, then act on what you felt.'},
    {'source': 'Mission thought', 'text': 'Every number is a person. Ask how they are doing before asking how many.'},
]


def inspiration():
    """Today's thought (a new one each day in the mission's time zone), its Church link in the reader's language."""
    choice = dict(INSPIRATIONS[datetime.now(MISSION_TZ).date().toordinal() % len(INSPIRATIONS)])
    if choice.get('url'):
        choice['url'] = church_links.church_url(choice['url'])
    return choice


def mission_default_language(conn, c):
    """The language the mission's people get when nothing else says (public.missions.default_language, migration 043)."""
    found = rows(conn, 'SELECT default_language FROM public.missions WHERE id=%s', (c.get('mission_id'),))
    return found[0]['default_language'] if found else 'en'


def selected_language(conn, c):
    """The language c chose in the portal, else their primary language, else the mission's default language (reminders
    use it too)."""
    pref = rows(conn, 'SELECT language FROM portal.user_preferences WHERE user_id=%s', (c['user_id'],))
    if pref:
        return pref[0]['language']
    assigned = rows(conn, '''SELECT primary_language FROM public.missionary_language_assignments
        WHERE missionary_id=%s''', (c.get('missionary_id'),))
    return assigned[0]['primary_language'] if assigned else mission_default_language(conn, c)


def mission_focus_payload(conn, c):
    """This week's mission focus in the language the page is shown in (managers also get every translation)."""
    sunday = current_reporting_sunday(conn)
    found = rows(conn, 'SELECT translations,updated_at FROM portal.mission_focus WHERE mission_id=%s AND reporting_sunday=%s',
                 (c['mission_id'], sunday))
    language = selected_language(conn, c)
    translations = found[0]['translations'] if found else {}
    # The language the page is shown in first (X-Mission-Language), then the saved one, then English.
    shown = church_links.request_language() or language
    focus = (translations.get(shown) or translations.get(shown.split('-')[0]) or translations.get(language)
             or translations.get(language.split('-')[0]) or translations.get('en'))
    if focus and focus.get('url'):
        focus = {**focus, 'url': church_links.church_url(focus['url'])}
    return {'week': sunday, 'language': language, 'focus': focus,
            'translations': translations if roles.is_manager(c) else None,
            'can_edit': roles.is_manager(c), 'updated_at': found[0]['updated_at'] if found else None}


def current_reporting_sunday(conn):
    """The Sunday of the current reporting week (the database decides, public.current_reporting_sunday)."""
    return rows(conn, 'SELECT public.current_reporting_sunday() sunday')[0]['sunday']


@app.route('/api/mission-focus', methods=['GET', 'PUT'])
def mission_focus():
    """GET: this week's mission focus. PUT (managers): save it in one language ({language, text, reference, url})."""
    with db() as conn:
        if request.method == 'GET':
            return jsonify(mission_focus_payload(conn, g.context))
        if not roles.is_manager(g.context):
            abort(403, 'Mission managers may set the weekly focus.')
        save_mission_focus(conn, g.context, request.json or {})
        return jsonify(mission_focus_payload(conn, g.context))


def save_mission_focus(conn, c, data):
    """Save this week's focus in one language; the other languages stay as they are."""
    language, text = str(data.get('language', '')).strip(), str(data.get('text', '')).strip()
    if not language or len(language) > 35 or not text or len(text) > 1000:
        abort(400, 'Choose a language and enter a mission focus.')
    sunday = current_reporting_sunday(conn)
    entry = {'text': text, 'reference': str(data.get('reference', '')).strip()[:300],
             'url': safe_url(data.get('url')) if data.get('url') else ''}
    rows(conn, '''INSERT INTO portal.mission_focus(mission_id,reporting_sunday,translations,updated_by)
      VALUES(%s,%s,jsonb_build_object(%s,%s::jsonb),%s)
      ON CONFLICT(mission_id,reporting_sunday) DO UPDATE
      SET translations=portal.mission_focus.translations||excluded.translations,
          updated_by=excluded.updated_by,updated_at=now()''',
         (c['mission_id'], sunday, language, Json(entry), c['user_id']))


def language_choices(conn, c):
    """(primary, allowed, selected): the languages the APs assigned to this missionary (the mission's default language
    without an assignment), and the one chosen in the portal if it is still allowed, else the first allowed one."""
    assigned = rows(conn, '''SELECT primary_language,additional_languages FROM public.missionary_language_assignments
        WHERE missionary_id=%s''', (c.get('missionary_id'),))
    pref = rows(conn, 'SELECT language FROM portal.user_preferences WHERE user_id=%s', (c['user_id'],))
    a = assigned[0] if assigned else {'primary_language': mission_default_language(conn, c), 'additional_languages': []}
    allowed = list(dict.fromkeys([a['primary_language']] + a['additional_languages']))
    selected = pref[0]['language'] if pref and pref[0]['language'] in allowed else allowed[0]
    return a['primary_language'], allowed, selected


@app.get('/api/languages')
def languages():
    """The languages this person may choose and the one chosen."""
    with db() as conn:
        primary, allowed, selected = language_choices(conn, g.context)
    return jsonify(primary=primary, allowed=allowed, selected=selected)


@app.put('/api/languages')
def language_save():
    """Choose one of the assigned languages."""
    with db() as conn:
        _, allowed, _ = language_choices(conn, g.context)
    language = request.json['language']
    if language not in allowed:
        abort(403, 'Choose a language assigned by the APs.')
    with db() as conn:
        rows(conn, '''INSERT INTO portal.user_preferences(user_id,language) VALUES(%s,%s)
            ON CONFLICT(user_id) DO UPDATE SET language=excluded.language''', (g.context['user_id'], language))
    return jsonify(ok=True, selected=language)


# =================================================================================================== 9. Weekly Planning
# The page is portal/planning.html. These routes only unpack the request; planning.py does the work, as the
# signed-in person (user_db), so the database's row-level security has the last word.

@app.get('/api/planning/form')
def planning_form_get():
    """The week's plan with its questions, answers and people (?unit_id= picks one ward or branch of the area)."""
    with user_db() as conn:
        return jsonify(planning.planning_form(conn, g.context, request.args.get('unit_id', type=int)))


@app.put('/api/planning/reports/<int:report_id>/answers')
def planning_answers_save(report_id):
    """Save the answers the page changed ({"answers": {question key: answer}})."""
    payload = request.json or {}
    if not isinstance(payload.get('answers'), dict):
        abort(400, 'Answers must be an object.')
    with user_db() as conn:
        return jsonify(planning.save_planning_answers(conn, g.context, report_id, payload['answers']))


@app.put('/api/planning/reports/<int:report_id>/people')
def planning_people_save(report_id):
    """Save the person-card fields the page changed ({"people": {group: [rows]}})."""
    payload = request.json or {}
    if not isinstance(payload.get('people'), dict):
        abort(400, 'People must be grouped by planning section.')
    with user_db() as conn:
        return jsonify(planning.save_planning_people(conn, g.context, report_id, payload['people']))


@app.post('/api/planning/reports/<int:report_id>/people/<kind>')
def planning_person_create(report_id, kind):
    """Add a person to the plan (a New Member, a friend with a baptismal date, a high-potential friend)."""
    with user_db() as conn:
        return jsonify(planning.create_planning_person(conn, g.context, report_id, kind, request.json or {})), 201


@app.post('/api/planning/reports/<int:report_id>/people/<group>/<int:person_id>/<action>')
def planning_person_action(report_id, group, person_id, action):
    """Edit / transfer / end follow-up / drop / baptized / delete a person on the plan
    (planning.manage_planning_person)."""
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        abort(400, 'Send the details as a JSON object.')
    try:
        with user_db() as conn:
            return jsonify(planning.manage_planning_person(conn, g.context, report_id, group, person_id, action,
                                                           payload))
    except planning.PersonActionRefused as error:
        # The record is kept (e.g. already on a submitted plan); the page offers End follow-up / No longer on date
        # instead.
        return jsonify(error=str(error), refused=True), 409


@app.get('/api/planning/transfer-targets')
def planning_transfer_targets_get():
    """The areas a person on the plan can be moved to."""
    with user_db() as conn:
        return jsonify(planning.planning_transfer_targets(conn, g.context))


@app.post('/api/planning/reports/<int:report_id>/<action>')
def planning_action(report_id, action):
    """Submit a plan, or unlock a submitted one (leaders)."""
    if action not in {'submit', 'unlock'}:
        abort(404)
    with user_db() as conn:
        step = planning.submit_planning_report if action == 'submit' else planning.unlock_planning_report
        result = step(conn, g.context, report_id)
    return jsonify(result)


# =================================================================================================== 10. push reminders
# Reminders are kept per device: one row in portal.push_subscriptions per browser push endpoint, several per person.
# The endpoint is known only to that browser (and the push service), so a request that sends it comes from that
# browser. reminders.py sends the reminders.

PUSH_PROVIDERS = ('fcm.googleapis.com', 'push.services.mozilla.com', 'notify.windows.com', 'push.apple.com')


@app.get('/api/push/config')
def push_config():
    """What the reminder switch needs: the server's public key and whether this person has reminders anywhere."""
    with db() as conn:
        count = rows(conn, 'SELECT count(*) AS n FROM portal.push_subscriptions WHERE user_id=%s',
                     (g.context['user_id'],))[0]['n']
    # subscribed: on any device (devices: how many). Whether this browser is one of them: POST /api/push/device.
    return jsonify(public_key=os.environ['VAPID_PUBLIC_KEY'], subscribed=bool(count), devices=count, required=True,
                   reminder=f'Sunday at 18:00, {mission_time.NAME}; suppressed while your companionship is working.')


@app.post('/api/push/subscriptions')
def push_subscribe():
    """Turn reminders on for this browser ({endpoint, keys} from the browser's push subscription)."""
    data = request.json
    check_push_provider(data['endpoint'])
    keys = data['keys']
    try:
        check_push_keys(keys)
    except Exception:
        abort(400, 'The browser subscription keys are invalid. Enable reminders again.')
    with db() as conn:
        rows(conn, '''INSERT INTO portal.push_subscriptions(user_id,endpoint,keys) VALUES(%s,%s,%s)
            ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,keys=excluded.keys''',
             (g.context['user_id'], data['endpoint'], Json(keys)))
    return jsonify(ok=True)


def check_push_provider(endpoint):
    """400 unless the endpoint is an https address of a known browser push service (no other server is ever
    contacted by the reminder worker)."""
    parsed = urlparse(endpoint)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in {None, 443}
            or not any(host == h or host.endswith('.' + h) for h in PUSH_PROVIDERS)):
        abort(400, 'Unrecognized browser push provider.')


def check_push_keys(keys):
    """Raises unless keys holds a valid P-256 public key (p256dh, 65 bytes) and a 16-byte auth secret."""
    public, auth = push_key_bytes(keys, 'p256dh'), push_key_bytes(keys, 'auth')
    if len(public) != 65 or len(auth) != 16:
        raise ValueError()
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)


def push_key_bytes(keys, name):
    """One key of a push subscription, decoded from URL-safe base64 (raises when it is not)."""
    value = keys[name]
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', value):
        raise ValueError()
    return base64.urlsafe_b64decode(value + '=' * ((-len(value)) % 4))


def push_endpoint():
    """The endpoint this browser sent ({"endpoint": ...}); 400 when it is missing."""
    data = request.get_json(silent=True)
    endpoint = data.get('endpoint') if isinstance(data, dict) else None
    if not isinstance(endpoint, str) or not endpoint.startswith('https://') or len(endpoint) > 2000:
        abort(400, 'This browser did not send its reminder address. Reload the page and try again.')
    return endpoint


@app.post('/api/push/device')
def push_device():
    """Whether this browser gets this person's reminders. If it still gets someone else's (a shared phone or
    computer where the last person did not sign out), theirs are removed from this browser."""
    endpoint = push_endpoint()
    with db() as conn:
        found = rows(conn, 'SELECT user_id FROM portal.push_subscriptions WHERE endpoint=%s', (endpoint,))
        mine = bool(found) and str(found[0]['user_id']) == str(g.context['user_id'])
        released = [] if mine or not found else rows(conn, '''DELETE FROM portal.push_subscriptions
            WHERE endpoint=%s AND user_id<>%s RETURNING id''', (endpoint, g.context['user_id']))
    return jsonify(subscribed=mine, released=bool(released))


@app.delete('/api/push/subscriptions')
def push_unsubscribe():
    """Turns reminders off on this browser only (the off switch, and sign-out). Other devices keep theirs."""
    endpoint = push_endpoint()
    with db() as conn:
        removed = rows(conn, '''DELETE FROM portal.push_subscriptions WHERE endpoint=%s AND user_id=%s
            RETURNING id''', (endpoint, g.context['user_id']))
    return jsonify(ok=True, removed=len(removed))


# ==================================================================================================== 11. presentations
# The Slidev manager asks these /internal/ routes (with the service key) what a person may do with the decks.
# Every deck has an owner (portal.presentation_access.owner_zone_id, migration 035): the mission (NULL, or no rule at
# all) or one zone. Managers open and change every deck. A ZL or STL opens and changes their own zone's decks, and
# opens (never changes) decks a manager shared with them through the deck's access rule. A DL opens (never changes)
# decks a manager shared with them. Missionaries have no Presentations. A zone's deck is never opened by anyone of
# another zone except managers (deck_allowed), because its slides are page code its zone's leaders wrote.

SHARE_IN_ZONE = "A zone's presentation can be shared only inside its own zone."
KPI_KEYS = ('friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance',
            'members_at_lessons', 'new_member_sacrament')


def deck_rules(conn, c, slugs):
    """The access rules of these decks in c's mission, by slug. Each carries owner_zone_name, the owning zone's name."""
    found = rows(conn, '''SELECT p.*,z.name AS owner_zone_name FROM portal.presentation_access p
        LEFT JOIN public.zones z ON z.id=p.owner_zone_id
        WHERE p.mission_id=%s AND p.deck_slug=ANY(%s::text[])''', (c['mission_id'], [str(s) for s in slugs]))
    return {r['deck_slug']: r for r in found}


def deck_editable(rule, c):
    """May c change this deck (Studio, Source, publish, rename, duplicate, delete, download its source)?
    Managers: every deck. A ZL or STL: only the decks their own zone owns. A shared deck stays read-only."""
    if roles.is_manager(c):
        return True
    zone = roles.presentation_zone(c)
    return bool(zone and rule and rule.get('owner_zone_id') == zone)


def deck_allowed(rule, c):
    """May c open this deck (view, present, Download PDF)? Managers: every deck. A ZL or STL: their zone's decks,
    and decks whose access rule includes them. A DL: decks whose access rule includes them. Missionaries: none."""
    if roles.is_manager(c):
        return True
    if not roles.can_use_presentations(c) or not rule:
        return False
    if deck_editable(rule, c):
        return True
    zone = c.get('leadership_zone_id') or c['zone_id']
    district = c.get('leadership_district_id') or c['district_id']
    # A zone's deck opens only inside that zone, whatever its rule says: its slides are page code written by that
    # zone's leaders, so they must never run in the browser (with the rights) of a leader of another zone.
    if rule.get('owner_zone_id') and zone != rule['owner_zone_id']:
        return False
    if str(c['user_id']) in [str(x) for x in rule['user_ids']]:
        return True
    if not rule['everyone'] and roles.main_role(c) not in rule['roles']:
        return False
    if rule['zone_ids'] or rule['district_ids']:
        return zone in rule['zone_ids'] or district in rule['district_ids']
    # A role-only mission-wide deck is deliberately available throughout that role's stewardship.
    return True


@app.post('/internal/presentations/check')
def presentation_check():
    """For the Slidev manager: what c may do with these decks. allowed_slugs: may open. editable_slugs: may change.
    can_use: may use Presentations at all. can_create: may make a new deck (managers; a ZL or STL with a zone).
    owner_zones: which zone owns each zone deck (managers only; the library shows it on the cards)."""
    with db() as conn:
        c = internal_context(conn)
        slugs = [str(s) for s in (request.json.get('deck_slugs') or [])[:500]]
        rules = deck_rules(conn, c, slugs)
    manager = roles.is_manager(c)
    return jsonify(role=roles.main_role(c), roles=roles.roles(c), can_manage=manager,
                   can_use=roles.can_use_presentations(c), can_create=manager or bool(roles.presentation_zone(c)),
                   zone_id=roles.presentation_zone(c),
                   allowed_slugs=[s for s in slugs if deck_allowed(rules.get(s), c)],
                   editable_slugs=[s for s in slugs if deck_editable(rules.get(s), c)],
                   owner_zones={s: r['owner_zone_name'] for s, r in rules.items()
                                if manager and r.get('owner_zone_id')})


@app.post('/internal/presentations/access')
def presentation_access():
    """The Slidev manager's changes to a deck's access rule ({user_id, deck_slug, operation, ...}).
    create: a new deck (made by a manager: owned by the mission; by a ZL or STL: owned by their zone).
    rename, duplicate, delete: whoever may change the deck; the copy keeps the owner (a leader's copy is shared with
    nobody until a manager shares it).
    get, save: managers only (Manage access, which also sets the owner; a zone's deck is shared only inside its
    zone)."""
    with db() as conn:
        c = internal_context(conn)
        data = request.json
        slug, operation = str(data['deck_slug']), data.get('operation', 'get')
        old = deck_rules(conn, c, [slug]).get(slug)
        if operation == 'create':
            return jsonify(ok=True, owner_zone_id=create_deck_rule(conn, c, slug))
        check_deck_operation(c, operation, old)
        if operation in {'rename', 'duplicate'}:
            slug = copy_deck_rule(conn, c, operation, slug, str(data['new_slug']), old)
        elif operation == 'save':
            save_deck_access(conn, c, slug, data.get('rule', {}), old)
        elif operation == 'delete':
            return jsonify(ok=True, deleted=forget_deck(conn, c, slug))
        elif operation != 'get':
            abort(400)
        return jsonify(deck_access_answer(conn, c, slug))


def check_deck_operation(c, operation, old):
    """403 unless c may do this: rename, duplicate and delete need a deck c may change; get and save need a manager."""
    if operation in {'rename', 'duplicate', 'delete'}:
        if not deck_editable(old, c):
            abort(403, "You can change only your own zone's presentations.")
    elif not roles.is_manager(c):
        abort(403)


def create_deck_rule(conn, c, slug):
    """A new deck: a manager's belongs to the mission, a ZL's or STL's to their zone. Returns the owning zone
    (or None)."""
    zone = roles.presentation_zone(c)
    if not roles.is_manager(c) and not zone:
        abort(403, 'A zone assignment is needed to make presentations.')
    save_deck_rule(conn, c, slug, {}, zone)
    return zone


def copy_deck_rule(conn, c, operation, slug, new_slug, old):
    """Rename or duplicate: the new slug gets the rule and owner of the old one. Returns the new slug.
    A leader's copy is a new deck whose content no manager has seen: it is shared with nobody (only its zone's ZLs
    and STLs see it) until a manager shares it again in Manage access. A manager's copy keeps the sharing."""
    rule = old or {}
    if operation == 'duplicate' and not roles.is_manager(c):
        rule = {}
    save_deck_rule(conn, c, new_slug, rule, (old or {}).get('owner_zone_id'))
    if operation == 'rename':
        rows(conn, 'DELETE FROM portal.presentation_access WHERE mission_id=%s AND deck_slug=%s', (c['mission_id'], slug))
    return new_slug


def save_deck_access(conn, c, slug, rule, old):
    """Manage access (managers): who may open the deck, and which zone owns it."""
    clean = validate_targets(conn, c, rule, purpose='presentations')
    if any(r not in roles.LEADER_ROLES for r in clean['roles']):
        abort(400, 'Select DL, ZL or STL for deck access.')
    # Without owner_zone_id (an older library page) the deck keeps its owner.
    if 'owner_zone_id' in rule:
        owner = mission_zone(conn, c, rule['owner_zone_id'])
    else:
        owner = (old or {}).get('owner_zone_id')
    refuse_sharing_outside_zone(conn, clean, owner)
    save_deck_rule(conn, c, slug, dict(clean, everyone=bool(rule.get('everyone'))), owner)


def forget_deck(conn, c, slug):
    """The deck was deleted: forget its access rule. Returns whether there was one (deleting twice is fine)."""
    gone = rows(conn, 'DELETE FROM portal.presentation_access WHERE mission_id=%s AND deck_slug=%s RETURNING deck_slug',
                (c['mission_id'], slug))
    return bool(gone)


def deck_access_answer(conn, c, slug):
    """The deck's access rule (or an empty one) and the choices of the Manage access dialog."""
    found = rows(conn, 'SELECT * FROM portal.presentation_access WHERE mission_id=%s AND deck_slug=%s',
                 (c['mission_id'], slug))
    choices = {'roles': ['DL', 'ZL', 'STL'],
               'zones': rows(conn, 'SELECT id,name FROM public.zones WHERE mission_id=%s ORDER BY name', (c['mission_id'],)),
               'districts': rows(conn, '''SELECT d.id,d.name,d.zone_id FROM public.districts d JOIN public.zones z
                  ON z.id=d.zone_id WHERE z.mission_id=%s ORDER BY d.name''', (c['mission_id'],)),
               # Only DLs, ZLs and STLs can use a shared deck (managers see every deck anyway).
               'users': rows(conn, '''SELECT DISTINCT user_id,display_name AS name FROM public.current_user_context
                  WHERE user_active AND mission_id=%s AND leadership_role IN ('DL','ZL','STL') ORDER BY name''',
                             (c['mission_id'],))}
    empty = {'roles': [], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': False, 'owner_zone_id': None}
    return {'access': found[0] if found else empty, 'options': choices}


def mission_zone(conn, c, zone_id):
    """None (the mission owns the deck) or the id of a zone of c's mission; anything else is refused."""
    if zone_id in (None, ''):
        return None
    found = rows(conn, 'SELECT id FROM public.zones WHERE id=%s AND mission_id=%s', (int(zone_id), c['mission_id']))
    if not found:
        abort(400, 'Choose a zone of this mission.')
    return found[0]['id']


def refuse_sharing_outside_zone(conn, rule, owner):
    """Manage access: a zone's deck may be shared only with that zone, its districts and its own people (400 otherwise).
    Roles and 'everyone' need no zone here: for a zone deck they mean that zone's people only (deck_allowed)."""
    if not owner:
        return
    if any(z != owner for z in rule['zone_ids']):
        abort(400, SHARE_IN_ZONE)
    if rule['district_ids']:
        inside = rows(conn, 'SELECT count(*) AS n FROM public.districts WHERE id=ANY(%s) AND zone_id=%s',
                      (rule['district_ids'], owner))[0]['n']
        if inside != len(rule['district_ids']):
            abort(400, SHARE_IN_ZONE)
    if rule['user_ids']:
        inside = rows(conn, '''SELECT count(DISTINCT user_id) AS n FROM public.current_user_context
            WHERE user_id=ANY(%s::uuid[]) AND zone_id=%s''', (rule['user_ids'], owner))[0]['n']
        if inside != len(rule['user_ids']):
            abort(400, SHARE_IN_ZONE)


def save_deck_rule(conn, c, slug, rule, owner):
    """Writes a deck's whole access rule and its owner (insert or replace)."""
    rows(conn, '''INSERT INTO portal.presentation_access(mission_id,deck_slug,roles,zone_ids,district_ids,user_ids,everyone,
            owner_zone_id,created_by,updated_by)
        VALUES(%s,%s,%s,%s,%s,%s::uuid[],%s,%s,%s,%s) ON CONFLICT(mission_id,deck_slug) DO UPDATE
        SET roles=excluded.roles,zone_ids=excluded.zone_ids,district_ids=excluded.district_ids,user_ids=excluded.user_ids,
            everyone=excluded.everyone,owner_zone_id=excluded.owner_zone_id,updated_by=excluded.updated_by,updated_at=now()''',
         (c['mission_id'], slug, list(rule.get('roles') or []), list(rule.get('zone_ids') or []),
          list(rule.get('district_ids') or []), [str(x) for x in rule.get('user_ids') or []], bool(rule.get('everyone')),
          owner, c['user_id'], c['user_id']))


@app.post('/internal/presentations/kpis')
def presentation_kpis():
    """Totals of the six key indicators for slides, oldest week first.

    Managers get the mission totals (dashboards.kpi_mission_week, migration 018). Leaders (a ZL or STL, a DL on a
    deck shared with them) never get mission totals: they get the totals of their own stewardship instead (a zone,
    a DL's district; charts.leader_units, the same rule as the database charts), or no weeks when they have none.
    goal is the goal set in the previous reporting week, the one each week's result is measured
    against (as in Call-ins).

    deck (round 8, optional): the deck the chart is in. It must be one c may open, and a zone's deck shows at most
    that zone's totals, to everyone (charts.deck_units), because its slides are page code that zone's leaders wrote."""
    weeks = kpi_week_count((request.json or {}).get('weeks', 26))
    deck = str((request.json or {}).get('deck') or '')
    with db() as conn:
        c = internal_context(conn)
        if not roles.can_use_presentations(c):
            abort(403, 'Presentations are available to assigned leaders.')
        rule = deck_rules(conn, c, [deck]).get(deck) if deck else None
        if deck and not deck_allowed(rule, c):
            abort(403, 'This presentation is not assigned to you.')
        found = kpi_rows(conn, c, rule, weeks)
    result = []
    for r in reversed(found):
        entry = {'week': r['sunday']}
        entry.update({k: {'actual': r[k + '_actual'], 'goal': r[k + '_previous_goal']} for k in KPI_KEYS})
        result.append(entry)
    return jsonify(json_ready(result))


def kpi_week_count(weeks):
    """How many weeks the slide asked for: a whole number from 1 to 104 (also as text); 400 otherwise."""
    if isinstance(weeks, str) and weeks.isdigit():
        weeks = int(weeks)
    if isinstance(weeks, bool) or not isinstance(weeks, int) or not 1 <= weeks <= 104:
        abort(400, 'Choose between 1 and 104 weeks.')
    return weeks


def kpi_rows(conn, c, rule, weeks):
    """The key-indicator rows c may see, newest week first: the mission totals, their own zone's, or none."""
    steward = charts.deck_units(conn, c, 'mission', rule)
    if steward is None or steward[1] is None:  # a manager (or a stewardship that is the whole mission)
        columns = ','.join(f'{k}_actual,{k}_previous_goal' for k in KPI_KEYS)
        return rows(conn, f'''SELECT sunday,{columns} FROM dashboards.kpi_mission_week
            WHERE mission_id=%s AND sunday<=public.current_reporting_sunday() ORDER BY sunday DESC LIMIT %s''',
                    (c['mission_id'], weeks))
    if steward[1]:
        return charts.stewardship_kpis(conn, c['mission_id'], steward[0], steward[1], weeks, KPI_KEYS)
    return []


# ================================================================================================== 12. the other files
# Each of these files adds its own routes (a Flask "blueprint"). They use db(), user_db() and rows() from this file.

app.register_blueprint(callins_bp)       # Call-ins: /api/callins and its saves (callins.py)
app.register_blueprint(dataease_bp)      # Dashboards (DataEase) sign-in: POST /api/dataease/session (dataease_auth.py)
app.register_blueprint(charts_bp)        # Database charts for slides: /internal/presentations/chart-* (charts.py)
app.register_blueprint(whiteboards_bp)   # Whiteboard tab: /api/whiteboards (whiteboards.py, migration 031)
app.register_blueprint(archetypes_bp)    # Archetypal Health: /api/archetypes and its settings (archetypes.py)
app.register_blueprint(wiki_bp)          # Wiki editing: /api/wiki (wiki_edit.py)
