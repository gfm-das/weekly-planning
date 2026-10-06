"""Whiteboards (whiteboards.py, migration 031) through the real portal routes, against a THROWAWAY database copy.

Refuses unless DATABASE_URL names a database containing "test" and WHITEBOARDS_TEST_THROWAWAY=yes. Apply migration
031 first (as postgres, after the live order of 024, 025, 019, the hotfix replay, 028, 029, 019, 030, 019).
It changes app_role and additional_roles of two accounts for a moment (one account without leadership is, in turn,
Office, a missionary and the President; the DL is also a Data Analyst for a while), adds a second mission, and creates and
deletes boards; everything is put back or removed at the end. Identity lookups are replaced in-process (as in
roles_db.py); the database, its rights and constraints are the real ones. Prints counts, statuses and ids only.

Checks:
- access per role: AP, President and Data Analyst (also as an additional role on a DL) may list, create, open,
  save, rename, copy and delete every board of their mission; DL, ZL, Office and a missionary get 403 everywhere and
  change nothing;
- a board is shared: what one manager saves, the others open; "last saved by" names who saved;
- version conflicts: a save with an old version is refused (409, "someone else saved") and changes nothing; of two
  saves with the same version at the same moment exactly one wins; renaming keeps the version;
- limits: names (unique in the mission, letter case ignored), a picture over 2 MB, more than 60 pictures, more than
  12 MB of pictures, a drawing over 3 MB (each 413 with its sentence, and the board as it was); the drawing measured
  as the database measures it (jsonb text), and a drawing the table itself refuses answered with the same 413 and
  sentence, never a 500; the table constraints refuse the same even without portal-api;
- no 'iframe' element is ever stored (Excalidraw would run its HTML), even with our chart link, and generationData
  is taken off every element; the list never reads a drawing (no size in it);
- pictures: kept once, forgotten when no element uses them, deleted with the board; Duplicate (copy_of) and "Keep
  mine" (files_from) copy them on the server, never from another mission;
- other missions: their boards are invisible (404) and cannot be copied;
- rights: anon, authenticated, service_role and gfm_dashboard_reader cannot read the tables; row security is on.

Run inside a temporary portal-api container on the test network:
  python tests/whiteboards_db.py
"""
import base64
import json
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('WHITEBOARDS_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to run: this test writes data and needs a throwaway *test* database.')
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'whiteboards-db-test')

import psycopg2  # noqa: E402
import app as api  # noqa: E402
import whiteboards as wb  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
results = []


def check(name, ok, detail=''):
    if callable(ok):
        try:
            ok = ok()
        except Exception as error:  # noqa: BLE001
            ok, detail = False, f'{type(error).__name__}: {error} {detail}'
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (f' - {str(detail)[:300]}' if detail != '' and not ok else ''), flush=True)


def token(user_id):
    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v, separators=(',', ':')).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc(
        {'sub': str(user_id), 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 600}) + '.fixture'


def call(user, method, path, body=None):
    response = api.app.test_client().open(path, method=method, json=body, headers={'Authorization': 'Bearer ' + token(user)})
    return response.status_code, response.get_json(silent=True) or {}


def sql(query, args=()):
    with api.db() as conn:
        return api.rows(conn, query, args)


def data_url(mime, data):
    return f'data:{mime};base64,{base64.b64encode(data).decode()}'


def png(size, seed=0):
    """A PNG-looking picture of exactly `size` bytes (the server checks the signature and the size)."""
    head = b'\x89PNG\r\n\x1a\n' + seed.to_bytes(4, 'big')
    return head + b'\x00' * (size - len(head))


def image(eid, file_id):
    return {'id': eid, 'type': 'image', 'fileId': file_id, 'x': 0, 'y': 0, 'width': 100, 'height': 100, 'version': 1}


