// Unit tests of manager/web.mjs (answering web requests) and manager/settings.mjs (the manager's settings).
// Plain Node, no packages. Run from slidev/:  node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import zlib from 'node:zlib';
import { escapeHtml, httpError, isReading, keptText, mimeType, parseCookies, readBody, sendHtml, sendJson, sendKept, sendNotFound, wantsHtml } from '../manager/web.mjs';

/** A stand-in for Node's response: remembers the status, the headers and the body (req: the request it answers). */
function fakeResponse(req = undefined) {
  return {
    req, status: 0, headers: {}, body: '', bytes: Buffer.alloc(0),
    writeHead(status, headers = {}) { this.status = status; Object.assign(this.headers, headers); },
    end(body = '') { this.body += body; if (Buffer.isBuffer(body)) this.bytes = Buffer.concat([this.bytes, body]); },
  };
}

/** A stand-in for a request whose body arrives in these pieces (Buffers). */
const requestWith = (...chunks) => Readable.from(chunks);

test('httpError: an Error that carries its HTTP status', () => {
  const error = httpError(403, 'Not for you.');
  assert.ok(error instanceof Error);
  assert.equal(error.status, 403);
  assert.equal(error.message, 'Not for you.');
});

test('escapeHtml: every character that could start HTML or end an attribute', () => {
  assert.equal(escapeHtml(`<a href="x" title='y'>Tom & Jerry</a>`), '&lt;a href=&quot;x&quot; title=&#039;y&#039;&gt;Tom &amp; Jerry&lt;/a&gt;');
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
  assert.equal(escapeHtml(42), '42');
});

test('parseCookies: every cookie by name, values decoded, pieces without = left out', () => {
  const req = { headers: { cookie: 'presentation_session=abc123; gfm_lang=pt%2DBR ; broken; a=b=c' } };
  assert.deepEqual(parseCookies(req), { presentation_session: 'abc123', gfm_lang: 'pt-BR', a: 'b=c' });
  assert.deepEqual(parseCookies({ headers: {} }), {});
});

test('sendJson, sendHtml and sendNotFound: status, type, never cached', () => {
  const json = fakeResponse();
  sendJson(json, 201, { ok: true }, { 'Set-Cookie': 'x=1' });
  assert.equal(json.status, 201);
  assert.equal(json.headers['Content-Type'], 'application/json; charset=utf-8');
  assert.equal(json.headers['Cache-Control'], 'no-store');
  assert.equal(json.headers['Set-Cookie'], 'x=1');
  assert.deepEqual(JSON.parse(json.body), { ok: true });

  const page = fakeResponse();
  sendHtml(page, '<p>hi</p>', 403);
  assert.equal(page.status, 403);
  assert.equal(page.headers['Content-Type'], 'text/html; charset=utf-8');
  assert.equal(page.headers['Cache-Control'], 'no-store');
  assert.equal(page.body, '<p>hi</p>');
  const plain = fakeResponse();
  sendHtml(plain, 'x');
  assert.equal(plain.status, 200);

  const missing = fakeResponse();
  sendNotFound(missing);
  assert.equal(missing.status, 404);
  assert.equal(missing.body, 'Not found.');
});

test('sendHtml: a page of more than 1 KB goes packed to a browser that takes gzip', () => {
  const page = `<p>${'Our zone council · '.repeat(100)}</p>`;
  const packed = fakeResponse({ headers: { 'accept-encoding': 'gzip, deflate, br' } });
  sendHtml(packed, page);
  assert.equal(packed.headers['Content-Encoding'], 'gzip');
  assert.equal(packed.headers.Vary, 'Accept-Encoding');
  assert.equal(zlib.gunzipSync(packed.bytes).toString(), page);
  assert.equal(packed.headers['Content-Length'], packed.bytes.length);
  const plain = fakeResponse({ headers: {} });
  sendHtml(plain, page);
  assert.equal(plain.headers['Content-Encoding'], undefined, 'a browser that does not take gzip');
  assert.equal(plain.body, page);
  const small = fakeResponse({ headers: { 'accept-encoding': 'gzip' } });
  sendHtml(small, '<p>hi</p>');
  assert.equal(small.headers['Content-Encoding'], undefined, 'not worth it under 1 KB');
});

