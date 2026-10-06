"""TEST ONLY: a made-up portal API plus the portal files, for browser checks of the calendar, announcements and
the portal shell's reminders switch and sign-out, without a database and without personal data.

Serves portal/ (mounted at /portal) on port 8080 and answers the /api/ calls those pages make from an in-memory
sample mission. index.html is index.template.html with a dummy public key. Every change is kept in memory and
listed at /stub/log, so a browser script can check which requests the page sent. Bearer tokens are not checked.
Supabase (port 18000) is never contacted: the browser script replaces fetch() for it inside the page.

  docker run --rm --name gfm-test-bugs-web --memory 256m -p 127.0.0.1:18071:8080 \
      -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/portal_stub_api.py
"""
import copy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

PORTAL = Path('/portal')
BERLIN = ZoneInfo('Europe/Berlin')
app = Flask(__name__)
log = []

today = datetime.now(BERLIN).replace(hour=19, minute=0, second=0, microsecond=0)
first = today + timedelta(days=1)
SERIES = {'id': 'e-weekly', 'title': 'District council', 'description': 'Counsel together about the people we teach.',
          'location': 'Chapel, room 2', 'meeting_url': '', 'timezone': 'Europe/Berlin', 'roles': [], 'zone_ids': [],
          'reminder_minutes': 30, 'author_id': 'u-ap',
          'recurrence': {'frequency': 'weekly', 'interval': 1, 'until': (first + timedelta(days=15)).isoformat()},
          'attachments': [{'id': 'a-1', 'filename': 'Präsentation – Größe ÄÖÜ.pdf', 'mime_type': 'application/pdf',
                           'bytes': 12}]}
SINGLE = {'id': 'e-single', 'title': 'Zone conference', 'description': 'Bring your Preach My Gospel.',
          'location': 'Stake centre', 'meeting_url': 'https://example.org/meet', 'timezone': 'Europe/Berlin',
          'roles': [], 'zone_ids': [], 'reminder_minutes': 60, 'author_id': 'u-ap', 'recurrence': None,
          'attachments': [{'id': 'a-2', 'filename': 'Tagesordnung für Sonntag.docx', 'mime_type': 'application/octet-stream',
                           'bytes': 8}]}
state = {'skipped': set(), 'events': {'e-weekly': SERIES, 'e-single': SINGLE},
         'announcements': [
             {'id': 'n-1', 'title': 'Transfers next week', 'body': 'Transfer calls are on Saturday.', 'pinned': True,
              'urgent': False, 'created_at': today.isoformat(), 'expires_at': None, 'read_at': None, 'can_edit': True,
              'roles': [], 'zone_ids': [], 'district_ids': [], 'area_ids': [], 'user_ids': [],
              'attachments': [{'id': 'a-3', 'filename': 'Übersicht der Zonen.pdf', 'mime_type': 'application/pdf',
                               'bytes': 5}]}],
         'device': 'https://fcm.googleapis.com/fcm/send/stub-device'}


def viewer():
    return request.headers.get('Authorization', '').split('.')[1] if '.' in request.headers.get('Authorization', '') else ''


def editor():
    return 'missionary' not in request.headers.get('Authorization', '')


def occurrences():
    shown = []
    series = state['events'].get('e-weekly')
    if series:
        for week in range(3):
            start = first + timedelta(days=7 * week)
            if start.date() in state['skipped']:
                continue
            shown.append(dict(copy.deepcopy(series), starts_at=start.isoformat(), ends_at=(start + timedelta(hours=1)).isoformat(),
                              occurrence=start.isoformat(), series_starts_at=first.isoformat(),
                              series_ends_at=(first + timedelta(hours=1)).isoformat()))
    single = state['events'].get('e-single')
    if single:
        start = first + timedelta(days=3, hours=-9)
        shown.append(dict(copy.deepcopy(single), starts_at=start.isoformat(), ends_at=(start + timedelta(hours=6)).isoformat(),
                          occurrence=start.isoformat()))
    return sorted(shown, key=lambda e: e['starts_at'])


@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def index():
    html = (PORTAL / 'index.template.html').read_text(encoding='utf-8').replace('__ANON_KEY__', 'eyJ-stub-anon-key')
    return Response(html, mimetype='text/html')


@app.get('/<path:name>')
def files(name):
    if name.startswith('api/') or name.startswith('stub/'):
        return jsonify(error='Not in the stub.'), 404
    return send_from_directory(PORTAL, name)


