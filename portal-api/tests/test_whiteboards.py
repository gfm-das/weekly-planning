"""Unit checks for whiteboards.py (the Whiteboard tab, migration 031), without a database.

- Names: spaces tidied, 1 to 80 characters.
- The drawing: deleted elements dropped, only our chart frames kept (no other embedded page, never an 'iframe'
  element, even with our chart link; generationData taken off every element), only the board settings kept, the
  style, and the size and element limits with their own sentences (the size measured as the database measures it).
- A refusal by the tables' own constraints is answered like portal-api's checks (413 or 400), never with a 500.
- Pictures: the five picture types only, the bytes must be what the type says, at most 2 MB (refused before
  decoding a huge one), ids as Excalidraw makes them.
- Who: every route answers 403 for anyone who is not an AP, the President or a Data Analyst, before the database;
  bad input is refused with a plain sentence before the database (400, 404, 413).
The database side (per role, version conflicts, limits, copies, other missions) is in whiteboards_db.py.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_whiteboards.py
"""
import base64
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import app as api  # noqa: E402
import whiteboards as wb  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 40
GIF = b'GIF89a' + b'\x00' * 40
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'\x00' * 40
SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
CHART = 'https://gfm-whiteboard.invalid/chart/abc123'


def data_url(mime, data):
    return f'data:{mime};base64,{base64.b64encode(data).decode()}'


def element(eid, kind='rectangle', **extra):
    return {'id': eid, 'type': kind, 'x': 0, 'y': 0, 'width': 10, 'height': 10, 'version': 1, **extra}


class Names(unittest.TestCase):
    def test_spaces_are_tidied(self):
        self.assertEqual(wb.clean_name('  Zone   council\t Nord '), 'Zone council Nord')

    def test_empty_and_long_names_are_refused_with_a_sentence(self):
        for value in ('', '   ', None, 42):
            with self.assertRaises(ValueError) as caught:
                wb.clean_name(value)
            self.assertEqual(str(caught.exception), 'Give the board a name.')
        self.assertEqual(wb.clean_name('x' * 80), 'x' * 80)
        with self.assertRaises(ValueError) as caught:
            wb.clean_name('x' * 81)
        self.assertIn('80 characters', str(caught.exception))


