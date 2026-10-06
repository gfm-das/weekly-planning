// Round 8: presentations on their own address (manager/deck-origin.mjs).
//
// Published decks and the deck editor run on the deck address (port 8089); the manager (port 3030) and its sign-in
// never serve deck code. These tests check:
// 1. The rules themselves (plain Node): which requests the manager address refuses (a page on the deck address, a
//    request without the X-GFM-Request header, Sec-Fetch-Site and Origin), which doorway requests need the person
//    to confirm, what the deck address refuses, and the deck passes (one deck, one mode, one sign-in).
// 2. The real manager/server.mjs (tests/helpers/manager-harness.mjs) with a portal-api stand-in: the manager's
//    session never opens anything on the deck address, a pass opens only its own deck, a deck page's requests to the
//    manager are refused, and signing out ends the passes. Needs a POSIX shell (node:24-alpine).
import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, test } from 'node:test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  addressFor, addressOf, cookieValues, DeckPasses, deckOfPath, deckOfRequest, deckRefusal, deckSocketAllowed, doorwayFromOtherPage,
  FROM_DECK_PAGE, FROM_OTHER_ADDRESS, FROM_OTHER_PAGE, isDeckOrigin, isOwnOrigin, managerRefusal, MISSING_HEADER, PASS_IDLE_MS,
  PASS_KEEPALIVE_MS, passCookie, passCookieName, passDomainFor, passFromCookies, publicSide,
} from '../manager/deck-origin.mjs';
import { NOT_PINNED } from '../manager/chart-access.mjs';
import { freePort, startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

// ---- 1. The rules ----

const HOST = '192.168.1.20:3030';
const ask = (pathname, headers = {}, method = 'GET') => managerRefusal({ method, pathname, headers: { host: HOST, ...headers } }, { deckPort: 8089 });

test('addresses: the same computer name the browser used, on another port', () => {
  assert.equal(addressFor('192.168.1.20:3030', 8089), 'http://192.168.1.20:8089');
  assert.equal(addressFor('localhost:3030', 8089), 'http://localhost:8089');
  assert.equal(addressFor('[::1]:3030', 8089), 'http://[::1]:8089');
  assert.equal(addressFor('localhost:8089', 3030), 'http://localhost:3030');
  assert.equal(addressFor('', 8089), '');
  assert.equal(addressFor('bad host"><script>', 8089), '', 'nothing odd ever goes into a page or a Location');
  assert.equal(isDeckOrigin('http://192.168.1.20:8089', 8089), true);
  assert.equal(isDeckOrigin('http://localhost:8089', 8089), true, 'any computer name');
  assert.equal(isDeckOrigin('http://192.168.1.20:8070', 8089), false);
  assert.equal(isDeckOrigin('null', 8089), false);
  assert.equal(isDeckOrigin(undefined, 8089), false);
  assert.equal(isOwnOrigin('http://192.168.1.20:3030', HOST), true);
  assert.equal(isOwnOrigin('http://192.168.1.20:8089', HOST), false);
});

test("the manager address: its own pages' data requests pass (with the header or a Bearer token)", () => {
  const own = { 'sec-fetch-site': 'same-origin', origin: `http://${HOST}`, 'x-gfm-request': '1' };
  assert.equal(ask('/api/presentations', own), null);
  assert.equal(ask('/api/presentations/a/access', own, 'POST'), null);
  assert.equal(ask('/__slidev/slides/2.json', own, 'POST'), null, "the chart builder's slide writes");
  assert.equal(ask('/@studio/deck', own, 'POST'), null);
  assert.equal(ask('/api/presentations', { authorization: 'Bearer x' }), null, 'a Bearer token also needs the browser to ask first');
  assert.equal(ask('/api/presentations', { 'x-gfm-request': '1' }), null, 'an older browser without Sec-Fetch-Site');
  // Pages, code and the health check need nothing.
  for (const pathname of ['/', '/health', '/_manager/portal-bridge.js', '/_manager/chart/chart-builder.mjs', '/vendor/monaco/vs/loader.js', '/whiteboard/chart'])
    assert.equal(ask(pathname, { 'sec-fetch-site': 'same-site' }), null, pathname);
  // The source download is a plain link (no header possible), from the library itself.
  assert.equal(ask('/api/presentations/a/download', { 'sec-fetch-site': 'same-origin', 'sec-fetch-mode': 'navigate' }), null);
  assert.equal(ask('/api/presentations/a/download', { 'sec-fetch-site': 'none' }), null, 'typed into the address bar');
});

test('the manager address refuses every request a deck page (or any other address) sends', () => {
  const deck = 'http://192.168.1.20:8089';
  // From the deck address: always refused, whatever it carries (a CORS preflight too).
  for (const [pathname, method] of [['/api/presentations', 'GET'], ['/api/presentations/a/access', 'POST'], ['/api/session', 'OPTIONS'], ['/api/session', 'POST'], ['/api/logout', 'POST'], ['/studio/a', 'GET'], ['/__slidev/slides/1.json', 'POST']])
    assert.equal(ask(pathname, { origin: deck, 'x-gfm-request': '1', authorization: 'Bearer x' }, method), FROM_DECK_PAGE, `${method} ${pathname}`);
  assert.equal(ask('/api/presentations', { origin: 'http://localhost:8089', 'x-gfm-request': '1' }), FROM_DECK_PAGE, 'any computer name');
  assert.equal(ask('/api/presentations/a/access', { origin: 'null', 'x-gfm-request': '1' }, 'POST'), FROM_DECK_PAGE, 'a page without an address');
  // Without the header: refused (a deck page cannot add it without the manager's yes, and never gets one).
  assert.equal(ask('/api/presentations'), MISSING_HEADER);
  assert.equal(ask('/api/presentations/a/access', { 'sec-fetch-site': 'same-origin' }, 'POST'), MISSING_HEADER);
  assert.equal(ask('/__slidev/slides/1.json', {}, 'POST'), MISSING_HEADER);
  // The browser says another address sent it (same-site covers the other ports of this computer).
  for (const site of ['same-site', 'cross-site'])
    assert.equal(ask('/api/presentations', { 'sec-fetch-site': site, 'x-gfm-request': '1' }), MISSING_HEADER, site);
  assert.equal(ask('/api/presentations/a/download', { 'sec-fetch-site': 'same-site' }), MISSING_HEADER, 'a download started by a deck page');
  assert.equal(ask('/api/presentations', { origin: 'http://192.168.1.20:8070', 'x-gfm-request': '1' }), MISSING_HEADER, 'another address');
  // The portal's own sign-in route keeps its own checks (CORS for the portal only), but never for a deck page.
  assert.equal(ask('/api/session', { origin: 'http://192.168.1.20:8070', 'sec-fetch-site': 'same-site' }, 'POST'), null);
});

test('doorways (/p/, /edit/, /studio/) started by another page need the person to confirm', () => {
  const from = site => doorwayFromOtherPage({ pathname: '/p/a/', headers: { 'sec-fetch-site': site } });
  assert.equal(from('same-origin'), false, 'the library or the editor page');
  assert.equal(from('none'), false, 'typed or a bookmark');
  assert.equal(from(undefined), false, 'an older browser');
  assert.equal(from('same-site'), true, 'a deck page (another port of this computer)');
  assert.equal(from('cross-site'), true);
  assert.equal(doorwayFromOtherPage({ pathname: '/studio/a', headers: { 'sec-fetch-site': 'same-site' } }), true);
  assert.equal(doorwayFromOtherPage({ pathname: '/edit/a/', headers: { 'sec-fetch-site': 'same-site' } }), true);
  assert.equal(doorwayFromOtherPage({ pathname: '/', headers: { 'sec-fetch-site': 'same-site' } }), false, 'the library opens from the portal');
});

test('the deck address: reading from anywhere (no CORS answers), changing only from its own pages', () => {
  const host = '192.168.1.20:8089';
  assert.equal(deckRefusal({ method: 'GET', headers: { host, 'sec-fetch-site': 'same-site' } }), null);
  assert.equal(deckRefusal({ method: 'POST', headers: { host, 'sec-fetch-site': 'same-origin', origin: `http://${host}` } }), null);
  assert.equal(deckRefusal({ method: 'POST', headers: { host } }), null, 'an older browser');
  assert.equal(deckRefusal({ method: 'POST', headers: { host, 'sec-fetch-site': 'same-site' } }), FROM_OTHER_ADDRESS);
  assert.equal(deckRefusal({ method: 'POST', headers: { host, origin: 'http://192.168.1.20:3030' } }), FROM_OTHER_ADDRESS);
  assert.equal(deckRefusal({ method: 'PUT', headers: { host, origin: 'http://192.168.1.20:8070' } }), FROM_OTHER_ADDRESS);
  assert.equal(deckSocketAllowed({ host, origin: `http://${host}` }), true);
  assert.equal(deckSocketAllowed({ host, origin: 'http://192.168.1.20:3030' }), false, "another page cannot use the editor's live connection");
  assert.equal(deckSocketAllowed({ host }), false);
});

test('deck passes: one sign-in, one deck, one mode; they end with the sign-in', () => {
  let n = 0;
  const passes = new DeckPasses({ maxMs: 1000, randomId: () => `id${++n}` });
  const view = passes.issue('s1', 'alpha', 'view', 0);
  assert.equal(passes.issue('s1', 'alpha', 'view', 10), view, 'the same pass again while it lasts');
  const edit = passes.issue('s1', 'alpha', 'edit', 0);
  assert.notEqual(edit, view);
  const other = passes.issue('s2', 'alpha', 'view', 0);
  assert.notEqual(other, view, "another person's sign-in gets its own");
  assert.equal(passes.find(view, 'alpha', 'view', 5).sessionId, 's1');
  assert.equal(passes.find(view, 'beta', 'view', 5), null, 'never for another deck');
  assert.equal(passes.find(view, 'alpha', 'edit', 5), null, 'a view pass never edits');
  assert.equal(passes.find('made-up', 'alpha', 'view', 5), null);
  assert.equal(passes.find(view, 'alpha', 'view', 1000), null, 'it ends after maxMs');
  assert.equal(passes.find(view, 'alpha', 'view', 5), null, 'and stays ended');
  passes.endSession('s1');
  assert.equal(passes.find(edit, 'alpha', 'edit', 5), null, 'signing out ends every pass of that sign-in');
  assert.equal(passes.find(other, 'alpha', 'view', 5).sessionId, 's2', "and no one else's");
  assert.throws(() => passes.issue('s1', '../x', 'view'), /Invalid presentation id/);
  assert.throws(() => passes.issue('s1', 'alpha', 'admin'), /viewing or for editing/);
  const small = new DeckPasses({ max: 2, randomId: () => `x${++n}` });
  for (let i = 0; i < 5; i++) small.issue(`s${i}`, 'alpha', 'view');
  assert.equal(small.size, 2, 'a limited number is kept');
  // Real passes are 64 random hex digits.
  assert.match(new DeckPasses().issue('s', 'alpha', 'view'), /^[0-9a-f]{64}$/);
});

test('pass cookies: HttpOnly, SameSite=Strict, per deck and mode; any added cookie of the same name is ignored', () => {
  assert.equal(passCookieName('alpha', 'view'), 'gfm_view_alpha');
  assert.equal(passCookieName('alpha-2', 'edit'), 'gfm_edit_alpha-2');
  assert.equal(passCookie('alpha', 'view', 'abc'), 'gfm_view_alpha=abc; HttpOnly; SameSite=Strict; Path=/');
  assert.deepEqual(cookieValues('a=1; gfm_view_alpha=x; b=2; gfm_view_alpha=y', 'gfm_view_alpha'), ['x', 'y']);
  const passes = new DeckPasses({ randomId: () => 'real' });
  passes.issue('s1', 'alpha', 'view');
  // A deck's code may add its own cookie of that name; only the one this server made counts.
  assert.equal(passFromCookies(passes, 'gfm_view_alpha=junk; gfm_view_alpha=real', 'alpha', 'view').id, 'real');
  assert.equal(passFromCookies(passes, 'gfm_view_alpha=junk', 'alpha', 'view'), null);
  assert.equal(passFromCookies(passes, 'presentation_session=real', 'alpha', 'view'), null, "the manager's cookie is never a pass");
  assert.equal(passFromCookies(passes, 'gfm_view_alpha=real', 'beta', 'view'), null);
  assert.equal(passFromCookies(passes, 'gfm_view_alpha=real', '', 'view'), null);
  assert.equal(deckOfPath('/p/alpha/3'), 'alpha');
  assert.equal(deckOfPath('/edit/alpha-2/'), 'alpha-2');
  assert.equal(deckOfPath('/api/charts/data'), '');
});

// Round 8 review: passes are short-lived. A pass that another deck's code could use ends soon after its own deck was
// closed (a view pass 30 minutes, an edit pass 15), not at the end of the sign-in (up to 12 hours).
test('deck passes last only a short while after their last use; an open page keeps its own', () => {
  const MIN = 60 * 1000;
  let n = 0;
  const passes = new DeckPasses({ randomId: () => `p${++n}` });
  assert.deepEqual({ ...PASS_IDLE_MS }, { view: 30 * MIN, edit: 15 * MIN });
  assert.equal(PASS_KEEPALIVE_MS, 5 * MIN, 'an open deck page uses its pass every 5 minutes, well within 30');
  const view = passes.issue('s1', 'alpha', 'view', 0);
  assert.ok(passes.find(view, 'alpha', 'view', 29 * MIN), 'a view pass lasts 30 minutes after it was made');
  assert.equal(passes.find(view, 'alpha', 'view', 30 * MIN), null, 'and ends then, when nothing used it');
  const again = passes.issue('s1', 'alpha', 'view', 31 * MIN);
  assert.notEqual(again, view, 'opening the deck again from the library gives a new pass');
  // An open deck page uses it every 5 minutes: it lasts as long as the page is open…
  const limit = 31 * MIN + 12 * 60 * MIN;
  for (let t = 31 * MIN; t < limit; t += PASS_KEEPALIVE_MS) passes.renew(passes.find(again, 'alpha', 'view', t), t);
  assert.ok(passes.find(again, 'alpha', 'view', limit - 1), 'still good almost 12 hours later while the page is open');
  // …but never longer than 12 hours after it was made, and 30 minutes after the page was closed it is gone.
  assert.equal(passes.find(again, 'alpha', 'view', limit), null, 'never past 12 hours');
  const closed = passes.issue('s2', 'beta', 'view', 0);
  passes.renew(passes.find(closed, 'beta', 'view', 10 * MIN), 10 * MIN);
  assert.ok(passes.find(closed, 'beta', 'view', 39 * MIN));
  assert.equal(passes.find(closed, 'beta', 'view', 40 * MIN), null, '30 minutes after the last use');
  // An edit pass: 15 minutes.
  const edit = passes.issue('s1', 'alpha', 'edit', 0);
  assert.ok(passes.find(edit, 'alpha', 'edit', 14 * MIN));
  assert.equal(passes.find(edit, 'alpha', 'edit', 15 * MIN), null, 'an edit pass ends 15 minutes after its last use');
  // live(): the sign-in's pass for a deck (what the /studio status question renews).
  const e1 = passes.issue('s1', 'alpha', 'edit', 100 * MIN, { holder: 'pageA' });
  assert.equal(passes.live('s1', 'alpha', 'edit', 101 * MIN).id, e1);
  assert.equal(passes.live('s2', 'alpha', 'edit', 101 * MIN), null, "never another sign-in's");
  assert.equal(passes.live('s1', 'alpha', 'edit', 116 * MIN), null);
});

test('edit passes end when their /studio page is left (not another tab of it) and when the editor stops', () => {
  let n = 0;
  const passes = new DeckPasses({ randomId: () => `e${++n}` });
  const a = passes.issue('s1', 'alpha', 'edit', 0, { holder: 'pageA' });
  assert.equal(passes.issue('s1', 'alpha', 'edit', 1, { holder: 'pageB' }), a, 'a second /studio tab of the same deck shares the pass');
  passes.endFor('s1', 'alpha', 'edit', 'pageA');
  assert.ok(passes.find(a, 'alpha', 'edit', 2), 'the first tab closing (or reloading) does not end it for the second');
  passes.endFor('s1', 'alpha', 'edit', 'pageB');
  assert.equal(passes.find(a, 'alpha', 'edit', 2), null, 'the page holding it was left: it ends at once');
  // The editor stopped: every edit pass of that deck ends (nothing can change it through the deck address until
  // someone opens it in /studio again); view passes and other decks stay.
  const e1 = passes.issue('s1', 'alpha', 'edit', 0);
  const e2 = passes.issue('s2', 'alpha', 'edit', 0);
  const v1 = passes.issue('s1', 'alpha', 'view', 0);
  const b1 = passes.issue('s1', 'beta', 'edit', 0);
  passes.endDeck('alpha', 'edit');
  assert.equal(passes.find(e1, 'alpha', 'edit', 1), null);
  assert.equal(passes.find(e2, 'alpha', 'edit', 1), null);
  assert.ok(passes.find(v1, 'alpha', 'view', 1));
  assert.ok(passes.find(b1, 'beta', 'edit', 1));
});

test("numbers on the deck address: for the deck of the page that asks, never a deck it names", () => {
  const host = '192.168.1.20:8089';
  const refused = { refusal: FROM_OTHER_PAGE };
  const from = (referer, named) => deckOfRequest({ host, referer }, named);
  assert.deepEqual(from('http://192.168.1.20:8089/p/alpha/3'), { deck: 'alpha' });
  assert.deepEqual(from('http://192.168.1.20:8089/p/alpha/presenter/2', 'alpha'), { deck: 'alpha' });
  assert.deepEqual(from('http://192.168.1.20:8089/edit/alpha-2/1', 'alpha-2'), { deck: 'alpha-2' }, 'the editor too');
  assert.deepEqual(from('http://192.168.1.20:8089/p/alpha/', 'mission-talk'), refused, 'a page naming another deck than its own');
  assert.deepEqual(from('http://192.168.1.20:3030/p/alpha/'), refused, 'a page on another address');
  assert.deepEqual(from('http://192.168.1.20:8089/'), refused, 'not a deck page');
  assert.deepEqual(from(''), refused, 'no page at all');
  assert.deepEqual(from('not an address'), refused);
  assert.equal(FROM_OTHER_PAGE, 'This request came from another page, so it was refused.');
});

// ---- 2. The real manager ----

const posix = process.platform !== 'win32';
const skip = posix ? false : 'needs a POSIX shell (run in node:24-alpine)';

// An AP (manager), the ZL of zone 5 and the ZL of zone 6; alpha is zone 5's deck, beta zone 6's, talk the mission's.
const PEOPLE = { 'user-ap': { role: 'AP', manager: true }, 'user-zl5': { role: 'ZL', zone: 5 }, 'user-zl6': { role: 'ZL', zone: 6 } };
const AS = Object.fromEntries(Object.keys(PEOPLE).map(id => [id.slice(5), token(id)]));
const OWNERS = { alpha: 5, beta: 6 };
const asked = [];
// The chart written in alpha (zone 5's deck, with a key-number chart too) and in talk (the mission's): on the deck
// address a deck page gets only the numbers of the charts written in its own deck ("pinned", round 8 review).
const PINNED = { measures: ['friends_found.actual'], level: 'zone' };
const CHART = `<MissionChart chart-id="zones" :query='${JSON.stringify(PINNED)}' />`;
const slides = (title, extra) => `---
title: ${title}
theme: default
---

# ${title}

${CHART}
${extra}`;

function portalApi(url, body) {
  const person = PEOPLE[body.user_id];
  const mine = slug => !!person.manager || OWNERS[slug] === person.zone;
  if (url.pathname === '/internal/presentations/check') {
    const slugs = body.deck_slugs || [];
    return [200, { role: person.role, can_manage: !!person.manager, can_use: true, can_create: true, allowed_slugs: slugs.filter(mine), editable_slugs: slugs.filter(mine), owner_zones: person.manager ? Object.fromEntries(slugs.filter(s => OWNERS[s]).map(s => [s, `Zone ${OWNERS[s]}`])) : {} }];
  }
  if (url.pathname === '/internal/presentations/access') { asked.push(`access:${body.operation}:${body.user_id}`); return [200, { ok: true, access: {}, options: {} }]; }
  if (url.pathname === '/internal/presentations/chart-data') { asked.push(`chart:${body.deck}:${body.user_id}`); return [200, { table: { labels: [], series: [] }, meta: { who: body.user_id, deck: body.deck } }]; }
  if (url.pathname === '/internal/presentations/kpis') { asked.push(`kpis:${body.deck || ''}:${body.user_id}`); return [200, []]; }
  return [404, { error: 'stand-in: not found' }];
}

let stub, manager;
before(async () => {
  if (!posix) return;
  stub = await startStub((req, url, body) => supabaseAnswer(req, url) || portalApi(url, body));
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  manager = await startManager({
    decks: { alpha: 'Alpha council', beta: 'Beta council', talk: 'Mission talk' },
    env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl, PRESENTATIONS_PORTAL_ORIGINS: 'http://127.0.0.1:8070', GFM_PUBLIC_DOMAIN: 'example.org' },
  });
  await fs.writeFile(path.join(manager.decks, 'alpha', 'slides.md'), slides('Alpha council', '<MissionKpiChart kpi="friends_found" />'));
  await fs.writeFile(path.join(manager.decks, 'talk', 'slides.md'), slides('Mission talk', ''));
});