@app.get('/stub/log')
def stub_log():
    return jsonify(log=log)


@app.post('/stub/reset')
def stub_reset():
    """Clears the request log; this browser gets reminders again (the off switch may have removed it)."""
    log.clear()
    state['device'] = 'https://fcm.googleapis.com/fcm/send/stub-device'
    return jsonify(ok=True)


@app.get('/api/options')
def options():
    return jsonify(roles=['MISSIONARY', 'DL', 'ZL', 'STL', 'OFFICE', 'AP', 'PRESIDENT', 'DATA_ADMIN'],
                   zones=[{'id': 5, 'name': 'North Zone'}], districts=[{'id': 51, 'name': 'Riverside', 'zone_id': 5}],
                   areas=[{'id': 511, 'name': 'Riverside North', 'district_id': 51, 'zone_id': 5}], users=[],
                   can_edit_calendar=editor(), can_publish=editor(), role='AP' if editor() else 'MISSIONARY')


@app.get('/api/events')
def events():
    return jsonify(events=occurrences(), can_edit=editor())


@app.delete('/api/events/<event_id>')
def event_delete(event_id):
    log.append({'method': 'DELETE', 'path': request.path, 'occurrence': request.args.get('occurrence')})
    if not editor():
        return jsonify(error='Only calendar editors may delete events.'), 403
    occurrence = request.args.get('occurrence')
    if occurrence and state['events'][event_id]['recurrence']:
        state['skipped'].add(datetime.fromisoformat(occurrence).astimezone(BERLIN).date())
        return jsonify(ok=True, deleted='occurrence')
    state['events'].pop(event_id, None)
    return jsonify(ok=True, deleted='event')


@app.get('/api/announcements')
def announcements():
    return jsonify(announcements=state['announcements'], can_publish=editor())


@app.delete('/api/announcements/<item_id>')
def announcement_delete(item_id):
    log.append({'method': 'DELETE', 'path': request.path})
    state['announcements'] = [a for a in state['announcements'] if a['id'] != item_id]
    return jsonify(ok=True)


@app.post('/api/announcements/<item_id>/read')
def announcement_read(item_id):
    return jsonify(ok=True)


@app.route('/api/attachments/<attachment_id>', methods=['GET', 'DELETE'])
def attachment(attachment_id):
    every = [f for e in state['events'].values() for f in e['attachments']] + \
            [f for a in state['announcements'] for f in a['attachments']]
    found = next((f for f in every if f['id'] == attachment_id), None)
    if request.method == 'GET':
        if not found:
            return jsonify(error='This attachment is no longer available.'), 404
        return send_file(__file__, as_attachment=True, download_name=found['filename'])
    log.append({'method': 'DELETE', 'path': request.path})
    for record in list(state['events'].values()) + state['announcements']:
        record['attachments'] = [f for f in record['attachments'] if f['id'] != attachment_id]
    return jsonify(ok=True) if found else (jsonify(error='This attachment was already removed. Reload the page.'), 404)


@app.get('/api/languages')
def languages():
    return jsonify(primary='en', allowed=['en', 'de'], selected='en')


@app.put('/api/languages')
def language_save():
    return jsonify(ok=True, selected=(request.json or {}).get('language', 'en'))


@app.get('/api/push/config')
def push_config():
    return jsonify(public_key='BStub', subscribed=bool(state['device']), devices=1 if state['device'] else 0,
                   required=True, reminder='stub')


@app.post('/api/push/device')
def push_device():
    endpoint = (request.json or {}).get('endpoint')
    log.append({'method': 'POST', 'path': request.path, 'endpoint': endpoint})
    return jsonify(subscribed=bool(state['device']) and endpoint == state['device'], released=False)


@app.delete('/api/push/subscriptions')
def push_unsubscribe():
    endpoint = (request.json or {}).get('endpoint')
    log.append({'method': 'DELETE', 'path': request.path, 'endpoint': endpoint,
                'authorization': request.headers.get('Authorization', '')[:13]})
    removed = int(endpoint == state['device'])
    if removed:
        state['device'] = None
    return jsonify(ok=True, removed=removed)


@app.get('/api/overview')
def overview():
    return jsonify(planning={}, events=occurrences()[:5], announcements=state['announcements'],
                   mission_focus={'focus': None}, inspiration={'reference': 'Alma 37:6', 'text': 'By small and simple things.'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
