// Protected decks (manager/protected-decks.mjs): a deck that another page opens by its folder name is
// protected, so the presentation manager refuses to rename or delete it, and the library shows why instead
// of offering Rename and Delete. Editing, publishing and duplicating work. Since round 6 the real list is
// empty (Dashboards are DataEase, no longer the deck `mission-dashboard`); the mechanism is kept and tested
// with `mission-dashboard` as the example: the helpers get it as their list, and the manager copy in
// section 2 gets a protected-decks.mjs whose list holds it.
//
// 1. The helpers, plain Node.
// 2. The real manager routes, run from a copy in a temporary folder (tests/helpers/manager-harness.mjs: a stand-in
//    `slidev build` that writes one page, and small stand-ins for the four packages the manager imports).
//    Supabase Auth, PostgREST and portal-api are one local stand-in that records every access call.
// 3. The library page as the manager serves it, its script run in a Node vm with a small fake DOM.
// 2 and 3 need a POSIX shell (the node:24-alpine test container); they are skipped on Windows.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { after, before, test } from 'node:test';
import vm from 'node:vm';
import { PROTECTED_DECKS, PROTECTED_MESSAGE, protectedReason, refuseIfProtected, withProtection } from '../manager/protected-decks.mjs';
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const MESSAGE = 'Another part of the mission portal opens this deck by its name, so it cannot be renamed or deleted. Duplicate it to experiment.';
const DECK = 'mission-dashboard';
const EXAMPLE = Object.freeze([DECK]);

// ---- 1. Helpers ----

test('one list, empty since round 6 (mission-dashboard is no longer protected), with the plain message', () => {
  assert.deepEqual([...PROTECTED_DECKS], []);
  assert.ok(Object.isFrozen(PROTECTED_DECKS));
  assert.equal(PROTECTED_MESSAGE, MESSAGE);
  assert.equal(protectedReason(DECK), null);
  assert.doesNotThrow(() => refuseIfProtected(DECK));
  const entry = { slug: DECK, title: 'Mission Dashboard', updated_at: '2026-09-28T07:00:00.000Z' };
  assert.equal(withProtection(entry), entry);
});

test('only the exact folder name is protected (copies and other decks are not)', () => {
  assert.equal(protectedReason(DECK, EXAMPLE), MESSAGE);
  for (const slug of ['mission-dashboard-copy', 'mission-dashboard-2', 'mission-dashboard-2026', 'chart-gallery', 'Mission-Dashboard', 'mission', '', undefined, null]) {
    assert.equal(protectedReason(slug, EXAMPLE), null, String(slug));
  }
});

test('refuseIfProtected throws 409 with the message, and nothing for other decks', () => {
  assert.throws(() => refuseIfProtected(DECK, EXAMPLE), error => error.status === 409 && error.message === MESSAGE && error.protectedDeck === true);
  assert.doesNotThrow(() => refuseIfProtected('mission-dashboard-copy', EXAMPLE));
  assert.doesNotThrow(() => refuseIfProtected('chart-gallery', EXAMPLE));
});

test('withProtection marks library entries of protected decks only', () => {
  const entry = { slug: DECK, title: 'Mission Dashboard', updated_at: '2026-09-28T07:00:00.000Z' };
  assert.deepEqual(withProtection(entry, EXAMPLE), { ...entry, protected: true, protected_reason: MESSAGE });
  assert.deepEqual(entry, { slug: DECK, title: 'Mission Dashboard', updated_at: '2026-09-28T07:00:00.000Z' }, 'the input is not changed');
  const other = { slug: 'chart-gallery', title: 'Chart gallery', updated_at: entry.updated_at };
  assert.equal(withProtection(other, EXAMPLE), other);
});

// ---- 2. The manager's routes ----

const posix = process.platform !== 'win32';
const skip = posix ? false : 'needs a POSIX shell (run in node:24-alpine)';
const AP = token('user-ap'), DL = token('user-dl');

