"""Whiteboards: the named boards of the portal's Whiteboard tab (portal/whiteboard/; migration 031).

What it is: the /api/whiteboards routes (list, create, open, save, rename, delete a board) and the checks that keep
a board's drawing and pictures safe and within their limits.
Who uses it: the AP, the President and Data Analysts (roles.is_manager, also as an additional role). Every board of a
mission is shared by all of them; nobody else may list, open or change a board.
How it fits: the tables are reached only here, as the server's database login (they are API-only, like the other
portal tables). The page draws with Excalidraw; this file only stores what it sends.

    GET    /api/whiteboards                  the mission's boards, newest change first (no drawing, no pictures)
    POST   /api/whiteboards                  {name}: a new empty board
                                             {name, copy_of}: a copy of another board of the mission (Duplicate)
                                             {name, scene, files?, files_from?}: a new board from a drawing ("Keep
                                             mine as a new board"); pictures it uses that files_from (a board of the
                                             mission) holds are copied on the server, so they need not be sent again
    GET    /api/whiteboards/<id>             one board: its drawing (scene) and its pictures (files)
    PUT    /api/whiteboards/<id>             {version, scene, files}: save; refused with 409 when someone else saved
                                             since `version` (the browser then offers Reload or Keep mine as a copy)
    PATCH  /api/whiteboards/<id>             {name}: rename (the drawing and its version stay as they are)
    DELETE /api/whiteboards/<id>             delete the board and its pictures

The drawing (scene) is Excalidraw's list of elements plus a few board settings:
    {"type": "gfm-whiteboard", "v": 1, "style": "hand" | "clean", "elements": [...], "appState": {...}}
Pictures are sent once, as data URLs {id: {mimeType, dataURL}}, only while an element on the board uses them; a
save forgets pictures no element uses any more. The browser may send a board's pictures over several saves (each
answer lists the pictures the board holds, file_ids), so one request stays well below the 16 MB request limit.
Limits: names 1-80 characters and unique in the mission, a drawing of at most 3 MB, a picture of at most 2 MB, at
most 60 pictures and 12 MB of pictures per board, at most 200 boards per mission. Every limit has its own plain
message.

Charts and key numbers on a board are Excalidraw "embeddable" elements whose link is CHART_LINK + an id and whose
customData.gfmChart holds the chart (the chart builder's board model: an ECharts option, and a query spec or a
pasted table). The board only stores them; the chart frame on the Presentation Manager (:3030, managers only) draws
them from the live numbers. Any other embedded page is dropped when a board is saved: an embeddable with another link,
and every "iframe" element (Excalidraw runs the HTML such an element carries, customData.generationData, with
scripts, whatever its link says). generationData is taken off every element. The page shows only our charts in frames.

The 3 MB drawing limit is measured as the database measures it (the jsonb text, with a space after every ':' and
','); should the database still find the drawing too large, the answer is the same 413 and sentence, never a 500.
"""
import base64
import binascii
import json
import re
import uuid

import psycopg2
from flask import Blueprint, abort, g, jsonify, request
from psycopg2 import errors as pg_errors
from psycopg2.extras import Json

import roles

whiteboards_bp = Blueprint('whiteboards', __name__)

NAME_MAX = 80
BOARDS_MAX = 200
SCENE_MAX_BYTES = 3 * 1024 * 1024
FILE_MAX_BYTES = 2 * 1024 * 1024
BOARD_FILES_MAX = 60
BOARD_FILES_MAX_BYTES = 12 * 1024 * 1024
ELEMENTS_MAX = 20000
STYLES = ('hand', 'clean')
FILE_TYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml')
FILE_ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
DATA_URL = re.compile(r'^data:([a-z0-9.+/-]+);base64,([A-Za-z0-9+/=\s]*)$', re.I)
# Board settings kept with the drawing (Excalidraw's appState); everything else (zoom, selection, open menus) is
# each person's own and is not saved.
APP_STATE_KEYS = (
    'viewBackgroundColor', 'gridModeEnabled', 'gridSize', 'gridStep', 'currentItemRoughness', 'currentItemFontFamily',
    'currentItemStrokeColor', 'currentItemBackgroundColor', 'currentItemFillStyle', 'currentItemStrokeWidth',
    'currentItemStrokeStyle', 'currentItemOpacity', 'currentItemFontSize', 'currentItemTextAlign',
    'currentItemRoundness', 'currentItemArrowType', 'currentItemStartArrowhead', 'currentItemEndArrowhead',
)

