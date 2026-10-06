"""Check the round-2 known-issue fixes against a THROWAWAY database copy with migration 026 applied (and 019 run
again afterwards, as in the deploy; the test also repeats 019's grant itself).

Refuses unless DATABASE_URL names a database containing "test" and KNOWN_ISSUES_TEST_THROWAWAY=yes: it creates and
deletes events, announcements, files and push subscriptions, runs the companionship sync and archives a New Member.
Identity lookups are replaced in-process (as in callins_db.py); database roles, grants and the routes are real.
Prints only counts, ids of test rows and PASS/FAIL, never names or other personal data.

Run inside a temporary portal-api container (uploads go to the container's own /data/uploads):
  python tests/known_issues_db.py
"""
import base64
import io
import json
import os
import secrets
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('KNOWN_ISSUES_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import psycopg2  # noqa: E402
import requests  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from pywebpush import WebPushException  # noqa: E402

import app as api  # noqa: E402
import reminders  # noqa: E402

UTC = timezone.utc
BERLIN = ZoneInfo('Europe/Berlin')
UPLOADS = Path('/data/uploads')


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.fixture'


def call(user, path, method='GET', body=None, **kwargs):
    response = client.open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)}, **kwargs)
    return response.status_code, response.get_json(silent=True), response


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def as_role(role, query):
    """Runs one statement as a database role in a transaction that is always rolled back; returns the error code."""
    conn = api.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET LOCAL ROLE {role}')
            cur.execute(query)
        return 'ok'
    except psycopg2.Error as exc:
        return exc.pgcode
    finally:
        conn.rollback()
        conn.close()


def as_api(role, query):
    """Runs one statement the way PostgREST would for a request with this role: SET ROLE plus the role in
    request.jwt.claims (the database connection is postgres here, not authenticator). Always rolled back.
    Returns (error code or 'ok', error message)."""
    conn = api.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({'role': role}),))
            cur.execute(f'SET LOCAL ROLE {role}')
            cur.execute(query)
        return 'ok', ''
    except psycopg2.Error as exc:
        return exc.pgcode, exc.diag.message_primary or ''
    finally:
        conn.rollback()
        conn.close()


def user(where):
    found = sql(f'SELECT DISTINCT user_id FROM public.current_user_context WHERE user_active AND {where} ORDER BY user_id LIMIT 1')
    return found[0]['user_id'] if found else None


ap = user("leadership_role='AP'")
dl = user("leadership_role='DL'")
zl = user("leadership_role='ZL'")
print(f'fixture: AP={bool(ap)} DL={bool(dl)} ZL={bool(zl)}', flush=True)
assert ap and dl and zl, 'needs an AP, a DL and a ZL'
# The checks need a DL who is not a calendar editor. On a copy of live Beta the DL account may have Office or Data
# Analyst ticked as an additional role (it has Office since 27 Sep): take that away, on this throwaway copy only.
if sql("""SELECT 1 FROM information_schema.columns
          WHERE table_schema='public' AND table_name='user_profiles' AND column_name='additional_roles'"""):
    sql("UPDATE public.user_profiles SET additional_roles='{}' WHERE id=%s AND additional_roles<>'{}'", (dl,))

# 1. sync_current_companionships: not through the public API any more ---------------------------------------------
SYNC = 'SELECT public.sync_current_companionships()'
REFUSED = 'sync_current_companionships() can only be run on the server (service role or postgres).'
# The deploy runs 019 again after the migrations, and 019 grants EXECUTE to authenticated again. Do the same here
# (the grant exactly as in 019), so the checks below hold whether or not 019 was run before this test.
sql('GRANT EXECUTE ON FUNCTION public.sync_current_companionships() TO postgres, authenticated, service_role')
check('after 019: anon and PUBLIC still have no EXECUTE',
      sql("""SELECT NOT has_function_privilege('anon', 'public.sync_current_companionships()', 'EXECUTE')
                AND NOT has_function_privilege('public', 'public.sync_current_companionships()', 'EXECUTE') AS ok""")[0]['ok'])