let decks, manager, stub, managerUrl;
const accessCalls = [];

// Supabase Auth + PostgREST + portal-api /internal/presentations/*: an AP (manager) and a DL (leader).
function stubAnswer(req, url, body) {
  if (url.pathname === '/rest/v1/current_user_context') {
    const id = url.searchParams.get('user_id').replace(/^eq\./, '');
    return [200, [{ user_id: id, user_active: true, app_role: id === 'user-dl' ? 'DL' : 'AP', mission_id: 1 }]];
  }
  const supabase = supabaseAnswer(req, url);
  if (supabase) return supabase;
  if (url.pathname === '/internal/presentations/check') {
    return [200, body.user_id === 'user-ap'
      ? { can_manage: true, role: 'AP', allowed_slugs: body.deck_slugs || [] }
      : { can_manage: false, role: 'DL', allowed_slugs: [] }];
  }
  if (url.pathname === '/internal/presentations/access') {
    accessCalls.push({ operation: body.operation, deck_slug: body.deck_slug, new_slug: body.new_slug });
    return [200, { ok: true, access: { roles: [], zone_ids: [], district_ids: [], user_ids: [], everyone: false }, options: {} }];
  }
  return [404, { error: 'stub: not found' }];
}

before(async () => {
  if (!posix) return;
  stub = await startStub(stubAnswer);
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  // The mechanism with the example list (the real one is empty since round 6).
  manager = await startManager({
    protectedDecks: [DECK],
    decks: { [DECK]: 'Mission Dashboard', 'chart-gallery': 'Chart gallery', 'old-notes': 'Old notes' },
    env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl },
  });
  managerUrl = manager.url;
  decks = manager.decks;
});

after(async () => {
  await manager?.stop();
  if (stub) await new Promise(r => stub.close(r));
});

