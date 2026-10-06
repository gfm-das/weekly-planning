// GFM Presentations V2 on the real manager (tests/helpers/manager-harness.mjs: a copy in a temporary folder with
// stand-ins for Slidev's packages, Supabase and portal-api). Checks the V2 routes use the same access rules as Slidev:
// managers read, make and change decks; a viewer reads a deck they may open and gets numbers only for the queries
// saved in it; nobody gets a page, a deck or numbers without a sign-in. Needs a POSIX shell (node:24-alpine).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const QUERY = { measures: ['friends_found.actual'], level: 'zone', by: 'unit', weeks: { last: 1 } };
const OTHER = { measures: ['baptismal_dates.actual'], level: 'zone', by: 'unit', weeks: { last: 1 } };
const deck = { version: 1, name: 'Demo', slides: [{ id: 's1', components: [
  { id: 'c1', type: 'chart', x: 5, y: 5, width: 80, height: 70, props: { query: QUERY } },
  { id: 't1', type: 'text', x: 5, y: 80, width: 40, height: 10, props: { text: '<img src=x onerror=alert(1)>' } },
] }] };
const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(32)]);

let manager, supabase, portal, app, chartCalls, accessCalls;
const as = (who, extra = {}) => ({ headers: { Authorization: `Bearer ${token(who)}`, 'Content-Type': 'application/json', ...extra.headers }, ...extra });
const call = (method, url, who, body) => fetch(manager.url + url, { method, headers: as(who).headers, body: body === undefined ? undefined : JSON.stringify(body) });

before(async () => {
  chartCalls = [];
  accessCalls = [];
  app = await fs.mkdtemp(path.join(os.tmpdir(), 'v2-app-'));
  await fs.mkdir(path.join(app, 'assets'));
  await fs.writeFile(path.join(app, 'index.html'), '<!doctype html><title>v2</title><div id="app"></div>');
  await fs.writeFile(path.join(app, 'assets', 'a.js'), 'export default 1');
  await fs.writeFile(path.join(app, 'assets', 'data-worker-Ab1_-x.js'), 'export default 2');
  supabase = await startStub((req, url) => supabaseAnswer(req, url) || [404, {}]);
  // User "manager" manages; user "viewer" may open deck "demo" only; user "nobody" has no Presentations.
  portal = await startStub((req, url, body) => {
    if (req.headers['x-service-key'] !== 'stub') return [401, { error: 'key' }];
    if (url.pathname === '/internal/presentations/check') {
      if (body.user_id === 'manager') return [200, { can_manage: true, can_create: true, role: 'data_analyst', allowed_slugs: [], editable_slugs: [], owner_zones: [] }];
      if (body.user_id === 'slidevonly') return [200, { can_manage: false, can_create: false, role: 'DL', allowed_slugs: ['same'], editable_slugs: [], owner_zones: [] }];
      if (body.user_id === 'viewer') return [200, { can_manage: false, can_create: false, role: 'DL', allowed_slugs: ['v2-demo'], editable_slugs: [], owner_zones: [] }];
      return [200, { can_manage: false, can_create: false, role: 'MISSIONARY', allowed_slugs: [], editable_slugs: [], owner_zones: [] }];
    }
    if (url.pathname === '/internal/presentations/chart-data') {
      chartCalls.push({ user: body.user_id, deck: body.deck, pinned: body.pinned, measures: body.spec.measures });
      return [200, { table: { labels: ['Z1', 'Z2'], series: [{ name: 'N', values: [1, 2] }] }, meta: {} }];
    }
    if (url.pathname === '/internal/presentations/access') {
      accessCalls.push(body);
      return [200, body.operation === 'get' ? { access: { roles: [], zone_ids: [], district_ids: [], user_ids: [], everyone: false }, options: { roles: ['DL', 'ZL', 'STL'] } } : { ok: true }];
    }
    return [404, { error: 'stand-in' }];
  });
  manager = await startManager({ env: {
    SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`, PRESENTATION_ACL_API_URL: `http://127.0.0.1:${portal.address().port}`,
    PRESENTATION_V2_APP_DIR: app, PRESENTATIONS_PORTAL_ORIGINS: 'http://127.0.0.1:8070',
  } });
});
after(async () => { await manager?.stop(); supabase?.close(); portal?.close(); if (app) await fs.rm(app, { recursive: true, force: true }); });

test('nothing without a sign-in', async () => {
  for (const url of ['/api/presentations-v2/demo', '/studio-v2/demo', '/p-v2/demo']) {
    const r = await fetch(manager.url + url, { headers: { 'X-GFM-Request': '1' } });
    assert.equal(r.status, 401, url);
  }
  assert.equal((await fetch(manager.url + '/api/presentations-v2/query', { method: 'POST', body: '{}', headers: { 'X-GFM-Request': '1' } })).status, 401);
  // Without the header a data route is refused at the door (a page of another address cannot send it).
  assert.equal((await fetch(manager.url + '/api/presentations-v2/demo')).status, 403);
  assert.equal((await fetch(manager.url + '/api/presentations-v2/demo', { method: 'PUT', body: '{}' })).status, 403);
});

