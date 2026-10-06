"""The reminder worker: push reminders for Weekly Planning and calendar meetings, and a daily clean-up.

What it is: a small program that runs on its own (the portal-reminders container, `python reminders.py`). Once a
minute it looks at every active account and sends a push message to their phones and computers when:
- it is Sunday 18:00 or later in the mission's time zone and their companionship's plan for the week is not submitted yet (and nobody
  of them worked on it in the last five minutes), or
- a calendar meeting they belong to starts soon (each event says how many minutes before).
Once a day, from 03:00 in the mission's time zone, it ends the follow-up of New Members baptized a year ago or more.
Who uses it: nobody calls it; it runs by itself. It uses app.py's database helpers and calendar rules.
How it fits: a database lock (pg_try_advisory_xact_lock) makes sure only one worker sends at a time, and
portal.reminder_deliveries remembers what was sent, so nobody gets the same reminder twice.
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pywebpush import WebPushException, webpush
from werkzeug.exceptions import HTTPException
from app import UTC, context_for, db, occurrences, rows, selected_language, visible
import mission_time
import push_texts

log = logging.getLogger('reminders')
logging.basicConfig(level=logging.INFO)
# The loop runs about once a minute, so a reminder stays due for at least this long; otherwise "At start"
# (0 minutes) and 1-minute reminders could fall between two runs. reminder_deliveries stops repeats.
REMINDER_GRACE = timedelta(minutes=5)
EVENT_HORIZON = timedelta(days=7)  # reminder_minutes is at most 10080 (7 days)
MISSION_TZ = mission_time.ZONE
COMPLETE = {'SUBMITTED', 'LOCKED'}


# ---------------------------------------------------------------------------------------------- sending
def push(conn, user_id, kind, reference, title, body, url):
    """Send one reminder to every device of a person, once. Returns True when at least one device got it."""
    if rows(conn, '''SELECT 1 FROM portal.reminder_deliveries WHERE user_id=%s AND kind=%s AND reference=%s''',
            (user_id, kind, reference)):
        return False
    subscriptions = rows(conn, 'SELECT * FROM portal.push_subscriptions WHERE user_id=%s', (user_id,))
    delivered = False
    for sub in subscriptions:
        try:
            webpush(subscription_info={'endpoint': sub['endpoint'], 'keys': sub['keys']},
                    data=json.dumps({'title': title, 'body': body, 'url': url, 'tag': f'{kind}-{reference}'}),
                    vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],
                    vapid_claims={'sub': os.environ['VAPID_SUBJECT']}, timeout=10, ttl=3600)
            delivered = True
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in {404, 410}:  # the browser unsubscribed or its subscription expired: forget that device
                rows(conn, 'DELETE FROM portal.push_subscriptions WHERE id=%s', (sub['id'],))
                log.info('Removed a device the push service reports as gone (status %s)', status)
            else:
                log.warning('Push provider failed with status %s', status)
        except Exception as exc:
            # A network error or timeout says nothing about the device, so it is kept (this used to delete it: one
            # outage on a Sunday evening removed everyone's reminders). The API stores only valid subscriptions.
            log.warning('Push to subscription %s failed (%s); it is kept for the next reminder',
                        sub['id'], type(exc).__name__)
    if delivered:
        rows(conn, '''INSERT INTO portal.reminder_deliveries(user_id,kind,reference) VALUES(%s,%s,%s)
            ON CONFLICT DO NOTHING''', (user_id, kind, reference))
    return delivered


# ---------------------------------------------------------------------------------------------- Weekly Planning
def planning_due(conn, c, now):
    """(due, reference): is the Sunday planning reminder due for c's area now? reference names the week ('YYYY-MM-DD')
    so it is sent once per week. Due from Sunday 18:00 in the mission's time zone while the week's plan (every ward or branch of the
    area) is not submitted and nobody has worked on it in the last five minutes."""
    local = now.astimezone(MISSION_TZ)
    if local.weekday() != 6 or local.hour < 18:
        return False, None
    sunday = local.date()
    units = rows(conn, '''SELECT unit_id FROM public.area_units WHERE area_id=%s AND active''', (c['area_id'],))
    reports = rows(conn, '''SELECT r.status,r.unit_id FROM public.weekly_area_reports r
        JOIN public.reporting_weeks w ON w.id=r.reporting_week_id WHERE r.area_id=%s AND w.sunday=%s''',
        (c['area_id'], sunday))
    statuses = {r['unit_id']: r['status'] for r in reports}
    if units:
        complete = bool(reports) and all(statuses.get(u['unit_id']) in COMPLETE for u in units)
    else:
        complete = bool(reports) and all(r['status'] in COMPLETE for r in reports)
    if complete:
        return False, str(sunday)
    return not worked_on_lately(conn, c['area_id'], sunday, now), str(sunday)


def worked_on_lately(conn, area_id, sunday, now):
    """Did anyone save this week's plan of the area in the last five minutes? Every save and every person added
    stamps the plan (planning._mark_worked_on) or an answer with the time, so the plan's own times tell."""
    cutoff = now - timedelta(minutes=5)
    recent = rows(conn, '''SELECT 1 FROM public.weekly_area_reports r JOIN public.reporting_weeks w ON w.id=r.reporting_week_id
        WHERE r.area_id=%s AND w.sunday=%s AND r.updated_at>%s
        UNION ALL SELECT 1 FROM public.weekly_planning_answers a
        JOIN public.weekly_area_reports r ON r.id=a.weekly_area_report_id
        JOIN public.reporting_weeks w ON w.id=r.reporting_week_id
        WHERE r.area_id=%s AND w.sunday=%s AND a.updated_at>%s LIMIT 1''',
        (area_id, sunday, cutoff, area_id, sunday, cutoff))
    return bool(recent)


