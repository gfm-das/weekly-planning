// Opening the editor fast: editors are started ahead of time, so "Edit" finds one ready.
//   manager/editors.mjs prestartRecentDeck, manager/manager-routes.mjs listLibrary and prestartEditor, library.html.
// Needs a POSIX shell (the stand-in editor of tests/helpers/manager-harness.mjs); skipped on Windows. The real
// "click Edit -> editable" timing in a browser is measured with tests/studio-perf (README there).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { after, before, test } from 'node:test';
import { freePort, startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const posix = process.platform !== 'win32';
const skip = posix ? false : 'needs a POSIX shell (run in node:24-alpine)';

// A Zone Leader who may change the decks one, two and three (and see, but not change, "locked").
const EDITABLE = ['one', 'two', 'three', 'four', 'five'];
const ALL = [...EDITABLE, 'locked'];
const ME = token('user-zl');

let stub, manager, session;
before(async () => {
  if (!posix) return;
  stub = await startStub((req, url, body) => supabaseAnswer(req, url) || (url.pathname === '/internal/presentations/check'
    ? [200, { role: 'ZL', can_manage: false, can_use: true, can_create: true, allowed_slugs: ALL, editable_slugs: EDITABLE, owner_zones: {} }]
    : [404, { error: 'stand-in' }]));
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  manager = await startManager({
    decks: Object.fromEntries(ALL.map(slug => [slug, slug])),
    editor: true,
    env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl, PRESENTATIONS_PORTAL_ORIGINS: 'http://127.0.0.1:8070', SLIDEV_PRESTART: '1', SLIDEV_BOOT_PRESTART: '0', SLIDEV_INTERNAL_PORT_START: String(await freePort()) },
  });
  // "locked" was changed last, then two, three, four, five and "one" (the oldest).
  const now = Date.now();
  for (const [slug, ago] of [['locked', 1000], ['two', 2000], ['three', 3000], ['four', 4000], ['five', 5000], ['one', 6000]]) {
    const when = new Date(now - ago * 1000);
    await fs.utimes(path.join(manager.decks, slug, 'slides.md'), when, when);
  }
  const signedIn = await fetch(`${manager.url}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${ME}` } });
  session = (signedIn.headers.get('set-cookie') || '').split(';')[0];
});

after(async () => {
  if (manager) await manager.stop();
  if (stub) await new Promise(resolve => stub.close(resolve));
});

const api = (pathname, method = 'GET', body) => fetch(`${manager.url}${pathname}`, {
  method, body: body ? JSON.stringify(body) : undefined,
  headers: { Cookie: session, 'X-GFM-Request': '1', 'Sec-Fetch-Site': 'same-origin', ...(body ? { 'Content-Type': 'application/json' } : {}) },
});
const startedDecks = () => [...manager.log().matchAll(/\[([a-z0-9-]+):edit\] starting Slidev/g)].map(match => match[1]);
const until = async (check, ms = 5000) => { const t = Date.now(); while (!await check()) { if (Date.now() - t > ms) throw new Error('timed out'); await new Promise(resolve => setTimeout(resolve, 50)); } };

test('opening the library starts the editors of the four most recently changed decks the person may change', { skip }, async () => {
  const list = await api('/api/presentations');
  assert.equal(list.status, 200);
  await until(() => startedDecks().length >= 4);
  assert.deepEqual(startedDecks().sort(), ['five', 'four', 'three', 'two'], 'not "locked" (newest, but not theirs to change), not the oldest');
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(startedDecks().length, 4, 'four editors at most start ahead of time (memory)');
});

test('Edit on a deck whose editor is already running answers at once (under 1 second)', { skip }, async () => {
  await until(async () => (await (await api('/api/presentations/two/editor')).json()).stage === 'ready');
  const t = performance.now();
  const opened = await api('/api/presentations/two/editor', 'POST', { page: 'pagea00001' });
  const ms = performance.now() - t;
  assert.equal(opened.status, 200);
  assert.ok(ms < 1000, `the editor answered in ${Math.round(ms)} ms`);
  assert.equal(startedDecks().filter(slug => slug === 'two').length, 1, 'the running editor was used, not started again');
});

test('the three dots of a card start the editor ahead of time (library.html), once per deck every 30 s', () => {
  const html = readFileSync(new URL('../manager/library.html', import.meta.url), 'utf8');
  assert.match(html, /function prestartEditor\(p\)[\s\S]*?30000/);
  assert.match(html, /\['pointerenter', 'focus', 'touchstart'\][\s\S]*?prestartEditor\(p\)/);
  assert.match(html, /add\('Edit', \(\) => openEditor\(p\)\);\s*[^\n]*\s*[^\n]*\n\s*prestartEditor\(p\);/);
});