class Scene(unittest.TestCase):
    def test_the_stored_drawing(self):
        scene = wb.clean_scene({
            'type': 'something', 'style': 'clean',
            'elements': [element('a'), element('b', isDeleted=True), element('c', 'text', text='Hello'),
                         element('d', 'embeddable', link=CHART, customData={'gfmChart': {'v': 2}}),
                         element('e', 'embeddable', link='https://www.youtube.com/embed/x'),
                         element('f', 'iframe', link='https://example.org/'),
                         element('g', 'embeddable')],
            'appState': {'viewBackgroundColor': '#fff', 'currentItemRoughness': 0, 'zoom': {'value': 3},
                         'selectedElementIds': {'a': True}, 'collaborators': {}, 'gridModeEnabled': True},
        })
        self.assertEqual(scene['type'], 'gfm-whiteboard')
        self.assertEqual(scene['v'], 1)
        self.assertEqual(scene['style'], 'clean')
        self.assertEqual([e['id'] for e in scene['elements']], ['a', 'c', 'd'], 'deleted and foreign embeds dropped')
        self.assertEqual(scene['appState'], {'viewBackgroundColor': '#fff', 'currentItemRoughness': 0, 'gridModeEnabled': True},
                         'zoom, selection and the like are each person\'s own')

    def test_iframe_elements_never_stay_and_generation_data_goes(self):
        # Excalidraw shows an iframe element's customData.generationData.html with scripts allowed, whatever its link.
        page = {'status': 'done', 'html': '<form>Session expired</form><script>alert(1)</script>'}
        scene = wb.clean_scene({'elements': [
            element('frame', 'iframe', link=CHART, customData={'generationData': page}),
            element('frame2', 'iframe', link=CHART),
            element('chart', 'embeddable', link=CHART, customData={'gfmChart': {'v': 2}, 'generationData': page}),
            element('note', customData={'generationData': page, 'mine': 1}),
        ]})
        self.assertEqual([e['id'] for e in scene['elements']], ['chart', 'note'])
        self.assertEqual(scene['elements'][0]['customData'], {'gfmChart': {'v': 2}})
        self.assertEqual(scene['elements'][1]['customData'], {'mine': 1})
        self.assertNotIn('Session expired', json.dumps(scene))

    def test_the_size_is_measured_as_the_database_measures_it(self):
        # jsonb text: a space after every ':' and ','. 800 pencil strokes of 300 points: under 3 MB written tightly,
        # over 3 MB as the database writes it (the table would refuse it).
        points = [[i, i + 0.5] for i in range(300)]
        strokes = [element(f'p{i}', 'freedraw', points=points, pressures=[]) for i in range(800)]
        tight = len(json.dumps({'type': 'gfm-whiteboard', 'v': 1, 'style': 'hand', 'elements': strokes, 'appState': {}},
                               separators=(',', ':')).encode())
        self.assertLess(tight, wb.SCENE_MAX_BYTES)
        with self.assertRaises(wb.TooLarge):
            wb.clean_scene({'elements': strokes})
        self.assertEqual(wb.scene_bytes({'a': [1, 2], 'b': 'ü'}), len('{"a": [1, 2], "b": "ü"}'.encode()))

    def test_unknown_style_is_hand_drawn(self):
        self.assertEqual(wb.clean_scene({'elements': [], 'style': 'fancy'})['style'], 'hand')
        self.assertEqual(wb.clean_scene({'elements': []})['appState'], {})

    def test_bad_drawings_are_refused(self):
        for value in (None, [], {'elements': 'x'}, {'elements': [{'type': 'rectangle'}]}, {'elements': [{'id': 1, 'type': 'x'}]},
                      {'elements': ['x']}):
            with self.assertRaises(ValueError) as caught:
                wb.clean_scene(value)
            self.assertEqual(str(caught.exception), wb.BAD_SCENE)

    def test_the_size_limit(self):
        big = [element(f'e{i}', 'text', text='x' * 1000) for i in range(3300)]
        with self.assertRaises(wb.TooLarge) as caught:
            wb.clean_scene({'elements': big})
        self.assertIn('at most 3 MB', str(caught.exception))
        many = [{'id': str(i), 'type': 'line'} for i in range(wb.ELEMENTS_MAX + 1)]
        with self.assertRaises(wb.TooLarge):
            wb.clean_scene({'elements': many})
        # Just under the limit is fine.
        wb.clean_scene({'elements': [element(f'e{i}', 'text', text='x' * 1000) for i in range(2600)]})

    def test_pictures_in_use(self):
        scene = wb.clean_scene({'elements': [element('i1', 'image', fileId='abc_1-2'), element('i2', 'image', fileId='bad id'),
                                             element('i3', 'image', fileId='gone', isDeleted=True), element('r', fileId='nope')]})
        self.assertEqual(wb.used_files(scene), {'abc_1-2'})


