"""The round-3 "small" fixes against a THROWAWAY database copy (migrations up to 027 applied, like live Beta).

- The event attendance list offers staff accounts (President, Office, Data Analyst without an area, migration 027)
  of the event's mission, lists everyone once and by name, and attendance can be recorded for them.
- An upload whose attachment row cannot be stored (insert or commit refused) leaves no file in /data/uploads; one
  whose commit answer is lost after the database committed keeps its file, so the attachment still downloads.
- A person action on a plan sends back the "Add from database" lists, the same ones the form has.

Refuses unless DATABASE_URL names a database containing "test" and SMALL_TEST_THROWAWAY=yes: it creates accounts,
events, files, plans and people. Identity lookups are replaced in-process (as in staff_accounts_db.py); database
roles, row-level security and the routes are real. Prints only counts, ids and PASS/FAIL, never names.

Run inside a temporary portal-api container (uploads go to the container's own /data/uploads):
  python tests/small_fixes_db.py
"""
import base64
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote, urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('SMALL_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')

import app as api  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
client = api.app.test_client()
results = []


def check(name, ok, detail=''):
    if callable(ok):  # evaluated here, so a missing key in a reply counts as a failed check
        try:
            ok = ok()
        except Exception as error:  # noqa: BLE001
            ok, detail = False, f'{type(error).__name__}: {error} {detail}'
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:400]}' if detail != '' and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.fixture'


def call(user, method, path, body=None, **kwargs):
    if body is not None:
        kwargs['json'] = body
    response = client.open(path, method=method, headers={'Authorization': 'Bearer ' + token(user)}, **kwargs)
    return response.status_code, response.get_json(silent=True)


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def account(key, role, mission=2, active=True, missionary=None):
    """A sign-in: a staff account (no missionary, a home mission) or, with missionary=, a missionary's account."""
    user = str(uuid.uuid4())
    sql("""INSERT INTO auth.users(id,instance_id,aud,role,email)
           VALUES(%s,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s)""",
        (user, f'small-db-{key}@example.invalid'))
    if missionary:
        sql('INSERT INTO public.user_profiles(id,missionary_id,app_role,active) VALUES(%s,%s,%s,true)', (user, missionary, role))
    else:
        sql("""INSERT INTO public.user_profiles(id,missionary_id,app_role,active,display_name,home_mission_id)
               VALUES(%s,NULL,%s,%s,%s,%s)""", (user, role, active, f'Zz Staff {key}', mission))
    people[key] = user
    return user


other_mission = sql("INSERT INTO public.missions(name) VALUES ('Small fixes test mission') RETURNING id")[0]['id']
people, events, extra_leadership = {}, [], []
upload_dir = Path('/data/uploads')
upload_dir.mkdir(parents=True, exist_ok=True)