# Plain English; the interface translation wraps these sentences.
NOT_MANAGER = 'The whiteboard is for the APs, the President and the Data Analysts.'
NOT_FOUND = 'This board no longer exists. Someone may have deleted it.'
CONFLICT = 'Someone else saved this board while you were working on it. Reload to see their changes.'
NAME_EMPTY = 'Give the board a name.'
NAME_LONG = f'Keep the name to {NAME_MAX} characters or fewer.'
NAME_TAKEN = 'A board with this name already exists. Choose another name.'
TOO_MANY_BOARDS = f'This mission already has {BOARDS_MAX} boards. Delete boards you no longer need first.'
SCENE_TOO_LARGE = ('This board is too large to save (at most {limit} MB of drawing). Remove some drawings, or move '
                   'part of it to a new board.')
FILE_TOO_LARGE = 'A picture is larger than {limit} MB. Use a smaller picture or a screenshot of part of it.'
TOO_MANY_FILES = f'A board can hold at most {BOARD_FILES_MAX} pictures. Remove some pictures first.'
FILES_TOO_LARGE = ('The pictures on this board would add up to more than {limit} MB. Remove some pictures, or use '
                   'smaller ones.')
BAD_FILE = 'A picture could not be read. Only PNG, JPEG, GIF, WebP and SVG pictures can be added.'
BAD_SCENE = 'The board could not be read. Reload the page and try again.'
# The link of a chart element (portal/whiteboard/board-core.js CHART_LINK); never fetched by anyone.
CHART_LINK = 'https://gfm-whiteboard.invalid/chart/'


def _app():
    import app  # imported here: app.py registers this blueprint while it is still loading
    return app


class TooLarge(Exception):
    """A limit was passed: answered with 413 and the sentence."""


def manager():
    """The signed-in manager's context, or 403 for everyone else."""
    c = g.context
    if not roles.is_manager(c):
        abort(403, NOT_MANAGER)
    return c


def board_id(value):
    """The board id from the address as text; 404 when it is not an id at all."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        abort(404, NOT_FOUND)


def mb(limit):
    """A byte limit in MB for messages (3145728 -> '3')."""
    return f'{limit / (1024 * 1024):g}'


def clean_name(value):
    """The board name with its spaces tidied; ValueError when it is empty or too long."""
    if not isinstance(value, str):
        raise ValueError(NAME_EMPTY)
    name = ' '.join(value.split())
    if not name:
        raise ValueError(NAME_EMPTY)
    if len(name) > NAME_MAX:
        raise ValueError(NAME_LONG)
    return name


def clean_scene(value):
    """The drawing in its stored form. Deleted elements are dropped (Excalidraw keeps them only for undo)."""
    if not isinstance(value, dict) or not isinstance(value.get('elements'), list):
        raise ValueError(BAD_SCENE)
    elements = []
    for element in value['elements']:
        if not isinstance(element, dict) or not isinstance(element.get('id'), str) or not isinstance(element.get('type'), str):
            raise ValueError(BAD_SCENE)
        if element.get('isDeleted'):
            continue
        # Only our live charts may be framed on a board (the page refuses other embeds too). An 'iframe' element is
        # never kept: Excalidraw shows its customData.generationData.html with scripts allowed, whatever its link.
        if element['type'] == 'iframe':
            continue
        if element['type'] == 'embeddable' and not str(element.get('link') or '').startswith(CHART_LINK):
            continue
        if isinstance(element.get('customData'), dict) and 'generationData' in element['customData']:
            element = dict(element, customData={k: v for k, v in element['customData'].items() if k != 'generationData'})
        elements.append(element)
    if len(elements) > ELEMENTS_MAX:
        raise TooLarge(SCENE_TOO_LARGE.format(limit=mb(SCENE_MAX_BYTES)))
    given = value.get('appState') if isinstance(value.get('appState'), dict) else {}
    app_state = {key: given[key] for key in APP_STATE_KEYS
                 if key in given and (given[key] is None or isinstance(given[key], (str, int, float, bool, dict)))}
    scene = {'type': 'gfm-whiteboard', 'v': 1, 'style': value.get('style') if value.get('style') in STYLES else 'hand',
             'elements': elements, 'appState': app_state}
    if scene_bytes(scene) > SCENE_MAX_BYTES:
        raise TooLarge(SCENE_TOO_LARGE.format(limit=mb(SCENE_MAX_BYTES)))
    return scene


def scene_bytes(scene):
    """The drawing's size as the table's constraint measures it (octet_length(scene::text)): jsonb text puts a space
    after every ':' and ',', like json.dumps with its default separators. (Numbers such as 1e-13 are written out
    longer by the database; save_board and create_board answer its refusal with the same 413.)"""
    return len(json.dumps(scene, ensure_ascii=False).encode('utf-8'))


def used_files(scene):
    """The picture ids the drawing's image elements use."""
    return {e['fileId'] for e in scene['elements']
            if e.get('type') == 'image' and isinstance(e.get('fileId'), str) and FILE_ID.match(e['fileId'])}