check('anon cannot run sync_current_companionships()', as_api('anon', SYNC)[0] == '42501'
      and as_role('anon', SYNC) == '42501')
answer = as_api('authenticated', SYNC)
check('signed-in users cannot run it, although 019 gave them EXECUTE again', answer == ('42501', REFUSED), answer)
check('service_role (API) and postgres (no claims) still can (rolled back)',
      as_api('service_role', SYNC) == ('ok', '') and as_role('postgres', SYNC) == 'ok')

# 2. Reporting week in Berlin time --------------------------------------------------------------------------------
boundary = sql('''SELECT public.reporting_sunday_at('2026-09-26 22:30+00') AS berlin,
    ('2026-09-26 22:30+00'::timestamptz AT TIME ZONE 'UTC')::date
      - extract(dow FROM ('2026-09-26 22:30+00'::timestamptz AT TIME ZONE 'UTC'))::integer AS old_rule,
    public.reporting_sunday_at('2026-09-26 21:59+00') AS saturday_night,
    public.reporting_sunday_at('2026-11-28 23:05+00') AS winter''')[0]
check('Sunday 00:30 Berlin (still Saturday in UTC) is the new week', boundary['berlin'] == date(2026, 9, 27)
      and boundary['old_rule'] == date(2026, 9, 20), boundary)
check('Saturday 23:59 Berlin is still the old week; winter time rolls over at 00:00 Berlin too',
      boundary['saturday_night'] == date(2026, 9, 20) and boundary['winter'] == date(2026, 11, 29), boundary)
now_berlin = datetime.now(BERLIN).date()
expected = now_berlin - timedelta(days=(now_berlin.weekday() + 1) % 7)
sundays = set()
for zone in ('UTC', 'Pacific/Kiritimati', 'America/Los_Angeles'):
    conn = api.connect()
    try:
        with conn.cursor() as cur:
            cur.execute('SET TIME ZONE %s', (zone,))
            cur.execute('SELECT public.current_reporting_sunday() AS s, (SELECT sunday FROM public.current_reporting_week) AS w')
            row = cur.fetchone()
            sundays.add(row['s'])
    finally:
        conn.rollback()
        conn.close()
check('current_reporting_sunday() is this week in Berlin, whatever the session time zone',
      sundays == {expected}, (sundays, expected))
week = sql('SELECT sunday FROM public.current_reporting_week')
latest = sql('SELECT max(sunday) AS s FROM public.reporting_weeks WHERE sunday<=%s', (expected,))[0]['s']
check('current_reporting_week shows the latest week up to that Sunday', (week[0]['sunday'] if week else None) == latest)

# 3. Calendar: delete a date, a series, attachments; Unicode names ------------------------------------------------
ap_context = sql('SELECT zone_id FROM public.current_user_context WHERE user_id=%s LIMIT 1', (ap,))[0]
first = (datetime.now(BERLIN) + timedelta(days=2)).replace(hour=19, minute=0, second=0, microsecond=0)
until = first + timedelta(days=21, hours=4)
weekly = {'title': 'zz-known-issues weekly', 'description': 'test', 'starts_at': first.isoformat(),
          'ends_at': (first + timedelta(hours=1)).isoformat(), 'timezone': 'Europe/Berlin', 'roles': [], 'zone_ids': [],
          'recurrence': {'frequency': 'weekly', 'interval': 1, 'until': until.isoformat()}, 'reminder_minutes': 30}
status, body, _ = call(ap, '/api/events', 'POST', weekly)
event_id = body['event']['id']
window = f"/api/events?start={quote(first.isoformat())}&end={quote((until + timedelta(days=1)).isoformat())}"


def dates_shown(who=ap):
    status, body, _ = call(who, window)
    return [e for e in body['events'] if e['id'] == event_id]


shown = dates_shown()
check('a weekly test event has four dates', status == 200 and len(shown) == 4, len(shown))