def note(eid, text='Note'):
    return {'id': eid, 'type': 'rectangle', 'x': 0, 'y': 0, 'width': 200, 'height': 120, 'version': 1, 'text': text}


def scene(*elements, style='hand'):
    return {'type': 'gfm-whiteboard', 'v': 1, 'style': style, 'elements': list(elements), 'appState': {'viewBackgroundColor': '#ffffff'}}


def pictures_of(bid):
    return sorted(r['file_id'] for r in sql('SELECT file_id FROM portal.whiteboard_files WHERE board_id=%s', (bid,)))


def leader(role):
    found = sql('''SELECT DISTINCT user_id FROM public.current_user_context WHERE user_active AND leadership_role=%s
                   ORDER BY user_id LIMIT 1''', (role,))
    return found[0]['user_id'] if found else None


ap, zl, dl = leader('AP'), leader('ZL'), leader('DL')
plain = [r['user_id'] for r in sql('''SELECT DISTINCT c.user_id FROM public.current_user_context c
    JOIN public.user_profiles up ON up.id = c.user_id
    WHERE c.user_active AND c.leadership_role IS NULL AND c.mission_id IS NOT NULL
      AND coalesce(up.app_role, 'MISSIONARY') NOT IN ('AP', 'PRESIDENT', 'DATA_ADMIN', 'OFFICE')
    ORDER BY c.user_id LIMIT 1''')]
print(f'fixture: AP={bool(ap)} ZL={bool(zl)} DL={bool(dl)} account without leadership={bool(plain)}', flush=True)
if not (ap and zl and dl and plain):
    sys.exit('This copy needs an AP, a ZL, a DL and an account without leadership.')
# One account plays Office, then a missionary, then the President.
president = office = missionary = plain[0]
saved_roles = {str(u): r for u in (plain[0], dl)
               for r in sql('SELECT app_role, additional_roles FROM public.user_profiles WHERE id=%s', (str(u),))}
before_boards = sql('SELECT count(*) AS n FROM portal.whiteboards')[0]['n']
mission = sql('SELECT mission_id FROM public.current_user_context WHERE user_id=%s LIMIT 1', (str(ap),))[0]['mission_id']
other_mission = None
created = []