def looks_like(mime, data):
    """Do the first bytes of a picture match its type? (So a file cannot pretend to be a picture.)"""
    if mime == 'image/png':
        return data.startswith(b'\x89PNG\r\n\x1a\n')
    if mime == 'image/jpeg':
        return data.startswith(b'\xff\xd8\xff')
    if mime == 'image/gif':
        return data[:6] in (b'GIF87a', b'GIF89a')
    if mime == 'image/webp':
        return data[:4] == b'RIFF' and data[8:12] == b'WEBP'
    if mime == 'image/svg+xml':
        head = data[:4096].lstrip(b'\xef\xbb\xbf \t\r\n').lower()
        return head.startswith(b'<') and b'<svg' in data[:65536].lower()
    return False


def clean_files(value):
    """{id: (mime, bytes)} from {id: {mimeType, dataURL}}; a picture over the limit is a TooLarge."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(BAD_FILE)
    files = {}
    for file_id, entry in value.items():
        if not isinstance(file_id, str) or not FILE_ID.match(file_id) or not isinstance(entry, dict):
            raise ValueError(BAD_FILE)
        match = DATA_URL.match(str(entry.get('dataURL') or ''))
        mime = str(entry.get('mimeType') or (match.group(1) if match else '')).lower()
        if not match or mime not in FILE_TYPES or match.group(1).lower() != mime:
            raise ValueError(BAD_FILE)
        # Size before decoding, so a huge string is refused without being decoded.
        if len(match.group(2)) * 3 // 4 > FILE_MAX_BYTES + 3:
            raise TooLarge(FILE_TOO_LARGE.format(limit=mb(FILE_MAX_BYTES)))
        try:
            data = base64.b64decode(''.join(match.group(2).split()), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(BAD_FILE) from None
        if not data or not looks_like(mime, data):
            raise ValueError(BAD_FILE)
        if len(data) > FILE_MAX_BYTES:
            raise TooLarge(FILE_TOO_LARGE.format(limit=mb(FILE_MAX_BYTES)))
        files[file_id] = (mime, data)
    return files


def iso(value):
    """A time as ISO text; None stays None."""
    return value.isoformat() if value else None


def names_of(conn, user_ids):
    """Display names for these accounts (as the rest of the portal shows them)."""
    ids = sorted({str(u) for u in user_ids if u})
    if not ids:
        return {}
    found = _app().rows(conn, '''SELECT DISTINCT ON (user_id) user_id, display_name FROM public.current_user_context
        WHERE user_id = ANY(%s::uuid[]) ORDER BY user_id, display_name NULLS LAST''', (ids,))
    return {str(r['user_id']): r['display_name'] for r in found}


def summary(row, names):
    """What the list shows of one board (never its drawing or pictures)."""
    return {'id': str(row['id']), 'name': row['name'], 'version': row['version'],
            'created_at': iso(row['created_at']), 'created_by_name': names.get(str(row['created_by'])),
            'updated_at': iso(row['updated_at']), 'updated_by_name': names.get(str(row['updated_by'])),
            'pictures': row.get('pictures', 0)}


# The list is asked for every 20 seconds while a board is open (other people's saves), so it never reads a drawing:
# the scene column is not touched, and the pictures are counted from the picture table's key alone.
LIST_SQL = '''SELECT b.id, b.name, b.version, b.created_at, b.created_by, b.updated_at, b.updated_by,
      (SELECT count(*) FROM portal.whiteboard_files f WHERE f.board_id = b.id) AS pictures
    FROM portal.whiteboards b
    WHERE b.mission_id = %s'''


def board_row(conn, c, bid):
    """One board of c's mission as the list shows it, or None."""
    found = _app().rows(conn, LIST_SQL + ' AND b.id = %s', (c['mission_id'], bid))
    return found[0] if found else None


