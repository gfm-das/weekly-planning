// Round 6: the portal menu per role, old deep links, the managers' Overview with the mission glimpse, and what is
// gone (Appsmith's Beta pages and placeholders, Grafana; the "Alpha" names). Runs the real portal-enhancements.js in a
// Node vm with a stand-in for the page (the template's globals, a DOM that accepts anything, fetch and timers that
// record what happens), as dashboards-deck-check.cjs does, and reads the pages as text.
// Run: node portal/tests/portal-menu-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const source = read('portal-enhancements.js');
const template = read('index.template.html');
const home = read('home.html');
const glimpse = read('glimpse.js');
const glimpseCss = read('glimpse.css');
const planning = read('planning.html');
const PORTAL = 'http://portal.test';
const code = text => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/<!--[\s\S]*?-->/g, '');

function world() {
  const log = { fetches: [], opened: [], visible: {}, timers: [], listeners: {}, messages: [], created: [], texts: [] };
  const elements = new Map();
  function element(name) {
    const store = { style: {}, dataset: {}, hidden: false, textContent: '', value: '', options: [], children: [], id: name,
      nextSibling: null, nextElementSibling: null, previousSibling: null, firstChild: null, lastChild: null, offsetParent: null,
      classList: { add(c) { store.classes.add(c); }, remove(c) { store.classes.delete(c); }, toggle() {}, contains: c => store.classes.has(c) },
      classes: new Set(),
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
  const context = {
    console: { ...console, log() {}, warn() {} }, URL, URLSearchParams, Promise, Date, Math, JSON, Set, Map, Object, Array, String, Number, Error, RegExp, Symbol, AbortController, Intl,
    atob: s => Buffer.from(s, 'base64').toString('binary'), btoa: s => Buffer.from(s, 'binary').toString('base64'),
    document, location, localStorage: storage(), sessionStorage: storage(), navigator: { serviceWorker: undefined, language: 'en' },
    history: { replaceState() {} }, Notification: undefined, CustomEvent: class {}, Event: class {}, MutationObserver: class { observe() {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    addEventListener: (type, fn) => (log.listeners[`window:${type}`] ||= []).push(fn),
    setTimeout: (fn, ms) => { log.timers.push({ fn, ms }); return log.timers.length; }, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0,
    fetch: async (url, options = {}) => {
      log.fetches.push({ url: String(url), method: options.method || 'GET' });
      if (String(url).endsWith(':3030/api/session')) return { ok: true, status: 200, json: async () => ({ expires_at: new Date(Date.now() + 600000).toISOString() }) };
      return { ok: true, status: 200, json: async () => ({}) };
    },
    log, byId,
  };
  context.window = context;
  context.GFM_SITE = { publicDomain: 'example.org', timeZone: 'Europe/Berlin' };  // site-config.js: the mission's own settings
  context.self = context;
  document.getElementById = byId;
  document.createElement = tag => { const e = element(`new-${tag}`); log.created.push(e); return e; };
  document.createTextNode = text => { log.texts.push(text); return { text }; };
  document.head = element('head');
  document.body = element('body');
  document.documentElement = element('html');
  vm.createContext(context);
  // The template's own URLS and TITLES (read from index.template.html), then the shell itself. deepLink is the
  // template's start-up rule (showPortal): a requested page that is not allowed opens the Overview.
  const urls = template.match(/const URLS = \{[\s\S]*?\n\};/)[0];
  const titles = template.match(/const TITLES = \{[\s\S]*?\n\};/)[0];
  vm.runInContext(`
    const PORTAL_PUBLIC_SITE = false;
    const PORTAL_HOST = location.protocol + '//' + location.hostname;
    const SUPABASE_URL = PORTAL_HOST + ':18000';
    const SUPABASE_ANON_KEY = 'anon-test';
    ${urls}
    ${titles}
    const frame = document.getElementById('appFrame');
    const title = document.getElementById('pageTitle');
    const sidebar = document.getElementById('sidebar');
    let currentUserContext = null;
    let allowedPages = new Set(['planning']);
    function setVisible(id, visible) { log.visible[id] = visible; }
    function applyRoleNavigation(context) {}
    function closeMenu() {}
    function clearMissionSession() { currentUserContext = null; allowedPages = new Set(['planning']); }
    function showLogin() {}
    function ensureMissionSession() { return Promise.resolve('portal-token'); }
    function openPage(name) { log.opened.push({ name, url: URLS[name] }); frame.src = URLS[name]; title.textContent = TITLES[name]; location.hash = '#' + name; }
    function deepLink(hash) { const requested = hash.replace('#', ''); return requested && requested !== 'login' && allowedPages.has(requested) ? requested : 'overview'; }
  `, context);
  vm.runInContext(source, context, { filename: 'portal-enhancements.js' });
  return context;
}

const settle = async (n = 4) => { for (let i = 0; i < n; i++) await new Promise(resolve => setImmediate(resolve)); };
const PEOPLE = {
  MISSIONARY: { app_role: 'MISSIONARY', leadership_role: null },
  DL: { app_role: 'MISSIONARY', leadership_role: 'DL' },
  ZL: { app_role: 'MISSIONARY', leadership_role: 'ZL' },
  STL: { app_role: 'MISSIONARY', leadership_role: 'STL' },
  AP: { app_role: 'AP', leadership_role: 'AP' },
  PRESIDENT: { app_role: 'PRESIDENT', leadership_role: null },
  DATA_ADMIN: { app_role: 'DATA_ADMIN', leadership_role: null },
  'DL + Data Analyst': { app_role: 'MISSIONARY', leadership_role: 'DL', additional_roles: ['DATA_ADMIN'] },
  'STL + Data Analyst': { app_role: 'MISSIONARY', leadership_role: 'STL', additional_roles: ['DATA_ADMIN'] },
  'Missionary + Office': { app_role: 'MISSIONARY', leadership_role: null, additional_roles: ['OFFICE'] },
  OFFICE: { app_role: 'OFFICE', leadership_role: null },
};
// What each person may open (the menu shows the same entries; Overview, Weekly Planning, Calendar and Announcements
// are everyone's).
const BASE = ['overview', 'planning', 'calendar', 'announcements'];
// Whiteboard: round 6; Archetypal Health: APs, the President and Data Analysts.
const MANAGER = [...BASE, 'callins', 'insights', 'management', 'presentations', 'whiteboard', 'archetypes'];
const EXPECTED = {
  MISSIONARY: BASE, OFFICE: BASE, 'Missionary + Office': BASE,
  DL: [...BASE, 'callins', 'presentations'], ZL: [...BASE, 'callins', 'presentations'],
  STL: [...BASE, 'presentations'],
  AP: MANAGER, PRESIDENT: MANAGER, DATA_ADMIN: MANAGER, 'DL + Data Analyst': MANAGER, 'STL + Data Analyst': MANAGER,
};
const GLIMPSE_OVERVIEW = '/home.html?glimpse=1';

function signIn(w, who) {
  const c = { user_id: 'u-' + who, additional_roles: [], display_name: 'Test person', ...PEOPLE[who] };
  vm.runInContext('currentUserContext = ctx; applyRoleNavigation(ctx);', Object.assign(w, { ctx: c }));
  return [...vm.runInContext('allowedPages', w)].sort();
}

let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };
const plain = v => v === undefined ? v : JSON.parse(JSON.stringify(v));  // objects from the vm have another prototype
const eq = (a, b, message) => { assert.deepEqual(plain(a), plain(b), message); passed++; };

(async () => {
  // ---- What is gone ---------------------------------------------------------------------------------------------
  ok(/<script src="\/portal-enhancements\.js\?v=\d+"><\/script>/.test(template), 'index.template.html loads portal-enhancements.js with a version number');
  for (const [name, text] of [['index.template.html', code(template)], ['portal-enhancements.js', code(source)]]) {
    ok(!/:8080|planning_beta|callins_beta|navPlanningBeta|navCallInsBeta|- Beta|mission-planning-activity/.test(text), `${name}: no Appsmith Beta page, link or message`);
    ok(!/grafana/i.test(text), `${name}: no Grafana code`);
    // Superset's old port 8089 is the presentation address since round 8 (docs/handoff/round8/deckorigin.md): only as that.
    ok(!/superset|:8089|APPSMITH_|correlation|\bmmm\b/i.test(text.replace(/const PRESENTATION_DECKS =\s*(PORTAL_PUBLIC_SITE \? "https:\/\/decks." \+ PUBLIC_DOMAIN : )?PORTAL_HOST \+ ":8089";/, '')), `${name}: no Superset or Appsmith placeholder pages`);
    // Superset's old port 8088 is DataEase's since round 6 (docs/handoff/round6/dataease.md): only as its address.
    ok(!/:8088/.test(text.replace("const DATAEASE_ORIGIN = PUBLIC_SITE ? DASHBOARDS_PUBLIC_ORIGIN : PORTAL_HOST + ':8088';", '')), `${name}: :8088 only as DataEase's address`);
    ok(!/Alpha|Beta/.test(text), `${name}: no "Alpha" or "Beta" in any name`);
  }
  ok(!/legacyFormLink|Legacy form|data-port="8080"/.test(planning), 'Weekly Planning: no "Legacy form" link to Appsmith');
  ok(!fs.existsSync(path.join(__dirname, '../grafana-session.html')), 'grafana-session.html is gone');

  // ---- The menu per role -------------------------------------------------------------------------------------------
  for (const who of Object.keys(PEOPLE)) {
    const w = world();
    const allowed = signIn(w, who);
    eq(allowed, [...EXPECTED[who]].sort(), `${who}: pages offered`);
    const manager = EXPECTED[who].includes('insights');
    eq(w.log.visible.navInsights, manager, `${who}: Dashboards ${manager ? 'shown' : 'hidden'}`);
    eq(w.log.visible.navManagement, manager, `${who}: DA Management ${manager ? 'shown' : 'hidden'}`);
    eq(w.log.visible.navCallIns, EXPECTED[who].includes('callins'), `${who}: Call-ins`);
    eq(w.log.visible.navPresentations, EXPECTED[who].includes('presentations'), `${who}: Presentations`);
    eq(w.log.visible.navArchetypes, EXPECTED[who].includes('archetypes'), `${who}: Archetypal Health`);
    ok(!('navCallInsBeta' in w.log.visible), `${who}: no Call-ins - Beta entry is shown or hidden`);
    eq(w.log.created.map(e => e.dataset.page).filter(p => p && /beta/.test(p)), [], `${who}: no Beta menu entry is created`);
    eq(vm.runInContext('URLS.overview', w), manager ? GLIMPSE_OVERVIEW : '/home.html',
      `${who}: the Overview ${manager ? 'starts with the mission glimpse' : 'is the cards'}`);
  }

  // ---- The names -----------------------------------------------------------------------------------------------------
  const n = world();
  eq(vm.runInContext('[TITLES.planning, TITLES.callins, TITLES.overview, TITLES.insights]', n),
    ['Weekly Planning', 'Call-ins', 'Overview', 'Dashboards'], 'page titles: Weekly Planning, Call-ins (no "Alpha")');
  ok(/data-page="planning"[^>]*>Weekly Planning</.test(template) && /data-page="callins"[^>]*>Call-ins</.test(template),
    'menu: "Weekly Planning" and "Call-ins"');
  ok(!n.log.texts.some(t => /Alpha|Beta/.test(t)) && !/Alpha|Beta/.test(code(template)), 'menu: no "Alpha" or "Beta" label');
  // The menu is shown in the language by i18n.js, from the catalogs (the shell keeps no second list of menu words).
  const catalog = language => JSON.parse(read(`i18n/${language}.json`));
  const [en, de] = [catalog('en'), catalog('de')];
  const planningKey = Object.keys(en).find(key => en[key] === 'Weekly Planning');
  ok(planningKey && de[planningKey] === 'Wochenplanung', 'menu (de): "Weekly Planning" is "Wochenplanung"');
  ok(!/Wochenplanung/.test(source), 'the shell has no menu words of its own besides English');

  // ---- Old deep links ----------------------------------------------------------------------------------------------
  for (const who of ['MISSIONARY', 'DL', 'AP', 'PRESIDENT']) {
    const w = world();
    signIn(w, who);
    const own = EXPECTED[who].includes('insights') ? GLIMPSE_OVERVIEW : '/home.html';
    for (const old of ['#planning_beta', '#callins_beta', '#correlation', '#mmm', '#grafana', '#overview_cards']) {
      eq(vm.runInContext(`deepLink(${JSON.stringify(old)})`, w), 'overview', `${who}: ${old} opens the Overview`);
      w.log.opened.length = 0;
      vm.runInContext(`openPage(${JSON.stringify(old.slice(1))})`, w);
      await settle();
      eq(w.log.opened.map(o => o.name), ['overview'], `${who}: openPage('${old.slice(1)}') opens the Overview`);
      eq(w.log.opened[0].url, own, `${who}: ... their own Overview`);
    }
  }

  // ---- A manager's Overview, the glimpse's links, the next person on the device ------------------------------------
  const p = world();
  signIn(p, 'PRESIDENT');
  vm.runInContext("openPage('overview')", p);
  await settle();
  eq(p.log.opened.at(-1), { name: 'overview', url: GLIMPSE_OVERVIEW }, 'President: the Overview opens with the glimpse');
  eq(p.byId('pageTitle').textContent, 'Overview', 'President: the header says Overview');
  const openFromFrame = (w, page) => { for (const fn of w.log.listeners['window:message'] || []) fn({ origin: PORTAL, data: { type: 'gfm-open-page', page } }); };
  for (const page of ['insights', 'callins', 'planning']) {
    openFromFrame(p, page);
    await settle(6);
    eq(p.log.opened.at(-1).name, page, `President: a "${page}" link in the Overview opens it`);
  }
  const before = p.log.opened.length;
  openFromFrame(p, 'planning_beta');
  for (const fn of p.log.listeners['window:message'] || []) fn({ origin: 'http://portal.test:8080', data: { type: 'gfm-open-page', page: 'insights' } });
  for (const fn of p.log.listeners['window:message'] || []) fn({ origin: 'http://portal.test:8080', data: { type: 'mission-planning-activity' } });
  await settle(6);
  eq(p.log.opened.length, before, 'a page nobody has, another origin and the old Appsmith message open nothing');
  ok(!p.log.fetches.some(f => /planning\/activity/.test(f.url)), 'the old Appsmith activity message records nothing');
  vm.runInContext('clearMissionSession()', p);
  signIn(p, 'DL');
  eq(vm.runInContext('URLS.overview', p), '/home.html', 'the next person on the same device (a DL) gets the Overview without the glimpse');
  openFromFrame(p, 'insights');
  await settle(6);
  ok(p.log.opened.at(-1).name !== 'insights', 'DL: a Dashboards link from a page is ignored');
  vm.runInContext('clearMissionSession()', p);
  signIn(p, 'STL + Data Analyst');
  eq(vm.runInContext('URLS.overview', p), GLIMPSE_OVERVIEW, 'an STL who is also the Data Analyst gets the glimpse');

  // ---- Sign-out asks nothing of Grafana -----------------------------------------------------------------------------
  const sent = p.log.fetches.length;
  for (const fn of p.log.listeners['logoutButton:click'] || []) fn({ target: p.byId('logoutButton') });
  await settle();
  ok(!p.log.fetches.slice(sent).some(f => /grafana/.test(f.url)), 'sign-out asks nothing of Grafana');

  // ---- The Overview page and the glimpse (as text) --------------------------------------------------------------
  const at = text => home.indexOf(text);
  ok(at('<section id="glimpse" hidden') > at('<main class="wrap loading" id="overview">') && at('<section id="glimpse" hidden') < at('<section class="hero">'),
    'home.html: the glimpse sits at the top of the Overview, before the usual Overview, hidden until it is started');
  ok(at('<script src="glimpse.js"></script>') > 0 && at('<script src="glimpse.js"></script>') < at('<script src="portal-client.js"></script>'),
    'home.html: glimpse.js loads before portal-client.js (which takes ?glimpse=1 off the address)');
  ok(home.includes('<link rel="stylesheet" href="glimpse.css" />'), 'home.html: glimpse.css is linked');
  ok(/MissionGlimpse\?\.update\(\{ allowed: !!data\.glimpse, viewingArea: !!data\.viewing_area \}\)/.test(home),
    'home.html: /api/overview decides (the "glimpse" flag), and the glimpse steps aside for another area');
  ok(fs.existsSync(path.join(__dirname, '../echarts.min.js')) && /script\.src = 'echarts\.min\.js(\?v=[\w.]+)?'/.test(glimpse),
    'glimpse.js loads the vendored ECharts (portal/echarts.min.js) only when it starts');
  // nginx.conf lets browsers keep the two vendored libraries for a year, so each page asks for them by version.
  ok(/script\.src = 'echarts\.min\.js\?v=6\.0\.0'/.test(glimpse) && home.includes('<script src="Sortable.min.js?v=1.15.6"></script>'),
    'the vendored libraries are asked for with their version (ECharts 6.0.0, SortableJS 1.15.6)');
  ok(/portalAPI\('dashboard'/.test(glimpse) && !/portalAPI\('overview'/.test(glimpse), 'glimpse.js reads /api/dashboard only');
  ok(/get\('glimpse'\) === '1'/.test(glimpse), 'glimpse.js starts at once on ?glimpse=1');
  ok(/data-open="insights"/.test(glimpse), 'the glimpse links to Dashboards through the shell');
  ok(!/Friends found|friends found/i.test(code(glimpse)), 'the glimpse never says "Friends found"');
  ok(!/Below goal|furthest|failed to|missing|overdue|behind/i.test(code(glimpse)), 'no verdict words (Preach My Gospel wording)');
  ok(/\[data-theme="dark"\] #glimpse/.test(glimpseCss) && /\[data-theme="light"\] #glimpse/.test(glimpseCss), 'glimpse.css: light and dark');
  ok(/@media \(max-width: 760px\)/.test(glimpseCss) && /min-height: 44px/.test(glimpseCss), 'glimpse.css: phone layout with 44 px controls');
  console.log(`portal menu: ${passed} checks passed (menu per role, names, old deep links, the managers' glimpse, nothing retired left)`);
})().catch(error => { console.error(error); process.exit(1); });