test('keptText and sendKept: packed once, "not changed" (304) for the same version', () => {
  const kept = keptText('console.log("portal-bridge");\n'.repeat(50));
  assert.equal(zlib.gunzipSync(kept.gzip).toString(), kept.body.toString());
  assert.match(kept.etag, /^"[0-9a-f]{20}"$/);
  assert.notEqual(keptText('other').etag, kept.etag);
  const packed = fakeResponse();
  sendKept({ method: 'GET', headers: { 'accept-encoding': 'gzip' } }, packed, kept, 'text/javascript; charset=utf-8');
  assert.deepEqual([packed.status, packed.headers['Content-Encoding'], packed.headers.ETag, packed.headers['Cache-Control']], [200, 'gzip', kept.etag, 'no-cache']);
  assert.deepEqual(packed.bytes, kept.gzip);
  const plain = fakeResponse();
  sendKept({ method: 'GET', headers: {} }, plain, kept, 'text/javascript', 'public, max-age=604800');
  assert.deepEqual([plain.status, plain.headers['Content-Encoding'], plain.headers['Cache-Control']], [200, undefined, 'public, max-age=604800']);
  assert.deepEqual(plain.bytes, kept.body);
  const same = fakeResponse();
  sendKept({ method: 'GET', headers: { 'if-none-match': kept.etag, 'accept-encoding': 'gzip' } }, same, kept, 'text/javascript');
  assert.deepEqual([same.status, same.bytes.length, same.body], [304, 0, '']);
  const head = fakeResponse();
  sendKept({ method: 'HEAD', headers: {} }, head, kept, 'text/javascript');
  assert.deepEqual([head.status, head.headers['Content-Length'], head.bytes.length], [200, kept.body.length, 0]);
});

test('readBody: JSON, an empty body, a character split between two pieces', async () => {
  assert.deepEqual(await readBody(requestWith(Buffer.from('{"title":"Zone conference"}'))), { title: 'Zone conference' });
  assert.deepEqual(await readBody(requestWith()), {});
  // "é" is two bytes; the pieces split it in the middle.
  const bytes = Buffer.from('{"title":"Réunion"}');
  const cut = bytes.indexOf(0xc3) + 1;
  assert.deepEqual(await readBody(requestWith(bytes.subarray(0, cut), bytes.subarray(cut))), { title: 'Réunion' });
});

test('readBody: 413 when too large, 400 when not JSON', async () => {
  await assert.rejects(readBody(requestWith(Buffer.alloc(20, 32)), 10), error => error.status === 413);
  await assert.rejects(readBody(requestWith(Buffer.from('{not json'))), error => error.status === 400 && error.message === 'The request could not be read.');
});

test('wantsHtml: only a browser opening a page; isReading: GET and HEAD', () => {
  assert.equal(wantsHtml({ method: 'GET', headers: { accept: 'text/html,application/xhtml+xml' } }), true);
  assert.equal(wantsHtml({ method: 'GET', headers: { accept: 'application/json' } }), false);
  assert.equal(wantsHtml({ method: 'POST', headers: { accept: 'text/html' } }), false);
  assert.equal(wantsHtml({ method: 'GET', headers: {} }), false);
  assert.equal(isReading({ method: 'GET' }), true);
  assert.equal(isReading({ method: 'HEAD' }), true);
  assert.equal(isReading({ method: 'POST' }), false);
});

test('mimeType: by the file extension, in any case; unknown files as bytes', () => {
  assert.equal(mimeType('/p/deck/index.html'), 'text/html; charset=utf-8');
  assert.equal(mimeType('assets/app-1a2b.JS'), 'text/javascript; charset=utf-8');
  assert.equal(mimeType('font.woff2'), 'font/woff2');
  assert.equal(mimeType('slides.pdf'), 'application/pdf');
  assert.equal(mimeType('notes.unknown'), 'application/octet-stream');
  assert.equal(mimeType('no-extension'), 'application/octet-stream');
  assert.equal(mimeType('x.constructor'), 'application/octet-stream');
});

// ---- settings.mjs ----