name = 'Präsentation – Größe ÄÖÜ ß é ł 会议.pdf'
content = secrets.token_bytes(2048)
status, body, _ = call(ap, f'/api/events/{event_id}/attachments', 'POST',
                       data={'file': (io.BytesIO(content), name)}, content_type='multipart/form-data')
attachment_id = body['attachment']['id']
check('an attachment keeps its umlauts and other letters', status == 200 and body['attachment']['filename'] == name, body)
stored = sql('SELECT storage_name FROM portal.attachments WHERE id=%s', (attachment_id,))[0]['storage_name']
status, _, response = call(dl, f'/api/attachments/{attachment_id}')
disposition = response.headers.get('Content-Disposition', '')
check('its download sends the name as RFC 5987 filename* and the same bytes',
      status == 200 and "filename*=UTF-8''Pr%C3%A4sentation%20%E2%80%93%20Gr%C3%B6%C3%9Fe" in disposition
      and response.data == content, (status, disposition))

status, body, _ = call(dl, f'/api/events/{event_id}?occurrence={quote(shown[1]["occurrence"])}', 'DELETE')
check('a DL (not a calendar editor) cannot delete an event', status == 403 and 'calendar editors' in body['error'], (status, body))
status, body, _ = call(dl, f'/api/attachments/{attachment_id}', 'DELETE')
check('a DL cannot remove an event attachment', status == 403, (status, body))

second = shown[1]
sql('''INSERT INTO portal.attendance(event_id,occurrence,user_id,attended,recorded_by) VALUES(%s,%s,%s,true,%s)''',
    (event_id, second['occurrence'], ap, ap))
status, body, _ = call(ap, f'/api/events/{event_id}?occurrence={quote(second["occurrence"])}', 'DELETE')
after = dates_shown()
skipped_day = datetime.fromisoformat(second['occurrence']).astimezone(BERLIN).date()
check('an AP deletes one date: the other three stay', status == 200 and body == {'ok': True, 'deleted': 'occurrence',
      'date': skipped_day.isoformat()} and [e['occurrence'] for e in after] == [e['occurrence'] for e in shown if e is not second],
      (status, body, len(after)))
check('the date is stored in skipped_dates and its attendance is gone',
      sql('SELECT skipped_dates FROM portal.events WHERE id=%s', (event_id,))[0]['skipped_dates'] == [skipped_day]
      and not sql('SELECT 1 FROM portal.attendance WHERE event_id=%s', (event_id,)))
status, body, _ = call(ap, f'/api/events/{event_id}?occurrence={quote(second["occurrence"])}', 'DELETE')
check('deleting the same date again is fine (another editor was quicker)', status == 200 and body['deleted'] == 'occurrence')
status, body, _ = call(ap, f'/api/events/{event_id}?occurrence={quote((first + timedelta(hours=3)).isoformat())}', 'DELETE')
check('a time that is not a date of the event -> 400 with a plain message', status == 400 and 'Reload' in body['error'], body)

# No reminder for the deleted date, one for the next date.
with api.db() as conn:
    events = reminders.upcoming_events(conn, datetime.fromisoformat(second['occurrence']) - timedelta(minutes=10))
    c_ap = api.context_for(conn, ap)
due_deleted = [e for e in reminders.due_events(events, c_ap, datetime.fromisoformat(second['occurrence']) - timedelta(minutes=10))
               if str(e['id']) == event_id]
with api.db() as conn:
    events = reminders.upcoming_events(conn, datetime.fromisoformat(shown[2]['occurrence']) - timedelta(minutes=10))
due_next = [e for e in reminders.due_events(events, c_ap, datetime.fromisoformat(shown[2]['occurrence']) - timedelta(minutes=10))
            if str(e['id']) == event_id]
check('no reminder for the deleted date; the next date still has one', due_deleted == [] and len(due_next) == 1,
      (len(due_deleted), len(due_next)))

status, body, _ = call(ap, f'/api/attachments/{attachment_id}', 'DELETE')
check('an AP removes the attachment: row and stored file are gone',
      status == 200 and not sql('SELECT 1 FROM portal.attachments WHERE id=%s', (attachment_id,))
      and not (UPLOADS / stored).exists(), (status, body))