test('a manager makes a deck, reads it back, and the bad ones are refused with a sentence', async () => {
  assert.equal((await call('GET', '/api/presentations-v2/demo', 'manager')).status, 404);
  const bad = await call('PUT', '/api/presentations-v2/demo', 'manager', { deck: { ...deck, version: 9 } });
  assert.equal(bad.status, 400);
  assert.match((await bad.json()).error, /version/);
  const put = await call('PUT', '/api/presentations-v2/demo', 'manager', { deck });
  assert.equal(put.status, 200);
  const got = await (await call('GET', '/api/presentations-v2/demo', 'manager')).json();
  assert.equal(got.deck.slides[0].components[0].props.query.measures[0], 'friends_found.actual');
  assert.equal(got.can_edit, true);
  // A second save keeps the first as deck.json.bak.
  await call('PUT', '/api/presentations-v2/demo', 'manager', { deck: { ...deck, name: 'Second' } });
  const folder = path.join(manager.decks, '..', 'decks-v2', 'demo');
  assert.deepEqual((await fs.readdir(folder)).filter(n => n.startsWith('deck.json')).sort(), ['deck.json', 'deck.json.bak']);
  assert.equal(JSON.parse(await fs.readFile(path.join(folder, 'deck.json.bak'), 'utf8')).name, 'Demo');
});