// settings.mjs reads the environment once, when it is loaded; a new ?query loads a fresh copy.
async function settingsWith(env) {
  const saved = { ...process.env };
  try {
    for (const name of Object.keys(env)) {
      if (env[name] === undefined) delete process.env[name];
      else process.env[name] = env[name];
    }
    return await import(`../manager/settings.mjs?${Math.random()}`);
  } finally {
    for (const name of Object.keys(env)) delete process.env[name];
    Object.assign(process.env, saved);
  }
}

const SETTING_NAMES = ['PRESENTATION_SLIDEV_HOME', 'PRESENTATION_BIND_ADDRESS', 'PRESENTATION_MANAGER_PORT', 'PRESENTATION_DECK_SERVER_PORT', 'PRESENTATIONS_DECK_PORT',
  'PRESENTATIONS_PUBLIC_PORT', 'PRESENTATIONS_PORTAL_ORIGINS', 'PRESENTATION_ACL_API_URL', 'SLIDEV_IDLE_MINUTES', 'SLIDEV_PRESTART', 'SLIDEV_BUILD_DEBOUNCE_MS',
  'SLIDEV_BUILD_CONCURRENCY', 'SLIDEV_ADDON_REBUILD', 'SLIDEV_MAX_RUNNING', 'SLIDEV_INTERNAL_PORT_START', 'PRESENTATIONS_HOST',
  'PRESENTATIONS_PUBLIC_MANAGER_ORIGIN', 'PRESENTATIONS_PUBLIC_DECK_ORIGIN', 'PRESENTATIONS_PUBLIC_COOKIE_DOMAIN', 'PRESENTATIONS_PUBLIC_PORTAL_ORIGINS', 'GFM_PUBLIC_DOMAIN'];
const unset = Object.fromEntries(SETTING_NAMES.map(name => [name, undefined]));

test('settings: without GFM_PUBLIC_DOMAIN there are no public names', async () => {
  const s = await settingsWith(unset);
  assert.deepEqual({ ...s.PUBLIC_NAMES }, { manager: '', deck: '', cookieDomain: '' });
  assert.deepEqual([...s.PORTAL_ORIGINS], ['http://localhost:8070', 'http://127.0.0.1:8070', 'http://192.168.1.20:8070']);
  assert.equal(s.PUBLIC_HOST, 'localhost');
  const other = await settingsWith({ ...unset, GFM_PUBLIC_DOMAIN: ' .Example.ORG. ' });
  assert.deepEqual({ ...other.PUBLIC_NAMES }, { manager: 'https://presentations.example.org', deck: 'https://decks.example.org', cookieDomain: 'example.org' });
  assert.ok(other.PORTAL_ORIGINS.has('https://www.example.org'));
});

test('settings: the defaults, with GFM_PUBLIC_DOMAIN set to the Frankfurt domain', async () => {
  const s = await settingsWith({ ...unset, GFM_PUBLIC_DOMAIN: 'example.org' });
  assert.equal(s.DECKS_DIR, '/slidev/decks');
  assert.equal(s.SLIDEV_DIR, '/slidev');
  assert.equal(s.SLIDEV_BIN, '/slidev/node_modules/.bin/slidev');
  assert.equal(s.MONACO_DIR, '/slidev/node_modules/monaco-editor/min/vs');
  assert.equal(s.PACKAGE_JSON, '/slidev/package.json');
  assert.equal(s.BIND_ADDRESS, '0.0.0.0');
  assert.equal(s.MANAGER_PORT, 3040);
  assert.equal(s.DECK_SERVER_PORT, 3041);
  assert.equal(s.DECK_PUBLIC_PORT, 8089);
  assert.equal(s.MANAGER_PUBLIC_PORT, 3030);
  assert.equal(s.PORTAL_API_URL, 'http://portal-api:8091');
  // Round 10: the portal's public addresses count too; the office ports stay the only port rule.
  assert.deepEqual([...s.PORTAL_ORIGINS], ['http://localhost:8070', 'http://127.0.0.1:8070', 'http://192.168.1.20:8070',
    'https://example.org', 'https://www.example.org']);
  assert.deepEqual([...s.PORTAL_PORTS], ['http:8070']);
  assert.deepEqual({ ...s.PUBLIC_NAMES }, { manager: 'https://presentations.example.org',
    deck: 'https://decks.example.org', cookieDomain: 'example.org' });
  assert.equal(s.ADDRESSES.managerPort, 3030);
  assert.equal(s.ADDRESSES.deckPort, 8089);
  assert.equal(s.PUBLIC_HOST, 'decks.example.org', 'Vite accepts the deck address\'s public name');
  assert.equal(s.SESSION_TTL_MS, 12 * 60 * 60 * 1000);
  assert.equal(s.FIRST_EDITOR_PORT, 3100);
  assert.equal(s.MAX_RUNNING_EDITORS, 10);
  assert.equal(s.IDLE_STOP_MS, 40 * 60 * 1000);
  assert.equal(s.PRESTART, true);
  assert.equal(s.BUILD_DEBOUNCE_MS, 10000);
  assert.equal(s.BUILD_CONCURRENCY, 1);
  assert.equal(s.ADDON_REBUILD, true);
});