def store_files(conn, c, bid, scene, files, copy_from=None):
    """Pictures after a save: forget the ones no element uses, add the new ones in use (copied from the board
    copy_from of the same mission where it holds them), then check the limits. Returns the ids the board holds."""
    rows = _app().rows
    used = used_files(scene)
    rows(conn, 'DELETE FROM portal.whiteboard_files WHERE board_id = %s AND NOT (file_id = ANY(%s::text[]))', (bid, sorted(used)))
    if copy_from and copy_from != bid and used:
        rows(conn, '''INSERT INTO portal.whiteboard_files(board_id, file_id, mime_type, bytes, data, created_by)
            SELECT %s, f.file_id, f.mime_type, f.bytes, f.data, f.created_by FROM portal.whiteboard_files f
            JOIN portal.whiteboards b ON b.id = f.board_id
            WHERE f.board_id = %s AND b.mission_id = %s AND f.file_id = ANY(%s::text[])
            ON CONFLICT (board_id, file_id) DO NOTHING''', (bid, copy_from, c['mission_id'], sorted(used)))
    for file_id, (mime, data) in files.items():
        if file_id in used:
            rows(conn, '''INSERT INTO portal.whiteboard_files(board_id, file_id, mime_type, bytes, data, created_by)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (board_id, file_id) DO NOTHING''',
                 (bid, file_id, mime, len(data), data, c['user_id']))
    total = rows(conn, 'SELECT count(*) AS n, coalesce(sum(bytes), 0) AS bytes FROM portal.whiteboard_files WHERE board_id = %s', (bid,))[0]
    if total['n'] > BOARD_FILES_MAX:
        raise TooLarge(TOO_MANY_FILES)
    if total['bytes'] > BOARD_FILES_MAX_BYTES:
        raise TooLarge(FILES_TOO_LARGE.format(limit=mb(BOARD_FILES_MAX_BYTES)))
    return sorted(r['file_id'] for r in rows(conn, 'SELECT file_id FROM portal.whiteboard_files WHERE board_id = %s', (bid,)))


def payload():
    """The request's JSON object; 400 when there is none."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, BAD_SCENE)
    return data


def too_large(error):
    """The 413 answer for a limit that was passed."""
    return jsonify(error=str(error), too_large=True), 413


def refused_by_table(error):
    """A constraint of the tables that portal-api's own checks let through: the same answer as those checks."""
    constraint = getattr(getattr(error, 'diag', None), 'constraint_name', None) or ''
    if constraint == 'whiteboards_scene_size':
        return too_large(SCENE_TOO_LARGE.format(limit=mb(SCENE_MAX_BYTES)))
    if constraint == 'whiteboard_files_size':
        return too_large(FILE_TOO_LARGE.format(limit=mb(FILE_MAX_BYTES)))
    if constraint == 'whiteboards_name_length':
        return jsonify(error=NAME_LONG), 400
    return jsonify(error=BAD_SCENE), 400


