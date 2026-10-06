// The portal shell's Whiteboard button (page key 'whiteboard', round 6): AP, President and Data Analyst (also as an
// additional role) see it, next to Presentations, and it opens /whiteboard/ in the portal frame; DL, ZL, STL, Office and
// missionaries are not offered it and asking for it opens the Overview. The shell tells the page the Presentations
// address (portalPresentationsUrl) and loads portal-enhancements.js with a version number.
// This runs the real portal-enhancements.js in a Node vm with the same small stand-in for the page as
// dashboards-deck-check.cjs (the template's globals, a DOM that accepts anything, fetch and timers that record).
// Run: node portal/tests/whiteboard-shell-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../portal-enhancements.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../index.template.html'), 'utf8');
const PORTAL = 'http://portal.test';

function world() {
  const log = { fetches: [], opened: [], visible: {}, timers: [], listeners: {}, messages: [] };
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
  const respond = { session: () => ({ ok: true, status: 200, json: async () => ({ expires_at: new Date(Date.now() + 600000).toISOString() }) }) };
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
      log.fetches.push({ url: String(url), method: options.method || 'GET', credentials: options.credentials, auth: (options.headers || {}).Authorization });
      if (String(url).endsWith(':3030/api/session')) return respond.session();
      return { ok: true, status: 200, json: async () => ({}) };
    },
    log, byId, respond,
  };
  context.window = context;
  context.self = context;
  document.getElementById = byId;
  document.createElement = tag => element(`new-${tag}`);
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
const PEOPLE = {
  AP: { leadership_role: 'AP', app_role: 'AP', additional_roles: [] },
  PRESIDENT: { leadership_role: null, app_role: 'PRESIDENT', additional_roles: [] },
  'DL + Data Analyst': { leadership_role: 'DL', app_role: 'MISSIONARY', additional_roles: ['DATA_ADMIN'] },
  DL: { leadership_role: 'DL', app_role: 'MISSIONARY', additional_roles: [] },
  ZL: { leadership_role: 'ZL', app_role: 'MISSIONARY', additional_roles: [] },
  STL: { leadership_role: 'STL', app_role: 'MISSIONARY', additional_roles: [] },
  OFFICE: { leadership_role: null, app_role: 'OFFICE', additional_roles: [] },
  MISSIONARY: { leadership_role: null, app_role: 'MISSIONARY', additional_roles: [] },
};
function signedIn(who) {
  const w = world();
  vm.runInContext('currentUserContext = ctx; applyRoleNavigation(ctx);', Object.assign(w, { ctx: { user_id: 'u-' + who, display_name: 'Test', ...PEOPLE[who] } }));
  return w;
}

(async () => {
  assert.ok(/<script src="\/portal-enhancements\.js\?v=\d+"><\/script>/.test(template), 'index.template.html loads portal-enhancements.js with a version number');
  for (const who of ['AP', 'PRESIDENT', 'DL + Data Analyst']) {
    const w = signedIn(who);
    assert.equal(w.log.visible.navWhiteboard, true, who + ' sees Whiteboard');
    assert.equal(vm.runInContext('URLS.whiteboard', w), '/whiteboard/');
    assert.equal(vm.runInContext('TITLES.whiteboard', w), 'Whiteboard');
    assert.equal(vm.runInContext('portalPresentationsUrl()', w), PORTAL + ':3030', 'the page learns the Presentations address');
    vm.runInContext("openPage('whiteboard')", w);
    for (let i = 0; i < 4; i++) await settle();
    assert.deepEqual(w.log.opened.map(o => o.url), ['/whiteboard/'], who + ' opens /whiteboard/');
    assert.equal(w.byId('pageTitle').textContent, 'Whiteboard');
  }
  for (const who of ['DL', 'ZL', 'STL', 'OFFICE', 'MISSIONARY']) {
    const w = signedIn(who);
    assert.equal(w.log.visible.navWhiteboard, false, who + ' does not see Whiteboard');
    vm.runInContext("openPage('whiteboard')", w);
    for (let i = 0; i < 4; i++) await settle();
    assert.ok(!w.log.opened.some(o => o.name === 'whiteboard' || o.url === '/whiteboard/'), who + ' cannot open the Whiteboard through the shell');
  }
  // The label follows the portal language like the other menu entries: i18n.js shows the English menu word in the
  // chosen language (catalog key nav.whiteboard).
  assert.match(source, /menuButton\('navWhiteboard', 'Whiteboard', 'whiteboard'/);
  const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'i18n', 'en.json'), 'utf8'));
  assert.equal(catalog['nav.whiteboard'], 'Whiteboard');
  console.log('whiteboard: shell checks passed (managers see and open it, others do not, versioned shell, Presentations address)');
})().catch(error => { console.error(error); process.exit(1); });