async function api(pathname, { method = 'GET', body, as = AP } = {}) {
  const response = await fetch(`${managerUrl}${pathname}`, {
    method, headers: { Authorization: `Bearer ${as}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let json = null;
  try { json = JSON.parse(text); } catch {}
  return { status: response.status, json, text };
}

const folders = async () => (await fs.readdir(decks)).filter(name => !name.startsWith('.')).sort();
const slidesOf = slug => fs.readFile(path.join(decks, slug, 'slides.md'), 'utf8');
const operations = () => accessCalls.map(c => `${c.operation}:${c.deck_slug}${c.new_slug ? `>${c.new_slug}` : ''}`);

test('the library list marks mission-dashboard as protected, with the message', { skip }, async () => {
  const { status, json } = await api('/api/presentations');
  assert.equal(status, 200);
  const bySlug = Object.fromEntries(json.presentations.map(p => [p.slug, p]));
  assert.equal(bySlug[DECK].protected, true);
  assert.equal(bySlug[DECK].protected_reason, MESSAGE);
  assert.equal(bySlug[DECK].title, 'Mission Dashboard');
  assert.equal('protected' in bySlug['chart-gallery'], false);
});

test('Rename of mission-dashboard is refused (409, the message) and changes nothing', { skip }, async () => {
  const before = await slidesOf(DECK), calls = accessCalls.length;
  for (const title of ['Mission Dashboard 2026', 'Mission Dashboard', 'mission dashboard']) {
    const { status, json } = await api(`/api/presentations/${DECK}/rename`, { method: 'POST', body: { title } });
    assert.equal(status, 409, title);
    assert.equal(json.error, MESSAGE);
  }
  assert.deepEqual(await folders(), ['chart-gallery', DECK, 'old-notes']);
  assert.equal(await slidesOf(DECK), before);
  assert.equal(accessCalls.length, calls, 'the access rule was not moved');
});

test('Delete of mission-dashboard is refused (409, the message) and changes nothing', { skip }, async () => {
  const calls = accessCalls.length;
  const { status, json } = await api(`/api/presentations/${DECK}`, { method: 'DELETE' });
  assert.equal(status, 409);
  assert.equal(json.error, MESSAGE);
  assert.ok((await folders()).includes(DECK));
  assert.equal(accessCalls.length, calls, 'the access rule was not removed');
});

test('a leader is still refused as before (the manager check comes first)', { skip }, async () => {
  const rename = await api(`/api/presentations/${DECK}/rename`, { method: 'POST', body: { title: 'X' }, as: DL });
  const remove = await api(`/api/presentations/${DECK}`, { method: 'DELETE', as: DL });
  assert.equal(rename.status, 403);
  assert.equal(remove.status, 403);
  assert.notEqual(rename.json.error, MESSAGE);
});

test('editing mission-dashboard still works (Source: load and save)', { skip }, async () => {
  const loaded = await api(`/api/presentations/${DECK}/source`);
  assert.equal(loaded.status, 200);
  const markdown = loaded.json.markdown + '\n---\n\n# A new slide\n';
  const saved = await api(`/api/presentations/${DECK}/source`, { method: 'PUT', body: { markdown, version: loaded.json.version } });
  assert.equal(saved.status, 200, saved.text);
  assert.equal(await slidesOf(DECK), markdown);
});

test('publishing mission-dashboard still works', { skip }, async () => {
  const { status, json, text } = await api(`/api/presentations/${DECK}/publish`, { method: 'POST' });
  assert.equal(status, 200, `${text}\n${manager.log().slice(-2000)}`);
  assert.equal(json.slug, DECK);
  await fs.access(path.join(decks, DECK, 'dist', 'index.html'));
});

test('duplicating mission-dashboard still works, and the copy can be renamed and deleted', { skip }, async () => {
  const copy = await api(`/api/presentations/${DECK}/duplicate`, { method: 'POST' });
  assert.equal(copy.status, 201, copy.text);
  assert.equal(copy.json.slug, 'mission-dashboard-copy');
  assert.equal(copy.json.build_error, undefined, copy.json.build_error);
  assert.ok(operations().includes(`duplicate:${DECK}>mission-dashboard-copy`));
  const list = await api('/api/presentations');
  assert.equal('protected' in list.json.presentations.find(p => p.slug === 'mission-dashboard-copy'), false);

  const renamed = await api('/api/presentations/mission-dashboard-copy/rename', { method: 'POST', body: { title: 'Dashboard experiments' } });
  assert.equal(renamed.status, 200, renamed.text);
  assert.equal(renamed.json.slug, 'dashboard-experiments');
  assert.ok(operations().includes('rename:mission-dashboard-copy>dashboard-experiments'));

  const removed = await api('/api/presentations/dashboard-experiments', { method: 'DELETE' });
  assert.equal(removed.status, 200, removed.text);
  assert.ok(operations().includes('delete:dashboard-experiments'));
  assert.deepEqual(await folders(), ['chart-gallery', DECK, 'old-notes']);
});

test('other decks can still be renamed and deleted', { skip }, async () => {
  const renamed = await api('/api/presentations/chart-gallery/rename', { method: 'POST', body: { title: 'Chart examples' } });
  assert.equal(renamed.status, 200, renamed.text);
  assert.equal(renamed.json.slug, 'chart-examples');
  const removed = await api('/api/presentations/old-notes', { method: 'DELETE' });
  assert.equal(removed.status, 200, removed.text);
  assert.deepEqual(await folders(), ['chart-examples', DECK]);
  assert.equal((await api('/api/presentations')).json.presentations.find(p => p.slug === DECK).protected, true);
});

test('the editor page (/studio) knows mission-dashboard keeps its name', { skip }, async () => {
  const studioData = async slug => {
    const { status, text } = await api(`/studio/${slug}`);
    assert.equal(status, 200);
    return JSON.parse(/window\.STUDIO=(.*?);<\/script>/.exec(text)[1]);
  };
  assert.equal((await studioData(DECK)).protected_reason, MESSAGE);
  assert.equal((await studioData('chart-examples')).protected_reason, null);
  const { text } = await api(`/studio/${DECK}`);
  assert.match(text, /if \(STUDIO\.protected_reason\) \{ toast\(STUDIO\.protected_reason, true\); return; \}/, 'clicking the title shows the message instead of renaming');
});

// ---- 3. The library page ----

class FakeElement {
  constructor(tag, id = '') {
    this.tagName = tag.toUpperCase(); this.id = id; this.children = []; this.attributes = {}; this.style = {}; this.dataset = {};
    this.textContent = ''; this.className = ''; this.value = ''; this.open = false; this.disabled = false; this.offsetWidth = 220; this.offsetHeight = 260;
    this.parts = new Map(); this.html = '';
    const set = new Set();
    this.classList = { add: c => set.add(c), remove: c => set.delete(c), contains: c => set.has(c), toggle: (c, on = !set.has(c)) => (on ? set.add(c) : set.delete(c), on) };
  }
  set innerHTML(value) { this.html = value; this.children = []; this.parts = new Map(); }
  get innerHTML() { return this.html; }
  appendChild(child) { this.children.push(child); return child; }
  querySelector(selector) { if (!this.parts.has(selector)) this.parts.set(selector, new FakeElement('div')); return this.parts.get(selector); }
  querySelectorAll() { return []; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener() {}
  getBoundingClientRect() { return { left: 0, top: 0, right: 300, bottom: 120 }; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
}

async function libraryPage() {
  const html = await fetch(`${managerUrl}/`).then(r => r.text());
  const script = /<script>([\s\S]*?)<\/script>/.exec(html)[1];
  const elements = new Map();
  const document = {
    body: new FakeElement('body'),
    getElementById: id => { if (!elements.has(id)) elements.set(id, new FakeElement('div', id)); return elements.get(id); },
    createElement: tag => new FakeElement(tag),
    addEventListener() {}, querySelectorAll: () => [],
  };
  const alerts = [], requests = [];
  const PresentationSession = {
    ensure: async () => {},
    api: async (url, options = {}) => {
      requests.push(`${options.method || 'GET'} ${url}`);
      const r = await api(url, { method: options.method, body: options.body ? JSON.parse(options.body) : undefined });
      if (r.status >= 400) throw new Error(r.json?.error || 'error');
      return r.json;
    },
  };
  const context = vm.createContext({
    document, PresentationSession, location: { href: '' }, alert: message => alerts.push(message), setTimeout, clearTimeout,
    window: { innerWidth: 1280, innerHeight: 800, addEventListener() {} },
  });
  vm.runInContext(script, context);
  for (let i = 0; i < 100 && !document.getElementById('grid').children.length; i++) await new Promise(r => setTimeout(r, 20));
  const run = code => vm.runInContext(code, context);
  const menuOf = slug => {
    run(`menuFor(state.data.presentations.find(p => p.slug === ${JSON.stringify(slug)}), document.getElementById('grid').children[0].querySelector('.kebab'))`);
    return document.getElementById('menu').children;
  };
  return { document, alerts, requests, run, menuOf };
}

test('library: mission-dashboard\'s menu has no Rename or Delete and shows the message instead', { skip }, async () => {
  const page = await libraryPage();
  assert.equal(page.document.getElementById('status').textContent, '2 presentations');
  const items = page.menuOf(DECK);
  assert.deepEqual(items.filter(e => e.tagName === 'BUTTON').map(e => e.textContent), ['Download PDF', 'Edit', 'Manage access', 'Duplicate', 'Download source (.zip)']);
  const note = items.find(e => e.className === 'menu-note');
  assert.equal(note.textContent, MESSAGE);
  assert.equal(note.attributes.role, 'note');
  assert.equal(items[items.length - 1], note, 'the message is where Rename and Delete would be');

  const other = page.menuOf('chart-examples').map(e => e.textContent);
  assert.deepEqual(other, ['Download PDF', 'Edit', 'Manage access', 'Duplicate', 'Download source (.zip)', 'Rename', 'Delete']);
});

test('library: the rename and delete dialogs never open for mission-dashboard', { skip }, async () => {
  const page = await libraryPage();
  page.run(`showDelete(state.data.presentations.find(p => p.slug === '${DECK}'))`);
  page.run(`showName('rename', state.data.presentations.find(p => p.slug === '${DECK}'))`);
  assert.deepEqual(page.alerts, [MESSAGE, MESSAGE]);
  assert.equal(page.document.getElementById('deleteDialog').open, false);
  assert.equal(page.document.getElementById('nameDialog').open, false);
  page.run(`showDelete(state.data.presentations.find(p => p.slug === 'chart-examples'))`);
  assert.equal(page.document.getElementById('deleteDialog').open, true, 'other decks still ask before deleting');
});

test('library: Duplicate in mission-dashboard\'s menu makes a copy', { skip }, async () => {
  const page = await libraryPage();
  const duplicate = page.menuOf(DECK).find(e => e.textContent === 'Duplicate');
  await duplicate.onclick({ stopPropagation() {} });
  for (let i = 0; i < 100 && !page.requests.includes(`POST /api/presentations/${DECK}/duplicate`); i++) await new Promise(r => setTimeout(r, 20));
  for (let i = 0; i < 100 && page.document.getElementById('status').textContent !== '3 presentations'; i++) await new Promise(r => setTimeout(r, 20));
  assert.ok(page.requests.includes(`POST /api/presentations/${DECK}/duplicate`));
  assert.equal(page.document.getElementById('status').textContent, '3 presentations');
  assert.deepEqual(page.alerts, []);
  assert.deepEqual(await folders(), ['chart-examples', DECK, 'mission-dashboard-copy']);
});

// ---- 4. Download PDF (round 6): the deck's /export page, for everyone who may open the deck ----

test("library: Download PDF opens the deck's /export page, for managers and for leaders", { skip }, async () => {
  const page = await libraryPage();
  const pdf = page.menuOf('chart-examples').find(e => e.textContent === 'Download PDF');
  pdf.onclick({ stopPropagation() {} });
  assert.equal(page.run('location.href'), '/p/chart-examples/export');
  // A leader's menu for a deck they may open but not change (round 7: can_edit false): Download PDF only (the card
  // itself opens the deck; round 9 took the menu's Open away), no source download. A zone's own decks are tested in
  // zone-decks.test.mjs.
  page.run('state.data.can_manage = false; for (const p of state.data.presentations) p.can_edit = false');
  assert.deepEqual(page.menuOf('chart-examples').map(e => e.textContent), ['Download PDF']);
});

// Round 8: /p/ on the manager address gives a view pass and sends the browser on to the deck address.
async function openDeck(pathname, as) {
  const signIn = await fetch(`${managerUrl}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${as}` } });
  const session = (signIn.headers.get('set-cookie') || '').split(';')[0];
  const door = await fetch(`${managerUrl}${pathname}`, { redirect: 'manual', headers: { Cookie: session, Accept: 'text/html' } });
  if (door.status !== 302) return { status: door.status, text: await door.text() };
  const page = await fetch(door.headers.get('location'), { headers: { Cookie: (door.headers.get('set-cookie') || '').split(';')[0], Accept: 'text/html' } });
  return { status: page.status, text: await page.text() };
}

test("/p/<deck>/export is the published deck's page for those who may open it; others are refused", { skip }, async () => {
  const ap = await openDeck('/p/chart-examples/export', AP);
  assert.equal(ap.status, 200);
  assert.match(ap.text, /<title>built<\/title>/, 'the built deck (Slidev routes /export itself)');
  assert.match(ap.text, /@media print \{\s*#portal-edit-presentation,\s*#portal-edit-loading \{\s*display: none !important;/, 'the edit button stays off the PDF');
  const dl = await openDeck('/p/chart-examples/export', DL);
  assert.equal(dl.status, 403);
  assert.doesNotMatch(dl.text, /<title>built<\/title>/);
});