after(async () => {
  if (manager) await manager.stop();
  if (stub) await new Promise(r => stub.close(r));
});

const cookieOf = response => (response.headers.get('set-cookie') || '').split(';')[0];

/** Signs in to Presentations the way the portal does (POST /api/session with the portal's token); the session cookie. */
async function signIn(as) {
  const response = await fetch(`${manager.url}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${as}` } });
  assert.equal(response.status, 200);
  return cookieOf(response);
}

/** The library opening a deck (a same-origin navigation): the manager's answer. */
function door(pathname, cookie, headers = {}) {
  return fetch(`${manager.url}${pathname}`, { redirect: 'manual', headers: { Cookie: cookie, Accept: 'text/html', 'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'navigate', ...headers } });
}

const deckGet = (pathname, cookie, headers = {}) => fetch(`${manager.deckUrl}${pathname}`, { headers: { ...(cookie ? { Cookie: cookie } : {}), Accept: 'text/html', ...headers } });

test("opening a deck: a view pass for that deck only, and on to the deck address", { skip }, async () => {
  const session = await signIn(AS.ap);
  const response = await door('/p/alpha/3?x=1', session);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get('location'), `${manager.deckUrl}/p/alpha/3?x=1`);
  const setCookie = response.headers.get('set-cookie');
  assert.match(setCookie, /^gfm_view_alpha=[0-9a-f]{64}; HttpOnly; SameSite=Strict; Path=\/$/);
  const page = await deckGet('/p/alpha/', cookieOf(response));
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.match(html, /<title>built<\/title>/, 'a manager sees the zone deck itself (no sandbox)');
  assert.doesNotMatch(page.headers.get('content-security-policy') || '', /sandbox/);
  assert.ok(html.includes(`${manager.url}/studio/alpha`), 'the edit button leads back to the manager address');
  // The pass opens only its own deck.
  assert.equal((await deckGet('/p/beta/', cookieOf(response))).status, 401);
});

test("the manager's sign-in never opens anything on the deck address", { skip }, async () => {
  const session = await signIn(AS.ap);
  for (const pathname of ['/p/alpha/', '/p/talk/', '/edit/alpha/', '/edit/alpha/1']) {
    const withSession = await deckGet(pathname, session);
    assert.equal(withSession.status, 401, pathname);
    assert.match(await withSession.text(), /Please open the presentation again/);
    assert.equal((await deckGet(pathname, '', { Authorization: `Bearer ${AS.ap}` })).status, 401, `${pathname} with a Bearer token`);
  }
  const chart = await fetch(`${manager.deckUrl}/api/charts/data`, { method: 'POST', headers: { Cookie: session, 'Content-Type': 'application/json', Referer: `${manager.deckUrl}/p/alpha/` }, body: JSON.stringify({ deck: 'alpha', spec: { measures: ['friends_found.actual'] } }) });
  assert.equal(chart.status, 401);
  // No other manager route exists there.
  for (const pathname of ['/api/presentations', '/api/presentations/alpha/source', '/api/session', '/studio/alpha', '/'])
    assert.notEqual((await deckGet(pathname, session, { Accept: 'application/json' })).status, 200, pathname);
});

test("a deck page's requests to the manager are refused, and CORS never lets the deck address in", { skip }, async () => {
  const session = await signIn(AS.ap);
  const deckPage = manager.deckUrl;
  const calls = asked.length;
  // What a deck's code could try with the manager's cookie (the browser sends it: same computer, same-site).
  for (const [pathname, method, extra] of [
    ['/api/presentations', 'GET', {}],
    ['/api/presentations/alpha/access', 'POST', { 'Content-Type': 'text/plain' }],
    ['/api/presentations/talk/source', 'PUT', { 'Content-Type': 'text/plain' }],
    ['/api/presentations/talk', 'DELETE', {}],
    ['/__slidev/slides/1.json', 'POST', { Referer: `${manager.url}/edit/talk/1` }],
  ]) {
    const response = await fetch(`${manager.url}${pathname}`, { method, headers: { Cookie: session, Origin: deckPage, 'Sec-Fetch-Site': 'same-site', ...extra }, body: method === 'GET' || method === 'DELETE' ? undefined : '{}' });
    assert.equal(response.status, 403, `${method} ${pathname}`);
    assert.equal(response.headers.get('access-control-allow-origin'), null);
    assert.equal((await response.json()).refused, true);
  }
  // The browser's preflight for the header (or a Bearer token): no.
  for (const pathname of ['/api/presentations', '/api/session']) {
    const preflight = await fetch(`${manager.url}${pathname}`, { method: 'OPTIONS', headers: { Origin: deckPage, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'x-gfm-request,authorization' } });
    assert.equal(preflight.status, 403, pathname);
    assert.equal(preflight.headers.get('access-control-allow-origin'), null);
    assert.equal(preflight.headers.get('access-control-allow-credentials'), null);
  }
  // The portal still gets its CORS answer for the sign-in.
  const portal = await fetch(`${manager.url}/api/session`, { method: 'OPTIONS', headers: { Origin: 'http://127.0.0.1:8070', 'Access-Control-Request-Method': 'POST' } });
  assert.equal(portal.status, 204);
  assert.equal(portal.headers.get('access-control-allow-origin'), 'http://127.0.0.1:8070');
  // The same routes work from the manager's own pages (the header), so nothing is refused by accident.
  const own = await fetch(`${manager.url}/api/presentations`, { headers: { Cookie: session, 'X-GFM-Request': '1', 'Sec-Fetch-Site': 'same-origin' } });
  assert.equal(own.status, 200);
  assert.equal(asked.slice(calls).filter(c => c.startsWith('access:')).length, 0, 'nothing reached portal-api for the refused requests');
  // A deck page cannot open another deck or an editor for itself: the person is asked (no pass is given).
  for (const pathname of ['/p/talk/', '/studio/talk']) {
    const confirm = await door(pathname, session, { 'Sec-Fetch-Site': 'same-site' });
    assert.equal(confirm.status, 200, pathname);
    assert.equal(confirm.headers.get('set-cookie'), null, `${pathname}: no pass`);
    const html = await confirm.text();
    assert.match(html, /To keep your sign-in safe, please confirm/);
    assert.match(html, /Mission talk/);
    assert.match(confirm.headers.get('content-security-policy'), /^frame-ancestors 'self' http:\/\/127\.0\.0\.1:8070/, 'only the portal may frame it (not a deck page)');
  }
  // The manager's pages cannot be framed by a deck page either.
  const library = (await fetch(`${manager.url}/`)).headers.get('content-security-policy');
  assert.match(library, /^frame-ancestors 'self' /);
  assert.ok(!library.includes(`:${new URL(manager.deckUrl).port}`), library);
});

test("charts on a deck page: that deck's pass only, and portal-api is told which deck", { skip }, async () => {
  const session = await signIn(AS.zl5);
  const pass = cookieOf(await door('/p/alpha/', session));
  // A deck page's requests name their page (Referer, added by the browser).
  const onPage = (page, extra = {}) => ({ 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'same-origin', Referer: `${manager.deckUrl}/p/${page}/1`, ...extra });
  const post = (deck, cookie, headers = onPage(deck)) => fetch(`${manager.deckUrl}/api/charts/data`, { method: 'POST', headers: { Cookie: cookie, ...headers }, body: JSON.stringify({ deck, spec: PINNED }) });
  const own = await post('alpha', pass);
  assert.equal(own.status, 200);
  assert.deepEqual((await own.json()).meta.deck, 'alpha');
  assert.ok(asked.includes('chart:alpha:user-zl5'));
  assert.equal((await post('beta', pass)).status, 401, "another deck's numbers need that deck's pass");
  assert.equal((await post('alpha', pass, onPage('alpha', { 'Sec-Fetch-Site': 'same-site', Origin: manager.url }))).status, 403, 'not from another address');
  const kpis = await fetch(`${manager.deckUrl}/api/mission-kpis?weeks=12&deck=alpha`, { headers: { Cookie: pass, Referer: `${manager.deckUrl}/p/alpha/1` } });
  assert.equal(kpis.status, 200);
  assert.ok(asked.includes('kpis:alpha:user-zl5'), 'portal-api narrows a zone deck to its zone');
  // Older built decks name the deck only in the address they are on (the Referer).
  const older = await fetch(`${manager.deckUrl}/api/mission-kpis?weeks=12`, { headers: { Cookie: pass, Referer: `${manager.deckUrl}/p/alpha/2` } });
  assert.equal(older.status, 200);
  // A ZL of another zone gets no pass for this zone's deck.
  const other = await door('/p/alpha/', await signIn(AS.zl6));
  assert.equal(other.status, 403);
  assert.equal(other.headers.get('set-cookie'), null);
});

// Round 8 review: all decks share the deck address, so the browser sends every pass it holds with every request
// there. A deck page therefore gets numbers only for its own deck (the page it is on), and only for the charts
// written in that deck, whoever opened it: a zone deck's code never gets the mission's numbers for a query of its own.
test("a deck page gets only the charts written in its own deck, managers too", { skip }, async () => {
  const session = await signIn(AS.ap);
  const alpha = cookieOf(await door('/p/alpha/', session));
  const talk = cookieOf(await door('/p/talk/', session));
  const both = `${alpha}; ${talk}`;
  const ask = (page, body, cookie = both) => fetch(`${manager.deckUrl}/api/charts/data`, {
    method: 'POST', body: JSON.stringify(body),
    headers: { Cookie: cookie, 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'same-origin', Origin: manager.deckUrl, Referer: `${manager.deckUrl}/p/${page}/2` },
  });
  const calls = asked.length;
  // The zone deck's page: its own chart, yes (the deck is the page's own, also when the request names none).
  const own = await ask('alpha', { spec: PINNED });
  assert.equal(own.status, 200);
  assert.equal((await own.json()).meta.deck, 'alpha');
  // Naming the mission deck from the zone deck's page: refused (the page decides the deck, not the request).
  const named = await ask('alpha', { deck: 'talk', spec: PINNED });
  assert.equal(named.status, 403);
  assert.equal((await named.json()).error, FROM_OTHER_PAGE);
  // Any query not written in the deck: refused on the deck address, for the AP too.
  const other = await ask('alpha', { deck: 'alpha', spec: { measures: ['friends_found.actual'], level: 'district' } });
  assert.equal(other.status, 403);
  assert.equal((await other.json()).error, NOT_PINNED);
  assert.equal((await ask('talk', { deck: 'talk', spec: { measures: ['friends_found.actual'], level: 'area' } })).status, 403, "the mission deck's page too");
  // A request that claims another deck's page needs that deck's own pass.
  assert.equal((await ask('talk', { spec: PINNED }, alpha)).status, 401);
  assert.deepEqual(asked.slice(calls).filter(c => c.startsWith('chart:')), ['chart:alpha:user-ap'], 'portal-api was asked once, for the zone deck');
  // Key numbers: only for a deck with a key-number chart in it.
  const kpi = page => fetch(`${manager.deckUrl}/api/mission-kpis?weeks=104`, { headers: { Cookie: both, Referer: `${manager.deckUrl}/p/${page}/1` } });
  assert.equal((await kpi('alpha')).status, 200);
  const none = await kpi('talk');
  assert.equal(none.status, 403, 'the mission deck holds no key-number chart');
  assert.equal((await none.json()).error, NOT_PINNED);
  // The chart builder's preview asks the manager address (with its header), which keeps the manager's rules.
  const preview = await fetch(`${manager.url}/api/charts/data`, {
    method: 'POST', body: JSON.stringify({ deck: 'alpha', spec: { measures: ['friends_found.actual'], level: 'district' } }),
    headers: { Cookie: session, 'X-GFM-Request': '1', 'Sec-Fetch-Site': 'same-origin', 'Content-Type': 'application/json' },
  });
  assert.equal(preview.status, 200);
});

test('an open deck page keeps its own pass (it asks every few minutes); nothing else does', { skip }, async () => {
  const session = await signIn(AS.zl5);
  const pass = cookieOf(await door('/p/alpha/', session));
  const html = await (await deckGet('/p/alpha/', pass)).text();
  assert.ok(html.includes("fetch('/api/deck-pass'"), 'the page asks for /api/deck-pass');
  assert.ok(html.includes(`},${PASS_KEEPALIVE_MS});`), 'every 5 minutes');
  const alive = (cookie, referer = `${manager.deckUrl}/p/alpha/4`) => fetch(`${manager.deckUrl}/api/deck-pass`, { headers: { Cookie: cookie, ...(referer ? { Referer: referer } : {}) } });
  assert.equal((await alive(pass)).status, 204);
  assert.equal((await alive('')).status, 401, 'no pass: "Please open the presentation again"');
  assert.equal((await alive(pass, '')).status, 403, 'only from a deck page');
  assert.equal((await alive(pass, `${manager.url}/p/alpha/`)).status, 403, 'not from a page on another address');
});

test('an edit pass lives with its /studio page and its editor; the deck address never starts an editor', { skip }, async () => {
  const editorPort = await freePort();
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  const own = await startManager({
    decks: { alpha: 'Alpha council' }, editor: true,
    env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl, PRESENTATIONS_PORTAL_ORIGINS: 'http://127.0.0.1:8070', GFM_PUBLIC_DOMAIN: 'example.org', SLIDEV_INTERNAL_PORT_START: String(editorPort) },
  });
  try {
    const session = cookieOf(await fetch(`${own.url}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${AS.ap}` } }));
    const api = (pathname, method = 'GET', body) => fetch(`${own.url}${pathname}`, {
      method, body: body ? JSON.stringify(body) : undefined,
      headers: { Cookie: session, 'X-GFM-Request': '1', 'Sec-Fetch-Site': 'same-origin', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    });
    const editorPage = cookie => fetch(`${own.deckUrl}/edit/alpha/1`, { headers: { Cookie: cookie, Accept: 'text/html' } });
    const stage = async () => (await (await api('/api/presentations/alpha/status')).json()).editor;
    const starts = () => (own.log().match(/starting Slidev/g) || []).length;
    // /studio opens the editor: the edit pass, for this page (its random id).
    const opened = await api('/api/presentations/alpha/editor', 'POST', { page: 'pagea00001' });
    assert.equal(opened.status, 200);
    const pass = cookieOf(opened);
    assert.match(pass, /^gfm_edit_alpha=[0-9a-f]{64}$/);
    assert.equal((await editorPage(pass)).status, 200);
    assert.equal(await stage(), 'ready', "/studio's status question keeps the pass while the page is open");
    // Another tab of the same deck being left does not end it; this page being left does.
    await api('/api/presentations/alpha/editor/leave', 'POST', { page: 'otherpage01' });
    assert.equal((await editorPage(pass)).status, 200);
    await api('/api/presentations/alpha/editor/leave', 'POST', { page: 'pagea00001' });
    const left = await editorPage(pass);
    assert.equal(left.status, 401);
    assert.match(await left.text(), /Please open the presentation again/);
    assert.equal(await stage(), 'stopped', '/studio, if it is still open, opens the editor again with a new pass');
    // The editor stops (not used, or anything else): its passes end with it, and the deck address never starts it.
    const again = cookieOf(await api('/api/presentations/alpha/editor', 'POST', { page: 'pagea00002' }));
    assert.equal((await editorPage(again)).status, 200);
    const started = starts();
    assert.equal(started, 1, 'one editor was started (by /studio)');
    await fetch(`http://127.0.0.1:${editorPort}/__exit`).catch(() => {});
    let status = 0;
    for (let i = 0; i < 50 && status !== 401; i++) { await new Promise(r => setTimeout(r, 100)); status = (await editorPage(again)).status; }
    assert.equal(status, 401, 'the pass ended with the editor');
    assert.equal(await stage(), 'stopped');
    for (let i = 0; i < 3; i++) await editorPage(again);
    assert.equal(starts(), started, 'the deck address started no editor');
  } finally {
    await own.stop();
  }
});