status, body, _ = call(ap, f'/api/attachments/{attachment_id}', 'DELETE')
check('removing it again -> 404 with a plain message', status == 404 and 'already removed' in body['error'], body)

status, body, _ = call(ap, f'/api/events/{event_id}/attachments', 'POST',
                       data={'file': (io.BytesIO(b'agenda'), 'Tagesordnung.txt')}, content_type='multipart/form-data')
series_file = sql('SELECT storage_name FROM portal.attachments WHERE id=%s', (body['attachment']['id'],))[0]['storage_name']
status, body, _ = call(ap, f'/api/events/{event_id}', 'DELETE')
check('deleting every date removes the event and its stored files',
      status == 200 and body['deleted'] == 'event' and not sql('SELECT 1 FROM portal.events WHERE id=%s', (event_id,))
      and not (UPLOADS / series_file).exists() and dates_shown() == [], (status, body))
status, body, _ = call(ap, f'/api/events/{event_id}', 'DELETE')
check('a deleted event -> 404', status == 404, (status, body))

# The last date left deletes the whole event.
daily = dict(weekly, title='zz-known-issues daily', recurrence={'frequency': 'daily', 'interval': 1,
             'until': (first + timedelta(days=1, hours=2)).isoformat()})
event_id = call(ap, '/api/events', 'POST', daily)[1]['event']['id']
two = dates_shown()
first_delete = call(ap, f'/api/events/{event_id}?occurrence={quote(two[0]["occurrence"])}', 'DELETE')[1]
last_delete = call(ap, f'/api/events/{event_id}?occurrence={quote(two[1]["occurrence"])}', 'DELETE')[1]
check('deleting the last remaining date deletes the event', len(two) == 2 and first_delete['deleted'] == 'occurrence'
      and last_delete['deleted'] == 'event' and not sql('SELECT 1 FROM portal.events WHERE id=%s', (event_id,)),
      (len(two), first_delete, last_delete))

# Two editors delete two different dates of one series at the same moment: both dates stay deleted. The barrier
# holds each request right after it has read the event; without the row lock both read the same skipped_dates and
# the second write drops the first date. With the lock the second request waits in the database (the barrier then
# times out and the first goes on alone), and reads the first one's change.
event_id = call(ap, '/api/events', 'POST', dict(weekly, title='zz-known-issues two editors'))[1]['event']['id']
four = dates_shown()
barrier = threading.Barrier(2, timeout=3)
real_item = api.item
answers = []


def item_then_wait(conn, table, item_id, c):
    found = real_item(conn, table, item_id, c)
    try:
        barrier.wait()
    except threading.BrokenBarrierError:
        pass
    return found


def delete_date(occurrence):
    response = api.app.test_client().delete(f'/api/events/{event_id}?occurrence={quote(occurrence)}',
                                            headers={'Authorization': 'Bearer ' + token(ap)})
    answers.append((response.status_code, (response.get_json(silent=True) or {}).get('deleted')))


with patch.object(api, 'item', item_then_wait):
    editors = [threading.Thread(target=delete_date, args=(e['occurrence'],)) for e in (four[0], four[2])]
    for editor in editors:
        editor.start()
    for editor in editors:
        editor.join(30)
kept = sql('SELECT skipped_dates FROM portal.events WHERE id=%s', (event_id,))[0]['skipped_dates']
expected_days = sorted(datetime.fromisoformat(e['occurrence']).astimezone(BERLIN).date() for e in (four[0], four[2]))
check('two editors delete two dates of one series at the same moment: both dates stay deleted',
      len(four) == 4 and answers == [(200, 'occurrence')] * 2 and kept == expected_days
      and [e['occurrence'] for e in dates_shown()] == [four[1]['occurrence'], four[3]['occurrence']],
      (answers, len(kept)))
call(ap, f'/api/events/{event_id}', 'DELETE')