class Pictures(unittest.TestCase):
    def test_every_picture_type(self):
        for mime, data in (('image/png', PNG), ('image/jpeg', JPEG), ('image/gif', GIF), ('image/webp', WEBP), ('image/svg+xml', SVG)):
            files = wb.clean_files({'p1': {'mimeType': mime, 'dataURL': data_url(mime, data)}})
            self.assertEqual(files, {'p1': (mime, data)}, mime)

    def test_the_bytes_must_be_what_the_type_says(self):
        for mime, data in (('image/png', JPEG), ('image/jpeg', b'<svg></svg>'), ('image/svg+xml', b'<html><body>hi</body></html>'),
                           ('image/gif', PNG), ('image/webp', b'RIFF0000AVI ')):
            with self.assertRaises(ValueError, msg=mime) as caught:
                wb.clean_files({'p1': {'mimeType': mime, 'dataURL': data_url(mime, data)}})
            self.assertEqual(str(caught.exception), wb.BAD_FILE)

    def test_other_types_ids_and_broken_data_are_refused(self):
        bad = [
            {'p1': {'mimeType': 'text/html', 'dataURL': data_url('text/html', b'<b>x</b>')}},
            {'p1': {'mimeType': 'image/png', 'dataURL': data_url('image/jpeg', JPEG)}},
            {'p 1': {'mimeType': 'image/png', 'dataURL': data_url('image/png', PNG)}},
            {'p1': {'mimeType': 'image/png', 'dataURL': 'data:image/png;base64,@@@'}},
            {'p1': {'mimeType': 'image/png', 'dataURL': 'https://example.org/a.png'}},
            {'p1': {'mimeType': 'image/png', 'dataURL': 'data:image/png;base64,'}},
            {'p1': 'x'},
            ['x'],
        ]
        for value in bad:
            with self.assertRaises(ValueError, msg=str(value)[:60]):
                wb.clean_files(value)
        self.assertEqual(wb.clean_files(None), {})

    def test_the_picture_limit(self):
        exact = PNG + b'\x00' * (wb.FILE_MAX_BYTES - len(PNG))
        self.assertEqual(len(wb.clean_files({'p': {'mimeType': 'image/png', 'dataURL': data_url('image/png', exact)}})['p'][1]), wb.FILE_MAX_BYTES)
        over = exact + b'\x00'
        with self.assertRaises(wb.TooLarge) as caught:
            wb.clean_files({'p': {'mimeType': 'image/png', 'dataURL': data_url('image/png', over)}})
        self.assertIn('larger than 2 MB', str(caught.exception))

    def test_a_huge_picture_is_refused_without_decoding_it(self):
        huge = 'data:image/png;base64,' + 'A' * (12 * 1024 * 1024)
        with patch.object(wb.base64, 'b64decode', side_effect=AssertionError('decoded')):
            with self.assertRaises(wb.TooLarge):
                wb.clean_files({'p': {'mimeType': 'image/png', 'dataURL': huge}})


# The routes, without a database: the role check and the input checks come first. ----------------------------------

