"""Run one reminder cycle against a THROWAWAY database copy, with push replaced by a recorder.

Adds three calendar events (titles start with "zz-reminder-test"), runs reminders.run_once at a fixed
Sunday-evening time and deletes the events again. Nothing is sent and no delivery rows are written.
Refuses unless DATABASE_URL names a database containing "test" and REMINDERS_TEST_THROWAWAY=yes.

Run inside a temporary portal-api container:  python tests/reminders_db.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('REMINDERS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes events and needs a throwaway *test* database.')

import app as api  # noqa: E402
import reminders  # noqa: E402

NOW = datetime(2026, 9, 27, 17, 5, tzinfo=timezone.utc)  # Sunday 19:05 in Berlin: planning reminders are due too
MINUTE = timedelta(minutes=1)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


leaders = {r['leadership_role']: r for r in sql('''SELECT DISTINCT ON (leadership_role) user_id,leadership_role,zone_id,mission_id
    FROM public.current_user_context WHERE user_active AND leadership_role IN ('ZL','AP') ORDER BY leadership_role,user_id''')}
zl, ap = leaders['ZL'], leaders['AP']
assert zl['zone_id'] != ap['zone_id'], 'needs a ZL and an AP in different zones'
people = {str(r['user_id']): r for r in sql('''SELECT DISTINCT ON (user_id) user_id,app_role,leadership_role,zone_id,area_id,
    mission_id FROM public.current_user_context WHERE user_active ORDER BY user_id,leadership_role NULLS LAST''')}
label = lambda uid: (people[uid]['leadership_role'] or people[uid]['app_role']) + ('' if people[uid]['area_id'] else ' (no area)')
events = [('zz-reminder-test at start, zone of the ZL', NOW - 2 * MINUTE, 0, [zl['zone_id']]),
          ('zz-reminder-test in 10 min, zone of the ZL', NOW + 10 * MINUTE, 30, [zl['zone_id']]),
          ('zz-reminder-test in 5 min, whole mission', NOW + 5 * MINUTE, 15, [])]
ids = []
try:
    for title, start, minutes, zones in events:
        ids.append(sql('''INSERT INTO portal.events(mission_id,author_id,title,starts_at,ends_at,reminder_minutes,zone_ids)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (zl['mission_id'], ap['user_id'], title, start,
                                                         start + timedelta(hours=1), minutes, zones))[0]['id'])
    titles = dict(zip([str(i) for i in ids], [e[0] for e in events]))
    sent = []

    def record(conn, user_id, kind, reference, title, body, url):
        sent.append((label(str(user_id)), kind, titles.get(reference.split(':')[0], reference)))
        return False  # nothing delivered, so nothing is written to reminder_deliveries

    deliveries = sql('SELECT count(*) AS n FROM portal.reminder_deliveries')[0]['n']
    with patch.object(reminders, 'push', record), patch.object(reminders.log, 'exception') as failed:
        result = reminders.run_once(NOW)
    print(f'{len(people)} active accounts: ' + ', '.join(sorted(label(u) for u in people)))
    for line in sorted(sent):
        print('  ', *line)
    print('run_once result', result, '| evaluation errors logged:', failed.call_count,
          '| reminder_deliveries unchanged:', sql('SELECT count(*) AS n FROM portal.reminder_deliveries')[0]['n'] == deliveries)
finally:
    sql('DELETE FROM portal.events WHERE id=ANY(%s)', (ids,))