single = dict(weekly, title='zz-known-issues single', recurrence=None)
event_id = call(ap, '/api/events', 'POST', single)[1]['event']['id']
body = call(ap, f'/api/events/{event_id}/attachments', 'POST', data={'file': (io.BytesIO(b'x'), '../../etc/Plan März.txt')},
            content_type='multipart/form-data')[1]
single_file = sql('SELECT storage_name,filename FROM portal.attachments WHERE id=%s', (body['attachment']['id'],))[0]
status, body, _ = call(ap, f'/api/events/{event_id}?occurrence={quote(first.isoformat())}', 'DELETE')
check('an event that does not repeat is deleted with its file (folder names are dropped from file names)',
      single_file['filename'] == 'Plan März.txt' and status == 200 and body['deleted'] == 'event'
      and not (UPLOADS / single_file['storage_name']).exists(), (status, body, single_file['filename']))

# Announcement attachments: the author or a manager.
announcement = call(dl, '/api/announcements', 'POST', {'title': 'zz-known-issues update', 'body': 'test'})[1]['announcement']
body = call(dl, f"/api/announcements/{announcement['id']}/attachments", 'POST',
            data={'file': (io.BytesIO(b'a'), 'Übersicht.pdf')}, content_type='multipart/form-data')[1]
file_id = body['attachment']['id']
status, _, _ = call(zl, f'/api/attachments/{file_id}', 'DELETE')
check("another leader cannot remove the DL's announcement file", status in {403, 404}, status)
status, _, _ = call(dl, f'/api/attachments/{file_id}', 'DELETE')
check('the author removes it', status == 200 and not sql('SELECT 1 FROM portal.attachments WHERE id=%s', (file_id,)))
body = call(dl, f"/api/announcements/{announcement['id']}/attachments", 'POST',
            data={'file': (io.BytesIO(b'b'), 'Zweite Übersicht.pdf')}, content_type='multipart/form-data')[1]
status, _, _ = call(ap, f"/api/attachments/{body['attachment']['id']}", 'DELETE')
check("a manager removes a file from someone else's announcement", status == 200)
missing = call(dl, f"/api/announcements/{announcement['id']}/attachments", 'POST',
               data={'file': (io.BytesIO(b'c'), 'weg.pdf')}, content_type='multipart/form-data')[1]['attachment']['id']
(UPLOADS / sql('SELECT storage_name FROM portal.attachments WHERE id=%s', (missing,))[0]['storage_name']).unlink()
status, body, _ = call(dl, f'/api/attachments/{missing}')
check('a download whose file is missing -> 404 with a plain message (was a 500)', status == 404 and 'no longer' in body['error'],
      (status, body))
call(dl, f"/api/announcements/{announcement['id']}", 'DELETE')

# 4. Push: per device, several per person, off switch, a shared device ------------------------------------------


def subscription(device):
    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return {'endpoint': f'https://fcm.googleapis.com/fcm/send/zz-known-issues-{device}-{secrets.token_hex(8)}',
            'keys': {'p256dh': b64(point), 'auth': b64(secrets.token_bytes(16))}}


phone, laptop = subscription('phone'), subscription('laptop')
for device in (phone, laptop):
    call(dl, '/api/push/subscriptions', 'POST', device)
config = call(dl, '/api/push/config')[1]
check('one person can have two devices', config['subscribed'] is True and config['devices'] >= 2, config.get('devices'))
check('each device knows it gets reminders', call(dl, '/api/push/device', 'POST', {'endpoint': phone['endpoint']})[1]
      == {'subscribed': True, 'released': False})
status, body, _ = call(dl, '/api/push/subscriptions', 'DELETE', {'endpoint': phone['endpoint']})
check('the off switch removes only this device', status == 200 and body['removed'] == 1
      and call(dl, '/api/push/config')[1]['devices'] == config['devices'] - 1
      and call(dl, '/api/push/device', 'POST', {'endpoint': laptop['endpoint']})[1]['subscribed'] is True)