def saved_answer(conn, c, bid, file_ids=None):
    """The board as the list shows it, plus the picture ids it holds after a save."""
    row = board_row(conn, c, bid)
    names = names_of(conn, [row['created_by'], row['updated_by']])
    answer = summary(row, names)
    if file_ids is not None:
        answer['file_ids'] = file_ids
    return answer


@whiteboards_bp.get('/api/whiteboards')
def list_boards():
    """The mission's boards, newest change first, with the limits the page shows."""
    c = manager()
    app = _app()
    with app.db() as conn:
        found = app.rows(conn, LIST_SQL + ' ORDER BY b.updated_at DESC, lower(b.name)', (c['mission_id'],))
        names = names_of(conn, [r['created_by'] for r in found] + [r['updated_by'] for r in found])
    return jsonify(boards=[summary(r, names) for r in found],
                   limits={'name': NAME_MAX, 'picture_bytes': FILE_MAX_BYTES, 'pictures': BOARD_FILES_MAX,
                           'pictures_bytes': BOARD_FILES_MAX_BYTES, 'scene_bytes': SCENE_MAX_BYTES})


@whiteboards_bp.post('/api/whiteboards')
def create_board():
    """A new board: empty, a copy of another board (copy_of), or from a drawing the page sends."""
    c = manager()
    data = payload()
    app = _app()
    copy_of = board_id(data['copy_of']) if data.get('copy_of') else None
    files_from = picture_source(data.get('files_from'))
    try:
        name = clean_name(data.get('name'))
        scene, files = (None, {}) if copy_of else new_drawing(data)
    except TooLarge as error:
        return too_large(error)
    try:
        with app.db() as conn:
            check_room_for_board(conn, c, name)
            if copy_of:
                scene = scene_of(conn, c, copy_of)
            bid = str(app.rows(conn, '''INSERT INTO portal.whiteboards(mission_id, name, scene, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s) RETURNING id''', (c['mission_id'], name, Json(scene), c['user_id'], c['user_id']))[0]['id'])
            file_ids = store_files(conn, c, bid, scene, files, copy_from=copy_of or files_from)
            answer = saved_answer(conn, c, bid, file_ids)
    except TooLarge as error:
        return too_large(error)
    except pg_errors.UniqueViolation:
        abort(409, NAME_TAKEN)
    except (pg_errors.CheckViolation, psycopg2.DataError) as error:
        return refused_by_table(error)
    return jsonify(board=answer), 201


def picture_source(value):
    """The board to take pictures from (files_from) as an id text, or None. One that no longer exists simply gives
    no pictures, and anything that is not an id is ignored."""
    try:
        return str(uuid.UUID(str(value))) if value else None
    except ValueError:
        return None


def new_drawing(data):
    """(scene, pictures) of a new board: the drawing the page sent, or an empty one."""
    scene = clean_scene(data['scene']) if data.get('scene') is not None else clean_scene({'elements': []})
    return scene, clean_files(data.get('files'))


def check_room_for_board(conn, c, name):
    """400 when the mission already has BOARDS_MAX boards; 409 when a board of it has this name."""
    rows = _app().rows
    count = rows(conn, 'SELECT count(*) AS n FROM portal.whiteboards WHERE mission_id = %s', (c['mission_id'],))[0]['n']
    if count >= BOARDS_MAX:
        abort(400, TOO_MANY_BOARDS)
    if rows(conn, 'SELECT 1 FROM portal.whiteboards WHERE mission_id = %s AND lower(name) = lower(%s)', (c['mission_id'], name)):
        abort(409, NAME_TAKEN)


def scene_of(conn, c, bid):
    """The drawing of a board of c's mission (for Duplicate); 404 when it is gone."""
    found = _app().rows(conn, 'SELECT scene FROM portal.whiteboards WHERE id = %s AND mission_id = %s',
                        (bid, c['mission_id']))
    if not found:
        abort(404, NOT_FOUND)
    return found[0]['scene']