CONTEXTS = {
    'ap': {'user_id': '00000000-0000-0000-0000-00000000000a', 'app_role': 'MISSIONARY', 'leadership_role': 'AP', 'mission_id': 1},
    'president': {'user_id': '00000000-0000-0000-0000-00000000000b', 'app_role': 'PRESIDENT', 'mission_id': 1},
    'analyst': {'user_id': '00000000-0000-0000-0000-00000000000c', 'app_role': 'MISSIONARY', 'leadership_role': 'DL',
                'additional_roles': ['DATA_ADMIN'], 'mission_id': 1},
    'dl': {'user_id': '00000000-0000-0000-0000-00000000000d', 'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'mission_id': 1},
    'zl': {'user_id': '00000000-0000-0000-0000-00000000000e', 'app_role': 'MISSIONARY', 'leadership_role': 'ZL', 'mission_id': 1},
    'stl': {'user_id': '00000000-0000-0000-0000-00000000000f', 'app_role': 'STL', 'mission_id': 1},
    'office': {'user_id': '00000000-0000-0000-0000-000000000010', 'app_role': 'OFFICE', 'mission_id': 1},
    'missionary': {'user_id': '00000000-0000-0000-0000-000000000011', 'app_role': 'MISSIONARY', 'mission_id': 1},
}
BOARD = '11111111-2222-3333-4444-555555555555'


class NoDatabase(Exception):
    pass


@contextmanager
def no_db():
    raise NoDatabase('the database was used')
    yield  # pragma: no cover


class Routes(unittest.TestCase):
    def setUp(self):
        self.client = api.app.test_client()
        self.who = None

        def context_for(conn, user_id):
            c = dict(CONTEXTS[self.who])
            c['is_manager'] = api.roles.is_manager(c)
            return c

        @contextmanager
        def auth_db():
            yield None

        # Sign-in: the token names the person; their context comes from CONTEXTS. Any later database use fails.
        patches = [
            patch.object(api.requests, 'get', return_value=SimpleNamespace(status_code=200, json=lambda: {'id': CONTEXTS[self.who]['user_id']})),
            patch.object(api, 'context_for', side_effect=context_for),
            patch.object(api, 'db', side_effect=lambda: auth_db() if not self.signed_in() else no_db()),
            patch.object(api.app.logger, 'exception'),  # the expected NoDatabase failures are not logged
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self._signed = False

    def signed_in(self):
        # The first db() is authenticate()'s; any later one is the route's.
        was = self._signed
        self._signed = True
        return was

    def call(self, who, method, path, body=None, raw=None):
        self.who = who
        self._signed = False
        claims = base64.urlsafe_b64encode(json.dumps({'sub': CONTEXTS[who]['user_id']}).encode()).decode().rstrip('=')
        kwargs = {'data': raw, 'content_type': 'application/json'} if raw is not None else {'json': body}
        response = self.client.open(path, method=method, headers={'Authorization': f'Bearer x.{claims}.y'}, **kwargs)
        return response.status_code, response.get_json(silent=True)

    ROUTES = [('GET', '/api/whiteboards', None), ('POST', '/api/whiteboards', {'name': 'A'}),
              ('GET', f'/api/whiteboards/{BOARD}', None), ('PUT', f'/api/whiteboards/{BOARD}', {'version': 1, 'scene': {'elements': []}}),
              ('PATCH', f'/api/whiteboards/{BOARD}', {'name': 'B'}), ('DELETE', f'/api/whiteboards/{BOARD}', None)]

    def test_everyone_but_the_managers_is_refused_before_the_database(self):
        for who in ('dl', 'zl', 'stl', 'office', 'missionary'):
            for method, path, body in self.ROUTES:
                status, answer = self.call(who, method, path, body)
                self.assertEqual((status, answer['error']), (403, wb.NOT_MANAGER), f'{who} {method} {path}')

    def test_managers_get_to_the_database(self):
        for who in ('ap', 'president', 'analyst'):
            for method, path, body in self.ROUTES:
                status, answer = self.call(who, method, path, body)
                # NoDatabase is answered as a failed request: the role check let them through.
                self.assertEqual(status, 500, f'{who} {method} {path} {answer}')

    def test_bad_input_is_refused_before_the_database(self):
        cases = [
            ('POST', '/api/whiteboards', {'name': '  '}, 400, 'Give the board a name.'),
            ('POST', '/api/whiteboards', {'name': 'x' * 81}, 400, wb.NAME_LONG),
            ('POST', '/api/whiteboards', {'name': 'A', 'scene': {'elements': 5}}, 400, wb.BAD_SCENE),
            ('POST', '/api/whiteboards', {'name': 'A', 'copy_of': 'not-a-board'}, 404, wb.NOT_FOUND),
            ('PATCH', f'/api/whiteboards/{BOARD}', {'name': ''}, 400, 'Give the board a name.'),
            ('PUT', f'/api/whiteboards/{BOARD}', {'scene': {'elements': []}}, 400, wb.BAD_SCENE),
            ('PUT', f'/api/whiteboards/{BOARD}', {'version': 0, 'scene': {'elements': []}}, 400, wb.BAD_SCENE),
            ('PUT', f'/api/whiteboards/{BOARD}', {'version': True, 'scene': {'elements': []}}, 400, wb.BAD_SCENE),
            ('PUT', f'/api/whiteboards/{BOARD}', {'version': 1}, 400, wb.BAD_SCENE),
            ('PUT', f'/api/whiteboards/{BOARD}', {'version': 1, 'scene': {'elements': []}, 'files': {'p': {'mimeType': 'text/html', 'dataURL': 'data:text/html;base64,PGI+'}}}, 400, wb.BAD_FILE),
            ('GET', '/api/whiteboards/not-a-board', None, 404, wb.NOT_FOUND),
            ('DELETE', '/api/whiteboards/1', None, 404, wb.NOT_FOUND),
        ]
        for method, path, body, status, error in cases:
            got, answer = self.call('ap', method, path, body)
            self.assertEqual((got, answer.get('error')), (status, error), f'{method} {path} {str(body)[:60]}')
        got, answer = self.call('ap', 'PUT', f'/api/whiteboards/{BOARD}', raw='not json')
        self.assertEqual((got, answer['error']), (400, wb.BAD_SCENE))

    def test_too_large_is_413_with_its_sentence(self):
        big = {'elements': [element(f'e{i}', 'text', text='x' * 1000) for i in range(3300)]}
        got, answer = self.call('ap', 'PUT', f'/api/whiteboards/{BOARD}', {'version': 1, 'scene': big})
        self.assertEqual(got, 413)
        self.assertTrue(answer['too_large'])
        self.assertIn('too large to save', answer['error'])
        over = data_url('image/png', PNG + b'\x00' * wb.FILE_MAX_BYTES)
        got, answer = self.call('ap', 'POST', '/api/whiteboards', {'name': 'A', 'scene': {'elements': []}, 'files': {'p': {'mimeType': 'image/png', 'dataURL': over}}})
        self.assertEqual((got, answer['too_large']), (413, True))
        self.assertIn('larger than 2 MB', answer['error'])


class TableRefusals(unittest.TestCase):
    """The tables' constraints (should portal-api's own checks ever let something through) and a value the database
    cannot hold: a 413 or 400 with a sentence, which the page shows, never a 500 that it would send again and again."""

    def setUp(self):
        self.client = api.app.test_client()
        ctx = dict(CONTEXTS['ap'], is_manager=True)

        def refused(constraint):
            class Refused(api.psycopg2.errors.CheckViolation):
                diag = SimpleNamespace(constraint_name=constraint)
            return Refused('refused by the table')

        self.refused = refused
        self.error = None

        @contextmanager
        def fake_db():
            yield object()

        def fake_rows(conn, sql, args=()):
            if 'current_user_context' in sql:
                return []
            if sql.lstrip().startswith('SELECT count(*)'):
                return [{'n': 0}]
            if sql.lstrip().startswith('SELECT 1'):
                return []
            raise self.error

        for p in [patch.object(api.requests, 'get', return_value=SimpleNamespace(status_code=200, json=lambda: {'id': ctx['user_id']})),
                  patch.object(api, 'context_for', return_value=ctx), patch.object(api, 'db', side_effect=fake_db),
                  patch.object(api, 'rows', side_effect=fake_rows), patch.object(api.app.logger, 'exception')]:
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, path, body):
        claims = base64.urlsafe_b64encode(json.dumps({'sub': CONTEXTS['ap']['user_id']}).encode()).decode().rstrip('=')
        response = self.client.open(path, method=method, json=body, headers={'Authorization': f'Bearer x.{claims}.y'})
        return response.status_code, response.get_json(silent=True)

    def test_the_drawing_size_constraint_is_a_413_with_the_sentence(self):
        for method, path, body in (('PUT', f'/api/whiteboards/{BOARD}', {'version': 1, 'scene': {'elements': []}}),
                                   ('POST', '/api/whiteboards', {'name': 'A', 'scene': {'elements': []}})):
            self.error = self.refused('whiteboards_scene_size')
            status, answer = self.call(method, path, body)
            self.assertEqual((status, answer.get('too_large')), (413, True), method)
            self.assertIn('too large to save', answer['error'])

    def test_other_refusals_are_a_400_with_a_sentence(self):
        self.error = self.refused('whiteboards_scene_object')
        self.assertEqual(self.call('PUT', f'/api/whiteboards/{BOARD}', {'version': 1, 'scene': {'elements': []}}), (400, {'error': wb.BAD_SCENE}))
        self.error = api.psycopg2.errors.UntranslatableCharacter('unsupported Unicode escape sequence')
        self.assertEqual(self.call('PUT', f'/api/whiteboards/{BOARD}', {'version': 1, 'scene': {'elements': []}}), (400, {'error': wb.BAD_SCENE}))


class Limits(unittest.TestCase):
    def test_the_page_and_the_server_agree(self):
        core = (Path(__file__).resolve().parents[2] / 'portal' / 'whiteboard' / 'board-core.js')
        if not core.exists():
            self.skipTest('portal/ is not mounted')
        text = core.read_text(encoding='utf-8')
        self.assertIn(f"CHART_LINK = '{wb.CHART_LINK}'", text)
        self.assertIn('pictureBytes: 2 * 1024 * 1024, pictures: 60, picturesBytes: 12 * 1024 * 1024, sceneBytes: 3 * 1024 * 1024', text)
        self.assertEqual((wb.FILE_MAX_BYTES, wb.BOARD_FILES_MAX, wb.BOARD_FILES_MAX_BYTES, wb.SCENE_MAX_BYTES),
                         (2 * 1024 * 1024, 60, 12 * 1024 * 1024, 3 * 1024 * 1024))
        for key in wb.APP_STATE_KEYS:
            self.assertIn(f"'{key}'", text, key)


if __name__ == '__main__':
    unittest.main(verbosity=1)