status, body, _ = call(zl, '/api/push/subscriptions', 'DELETE', {'endpoint': laptop['endpoint']})
check("someone else cannot switch off another person's device", status == 200 and body['removed'] == 0)
# A shared laptop: the DL did not sign out, the ZL signs in on it. The page asks; the DL's reminders leave it.
state = call(zl, '/api/push/device', 'POST', {'endpoint': laptop['endpoint']})[1]
check("a shared device: the next person's check removes the previous person's reminders from it",
      state == {'subscribed': False, 'released': True}
      and not sql('SELECT 1 FROM portal.push_subscriptions WHERE endpoint=%s', (laptop['endpoint'],)), state)
status, body, _ = call(zl, '/api/push/device', 'POST', {'endpoint': 'http://127.0.0.1/x'})
check('a request without a proper endpoint -> 400 with a plain message', status == 400 and 'Reload' in body['error'])

# Sending: a network error keeps a device; 404/410 from the push service removes it.
ok_device, gone_device, offline_device = subscription('ok'), subscription('gone'), subscription('offline')
for device in (ok_device, gone_device, offline_device):
    call(ap, '/api/push/subscriptions', 'POST', device)


def fake_webpush(subscription_info, **kwargs):
    endpoint = subscription_info['endpoint']
    if 'offline' in endpoint:
        raise requests.ConnectionError('network down')
    if 'gone' in endpoint:
        raise WebPushException('gone', response=SimpleNamespace(status_code=410))


reference = f'zz-known-issues:{secrets.token_hex(4)}'
with patch.object(reminders, 'webpush', fake_webpush), patch.dict(os.environ, {'VAPID_PRIVATE_KEY': 'x', 'VAPID_SUBJECT': 'mailto:x@example.org'}):
    with api.db() as conn:
        delivered = reminders.push(conn, ap, 'event', reference, 'Test', 'Test', '/#calendar')
left = {r['endpoint'] for r in sql('SELECT endpoint FROM portal.push_subscriptions WHERE user_id=%s', (ap,))}
check('sending: delivered to the working device, the gone one removed, the offline one kept',
      delivered and ok_device['endpoint'] in left and offline_device['endpoint'] in left and gone_device['endpoint'] not in left)
sql('DELETE FROM portal.reminder_deliveries WHERE reference=%s', (reference,))
sql("DELETE FROM portal.push_subscriptions WHERE endpoint LIKE 'https://fcm.googleapis.com/fcm/send/zz-known-issues-%%'")

# 6. New Members baptized a year ago or more: archived by the reminders loop over the server connection ----------
# Migration 023 (people) takes EXECUTE away from PUBLIC, anon and signed-in users; do the same here first.
sql('REVOKE ALL ON FUNCTION public.archive_expired_new_members() FROM PUBLIC, anon, authenticated')
sql('GRANT EXECUTE ON FUNCTION public.archive_expired_new_members() TO service_role')
check('after 023, anon and signed-in users cannot archive',
      as_role('anon', 'SELECT public.archive_expired_new_members()') == '42501'
      and as_role('authenticated', 'SELECT public.archive_expired_new_members()') == '42501')
member = sql('''SELECT id FROM public.new_members WHERE follow_up_status='current' AND baptism_date IS NOT NULL
                ORDER BY id LIMIT 1''')
if member:
    sql("UPDATE public.new_members SET baptism_date=current_date-400 WHERE id=%s", (member[0]['id'],))
state = {}
with patch.object(reminders.log, 'info') as logged:
    count = reminders.daily_archive(datetime.now(UTC).replace(hour=12), state)
status = sql('SELECT follow_up_status FROM public.new_members WHERE id=%s', (member[0]['id'],))[0]['follow_up_status'] if member else None
check('the reminders loop archives them over the server connection and logs the count only',
      member and count >= 1 and status == 'ended' and logged.call_args[0][1] == count, (bool(member), count, status))
check('a second run the same day does nothing', reminders.daily_archive(datetime.now(UTC).replace(hour=13), state) is None)
check('running the function again archives nobody new', reminders.archive_expired_new_members() == 0)

print(f'{sum(results)} of {len(results)} checks passed')
sys.exit(0 if all(results) else 1)