test('signing out ends the passes; a new person on the same browser starts without them', { skip }, async () => {
  const session = await signIn(AS.ap);
  const pass = cookieOf(await door('/p/talk/', session));
  assert.equal((await deckGet('/p/talk/', pass)).status, 200);
  const out = await fetch(`${manager.url}/api/logout`, { method: 'POST', headers: { Cookie: session } });
  assert.equal(out.status, 200);
  assert.equal((await deckGet('/p/talk/', pass)).status, 401);
  // Another person signs in on the same browser (the old session cookie is sent along): the old passes stay ended.
  const session2 = await signIn(AS.zl5);
  const pass2 = cookieOf(await door('/p/alpha/', session2));
  assert.equal((await deckGet('/p/alpha/', pass2)).status, 200);
  const replaced = await fetch(`${manager.url}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${AS.zl6}`, Cookie: session2 } });
  assert.equal(replaced.status, 200);
  assert.equal((await deckGet('/p/alpha/', pass2)).status, 401, "the ZL's passes ended when someone else signed in here");
});

test("the editor's live connection: never on the manager address; on the deck address only from its own pages with an edit pass", { skip }, async () => {
  const session = await signIn(AS.ap);
  const upgrade = (base, headers) => new Promise(resolve => {
    const url = new URL('/edit/alpha/', base);
    const req = http.request({ host: url.hostname, port: url.port, path: url.pathname, headers: { Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==', ...headers } });
    req.on('upgrade', () => resolve('upgraded'));
    req.on('response', r => resolve(`status ${r.statusCode}`));
    req.on('error', () => resolve('closed'));
    req.end();
  });
  assert.equal(await upgrade(manager.url, { Cookie: session, Origin: manager.url }), 'closed');
  assert.equal(await upgrade(manager.deckUrl, { Cookie: session, Origin: manager.deckUrl }), 'closed', "the manager's cookie is no edit pass");
  const view = cookieOf(await door('/p/alpha/', session));
  assert.equal(await upgrade(manager.deckUrl, { Cookie: view, Origin: manager.deckUrl }), 'closed', 'a view pass is no edit pass');
  assert.ok(!/starting Slidev/.test(manager.log()), 'no editor was started');
});

// ---- Round 10: the public names (docs/handoff/round10/public-everything.md) ----------------------------------------
const NAMES = { manager: 'https://presentations.example.org', deck: 'https://decks.example.org', cookieDomain: 'example.org' };
const ADDR = { managerPort: 3030, deckPort: 8089, names: NAMES };

test('round 10: the public names are exactly the two configured names', () => {
  assert.equal(publicSide('presentations.example.org', NAMES), 'manager');
  assert.equal(publicSide('DECKS.Example.ORG', NAMES), 'deck');
  for (const host of ['192.168.1.20:3030', 'localhost:8089', 'example.org', 'dashboards.example.org',
    'presentations.example.org.evil.example', 'xdecks.example.org', '', undefined]) {
    assert.equal(publicSide(host, NAMES), '', String(host));
  }
  assert.equal(publicSide('presentations.example.org', {}), '', 'no names configured');
});

test('round 10: addressOf names the other side by its public name there, by its port elsewhere (as before)', () => {
  assert.equal(addressOf('deck', 'presentations.example.org', ADDR), 'https://decks.example.org');
  assert.equal(addressOf('manager', 'decks.example.org', ADDR), 'https://presentations.example.org');
  assert.equal(addressOf('deck', '192.168.1.20:3030', ADDR), 'http://192.168.1.20:8089');
  assert.equal(addressOf('manager', 'localhost:8089', ADDR), 'http://localhost:3030');
  assert.equal(addressOf('deck', 'bad host"><script>', ADDR), '');
  assert.equal(addressOf('deck', 'presentations.example.org', { ...ADDR, names: { ...NAMES, deck: '' } }), '',
    'the deck name turned off: no address at all on the manager\'s public name (the doorway answers "not found")');
});

test('round 10: on the public names a pass is a Secure cookie of the domain; elsewhere it stays the computer\'s', () => {
  assert.equal(passDomainFor('presentations.example.org', NAMES), 'example.org');
  assert.equal(passDomainFor('192.168.1.20:3030', NAMES), '');
  assert.equal(passDomainFor('presentations.example.org', { ...NAMES, cookieDomain: 'x; Domain=evil' }), '');
  assert.equal(passCookie('alpha', 'view', 'abc', 'example.org'),
    'gfm_view_alpha=abc; HttpOnly; SameSite=Strict; Path=/; Domain=example.org; Secure');
  assert.equal(passCookie('alpha', 'view', 'abc', ''), 'gfm_view_alpha=abc; HttpOnly; SameSite=Strict; Path=/');
});

test('round 10: a page on the deck address\'s public name counts as a deck page everywhere', () => {
  assert.equal(isDeckOrigin('https://decks.example.org', 8089, NAMES.deck), true);
  assert.equal(isDeckOrigin('https://DECKS.Example.ORG', 8089, NAMES.deck), true);
  assert.equal(isDeckOrigin('https://example.org', 8089, NAMES.deck), false);
  assert.equal(isDeckOrigin('https://decks.example.org', 8089), false, 'without the name: the port rule only');
  const host = 'presentations.example.org';
  const ask10 = (pathname, headers, method = 'GET') => managerRefusal({ method, pathname, headers: { host, ...headers } }, { deckPort: 8089, deckName: NAMES.deck });
  assert.equal(ask10('/api/presentations', { origin: NAMES.deck, 'sec-fetch-site': 'same-site', 'x-gfm-request': '1' }), FROM_DECK_PAGE);
  assert.equal(ask10('/api/session', { origin: NAMES.deck }, 'POST'), FROM_DECK_PAGE, 'not even the sign-in');
  assert.equal(ask10('/api/presentations', { origin: NAMES.manager, 'sec-fetch-site': 'same-origin', 'x-gfm-request': '1' }), null, 'the library itself');
  assert.equal(ask10('/api/presentations', { origin: 'https://example.org', 'sec-fetch-site': 'same-site', 'x-gfm-request': '1' }), MISSING_HEADER);
  assert.equal(doorwayFromOtherPage({ pathname: '/p/alpha/', headers: { 'sec-fetch-site': 'same-site' } }), true, 'a deck page opening a deck: confirm first');
});

// The real manager, asked the way the Cloudflare tunnel brings the public names in: plain http, with the public
// name in the Host header.
function onName(base, host, pathname, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(pathname, base);
    const req = http.request({ host: url.hostname, port: url.port, path: url.pathname + url.search, method, headers: { Host: host, ...headers } }, res => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { text += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text }));
    });
    req.on('error', reject);
    req.end(body);
  });
}
const MANAGER_NAME = 'presentations.example.org';
const DECK_NAME = 'decks.example.org';
const firstCookie = res => String([].concat(res.headers['set-cookie'] || [])[0] || '');