test('settings: the environment changes them, within their limits', async () => {
  const s = await settingsWith({
    ...unset, GFM_PUBLIC_DOMAIN: 'example.org',
    PRESENTATION_SLIDEV_HOME: '/tmp/slidev-test', PRESENTATION_BIND_ADDRESS: '127.0.0.1', PRESENTATION_DECK_SERVER_PORT: '0',
    PRESENTATIONS_PORTAL_ORIGINS: ' https://portal.example:8443 ,, http://10.0.0.5:8070 ', PRESENTATION_ACL_API_URL: 'http://api:9000/',
    SLIDEV_IDLE_MINUTES: '1', SLIDEV_PRESTART: '0', SLIDEV_BUILD_DEBOUNCE_MS: '5', SLIDEV_BUILD_CONCURRENCY: '7', SLIDEV_ADDON_REBUILD: '0',
  });
  assert.equal(s.DECKS_DIR, '/tmp/slidev-test/decks');
  assert.equal(s.SLIDEV_BIN, '/tmp/slidev-test/node_modules/.bin/slidev');
  assert.equal(s.BIND_ADDRESS, '127.0.0.1');
  assert.equal(s.DECK_SERVER_PORT, 0, '0 means any free port (tests)');
  assert.deepEqual([...s.PORTAL_ORIGINS], ['https://portal.example:8443', 'http://10.0.0.5:8070',
    'https://example.org', 'https://www.example.org']);
  assert.deepEqual([...s.PORTAL_PORTS].sort(), ['http:8070', 'https:8443']);
  assert.equal(s.PORTAL_API_URL, 'http://api:9000', 'no slash at the end');
  assert.equal(s.IDLE_STOP_MS, 5 * 60 * 1000, 'at least 5 minutes');
  assert.equal(s.PRESTART, false);
  assert.equal(s.BUILD_DEBOUNCE_MS, 1000, 'at least a second');
  assert.equal(s.BUILD_CONCURRENCY, 2, 'at most two builds at once');
  assert.equal(s.ADDON_REBUILD, false);
});

test('settings: round 10, the public names can be changed or turned off', async () => {
  const off = await settingsWith({ ...unset, GFM_PUBLIC_DOMAIN: 'example.org', PRESENTATIONS_PUBLIC_MANAGER_ORIGIN: '', PRESENTATIONS_PUBLIC_DECK_ORIGIN: '',
    PRESENTATIONS_PUBLIC_PORTAL_ORIGINS: '' });
  assert.deepEqual({ ...off.PUBLIC_NAMES }, { manager: '', deck: '', cookieDomain: 'example.org' });
  assert.deepEqual([...off.PORTAL_ORIGINS], ['http://localhost:8070', 'http://127.0.0.1:8070', 'http://192.168.1.20:8070']);
  assert.equal(off.PUBLIC_HOST, 'localhost');
  const other = await settingsWith({ ...unset, PRESENTATIONS_PUBLIC_MANAGER_ORIGIN: 'https://p.example/ ',
    PRESENTATIONS_PUBLIC_DECK_ORIGIN: 'javascript:alert(1)', PRESENTATIONS_HOST: 'editor.example' });
  assert.equal(other.PUBLIC_NAMES.manager, 'https://p.example', 'only the origin');
  assert.equal(other.PUBLIC_NAMES.deck, '', 'not an http(s) address: off');
  assert.equal(other.PUBLIC_HOST, 'editor.example', 'a real PRESENTATIONS_HOST wins');
});