test('the pages and files: the same prebuilt page for every deck, with a strict policy, and no path out of the folder', async () => {
  const page = await fetch(manager.url + '/p-v2/demo', as('manager'));
  assert.equal(page.status, 200);
  assert.match(await page.text(), /id="app"/);
  const csp = page.headers.get('content-security-policy');
  assert.match(csp, /script-src 'self' 'nonce-/);
  assert.doesNotMatch(csp, /unsafe-eval|script-src[^;]*unsafe-inline/);
  assert.equal((await fetch(manager.url + '/studio-v2/demo', as('manager'))).status, 200);
  assert.equal((await fetch(manager.url + '/studio-v2/not-yet', as('manager'))).status, 200, 'a manager may open a deck that does not exist yet, to make it');
  assert.equal((await fetch(manager.url + '/p-v2/not-yet', as('manager'))).status, 404);
  assert.equal((await fetch(manager.url + '/_v2/assets/a.js')).status, 200);
  // Only the data worker may build functions from text, and only with no network (its own policy).
  const worker = await fetch(manager.url + '/_v2/assets/data-worker-Ab1_-x.js');
  assert.match(worker.headers.get('content-security-policy'), /unsafe-eval.*connect-src 'none'/);
  assert.doesNotMatch((await fetch(manager.url + '/_v2/assets/a.js')).headers.get('content-security-policy') ?? '', /unsafe-eval/);
  assert.equal((await fetch(manager.url + '/_v2/..%2findex.html')).status, 404);
  assert.equal((await fetch(manager.url + '/_v2/%2e%2e/%2e%2e/etc/passwd')).status, 404);
});

test('a viewer opens a deck they are given but cannot change it, make one, or open the editor', async () => {
  assert.equal((await call('GET', '/api/presentations-v2/demo', 'viewer')).status, 200);
  assert.equal((await call('GET', '/api/presentations-v2/demo', 'viewer').then(r => r.json())).can_edit, false);
  assert.equal((await call('PUT', '/api/presentations-v2/demo', 'viewer', { deck })).status, 403);
  assert.equal((await call('PUT', '/api/presentations-v2/other', 'viewer', { deck })).status, 403);
  assert.equal((await fetch(manager.url + '/studio-v2/demo', as('viewer'))).status, 403);
  assert.equal((await fetch(manager.url + '/p-v2/demo', as('viewer'))).status, 200);
  assert.equal((await call('GET', '/api/presentations-v2/other', 'viewer')).status, 403, 'a deck not given to them');
  assert.equal((await call('GET', '/api/presentations-v2/demo', 'nobody')).status, 403);
});

test('a Slidev deck with the same name gives no access to the V2 deck (the sharing keys are apart)', async () => {
  // This person was given the Slidev deck "same" only; the V2 deck "same" must stay closed to them.
  await call('PUT', '/api/presentations-v2/same', 'manager', { deck });
  assert.equal((await call('GET', '/api/presentations-v2/same', 'slidevonly')).status, 403);
  assert.equal((await fetch(manager.url + '/p-v2/same', as('slidevonly'))).status, 403);
});

test('the library lists only the V2 decks a person may open', async () => {
  await call('PUT', '/api/presentations-v2/hidden', 'manager', { deck: { ...deck, name: 'Hidden one' } });
  const names = async who => (await (await call('GET', '/api/presentations-v2', who)).json()).decks.map(d => d.slug);
  assert.deepEqual((await names('manager')).filter(n => ['demo', 'hidden'].includes(n)).sort(), ['demo', 'hidden']);
  assert.deepEqual(await names('viewer'), ['demo'], 'only the deck given to them');
  const mine = await (await call('GET', '/api/presentations-v2', 'viewer')).json();
  assert.equal(mine.decks[0].can_edit, false);
  assert.equal(mine.can_manage, false);
  assert.equal((await call('GET', '/api/presentations-v2', 'nobody')).status, 403);
  assert.equal((await fetch(manager.url + '/library-v2', as('viewer'))).status, 200);
  assert.equal((await fetch(manager.url + '/library-v2', as('nobody'))).status, 403);
});

test('who may view: managers read and set it under the deck own key; nobody else', async () => {
  assert.equal((await call('GET', '/api/presentations-v2/demo/viewers', 'viewer')).status, 403);
  assert.equal((await call('PUT', '/api/presentations-v2/demo/viewers', 'viewer', { rule: { everyone: true } })).status, 403);
  assert.equal((await call('GET', '/api/presentations-v2/nothing/viewers', 'manager')).status, 404);
  accessCalls.length = 0;
  assert.equal((await call('GET', '/api/presentations-v2/demo/viewers', 'manager')).status, 200);
  assert.equal(accessCalls.at(-1).deck_slug, 'v2-demo');
  const put = await call('PUT', '/api/presentations-v2/demo/viewers', 'manager', { rule: { roles: ['ZL'], zone_ids: [3], everyone: false, owner_zone_id: 7, evil: 1 } });
  assert.equal(put.status, 200);
  const sent = accessCalls.at(-1);
  assert.equal(sent.operation, 'save');
  assert.equal(sent.deck_slug, 'v2-demo');
  assert.deepEqual(sent.rule, { roles: ['ZL'], zone_ids: [3], everyone: false }, 'only the viewing choices go on; the owner and anything else are dropped');
});

test('numbers: a viewer gets only the queries saved in the deck; portal-api is told which are pinned', async () => {
  chartCalls.length = 0;
  const ok = await call('POST', '/api/presentations-v2/query', 'viewer', { deck: 'demo', spec: { weeks: { last: 1 }, by: 'unit', level: 'zone', measures: ['friends_found.actual'] } });
  assert.equal(ok.status, 200);
  assert.deepEqual(chartCalls.at(-1), { user: 'viewer', deck: 'v2-demo', pinned: true, measures: ['friends_found.actual'] });
  const no = await call('POST', '/api/presentations-v2/query', 'viewer', { deck: 'demo', spec: OTHER });
  assert.equal(no.status, 403);
  assert.equal((await call('POST', '/api/presentations-v2/query', 'viewer', { deck: 'demo', spec: { ...QUERY, level: 'area' } })).status, 403);
  assert.equal((await call('POST', '/api/presentations-v2/query', 'viewer', { spec: QUERY })).status, 403, 'no deck: managers only');
  assert.equal((await call('POST', '/api/presentations-v2/query', 'nobody', { deck: 'demo', spec: QUERY })).status, 403);
  assert.equal(chartCalls.length, 1, 'refused requests never reach portal-api');
  // A manager may try any query (the editor's preview), with or without a deck.
  assert.equal((await call('POST', '/api/presentations-v2/query', 'manager', { deck: 'demo', spec: OTHER })).status, 200);
  assert.equal((await call('POST', '/api/presentations-v2/query', 'manager', { spec: OTHER })).status, 200);
});

test('pictures: png yes (checked by its first bytes), svg and fakes no, the viewer may only read', async () => {
  const up = (name, data, who = 'manager') => fetch(`${manager.url}/api/presentations-v2/demo/assets/${name}`, { method: 'PUT', headers: { Authorization: `Bearer ${token(who)}` }, body: data });
  assert.equal((await up('logo.png', PNG)).status, 200);
  assert.equal((await up('logo2.png', Buffer.from('<svg onload=alert(1)>'))).status, 400, 'not really a png');
  assert.equal((await up('x.svg', Buffer.from('<svg/>'))).status, 400);
  assert.ok([400, 404].includes((await up('..%2f..%2fdeck.json.png', PNG)).status));
  assert.equal((await up('logo.png', PNG, 'viewer')).status, 403);
  const got = await fetch(`${manager.url}/p-v2-assets/demo/logo.png`, as('viewer'));
  assert.equal(got.status, 200);
  assert.equal(got.headers.get('content-type'), 'image/png');
  assert.equal(got.headers.get('x-content-type-options'), 'nosniff');
  assert.equal((await fetch(`${manager.url}/p-v2-assets/demo/missing.png`, as('viewer'))).status, 404);
  assert.equal((await fetch(`${manager.url}/p-v2-assets/demo/logo.png`, { headers: { 'X-GFM-Request': '1' } })).status, 401, 'no sign-in, no picture');
  assert.equal((await fetch(`${manager.url}/p-v2-assets/other/logo.png`, as('viewer'))).status, 403);
});

test('a new Slidev deck is never named v2-... (that start is how V2 decks are named in the sharing table)', async () => {
  const made = await call('POST', '/api/presentations', 'manager', { title: 'V2 Training' });
  assert.equal(made.status, 201);
  assert.equal((await made.json()).slug, 'deck-v2-training');
});

test('Slidev is untouched: its library API still answers', async () => {
  const r = await call('GET', '/api/presentations', 'manager');
  assert.equal(r.status, 200);
  assert.ok(Array.isArray((await r.json()).presentations));
});