# ---------------------------------------------------------------------------------------------- calendar meetings
def reminder_due(starts_at, minutes, now):
    """True from `minutes` before the start until the start, and for at least REMINDER_GRACE after it is due."""
    due_at = starts_at - timedelta(minutes=minutes)
    return due_at <= now < max(starts_at, due_at + REMINDER_GRACE)


def upcoming_events(conn, now):
    """Every event that can still have an occurrence in the reminder window (one query per cycle).
    One-off events store recurrence as JSON null, not SQL NULL."""
    return rows(conn, '''SELECT * FROM portal.events WHERE starts_at<=%s
        AND (jsonb_typeof(recurrence)='object' OR ends_at>=%s) ORDER BY starts_at''',
        (now + EVENT_HORIZON, now - REMINDER_GRACE))


def due_events(events, c, now):
    """Occurrences whose reminder is due for this user. Only the event's audience (its roles and zones, as
    visible(..., allow_admin=False) decides for attendance) is reminded, not every manager or office account
    that may see or edit the event."""
    due = []
    for event in events:
        if not visible(event, c, event=True, allow_admin=False):
            continue
        for o in occurrences(event, now - REMINDER_GRACE, now + EVENT_HORIZON):
            if now < o['ends_at'] and reminder_due(o['starts_at'], o['reminder_minutes'], now):
                due.append(o)
    return due


def event_message(event, language='en'):
    """The text under a meeting reminder's title: the place, else "starts now" or "starts soon"."""
    if event['location']:
        return event['location']
    return push_texts.text(language, 'push.meetingNow' if event['reminder_minutes'] == 0 else 'push.meetingSoon')


def reminder_language(conn, c):
    """The person's interface language for push texts: chosen in the portal, else primary, else English."""
    rows(conn, 'SAVEPOINT reminder_language')  # a failed lookup must not undo the person's other reminders
    try:
        language = push_texts.language_code(selected_language(conn, c))
        rows(conn, 'RELEASE SAVEPOINT reminder_language')
        return language
    except Exception:
        rows(conn, 'ROLLBACK TO SAVEPOINT reminder_language')
        log.warning('Reminder language lookup failed; English is used')
        return 'en'