try:
    president, office, analyst = account('president', 'PRESIDENT'), account('office', 'OFFICE'), account('analyst', 'DATA_ADMIN')
    turned_off, elsewhere = account('off', 'PRESIDENT', active=False), account('elsewhere', 'PRESIDENT', other_mission)
    zone = sql('SELECT id FROM public.zones WHERE mission_id=2 ORDER BY id LIMIT 1')[0]['id']

    # ---------- 1. Attendance: staff accounts are offered for their mission ----------
    now = datetime.now(timezone.utc).replace(microsecond=0)
    past = {'title': 'Zz attendance test', 'description': '', 'starts_at': (now - timedelta(hours=3)).isoformat(),
            'ends_at': (now - timedelta(hours=2)).isoformat(), 'roles': [], 'zone_ids': [], 'location': '',
            'meeting_url': '', 'reminder_minutes': 30}

    def new_event(**changes):
        status, body = call(office, 'POST', '/api/events', dict(past, **changes))
        assert status == 200, (status, body)
        events.append(body['event']['id'])
        return body['event']['id']

    def attendance(event_id, user=office):
        return call(user, 'GET', f'/api/events/{event_id}/attendance?occurrence={quote(past["starts_at"])}')

    everyone = new_event()
    status, body = attendance(everyone)
    listed = [u['user_id'] for u in (body or {}).get('users', [])]
    check('Office opens the attendance list of an event for everyone', status == 200, (status, body))
    check('the President, Office and Data Analyst staff accounts are offered',
          all(u in listed for u in (president, office, analyst)), [u in listed for u in (president, office, analyst)])
    check('a turned-off staff account and another mission\'s President are not',
          turned_off not in listed and elsewhere not in listed)
    missionaries = {str(r['user_id']) for r in sql('''SELECT user_id FROM public.current_user_context
        WHERE user_active AND mission_id=2 AND area_id IS NOT NULL''')}
    check('the missionaries of the mission are still offered', missionaries and missionaries <= set(listed),
          (len(missionaries), len(missionaries & set(listed))))
    check('everyone is listed once', len(listed) == len(set(listed)), len(listed) - len(set(listed)))
    names = [str(u['name'] or '').casefold() for u in body['users']]
    check('the list is in name order', names == sorted(names))

    status, body = call(office, 'POST', f'/api/events/{everyone}/attendance',
                        {'occurrence': past['starts_at'], 'attendance': [{'user_id': president, 'attended': True},
                                                                         {'user_id': analyst, 'attended': False}]})
    check('attendance can be recorded for staff accounts', status == 200, (status, body))
    status, body = attendance(everyone)
    recorded = {str(a['user_id']): a['attended'] for a in (body or {}).get('attendance', [])}
    check('and is read back once each', status == 200 and recorded == {president: True, analyst: False}
          and len(body['attendance']) == 2, recorded)
    status, body = call(office, 'POST', f'/api/events/{everyone}/attendance',
                        {'occurrence': past['starts_at'], 'attendance': [{'user_id': elsewhere, 'attended': True}]})
    check('another mission\'s President cannot be recorded (403)', status == 403, (status, body))

    for_president = new_event(roles=['PRESIDENT'])
    status, body = attendance(for_president)
    listed = [u['user_id'] for u in (body or {}).get('users', [])]
    check('an event for the President offers the President, not Office', president in listed and office not in listed, status)

    for_zone = new_event(zone_ids=[zone])
    status, body = attendance(for_zone)
    listed = [u['user_id'] for u in (body or {}).get('users', [])]
    check('an event for one zone does not offer staff accounts (they have no zone)',
          status == 200 and not {president, office, analyst} & set(listed), status)
    status, body = call(office, 'POST', f'/api/events/{for_zone}/attendance',
                        {'occurrence': past['starts_at'], 'attendance': [{'user_id': president, 'attended': True}]})
    check('and refuses to record them there (403)', status == 403, (status, body))

    # Someone with two current leadership rows has two rows in current_user_context: still listed once.
    leader = sql('''SELECT user_id, missionary_id, zone_id FROM public.current_user_context
                    WHERE user_active AND mission_id=2 AND leadership_role='DL' ORDER BY user_id LIMIT 1''')
    if leader:
        extra_leadership.append(sql('''INSERT INTO public.leadership_assignments(missionary_id,role,zone_id,mission_id,start_date)
            VALUES(%s,'STL',%s,2,current_date-1) RETURNING id''', (leader[0]['missionary_id'], leader[0]['zone_id']))[0]['id'])
        rows_now = sql('SELECT count(*) AS n FROM public.current_user_context WHERE user_id=%s', (leader[0]['user_id'],))[0]['n']
        status, body = attendance(everyone)
        listed = [u['user_id'] for u in (body or {}).get('users', [])]
        leader_id = str(leader[0]['user_id'])
        check('a leader with two leadership rows is listed once', rows_now == 2 and listed.count(leader_id) == 1,
              (rows_now, listed.count(leader_id)))
    else:
        check('a DL to give a second leadership row', False, 'no DL in mission 2 on this copy')

    # ---------- 2. Uploads: no file is left when the row cannot be stored ----------
    sql('''CREATE OR REPLACE FUNCTION public.zz_small_test_refuse_attachment() RETURNS trigger LANGUAGE plpgsql AS $$
           BEGIN IF NEW.filename = 'zz-refused.txt' THEN RAISE EXCEPTION 'refused by the test'; END IF; RETURN NEW; END $$''')
    sql('''CREATE TRIGGER zz_small_test_refuse BEFORE INSERT ON portal.attachments
           FOR EACH ROW EXECUTE FUNCTION public.zz_small_test_refuse_attachment()''')
    before = sorted(p.name for p in upload_dir.iterdir())
    with patch.object(api.app.logger, 'exception'):  # the expected 500 would print a traceback
        status, body = call(office, 'POST', f'/api/events/{everyone}/attachments',
                            data={'file': (io.BytesIO(b'refused'), 'zz-refused.txt')}, content_type='multipart/form-data')
    after = sorted(p.name for p in upload_dir.iterdir())
    check('an upload whose row is refused fails (500)', status == 500, (status, body))
    check('and leaves no file behind', after == before, (len(before), len(after)))
    check('and no attachment row', not sql("SELECT 1 FROM portal.attachments WHERE filename='zz-refused.txt'"))
    status, body = call(office, 'POST', f'/api/events/{everyone}/attachments',
                        data={'file': (io.BytesIO(b'kept'), 'zz-kept.txt')}, content_type='multipart/form-data')
    stored = sql("SELECT storage_name FROM portal.attachments WHERE filename='zz-kept.txt'")
    check('a normal upload still stores its row and its file', status == 200 and len(stored) == 1
          and (upload_dir / stored[0]['storage_name']).read_bytes() == b'kept', (status, body))

    # The database refuses the commit itself (a deferred check fails at COMMIT): no row, so no file.
    sql('''CREATE OR REPLACE FUNCTION public.zz_small_test_refuse_attachment_at_commit() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'refused at commit by the test'; END $$''')
    sql('''CREATE CONSTRAINT TRIGGER zz_small_test_refuse_at_commit AFTER INSERT ON portal.attachments
           DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.filename = 'zz-refused-at-commit.txt')
           EXECUTE FUNCTION public.zz_small_test_refuse_attachment_at_commit()''')
    before = sorted(p.name for p in upload_dir.iterdir())
    with patch.object(api.app.logger, 'exception'):
        status, body = call(office, 'POST', f'/api/events/{everyone}/attachments',
                            data={'file': (io.BytesIO(b'refused at commit'), 'zz-refused-at-commit.txt')},
                            content_type='multipart/form-data')
    after = sorted(p.name for p in upload_dir.iterdir())
    check('an upload whose commit is refused fails (500)', status == 500, (status, body))
    check('and leaves no file behind either', after == before, (len(before), len(after)))
    check('and no attachment row', not sql("SELECT 1 FROM portal.attachments WHERE filename='zz-refused-at-commit.txt'"))

    # The database commits, but the answer is lost on the way back (the connection breaks): commit() raises, the
    # row is stored all the same, so its file must stay and the attachment must still download.
    class LostCommitAnswer(api.psycopg2.extensions.connection):
        lose_next_answer = False

        def commit(self):
            super().commit()
            if self.lose_next_answer:
                self.lose_next_answer = False
                raise api.psycopg2.OperationalError('test: the answer to COMMIT was lost')

    real_rows = api.rows

    def marking_rows(conn, query, args=()):
        result = real_rows(conn, query, args)
        if 'INSERT INTO portal.attachments' in query and isinstance(conn, LostCommitAnswer):
            conn.lose_next_answer = True
        return result

    def lossy_connect():
        return api.psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=api.RealDictCursor, connect_timeout=8,
                                    connection_factory=LostCommitAnswer)

    with patch.object(api, 'connect', lossy_connect), patch.object(api, 'rows', marking_rows), \
            patch.object(api.app.logger, 'exception'):
        status, body = call(office, 'POST', f'/api/events/{everyone}/attachments',
                            data={'file': (io.BytesIO(b'committed'), 'zz-answer-lost.txt')},
                            content_type='multipart/form-data')
    stored = sql("SELECT id, storage_name FROM portal.attachments WHERE filename='zz-answer-lost.txt'")
    check('an upload whose commit answer is lost fails (500)', status == 500, (status, body))
    check('but its row was stored, and its file is kept', lambda: len(stored) == 1
          and (upload_dir / stored[0]['storage_name']).read_bytes() == b'committed', len(stored))
    if stored:
        response = client.get(f'/api/attachments/{stored[0]["id"]}', headers={'Authorization': 'Bearer ' + token(office)})
        check('and the attachment still downloads', response.status_code == 200 and response.data == b'committed',
              response.status_code)
    sql('DROP TRIGGER zz_small_test_refuse_at_commit ON portal.attachments')
    sql('DROP FUNCTION public.zz_small_test_refuse_attachment_at_commit()')
    sql('DROP TRIGGER zz_small_test_refuse ON portal.attachments')
    sql('DROP FUNCTION public.zz_small_test_refuse_attachment()')

    # ---------- 3. Person actions send back the "Add from database" lists ----------
    fixture = sql('''SELECT ma.missionary_id, ma.area_id FROM public.current_missionary_assignments ma
        WHERE ma.mission_id=2 AND NOT EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.missionary_id=ma.missionary_id)
          AND (SELECT count(*) FROM public.area_units au JOIN public.units u ON u.id=au.unit_id
               WHERE au.area_id=ma.area_id AND au.active AND u.active) >= 2
        ORDER BY ma.area_id, ma.missionary_id LIMIT 1''')
    if not fixture:
        check('an area with two wards or branches and a missionary without an account', False, 'none on this copy')
    else:
        area_id = fixture[0]['area_id']
        companion = account('companion', 'MISSIONARY', missionary=fixture[0]['missionary_id'])
        status, form = call(companion, 'GET', '/api/planning/form')
        check('the companionship opens its plan', status == 200, (status, form))
        report_id, unit_id = form['report']['report_id'], form['report']['unit_id']
        sql("UPDATE public.weekly_area_reports SET status='DRAFT', submitted_at=NULL, submitted_by=NULL WHERE id=%s", (report_id,))
        other_unit = sql('''SELECT au.unit_id FROM public.area_units au JOIN public.units u ON u.id=au.unit_id
            WHERE au.area_id=%s AND au.active AND u.active AND au.unit_id<>%s ORDER BY au.unit_id LIMIT 1''',
                         (area_id, unit_id))[0]['unit_id']
        base = f'/api/planning/reports/{report_id}/people'
        status, created = call(companion, 'POST', f'{base}/baptismal',
                               {'first_name': 'Zz Small', 'last_name': 'Friend', 'finding_source': 'Media/Referral'})
        friend = created['id']
        status, form = call(companion, 'GET', '/api/planning/form')
        ids = lambda lists, kind: [p['id'] for p in lists[kind]]  # noqa: E731
        check('a friend on the plan is not offered under "Add from database"',
              lambda: friend not in ids(form['available_people'], 'baptismal_friends'))
        status, body = call(companion, 'POST', f'{base}/baptismal_friends/{friend}/transfer',
                            {'area_id': area_id, 'unit_id': other_unit})
        check('moving the friend to another ward or branch of the area works', status == 200, (status, body))
        check('the reply lists the friend under "Add from database" at once',
              lambda: friend in ids(body['available_people'], 'baptismal_friends')
              and all(p['baptismal_date_person_id'] != friend for p in body['people']['baptismal_friends']))
        status, form = call(companion, 'GET', '/api/planning/form')
        check('the reply has the same lists as the form', lambda: status == 200 and body['available_people'] == form['available_people'])
        status, body = call(companion, 'POST', f'{base}/existing_baptismal', {'person_id': friend})
        check('added again from the database', status in (200, 201), (status, body))
        status, form = call(companion, 'GET', '/api/planning/form')
        check('and then no longer offered', lambda: friend not in ids(form['available_people'], 'baptismal_friends'))
finally:
    for event_id in events:
        files = sql('SELECT storage_name FROM portal.attachments WHERE event_id=%s', (event_id,))
        sql('DELETE FROM portal.events WHERE id=%s', (event_id,))
        api.remove_stored_files(files)
    sql('DROP TRIGGER IF EXISTS zz_small_test_refuse ON portal.attachments')
    sql('DROP FUNCTION IF EXISTS public.zz_small_test_refuse_attachment()')
    sql('DROP TRIGGER IF EXISTS zz_small_test_refuse_at_commit ON portal.attachments')
    sql('DROP FUNCTION IF EXISTS public.zz_small_test_refuse_attachment_at_commit()')
    for row_id in extra_leadership:
        sql('DELETE FROM public.leadership_assignments WHERE id=%s', (row_id,))
    for key, user in people.items():
        try:
            sql('DELETE FROM auth.users WHERE id=%s', (user,))
        except Exception as error:  # noqa: BLE001 - a plan or person row may still point to the companion
            print(f'note: account {key} kept ({type(error).__name__}); the throwaway database is dropped anyway')
    sql('DELETE FROM public.missions WHERE id=%s', (other_mission,))

print(f'{sum(results)}/{len(results)} passed', flush=True)
sys.exit(0 if all(results) else 1)
