// Small checks of the portal's shared helpers, each run for real in a Node vm with a stand-in browser:
//   - portal-session.js: a valid sign-in is used as it is; one about to run out is renewed once (also when several
//     requests ask at the same time); a refused renewal signs out; another tab's renewal is not overwritten.
//   - portal-client.js: the token leaves the address; portalAPI sends the sign-in, the language and JSON, and passes
//     on the server's message, status and per-field messages; escapeHTML; uploads (16 MB limit, no file twice).
//   - service-worker.js: a reminder shows its own words (or the defaults); a click opens the page in the portal tab,
//     or in a new tab, and never another site's address.
//   - index.template.html: the sign-in link reader, the new-password rules and adding a parameter to an address.
// Run from the repository root: node portal/tests/shell-helpers-check.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };
// Objects made inside the vm have its own prototypes: compared as plain JSON.
const plain = value => (value && typeof value === 'object' ? JSON.parse(JSON.stringify(value)) : value);
const eq = (actual, expected, message) => { assert.deepEqual(plain(actual), expected, message); passed++; };
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)); };

function storage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return { getItem: k => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, String(v)), removeItem: k => map.delete(k), map };
}
const b64 = object => Buffer.from(JSON.stringify(object)).toString('base64url');
const token = secondsLeft => `${b64({ alg: 'HS256' })}.${b64({ sub: 'u-1', exp: Math.floor(Date.now() / 1000) + secondsLeft })}.sig`;
const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body, blob: async () => new Blob(['x']) });
const baseContext = extra => vm.createContext({
  console, URL, URLSearchParams, Promise, Date, JSON, Math, Set, Map, WeakSet, Object, Array, String, Number, Error, RegExp, Blob,
  atob: s => Buffer.from(s, 'base64').toString('binary'),
  setTimeout, clearTimeout, setInterval: () => 0,
  ...extra,
});