# ---------------------------------------------------------------------------------------------- one cycle
def remind_person(conn, c, now, events, send, result):
    """Everything due for one person in this cycle: the planning reminder (only accounts with an area: Weekly
    Planning belongs to a companionship's area) and every meeting reminder. Counts go into result."""
    language = None  # looked up only when something is due
    if c.get('area_id'):
        due, reference = planning_due(conn, c, now)
        if due:
            result['planning_due'] += 1
            if send:
                language = language or reminder_language(conn, c)
                result['sent'] += push(conn, c['user_id'], 'planning', reference,
                                       push_texts.text(language, 'push.planningDueTitle'),
                                       push_texts.text(language, 'push.planningDueBody'), '/#planning')
    for event in due_events(events, c, now):
        result['event_due'] += 1
        if send:
            language = language or reminder_language(conn, c)
            result['sent'] += push(conn, c['user_id'], 'event', f"{event['id']}:{event['occurrence']}",
                                   event['title'], event_message(event, language), '/#calendar')


def run_once(now=None, send=True):
    """One cycle over every active account. send=False only counts what is due (for checks)."""
    now = now or datetime.now(UTC)
    result = {'planning_due': 0, 'event_due': 0, 'sent': 0}
    with db() as conn:
        if not rows(conn, "SELECT pg_try_advisory_xact_lock(9471801) AS locked")[0]['locked']:
            return result  # another worker is in the middle of a cycle
        # Accounts without an area (office, president, data analysts) are not left out of event reminders here:
        # context_for gives a staff account its home mission (migration 027); other area-less accounts are skipped.
        users = rows(conn, '''SELECT DISTINCT user_id FROM public.current_user_context WHERE user_active''')
        events = upcoming_events(conn, now)
        for user in users:
            # One person's failure must not stop the others: each person gets a savepoint.
            rows(conn, 'SAVEPOINT reminder_user')
            try:
                try:
                    c = context_for(conn, user['user_id'])
                except HTTPException:
                    continue  # no current assignment or mission: nothing to remind
                remind_person(conn, c, now, events, send, result)
            except Exception:
                rows(conn, 'ROLLBACK TO SAVEPOINT reminder_user')
                log.exception('Reminder evaluation failed')
            finally:
                rows(conn, 'RELEASE SAVEPOINT reminder_user')
    return result


# ---------------------------------------------------------------------------------------------- daily clean-up
# New Members baptized a year ago or more end their follow-up through public.archive_expired_new_members(). pg_cron
# is not installed, so this loop runs it once a day over the server connection (postgres, the function's owner;
# migration 023 takes it away from signed-in users). From 03:00 in the mission's time zone, when the database's (UTC) date is the
# same day as in the mission's time zone. Running it twice does nothing more.
ARCHIVE_HOUR = 3
ARCHIVE_RETRY = timedelta(hours=1)


def archive_expired_new_members():
    """Run the database's yearly archive of New Members; returns how many were archived."""
    with db() as conn:
        return rows(conn, 'SELECT public.archive_expired_new_members() AS archived')[0]['archived']


def daily_archive(now, state, archive=None):
    """Runs the archive once per day of the mission's time zone from ARCHIVE_HOUR; after a failure again an hour later.
    state is kept by the loop ({'done_on': date, 'retry_at': datetime}). Returns the count, or None if not run."""
    local = now.astimezone(MISSION_TZ)
    if local.hour < ARCHIVE_HOUR or state.get('done_on') == local.date() or now < (state.get('retry_at') or now):
        return None
    try:
        count = (archive or archive_expired_new_members)()
    except Exception:
        state['retry_at'] = now + ARCHIVE_RETRY
        log.exception('Archiving New Members baptized a year ago failed; trying again in an hour')
        return None
    state.update(done_on=local.date(), retry_at=None)
    log.info('Archived %s New Members baptized a year ago or more', count)
    return count


def main():
    """The worker's endless loop: one cycle a minute, and the daily archive when it is due."""
    archive_state = {}
    while True:
        try:
            result = run_once()
            if result['sent']:
                log.info('Delivered %s reminders', result['sent'])
        except Exception:
            log.exception('Reminder cycle failed; retrying next minute')
        daily_archive(datetime.now(UTC), archive_state)
        time.sleep(60)


if __name__ == '__main__':
    main()
