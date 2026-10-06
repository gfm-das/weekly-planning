// The portal shell's Dashboards button (page key 'insights') opens DataEase (:8088/gfm-start, round 6) after
// asking portal-api for the Dashboards sign-in, keeps that sign-in alive while it is on screen, offers Full screen,
// clears the sign-in on sign-out and no longer talks to Grafana or the Mission Dashboard deck. Leaders and
// missionaries are not offered it.
// This runs the real portal-enhancements.js in a Node vm with a small stand-in for the page (the
// template's globals, a DOM that accepts anything, fetch and timers that record what happens).
// Run: node portal/tests/dashboards-dataease-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../portal-enhancements.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../index.template.html'), 'utf8');
const PORTAL = 'http://portal.test';
const ORIGIN = PORTAL + ':8088';
const START = ORIGIN + '/gfm-start';
const START_EN = START + '?gfmLang=en'; // the viewer's portal language goes along (English when none is set)

function world() {
  const log = { fetches: [], opened: [], visible: {}, timers: [], listeners: {}, messages: [], created: [], buttons: {} };
  const elements = new Map();
  // An element that accepts any call or property; getElementById returns the same one per id.
  function element(name) {
    const store = { style: {}, dataset: {}, hidden: false, textContent: '', value: '', options: [], children: [], id: name,
      nextSibling: null, nextElementSibling: null, previousSibling: null, firstChild: null, lastChild: null, offsetParent: null,
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      contentWindow: { postMessage: (message, origin) => log.messages.push({ to: name, message, origin }), location: { href: 'about:blank' } } };
    return new Proxy(function () {}, {
      get(_, key) {
        if (key in store) return store[key];
        if (typeof key === 'symbol') return key === Symbol.toPrimitive ? () => '' : undefined;
        if (key === 'then') return undefined;
        if (key === 'querySelectorAll' || key === 'getElementsByTagName' || key === 'getClientRects') return () => [];
        if (key === 'querySelector') return selector => byId(`query:${selector}`);
        if (key === 'closest') return () => null;
        if (key === 'addEventListener') return (type, fn) => (log.listeners[`${name}:${type}`] ||= []).push(fn);
        if (key === 'getBoundingClientRect') return () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 });
        // Anything else is another such element, which can also be called (and gives one back).
        return (store[key] = element(`${name}.${String(key)}`));
      },
      apply: () => element(`${name}()`),
      set(_, key, value) { store[key] = value; return true; },
    });
  }
  const byId = id => (elements.has(id) ? elements.get(id) : (elements.set(id, element(id)), elements.get(id)));
  const document = element('document');
  const storage = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }; };
  const location = { hash: '#overview', origin: PORTAL, protocol: 'http:', hostname: 'portal.test', href: PORTAL + '/', pathname: '/', search: '' };
  const respond = {
    session: () => ({ ok: true, status: 200, json: async () => ({ expires_at: new Date(Date.now() + 600000).toISOString() }) }),
    dataease: () => ({ ok: true, status: 200, json: async () => ({ ok: true, expires_at: new Date(Date.now() + 900000).toISOString() }) }),
  };
  const context = {
    console, URL, URLSearchParams, Promise, Date, Math, JSON, Set, Map, Object, Array, String, Number, Error, RegExp, Symbol, AbortController, Intl,
    atob: s => Buffer.from(s, 'base64').toString('binary'), btoa: s => Buffer.from(s, 'binary').toString('base64'),
    document, location, localStorage: storage(), sessionStorage: storage(), navigator: { serviceWorker: undefined, language: 'en' },
    history: { replaceState() {} }, Notification: undefined, CustomEvent: class {}, Event: class {}, MutationObserver: class { observe() {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    addEventListener: (type, fn) => (log.listeners[`window:${type}`] ||= []).push(fn),
    setTimeout: (fn, ms) => { log.timers.push({ fn, ms }); return log.timers.length; }, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: fn => 0,
    fetch: async (url, options = {}) => {
      log.fetches.push({ url: String(url), method: options.method || 'GET', credentials: options.credentials, mode: options.mode, auth: (options.headers || {}).Authorization });
      if (String(url).endsWith(':3030/api/session')) return respond.session();
      if (String(url) === '/api/dataease/session') return respond.dataease();
      return { ok: true, status: 200, json: async () => ({}) };
    },
    log, byId, respond,
  };
  context.window = context;
  context.self = context;
  document.getElementById = byId;
  document.createElement = tag => {
    const made = element(`new-${tag}`);
    log.created.push(made);
    return made;
  };
  document.head = element('head');
  document.body = element('body');
  document.documentElement = element('html');
  vm.createContext(context);
  // The template's globals the shell uses (as in index.template.html), then the shell itself.
  vm.runInContext(`
    const PORTAL_PUBLIC_SITE = false;
    const PORTAL_HOST = location.protocol + '//' + location.hostname;
    const SUPABASE_URL = PORTAL_HOST + ':18000';
    const SUPABASE_ANON_KEY = 'anon-test';
    const URLS = { planning: '/planning.html', presentations: PORTAL_HOST + ':3030' };
    const TITLES = { planning: 'Weekly Planning', presentations: 'Presentations' };
    const frame = document.getElementById('appFrame');
    const title = document.getElementById('pageTitle');
    const sidebar = document.getElementById('sidebar');
    let currentUserContext = null;
    let allowedPages = new Set(['planning']);
    function setVisible(id, visible) { log.visible[id] = visible; }
    function applyRoleNavigation(context) {}
    function closeMenu() {}
    function clearMissionSession() {}
    function showLogin() {}
    function ensureMissionSession() { return Promise.resolve('portal-token'); }
    function openPage(name) { log.opened.push({ name, url: URLS[name] }); frame.src = URLS[name]; history.replaceState(null, '', '#' + name); location.hash = '#' + name; }
  `, context);
  vm.runInContext(source, context, { filename: 'portal-enhancements.js' });
  return context;
}

const settle = () => new Promise(resolve => setImmediate(resolve));
async function signedIn(role) {
  const w = world();
  const c = role === 'AP'
    ? { user_id: 'u-1', leadership_role: 'AP', app_role: 'AP', additional_roles: [], display_name: 'Test AP' }
    : { user_id: 'u-2', leadership_role: role, app_role: 'MISSIONARY', additional_roles: [], display_name: 'Test leader' };
  vm.runInContext('currentUserContext = ctx; applyRoleNavigation(ctx);', Object.assign(w, { ctx: c }));
  return w;
}

(async () => {
  assert.ok(/<script src="\/portal-enhancements\.js\?v=\d+"><\/script>/.test(template), 'index.template.html loads portal-enhancements.js with a version number');
  const code = source.replace(/\/\/.*$/gm, '');
  assert.ok(!/grafana/i.test(code), 'no Grafana address or call is left in the shell (outside comments)');
  assert.ok(!/mission-dashboard/.test(code), 'the Mission Dashboard deck is not linked any more');

  // A manager (AP): the button is offered and opens DataEase, after the Dashboards sign-in.
  const ap = await signedIn('AP');
  assert.equal(ap.log.visible.navInsights, true, 'an AP sees Dashboards');
  await settle();
  assert.ok(!ap.log.fetches.some(f => f.url === ORIGIN + '/gfm-signout'), "a manager's sign-in leaves the Dashboards sign-in alone");
  assert.equal(vm.runInContext('URLS.insights', ap), START_EN, 'Dashboards point at DataEase on :8088 (/gfm-start), with the language');
  ap.sessionStorage.setItem('mission_language', 'ar');
  assert.equal(vm.runInContext('URLS.insights', ap), START + '?gfmLang=ar', 'the portal language of the moment (Arabic)');
  ap.sessionStorage.removeItem('mission_language');
  assert.equal(vm.runInContext('TITLES.insights', ap), 'Dashboards');
  vm.runInContext("openPage('insights')", ap);
  await settle(); await settle(); await settle();
  const session = ap.log.fetches.findIndex(f => f.url === '/api/dataease/session');
  assert.ok(session >= 0, 'the Dashboards sign-in is asked for first');
  assert.equal(ap.log.fetches[session].method, 'POST');
  assert.equal(ap.log.fetches[session].auth, 'Bearer portal-token', 'with the portal sign-in, to portal-api on the portal address');
  assert.deepEqual(ap.log.opened.map(o => o.name), ['insights'], 'then Dashboards open');
  assert.equal(ap.log.opened[0].url, START_EN);
  assert.ok(!ap.log.opened[0].url.includes('token'), 'no token in the frame address');
  assert.equal(ap.byId('pageTitle').textContent, 'Dashboards');
  assert.ok(!ap.log.fetches.some(f => f.url.includes(':3030')), 'Presentations are not asked for anything when Dashboards open');
  assert.ok(ap.log.timers.some(t => t.ms === 600000), 'the Dashboards sign-in (15 minutes) is renewed every 10 minutes');
  const fullScreen = ap.log.created.find(el => el.textContent === 'Full screen');
  assert.ok(fullScreen, 'there is a Full screen button');
  assert.equal(fullScreen.hidden, false, 'shown while Dashboards are open');

  // The "Please open Dashboards" page in the frame asks for a renewal: answered only for DataEase's origin.
  const before = ap.log.fetches.length;
  const frameWindow = ap.byId('appFrame').contentWindow;
  for (const fn of ap.log.listeners['window:message'] || [])
    fn({ data: { type: 'dataease-session-request' }, origin: PORTAL + ':3030', source: frameWindow });
  await settle(); await settle();
  assert.equal(ap.log.fetches.length, before, 'a request from another origin is ignored');
  for (const fn of ap.log.listeners['window:message'] || [])
    fn({ data: { type: 'dataease-session-request' }, origin: ORIGIN, source: frameWindow });
  await settle(); await settle(); await settle();
  assert.ok(ap.log.fetches.slice(before).some(f => f.url === '/api/dataease/session'), 'a renewal request from DataEase is answered');
  assert.ok(ap.log.messages.some(m => m.message?.type === 'dataease-session-refreshed' && m.origin === ORIGIN), 'and only DataEase\'s origin hears back');

  // The glimpse's "More in Dashboards" asks for Dashboards: the shell opens DataEase the usual way.
  const opened = ap.log.opened.length;
  for (const fn of ap.log.listeners['window:message'] || [])
    fn({ data: { type: 'gfm-open-page', page: 'insights' }, origin: PORTAL, source: frameWindow });
  await settle(); await settle(); await settle();
  assert.equal(ap.log.opened.length, opened + 1, "the glimpse's link leads to DataEase");
  assert.equal(ap.log.opened.at(-1).url, START_EN);

  // Another page hides Full screen again.
  vm.runInContext("openPage('planning')", ap);
  await settle(); await settle();
  assert.equal(fullScreen.hidden, true, 'Full screen is only for Dashboards');

  // Sign-out: Presentations end and the Dashboards cookie is cleared through DataEase's front; no Grafana call.
  const out = ap.log.fetches.length;
  for (const fn of ap.log.listeners['logoutButton:click'] || []) fn({ target: ap.byId('logoutButton') });
  await settle();
  const after = ap.log.fetches.slice(out).map(f => `${f.method} ${f.url}`);
  assert.ok(after.includes(`POST ${PORTAL}:3030/api/logout`), 'sign-out ends the Presentations session');
  assert.ok(after.includes(`GET ${ORIGIN}/gfm-signout`), 'sign-out clears the Dashboards cookie');
  assert.ok(!after.some(f => f.includes('grafana')), 'no Grafana call on sign-out');

  // portal-api refuses (for example a role change since the portal loaded): the reason shows, DataEase does not open.
  const refused = await signedIn('AP');
  refused.respond.dataease = () => ({ ok: false, status: 403, json: async () => ({ error: 'Dashboards are available to the APs, the President and the Data Analysts.' }) });
  vm.runInContext("openPage('insights')", refused);
  for (let i = 0; i < 6; i++) await settle();
  assert.equal(refused.log.opened.length, 0, 'DataEase is not opened without the Dashboards sign-in');
  const chip = refused.log.created.find(el => el.className === 'portal-loading');
  assert.match(chip.textContent, /APs, the President and the Data Analysts/, 'the reason is shown in the loading chip');

  // The sign-in page (an expired portal session) ends the Dashboards sign-in too.
  const expired = await signedIn('AP');
  const beforeLogin = expired.log.fetches.length;
  vm.runInContext('showLogin()', expired);
  await settle();
  assert.ok(expired.log.fetches.slice(beforeLogin).some(f => f.method === 'GET' && f.url === ORIGIN + '/gfm-signout'), 'the sign-in page clears the Dashboards cookie');

  // Leaders and missionaries: no Dashboards button, and asking for it opens the Overview instead. A manager's
  // Dashboards cookie left in this browser (a shared computer) is cleared when they sign in.
  for (const role of ['DL', 'ZL', 'STL', 'MISSIONARY']) {
    const leader = await signedIn(role);
    assert.equal(leader.log.visible.navInsights, false, `a ${role} does not see Dashboards`);
    await settle();
    assert.ok(leader.log.fetches.some(f => f.method === 'GET' && f.url === ORIGIN + '/gfm-signout'), `a ${role}'s sign-in clears a Dashboards cookie left in this browser`);
    vm.runInContext("openPage('insights')", leader);
    for (let i = 0; i < 4; i++) await settle();
    assert.ok(!leader.log.opened.some(o => o.name === 'insights' || String(o.url).startsWith(START)), `a ${role} cannot open Dashboards through the shell`);
    assert.ok(!leader.log.fetches.some(f => f.url.includes('/api/dataease/')), `no Dashboards sign-in is asked for a ${role}`);
  }
  console.log('dashboards (DataEase): shell checks passed (AP opens DataEase signed in, renewal, full screen, the glimpse link to Dashboards, sign-out, sign-in page, refusal, DL/ZL/STL/missionary: no button and a leftover Dashboards cookie cleared)');
})().catch(error => { console.error(error); process.exit(1); });