try:
    def play(role):
        sql('UPDATE public.user_profiles SET app_role=%s WHERE id=%s', (role, str(plain[0])))

    # ---- access per role ----
    status, answer = call(ap, 'POST', '/api/whiteboards', {'name': 'Zone council'})
    check('an AP creates a board (201, version 1, empty)', status == 201 and answer['board']['version'] == 1, (status, answer))
    board = answer['board']['id']
    created.append(board)

    denied = {}
    for who, label, role in ((dl, 'DL', None), (zl, 'ZL', None), (office, 'Office', 'OFFICE'), (missionary, 'missionary', 'MISSIONARY')):
        if role:
            play(role)
        statuses = [call(who, 'GET', '/api/whiteboards')[0], call(who, 'POST', '/api/whiteboards', {'name': 'Mine'})[0],
                    call(who, 'GET', f'/api/whiteboards/{board}')[0],
                    call(who, 'PUT', f'/api/whiteboards/{board}', {'version': 1, 'scene': scene(note('x'))})[0],
                    call(who, 'PATCH', f'/api/whiteboards/{board}', {'name': 'Taken over'})[0],
                    call(who, 'POST', '/api/whiteboards', {'name': 'Copy', 'copy_of': board})[0],
                    call(who, 'DELETE', f'/api/whiteboards/{board}')[0]]
        denied[label] = statuses
    check('DL, ZL, Office and a missionary get 403 on every whiteboard route', all(s == [403] * 7 for s in denied.values()), denied)
    play('PRESIDENT')
    for who, label in ((president, 'the President'), (ap, 'an AP')):
        status, answer = call(who, 'GET', '/api/whiteboards')
        check(f"{label} sees the mission's boards", status == 200 and board in [b['id'] for b in answer['boards']], status)
    row = sql('SELECT name, version FROM portal.whiteboards WHERE id=%s', (board,))
    check('... and nothing changed', row and row[0]['name'] == 'Zone council' and row[0]['version'] == 1
          and sql('SELECT count(*) AS n FROM portal.whiteboards')[0]['n'] == before_boards + 1, row)

    # A DL who is also a Data Analyst (additional role) is a manager here.
    sql("UPDATE public.user_profiles SET additional_roles=ARRAY['DATA_ADMIN']::text[] WHERE id=%s", (str(dl),))
    status, answer = call(dl, 'GET', f'/api/whiteboards/{board}')
    check('a DL who is also a Data Analyst opens the board', status == 200 and answer['scene']['elements'] == [], status)

    # ---- shared, saved, "last saved by" ----
    status, answer = call(president, 'PUT', f'/api/whiteboards/{board}', {'version': 1, 'scene': scene(note('n1', 'From the President'))})
    check('the President saves (version 2)', status == 200 and answer['board']['version'] == 2, (status, answer))
    status, opened = call(ap, 'GET', f'/api/whiteboards/{board}')
    check('the AP opens what the President saved', status == 200 and opened['scene']['elements'][0]['id'] == 'n1' and opened['board']['version'] == 2)
    names = {r['user_id']: r['display_name'] for r in sql('SELECT user_id, display_name FROM public.current_user_context WHERE user_id IN (%s, %s)', (str(president), str(ap)))}
    check('"last saved by" names the President, "created by" the AP', opened['board']['updated_by_name'] == names.get(president)
          and opened['board']['created_by_name'] == names.get(ap) and opened['board']['updated_by_name'])
    status, answer = call(dl, 'PATCH', f'/api/whiteboards/{board}', {'name': '  Zone   council North '})
    check('a Data Analyst renames it (spaces tidied); the version stays', status == 200 and answer['board']['name'] == 'Zone council North'
          and answer['board']['version'] == 2, answer)

    # ---- version conflicts ----
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': 1, 'scene': scene(note('old'))})
    check('a save with an old version is refused: 409, "someone else saved", with who and the current version',
          status == 409 and answer.get('conflict') is True and answer['error'] == wb.CONFLICT and answer['board']['version'] == 2
          and answer['board']['updated_by_name'] == names.get(president), (status, answer.get('error')))
    check('... and changed nothing', sql('SELECT version, scene FROM portal.whiteboards WHERE id=%s', (board,))[0]['scene']['elements'][0]['id'] == 'n1')
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': 2, 'scene': scene(note('n1'), note('n2'))})
    check('after a reload the AP saves (version 3)', status == 200 and answer['board']['version'] == 3, (status, answer))

    outcomes = []
    def racer(who, eid):
        outcomes.append(call(who, 'PUT', f'/api/whiteboards/{board}', {'version': 3, 'scene': scene(note(eid))})[0])
    threads = [threading.Thread(target=racer, args=(ap, 'race-a')), threading.Thread(target=racer, args=(president, 'race-b'))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check('two saves of the same version at the same moment: exactly one wins, the other is told', sorted(outcomes) == [200, 409], outcomes)
    check('... the board is at version 4', sql('SELECT version FROM portal.whiteboards WHERE id=%s', (board,))[0]['version'] == 4)
    status, answer = call(ap, 'PUT', '/api/whiteboards/00000000-0000-0000-0000-000000000000', {'version': 1, 'scene': scene()})
    check('saving a board that no longer exists: 404 with a sentence', status == 404 and answer['error'] == wb.NOT_FOUND, status)

    # ---- names ----
    status, answer = call(ap, 'POST', '/api/whiteboards', {'name': 'zone COUNCIL north'})
    check('names are unique in the mission (letter case ignored): 409', status == 409 and answer['error'] == wb.NAME_TAKEN, status)
    status, second = call(ap, 'POST', '/api/whiteboards', {'name': 'Training'})
    created.append(second['board']['id'])
    status, answer = call(ap, 'PATCH', f'/api/whiteboards/{second["board"]["id"]}', {'name': 'Zone Council North'})
    check('renaming to a name in use: 409', status == 409 and answer['error'] == wb.NAME_TAKEN, status)

    # ---- pictures ----
    version = 4
    small = {'p1': {'mimeType': 'image/png', 'dataURL': data_url('image/png', png(5000, 1))},
             'p2': {'mimeType': 'image/png', 'dataURL': data_url('image/png', png(6000, 2))}}
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(image('i1', 'p1'), image('i2', 'p2')), 'files': small})
    check('pictures are kept with the board; the answer lists them', status == 200 and answer['board']['file_ids'] == ['p1', 'p2'] and pictures_of(board) == ['p1', 'p2'], answer)
    version = answer['board']['version']
    status, answer = call(president, 'GET', f'/api/whiteboards/{board}')
    check('opening gives the pictures back byte for byte', answer['files']['p1']['dataURL'] == small['p1']['dataURL'] and answer['files']['p2']['mimeType'] == 'image/png')
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(image('i1', 'p1'))})
    check('a picture no element uses any more is forgotten', status == 200 and pictures_of(board) == ['p1'], (status, pictures_of(board)))
    version = answer['board']['version']
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(image('i1', 'p1'), image('i9', 'p9'))})
    check('a picture in use but never sent is simply missing (the page sends it with its next save)', status == 200 and answer['board']['file_ids'] == ['p1'])
    version = answer['board']['version']

    # ---- limits ----
    over = {'big': {'mimeType': 'image/png', 'dataURL': data_url('image/png', png(wb.FILE_MAX_BYTES + 1))}}
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(image('i1', 'p1'), image('ib', 'big')), 'files': over})
    check('a picture over 2 MB: 413 with its sentence; the board stays as it was', status == 413 and 'larger than 2 MB' in answer['error']
          and sql('SELECT version FROM portal.whiteboards WHERE id=%s', (board,))[0]['version'] == version, (status, answer.get('error')))
    many = {f'm{i}': {'mimeType': 'image/png', 'dataURL': data_url('image/png', png(200, i))} for i in range(61)}
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(*[image(f'e{i}', f'm{i}') for i in range(61)]), 'files': many})
    check('more than 60 pictures: 413, nothing kept', status == 413 and answer['error'] == wb.TOO_MANY_FILES and pictures_of(board) == ['p1'], (status, answer.get('error')))
    heavy = [{f'h{i}': {'mimeType': 'image/png', 'dataURL': data_url('image/png', png(1900 * 1024, i))}} for i in range(7)]
    elements = [image('i1', 'p1')] + [image(f'eh{i}', f'h{i}') for i in range(7)]
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(*elements), 'files': {**heavy[0], **heavy[1], **heavy[2], **heavy[3]}})
    version = answer.get('board', {}).get('version', version)
    check('big pictures over two saves: the first four (7.4 MB) are kept', status == 200 and len(pictures_of(board)) == 5, status)
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(*elements), 'files': {**heavy[4], **heavy[5], **heavy[6]}})
    check('... the next three would pass 12 MB of pictures: 413 with its sentence, the board as it was',
          status == 413 and 'more than 12 MB' in answer['error'] and len(pictures_of(board)) == 5
          and sql('SELECT version FROM portal.whiteboards WHERE id=%s', (board,))[0]['version'] == version, (status, answer.get('error')))
    huge = scene(*[note(f'x{i}', 'x' * 1000) for i in range(3300)])
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': huge})
    check('a drawing over 3 MB: 413 with its sentence', status == 413 and 'at most 3 MB' in answer['error'], status)
    # Measured as the database measures it (jsonb text: a space after every ':' and ','): 1,000 pencil strokes that
    # are under 3 MB written tightly are refused by portal-api with the sentence, not by the table with a 500.
    pencil = [{'id': f'q{i}', 'type': 'freedraw', 'x': 0, 'y': 0, 'width': 10, 'height': 10, 'version': 1,
               'points': [[j, j + 0.5] for j in range(250)], 'pressures': []} for i in range(1000)]
    tight = len(json.dumps(scene(*pencil), separators=(',', ':')).encode())
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(*pencil)})
    check('a pencil drawing under 3 MB written tightly but over 3 MB as the database writes it: 413 with its sentence',
          tight < wb.SCENE_MAX_BYTES and status == 413 and 'at most 3 MB' in answer.get('error', ''), (tight, status))
    # Numbers such as 1.1368683772161603e-13 (Excalidraw writes them) are written out longer by the database, so a
    # drawing can pass portal-api's measure and still be refused by the table: the same 413 and sentence, not a 500.
    tiny = 1.1368683772161603e-13
    strokes = [{'id': f'd{i}', 'type': 'freedraw', 'x': 0, 'y': 0, 'width': 10, 'height': 10, 'version': 1,
                'points': [[j, tiny] for j in range(950)]} for i in range(100)]
    measured = wb.scene_bytes(wb.clean_scene(scene(*strokes)))
    boards_before = sql('SELECT count(*) AS n FROM portal.whiteboards')[0]['n']
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(*strokes)})
    status2, answer2 = call(ap, 'POST', '/api/whiteboards', {'name': 'Too large', 'scene': scene(*strokes)})
    check('a drawing the table refuses although portal-api measured it under 3 MB: 413 with the sentence (save and new board), '
          'nothing changed', measured <= wb.SCENE_MAX_BYTES and status == 413 and status2 == 413
          and 'at most 3 MB' in answer.get('error', '') and 'at most 3 MB' in answer2.get('error', '')
          and sql('SELECT version FROM portal.whiteboards WHERE id=%s', (board,))[0]['version'] == version
          and sql('SELECT count(*) AS n FROM portal.whiteboards')[0]['n'] == boards_before, (measured, status, status2))
    # An iframe element is never kept, even with our chart link: Excalidraw would run the HTML it carries.
    page = {'status': 'done', 'html': '<form>Session expired. Password: <input type=password></form><script>parent.postMessage(1, "*")</script>'}
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(image('i1', 'p1'),
        {'id': 'trap', 'type': 'iframe', 'link': wb.CHART_LINK + 'trap', 'x': 0, 'y': 0, 'width': 400, 'height': 300, 'customData': {'generationData': page}},
        dict(note('carrier'), customData={'generationData': page}))})
    stored = sql('SELECT scene FROM portal.whiteboards WHERE id=%s', (board,))[0]['scene']
    check("an 'iframe' element is dropped even with our chart link, and generationData is taken off every element",
          status == 200 and [e['id'] for e in stored['elements']] == ['i1', 'carrier'] and 'Session expired' not in json.dumps(stored),
          (status, [e['id'] for e in stored['elements']]))
    version = answer.get('board', {}).get('version', version)
    status, answer = call(ap, 'GET', '/api/whiteboards')
    check('the list gives no drawing size (the poll every 20 seconds never reads a drawing)',
          status == 200 and answer['boards'] and all('size' not in b and 'pictures' in b for b in answer['boards']), status)
    status, answer = call(ap, 'PUT', f'/api/whiteboards/{board}', {'version': version, 'scene': scene(image('i1', 'p1'), note('n1'),
        {'id': 'web', 'type': 'embeddable', 'link': 'https://example.org/', 'x': 0, 'y': 0, 'width': 10, 'height': 10},
        {'id': 'chart', 'type': 'embeddable', 'link': wb.CHART_LINK + 'chart', 'x': 0, 'y': 0, 'width': 10, 'height': 10, 'customData': {'gfmChart': {'v': 2}}})})
    kept = [e['id'] for e in sql('SELECT scene FROM portal.whiteboards WHERE id=%s', (board,))[0]['scene']['elements']]
    check('saving keeps our chart frames and drops any other embedded page', status == 200 and kept == ['i1', 'n1', 'chart'], kept)
    version = answer['board']['version']
    check('pictures no element uses after that save are forgotten', pictures_of(board) == ['p1'], pictures_of(board))

    # Constraints of the tables themselves (as postgres, without portal-api).
    def refused(query, args):
        try:
            sql(query, args)
            return False
        except (psycopg2.errors.CheckViolation, psycopg2.errors.UniqueViolation, psycopg2.errors.NotNullViolation):
            return True
    check('the table refuses a drawing over 3 MB', refused("UPDATE portal.whiteboards SET scene = jsonb_build_object('elements', jsonb_build_array(repeat('x', 3200000))) WHERE id=%s", (board,)))
    check('the table refuses a picture over 2 MB', refused("INSERT INTO portal.whiteboard_files(board_id, file_id, mime_type, bytes, data) VALUES (%s, 'x', 'image/png', %s, decode(repeat('00', %s), 'hex'))",
                                                        (board, 2 * 1024 * 1024 + 1, 2 * 1024 * 1024 + 1)))
    check('the table refuses other picture types', refused("INSERT INTO portal.whiteboard_files(board_id, file_id, mime_type, bytes, data) VALUES (%s, 'x', 'text/html', 1, 'a')", (board,)))
    check('the table refuses an empty name and a duplicate name', refused("INSERT INTO portal.whiteboards(mission_id, name) VALUES (%s, ' ')", (mission,))
          and refused("INSERT INTO portal.whiteboards(mission_id, name) VALUES (%s, 'ZONE council north')", (mission,)))

    # ---- copies ----
    status, answer = call(president, 'POST', '/api/whiteboards', {'name': 'Zone council North (copy)', 'copy_of': board})
    copy = answer.get('board', {}).get('id')
    created.append(copy)
    check('Duplicate copies the drawing and its pictures on the server', status == 201 and pictures_of(copy) == ['p1']
          and [e['id'] for e in call(ap, 'GET', f'/api/whiteboards/{copy}')[1]['scene']['elements']] == ['i1', 'n1', 'chart'], (status, answer))
    status, answer = call(ap, 'POST', '/api/whiteboards', {'name': 'Mine', 'scene': scene(image('i1', 'p1'), note('mine')), 'files_from': board})
    created.append(answer.get('board', {}).get('id'))
    check('"Keep mine as a new board": pictures the old board holds are copied, not sent', status == 201 and answer['board']['file_ids'] == ['p1'], (status, answer))
    status, answer = call(ap, 'DELETE', f'/api/whiteboards/{copy}')
    check('deleting a board deletes its pictures', status == 200 and pictures_of(copy) == [] and pictures_of(board) == ['p1'])
    status, answer = call(ap, 'GET', f'/api/whiteboards/{copy}')
    check('a deleted board: 404 with a sentence', status == 404 and answer['error'] == wb.NOT_FOUND)

    # ---- other missions ----
    other_mission = sql("INSERT INTO public.missions(id, name) VALUES ((SELECT max(id) + 1000 FROM public.missions), 'Whiteboard test mission') RETURNING id")[0]['id']
    foreign = sql("INSERT INTO portal.whiteboards(mission_id, name, scene) VALUES (%s, 'Another mission', %s) RETURNING id",
                  (other_mission, json.dumps(scene(image('i1', 'fp')))))[0]['id']
    sql("INSERT INTO portal.whiteboard_files(board_id, file_id, mime_type, bytes, data) VALUES (%s, 'fp', 'image/png', 12, %s)", (foreign, psycopg2.Binary(png(12))))
    statuses = [call(ap, 'GET', f'/api/whiteboards/{foreign}')[0], call(ap, 'PUT', f'/api/whiteboards/{foreign}', {'version': 1, 'scene': scene()})[0],
                call(ap, 'PATCH', f'/api/whiteboards/{foreign}', {'name': 'Mine now'})[0], call(ap, 'DELETE', f'/api/whiteboards/{foreign}')[0],
                call(ap, 'POST', '/api/whiteboards', {'name': 'Stolen', 'copy_of': str(foreign)})[0]]
    listed = [b['id'] for b in call(ap, 'GET', '/api/whiteboards')[1]['boards']]
    check("another mission's board is not listed and cannot be opened, saved, renamed, deleted or copied (404)",
          statuses == [404] * 5 and str(foreign) not in listed, statuses)
    status, answer = call(ap, 'POST', '/api/whiteboards', {'name': 'Stolen pictures', 'scene': scene(image('i1', 'fp')), 'files_from': str(foreign)})
    created.append(answer.get('board', {}).get('id'))
    check("pictures of another mission's board are never copied", status == 201 and answer['board']['file_ids'] == [], answer)
    row = sql('SELECT name, version FROM portal.whiteboards WHERE id=%s', (foreign,))[0]
    check("... and that board is unchanged", row['name'] == 'Another mission' and row['version'] == 1)

    # ---- the boards limit ----
    have = sql('SELECT count(*) AS n FROM portal.whiteboards WHERE mission_id=%s', (mission,))[0]['n']
    sql("INSERT INTO portal.whiteboards(mission_id, name) SELECT %s, 'Filler ' || g FROM generate_series(1, %s) g", (mission, wb.BOARDS_MAX - have))
    status, answer = call(ap, 'POST', '/api/whiteboards', {'name': 'One too many'})
    check(f'a mission has at most {wb.BOARDS_MAX} boards: 400 with its sentence', status == 400 and answer['error'] == wb.TOO_MANY_BOARDS, (status, answer))
    sql("DELETE FROM portal.whiteboards WHERE mission_id=%s AND name LIKE 'Filler %%'", (mission,))

    # ---- rights ----
    conn = api.connect()
    try:
        for role in ('anon', 'authenticated', 'service_role', 'gfm_dashboard_reader'):
            for table in ('portal.whiteboards', 'portal.whiteboard_files'):
                with conn.cursor() as cur:
                    try:
                        cur.execute(f'SET LOCAL ROLE {role}')
                        cur.execute(f'SELECT 1 FROM {table} LIMIT 1')
                        blocked = False
                    except (psycopg2.errors.InsufficientPrivilege, psycopg2.errors.UndefinedObject):
                        blocked = True
                conn.rollback()
                check(f'{role} cannot read {table}', blocked)
    finally:
        conn.close()
    rls = sql("SELECT bool_and(relrowsecurity) AS on FROM pg_class WHERE oid IN ('portal.whiteboards'::regclass, 'portal.whiteboard_files'::regclass)")[0]['on']
    check('row security is on for both tables', rls)
finally:
    for bid in created:
        if bid:
            sql('DELETE FROM portal.whiteboards WHERE id=%s', (bid,))
    if other_mission:
        sql('DELETE FROM portal.whiteboards WHERE mission_id=%s', (other_mission,))
        sql('DELETE FROM public.missions WHERE id=%s', (other_mission,))
    for uid, r in saved_roles.items():
        sql('UPDATE public.user_profiles SET app_role=%s, additional_roles=%s WHERE id=%s', (r['app_role'], r['additional_roles'], uid))
    left = sql('SELECT count(*) AS n FROM portal.whiteboards')[0]['n']
    print(f'clean-up: boards before {before_boards}, after {left}; roles put back for {len(saved_roles)} accounts', flush=True)

print(f'{sum(results)} of {len(results)} checks passed', flush=True)
sys.exit(0 if all(results) else 1)