@whiteboards_bp.get('/api/whiteboards/<bid>')
def get_board(bid):
    """One board with its drawing and pictures."""
    c = manager()
    bid = board_id(bid)
    app = _app()
    with app.db() as conn:
        row = board_row(conn, c, bid)
        if not row:
            abort(404, NOT_FOUND)
        scene = app.rows(conn, 'SELECT scene FROM portal.whiteboards WHERE id = %s', (bid,))[0]['scene']
        stored = app.rows(conn, '''SELECT file_id, mime_type, data, created_at FROM portal.whiteboard_files
            WHERE board_id = %s ORDER BY created_at, file_id''', (bid,))
        names = names_of(conn, [row['created_by'], row['updated_by']])
    files = {f['file_id']: {'id': f['file_id'], 'mimeType': f['mime_type'],
                            'dataURL': f"data:{f['mime_type']};base64,{base64.b64encode(bytes(f['data'])).decode('ascii')}",
                            'created': int(f['created_at'].timestamp() * 1000)} for f in stored}
    return jsonify(board=dict(summary(row, names), file_ids=sorted(files)), scene=scene, files=files)


@whiteboards_bp.put('/api/whiteboards/<bid>')
def save_board(bid):
    """Save a board's drawing and pictures; 409 when someone else saved since the version the page has."""
    c = manager()
    bid = board_id(bid)
    data = payload()
    version = data.get('version')
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        abort(400, BAD_SCENE)
    try:
        scene = clean_scene(data.get('scene'))
        files = clean_files(data.get('files'))
    except TooLarge as error:
        return too_large(error)
    app = _app()
    try:
        with app.db() as conn:
            saved = app.rows(conn, '''UPDATE portal.whiteboards SET scene = %s, version = version + 1, updated_by = %s,
                updated_at = now() WHERE id = %s AND mission_id = %s AND version = %s RETURNING version''',
                (Json(scene), c['user_id'], bid, c['mission_id'], version))
            if not saved:
                current = board_row(conn, c, bid)
                if not current:
                    abort(404, NOT_FOUND)
                names = names_of(conn, [current['updated_by']])
                return jsonify(error=CONFLICT, conflict=True, board=summary(current, names)), 409
            file_ids = store_files(conn, c, bid, scene, files)
            answer = saved_answer(conn, c, bid, file_ids)
    except TooLarge as error:
        return too_large(error)
    except (pg_errors.CheckViolation, psycopg2.DataError) as error:
        return refused_by_table(error)
    return jsonify(board=answer)


@whiteboards_bp.patch('/api/whiteboards/<bid>')
def rename_board(bid):
    """Rename a board (its drawing and version stay as they are)."""
    c = manager()
    bid = board_id(bid)
    name = clean_name(payload().get('name'))
    app = _app()
    try:
        with app.db() as conn:
            if app.rows(conn, 'SELECT 1 FROM portal.whiteboards WHERE mission_id = %s AND lower(name) = lower(%s) AND id <> %s',
                        (c['mission_id'], name, bid)):
                abort(409, NAME_TAKEN)
            if not app.rows(conn, 'UPDATE portal.whiteboards SET name = %s WHERE id = %s AND mission_id = %s RETURNING id',
                            (name, bid, c['mission_id'])):
                abort(404, NOT_FOUND)
            answer = saved_answer(conn, c, bid)
    except pg_errors.UniqueViolation:
        abort(409, NAME_TAKEN)
    return jsonify(board=answer)


@whiteboards_bp.delete('/api/whiteboards/<bid>')
def delete_board(bid):
    """Delete a board and its pictures."""
    c = manager()
    bid = board_id(bid)
    app = _app()
    with app.db() as conn:
        if not app.rows(conn, 'DELETE FROM portal.whiteboards WHERE id = %s AND mission_id = %s RETURNING id', (bid, c['mission_id'])):
            abort(404, NOT_FOUND)
    return jsonify(ok=True, deleted=bid)