test('round 10: on the public names the portal signs in, a deck opens on the deck name with a domain pass, and a deck page stays out', { skip }, async () => {
  const portal = 'https://example.org';
  const signIn10 = await onName(manager.url, MANAGER_NAME, '/api/session', { method: 'POST', headers: { Origin: portal, Authorization: `Bearer ${AS.ap}` } });
  assert.equal(signIn10.status, 200);
  assert.equal(signIn10.headers['access-control-allow-origin'], portal, 'the portal on its public address may sign in');
  assert.match(firstCookie(signIn10), /^presentation_session=[^;]+; HttpOnly; SameSite=Lax; Path=\/; Max-Age=\d+; Secure$/, 'Secure, and no Domain');
  const session = firstCookie(signIn10).split(';')[0];
  const www = await onName(manager.url, MANAGER_NAME, '/api/session', { method: 'OPTIONS', headers: { Origin: 'https://www.example.org', 'Access-Control-Request-Method': 'POST' } });
  assert.equal(www.status, 204);
  for (const origin of [`https://${DECK_NAME}`, 'https://dashboards.example.org', 'https://evil.example']) {
    const refused = await onName(manager.url, MANAGER_NAME, '/api/session', { method: 'POST', headers: { Origin: origin, Authorization: `Bearer ${AS.ap}` } });
    assert.equal(refused.headers['access-control-allow-origin'], undefined, origin);
  }

  const door10 = await onName(manager.url, MANAGER_NAME, '/p/alpha/3?x=1', { headers: { Cookie: session, Accept: 'text/html', 'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'navigate' } });
  assert.equal(door10.status, 302);
  assert.equal(door10.headers.location, `https://${DECK_NAME}/p/alpha/3?x=1`);
  assert.match(firstCookie(door10), /^gfm_view_alpha=[0-9a-f]{64}; HttpOnly; SameSite=Strict; Path=\/; Domain=example\.org; Secure$/);
  const pass = firstCookie(door10).split(';')[0];

  const page = await onName(manager.deckUrl, DECK_NAME, '/p/alpha/', { headers: { Cookie: pass, Accept: 'text/html' } });
  assert.equal(page.status, 200);
  assert.ok(page.text.includes(`https://${MANAGER_NAME}/studio/alpha`), 'the edit button leads to the manager\'s public name');
  const ancestors = page.headers['content-security-policy'];
  assert.match(ancestors, /frame-ancestors 'self' [^;]*https:\/\/example\.org/);
  assert.ok(ancestors.includes(`https://${MANAGER_NAME}`), ancestors);
  // The manager's own cookie opens nothing there (it would not even be sent: it has no Domain).
  assert.equal((await onName(manager.deckUrl, DECK_NAME, '/p/alpha/', { headers: { Cookie: session, Accept: 'text/html' } })).status, 401);

  // A deck page (Origin: the deck name) asking the manager: refused, even with the header.
  const fromDeck = await onName(manager.url, MANAGER_NAME, '/api/presentations', { headers: { Cookie: session, Origin: `https://${DECK_NAME}`, 'Sec-Fetch-Site': 'same-site', 'X-GFM-Request': '1' } });
  assert.equal(fromDeck.status, 403);
  // The library itself (same origin, https in the browser) is served.
  const library = await onName(manager.url, MANAGER_NAME, '/api/presentations', { headers: { Cookie: session, Origin: `https://${MANAGER_NAME}`, 'Sec-Fetch-Site': 'same-origin', 'X-GFM-Request': '1' } });
  assert.equal(library.status, 200);
  // Sign-out from the portal's public address ends it, and the cookie is cleared Secure.
  const out = await onName(manager.url, MANAGER_NAME, '/api/logout', { method: 'POST', headers: { Cookie: session, Origin: portal } });
  assert.equal(out.status, 200);
  assert.match(firstCookie(out), /^presentation_session=; .*Max-Age=0.*; Secure$/);
  assert.equal((await onName(manager.deckUrl, DECK_NAME, '/p/alpha/', { headers: { Cookie: pass, Accept: 'text/html' } })).status, 401, 'the pass ended with the sign-in');
});

test('round 10: the office addresses answer exactly as before (no Domain, no Secure, the port rule)', { skip }, async () => {
  const session = await signIn(AS.ap);
  const response = await door('/p/alpha/', session);
  assert.equal(response.headers.get('location'), `${manager.deckUrl}/p/alpha/`);
  assert.doesNotMatch(response.headers.get('set-cookie'), /Domain|Secure/);
});