(async () => {
  // ---- portal-session.js --------------------------------------------------------------------------------------
  function sessionWorld(tokens, answer) {
    const calls = [];
    const localStorage = storage(tokens);
    const context = baseContext({
      localStorage, SUPABASE_URL: 'http://portal.test:18000', SUPABASE_ANON_KEY: 'anon',
      fetch: async (url, options) => { calls.push({ url, options }); return answer(options); },
    });
    context.window = context;
    vm.runInContext(read('portal-session.js'), context, { filename: 'portal-session.js' });
    return { context, calls, localStorage };
  }

  {
    const fresh = token(3600);
    const w = sessionWorld({ mission_access_token: fresh, mission_refresh_token: 'r1' }, () => json({}));
    eq(await w.context.ensureMissionSession(), fresh, 'session: a token with an hour left is used as it is');
    eq(w.calls.length, 0, 'session: no request for a valid token');
  }
  {
    const w = sessionWorld({}, () => json({}));
    await assert.rejects(w.context.ensureMissionSession(), /Sign in to continue\./);
    passed++;
  }
  {
    const renewed = token(3600);
    let release;
    const w = sessionWorld({ mission_access_token: token(60), mission_refresh_token: 'r1' },
      () => new Promise(resolve => { release = () => resolve(json({ access_token: renewed, refresh_token: 'r2' })); }));
    const first = w.context.ensureMissionSession(), second = w.context.ensureMissionSession();
    await settle();
    release();
    eq([await first, await second], [renewed, renewed], 'session: a token about to run out is renewed, for both requests');
    eq(w.calls.length, 1, 'session: two requests at the same time share one renewal (a refresh token works once)');
    ok(w.calls[0].url.endsWith(':18000/auth/v1/token?grant_type=refresh_token') && JSON.parse(w.calls[0].options.body).refresh_token === 'r1',
      'session: the renewal sends the refresh token to Supabase');
    eq([w.localStorage.getItem('mission_access_token'), w.localStorage.getItem('mission_refresh_token')], [renewed, 'r2'],
      'session: the new pair is kept');
  }
  {
    const w = sessionWorld({ mission_access_token: token(-10), mission_refresh_token: 'r1' }, () => json({ msg: 'invalid' }, 401));
    await assert.rejects(w.context.ensureMissionSession(), /Your session expired\. Sign in again\./);
    ok(!w.localStorage.getItem('mission_access_token') && !w.localStorage.getItem('mission_refresh_token'),
      'session: a refused renewal forgets both tokens (the person signs in again)');
  }
  {
    const w = sessionWorld({ mission_access_token: token(-10), mission_refresh_token: 'r1' }, () => json({}, 503));
    await assert.rejects(w.context.ensureMissionSession(), /The sign-in service is unavailable\. Please retry\./);
    eq(w.localStorage.getItem('mission_refresh_token'), 'r1', 'session: a busy sign-in service signs nobody out');
  }
  {
    const w = sessionWorld({ mission_access_token: token(-10), mission_refresh_token: 'r1' }, () => {
      w.localStorage.setItem('mission_refresh_token', 'other-tab');
      return json({ access_token: token(3600), refresh_token: 'r2' });
    });
    await assert.rejects(w.context.ensureMissionSession(), /Your session changed\. Please retry\./);
    eq(w.localStorage.getItem('mission_refresh_token'), 'other-tab', "session: another tab's newer pair is not overwritten");
  }

  // ---- portal-client.js ---------------------------------------------------------------------------------------
  function clientWorld({ search = '?portal_token=abc&glimpse=1', answer = () => json({ ok: true }) } = {}) {
    const calls = [], replaced = [];
    const location = { search, pathname: '/home.html', hash: '#top' };
    const context = baseContext({
      location, localStorage: storage({ mission_access_token: 'stored' }),
      history: { replaceState: (_, __, url) => replaced.push(url) },
      addEventListener() {}, document: { documentElement: { lang: 'de', dataset: {} } },
      FormData: class FormData { constructor() { this.parts = []; } append(k, v) { this.parts.push([k, v]); } },
      fetch: async (url, options) => { calls.push({ url, options }); return answer(url, options); },
    });
    context.window = context;
    context.parent = { ensureMissionSession: async () => 'fresh-token' };
    context.window.parent = context.parent;
    vm.runInContext(read('portal-client.js'), context, { filename: 'portal-client.js' });
    return { context, calls, replaced };
  }

  {
    const w = clientWorld();
    eq(w.replaced, ['/home.html#top'], 'client: the sign-in token is taken out of the address at once');
    await w.context.portalAPI('announcements', { method: 'POST', body: { title: 'Hi' } });
    const sent = w.calls[0];
    eq(sent.url, '/api/announcements', 'client: portalAPI asks /api/<path>');
    eq([sent.options.headers.Authorization, sent.options.headers['X-Mission-Language'], sent.options.headers['Content-Type']],
      ['Bearer fresh-token', 'de', 'application/json'], 'client: a fresh token from the shell, the page language, JSON');
    eq([sent.options.body, sent.options.cache], ['{"title":"Hi"}', 'no-store'], 'client: the body is sent as JSON, never from a cache');
  }
  {
    const w = clientWorld({ search: '', answer: () => json({ error: 'Not allowed.', fields: { title: 'Too long.' } }, 403) });
    eq(w.replaced, [], 'client: an address without a token is left alone');
    const error = await w.context.portalAPI('events').catch(e => e);
    eq([error.message, error.status, error.fields], ['Not allowed.', 403, { title: 'Too long.' }],
      "client: the server's message, status and per-field messages come back with the error");
  }
  {
    const w = clientWorld();
    eq(w.context.escapeHTML(`<a href="x">Tom & 'Jo'</a>`), '&lt;a href=&quot;x&quot;&gt;Tom &amp; &#39;Jo&#39;&lt;/a&gt;',
      'client: escapeHTML makes text safe inside HTML');
    eq(w.context.escapeHTML(null), '', 'client: escapeHTML of nothing is empty');
  }
  {
    let fail = true;
    const w = clientWorld({ answer: url => (url.endsWith('/attachments') && fail ? json({ error: 'Disk full.' }, 500) : json({})) });
    const small = { name: 'Plan.pdf', size: 1000 }, second = { name: 'Größe.pdf', size: 2000 };
    await assert.rejects(w.context.uploadPortalFiles('events', 'e1', [{ name: 'Big.mp4', size: 17 * 1024 * 1024 }]),
      /“Big\.mp4” is larger than 16 MB\. Choose a smaller file\./);
    passed++;
    await assert.rejects(w.context.uploadPortalFiles('events', 'e1', [small, second]), /“Plan\.pdf” was not added: Disk full\./);
    passed++;
    fail = false;
    const before = w.calls.length;
    await w.context.uploadPortalFiles('events', 'e1', [small, second]);
    eq(w.calls.slice(before).map(c => c.url), ['/api/events/e1/attachments', '/api/events/e1/attachments'],
      'client: after a failure, trying again sends the files that were not added');
    await w.context.uploadPortalFiles('events', 'e1', [small, second]);
    eq(w.calls.length, before + 2, 'client: a file already added is never sent twice');
  }

  // ---- service-worker.js ---------------------------------------------------------------------------------------
  function workerWorld(windows = []) {
    const listeners = {}, shown = [], opened = [];
    const self = {
      location: { origin: 'http://portal.test' },
      addEventListener: (type, fn) => { listeners[type] = fn; },
      skipWaiting() {}, clients: { claim: async () => {} },
      registration: { showNotification: async (title, options) => shown.push({ title, options }) },
    };
    const clients = { matchAll: async () => windows, openWindow: async url => opened.push(url) };
    const context = baseContext({ self, clients });
    vm.runInContext(read('service-worker.js'), context, { filename: 'service-worker.js' });
    const fire = async (type, event) => { let wait = null; listeners[type]({ ...event, waitUntil: p => { wait = p; } }); await wait; return wait; };
    return { fire, shown, opened };
  }

  {
    const w = workerWorld();
    await w.fire('push', { data: { json: () => ({ title: 'Weekly Planning', body: 'Your plan is not submitted yet.', tag: 'plan', url: '/#planning' }) } });
    eq(w.shown[0], { title: 'Weekly Planning', options: { body: 'Your plan is not submitted yet.', tag: 'plan', icon: '/mission-icon.svg', badge: '/mission-icon.svg', data: { url: '/#planning' } } },
      'worker: a reminder shows its own title, words and page');
    await w.fire('push', { data: { json: () => { throw new Error('not JSON'); } } });
    eq([w.shown[1].title, w.shown[1].options.body, w.shown[1].options.data.url], ['GFM Mission System', 'Open the portal for your mission update.', '/#overview'],
      'worker: a message without words shows the defaults');
  }
  {
    const navigated = [];
    const tab = { url: 'http://portal.test/#calendar', frameType: 'top-level', navigate: async url => { navigated.push(url); return tab; }, focus: async () => tab };
    const inner = { url: 'http://portal.test/home.html', frameType: 'nested', navigate: async () => { throw new Error('inner'); }, focus: async () => inner };
    const w = workerWorld([inner, tab]);
    await w.fire('notificationclick', { notification: { close() {}, data: { url: '/#planning' } } });
    eq(navigated, ['http://portal.test/#planning'], 'worker: a click opens the page in the portal tab (not a page inside it)');
    const none = workerWorld([]);
    await none.fire('notificationclick', { notification: { close() {}, data: { url: '/#calendar' } } });
    eq(none.opened, ['http://portal.test/#calendar'], 'worker: without a portal tab it opens a new one');
    const foreign = workerWorld([tab]);
    const work = await foreign.fire('notificationclick', { notification: { close() {}, data: { url: 'https://evil.example/' } } });
    eq([work, foreign.opened, navigated.length], [null, [], 1], "worker: another site's address is never opened");
  }

  // ---- index.template.html: small helpers of the shell's own script ----------------------------------------------------
  {
    // Line ends made plain first: a Windows checkout (core.autocrlf) has \r\n, and each function ends at "\n}\n".
    const template = read('index.template.html').replace(/\r\n/g, '\n');
    const functionSource = name => {
      const start = template.indexOf(`function ${name}(`);
      assert.ok(start > 0, `index.template.html has ${name}()`);
      const end = template.indexOf('\n}\n', start);
      assert.ok(end > start, `index.template.html: the end of ${name}() is found (a "}" on its own line)`);
      return template.slice(start, end + 2);
    };
    const context = baseContext({ location: { hash: '', search: '' } });
    vm.runInContext(['parseAuthCallback', 'passwordProblem', 'withParameter'].map(functionSource).join('\n'), context);
    context.location.hash = '#access_token=a1&refresh_token=r1&type=invite';
    eq(context.parseAuthCallback(), { accessToken: 'a1', refreshToken: 'r1', type: 'invite' }, 'shell: an invitation link is read from the address');
    context.location.hash = '';
    context.location.search = '?access_token=a2&type=recovery';
    eq(context.parseAuthCallback(), { accessToken: 'a2', refreshToken: null, type: 'recovery' }, 'shell: a reset link in the query is read too');
    context.location.search = '';
    eq(context.parseAuthCallback(), null, 'shell: an ordinary address holds no sign-in link');
    eq(['', 'short1', 'longenough'].map(p => context.passwordProblem(p, p === 'longenough' ? 'different' : p)),
      ['Enter your new password twice.', 'Use at least 8 characters.', 'The passwords do not match.'], 'shell: the new-password rules, in order');
    eq(context.passwordProblem('longenough', 'longenough'), '', 'shell: a good new password has no problem');
    eq([context.withParameter('/planning.html', 'gfm_refresh', 5), context.withParameter('/home.html?glimpse=1', 'portal_token', 'a b')],
      ['/planning.html?gfm_refresh=5', '/home.html?glimpse=1&portal_token=a%20b'], 'shell: a parameter is added with ? or &, encoded');
  }

  console.log(`shell helpers: ${passed} checks passed (sign-in renewal, API requests, uploads, reminder clicks, sign-in links)`);
})().catch(error => { console.error(error); process.exit(1); });
