// Public-domain change (30 Sep 2026): the portal on https://example.org (the Cloudflare tunnel, which
// carries only port 8070) and on the office addresses (localhost, 192.168.1.20:8070).
//   - The template's address lines: Supabase on port 18000 on the office addresses, on the portal's own address on the
//     public one (nginx.conf passes the sign-in on); look-alike host names are not the public address.
//   - The shell (portal-enhancements.js) on the public address: Dashboards open
//     https://dashboards.example.org (a Cloudflare route to 8088, round 10 public-dashboards.md)
//     with the Dashboards sign-in, its renewal and its sign-out, as on the LAN. Since round 10 (public-everything.md)
//     Presentations open at https://presentations. (3030; its decks at https://decks., 8089) with their sign-in and
//     sign-out, and DA Management at https://management. (8090). No request goes to a port. On the office addresses
//     they open as before.
//   - nginx.conf passes on only the sign-in routes the pages use; office-only.html is a plain, translated page.
// Runs the real files in a Node vm with the same stand-in page as portal-menu-check.cjs.
// Run: node portal/tests/public-domain-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const source = read('portal-enhancements.js');
const template = read('index.template.html');
const nginx = read('nginx.conf');
const officeOnly = read('office-only.html');

function world({ hostname, protocol = 'http:', port = '' }) {
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
  const origin = protocol + '//' + hostname + (port ? ':' + port : '');
  const location = { hash: '#overview', origin, protocol, hostname, port, href: origin + '/', pathname: '/', search: '' };
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
      if (/(:3030|\/\/presentations\.example\.org)\/api\/session$/.test(String(url))) return { ok: true, status: 200, json: async () => ({ expires_at: new Date(Date.now() + 600000).toISOString() }) };
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
  // The template's own address lines (PORTAL_PUBLIC_SITE, PORTAL_HOST, SUPABASE_URL), as they are in the file.
  const addresses = template.match(/const PUBLIC_DOMAIN = [^\n]*\nconst PORTAL_PUBLIC_SITE = [^\n]*\nconst PORTAL_HOST = [^\n]*\nconst SUPABASE_URL = [^\n]*/)[0];
  const urls = template.match(/const URLS = \{[\s\S]*?\n\};/)[0];
  const titles = template.match(/const TITLES = \{[\s\S]*?\n\};/)[0];
  vm.runInContext(`
    ${addresses}
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

const settle = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise(resolve => setImmediate(resolve)); };
const AP = { user_id: 'u-ap', additional_roles: [], display_name: 'Test person', app_role: 'AP', leadership_role: 'AP' };
let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };
const eq = (a, b, message) => { assert.deepEqual(JSON.parse(JSON.stringify(a)), b, message); passed++; };
const PUBLIC = 'example.org';
const DASHBOARDS = 'https://dashboards.example.org';
const PRESENTATIONS = 'https://presentations.example.org';
const DECKS = 'https://decks.example.org';
const MANAGEMENT = 'https://management.example.org';
const otherPort = url => /^https?:\/\/[^/]+:\d+/.test(url);

function signInAs(w, person) {
  vm.runInContext('currentUserContext = ctx; applyRoleNavigation(ctx);', Object.assign(w, { ctx: person }));
}

async function open(w, page) {
  w.log.fetches.length = 0;
  w.log.opened.length = 0;
  vm.runInContext(`openPage(${JSON.stringify(page)})`, w);
  await settle();
  return { fetches: w.log.fetches.map(f => f.url), opened: w.log.opened.map(o => o.name), src: w.byId('appFrame').src };
}

(async () => {
  // ---- The template's addresses ----------------------------------------------------------------------------------
  const addresses = template.match(/const PUBLIC_DOMAIN = [^\n]*\nconst PORTAL_PUBLIC_SITE = [^\n]*\nconst PORTAL_HOST = [^\n]*\nconst SUPABASE_URL = [^\n]*/)[0];
  const supabaseFor = (protocol, hostname, port = '') => {
    const origin = protocol + '//' + hostname + (port ? ':' + port : '');
    return vm.runInNewContext(addresses + '\n;[PORTAL_PUBLIC_SITE, SUPABASE_URL]', { location: { protocol, hostname, port, origin }, window: { GFM_SITE: { publicDomain: PUBLIC } } });
  };
  eq(supabaseFor('http:', 'localhost', '8070'), [false, 'http://localhost:18000'], 'localhost:8070: Supabase on port 18000 as before');
  eq(supabaseFor('http:', '192.168.1.20', '8070'), [false, 'http://192.168.1.20:18000'], 'the LAN address: Supabase on port 18000 as before');
  eq(supabaseFor('http:', '127.0.0.1', '8070'), [false, 'http://127.0.0.1:18000'], '127.0.0.1: port 18000 as before');
  eq(supabaseFor('https:', PUBLIC), [true, 'https://' + PUBLIC], 'the public address: Supabase through the portal itself');
  eq(supabaseFor('https:', 'www.' + PUBLIC), [true, 'https://www.' + PUBLIC], 'www.: the same');
  eq(supabaseFor('https:', 'WWW.Example.ORG'), [true, 'https://WWW.Example.ORG'], 'the host name in any case');
  for (const lookalike of ['evil-' + PUBLIC, PUBLIC + '.example.com', 'example.org.evil', 'xexample.org']) {
    eq(supabaseFor('https:', lookalike)[0], false, `${lookalike} is not the public address`);
  }

  // The public domain is a setting (site-config.js): without one nothing is public, and another mission has its own domain.
  const withDomain = (domain, protocol, hostname) => vm.runInNewContext(addresses + '\n;[PORTAL_PUBLIC_SITE, SUPABASE_URL]',
    { location: { protocol, hostname, port: '', origin: protocol + '//' + hostname }, window: { GFM_SITE: { publicDomain: domain } } });
  eq(withDomain('', 'https:', PUBLIC)[0], false, 'no public domain set: even Frankfurt\'s name is an ordinary host');
  eq(withDomain(undefined, 'https:', PUBLIC)[0], false, 'no site-config.js value at all: no public address');
  eq(withDomain('other-mission.example', 'https:', 'www.other-mission.example'), [true, 'https://www.other-mission.example'], 'another mission has its own domain: Supabase through the portal itself');
  eq(withDomain('other-mission.example', 'https:', PUBLIC)[0], false, 'another mission has its own domain: this one is not public there');

  // Round 10: the deck address (the frame's "allow" list) per host.
  const decksLine = template.match(/const PRESENTATION_DECKS = [^\n]*/)[0];
  const decksFor = (protocol, hostname) => vm.runInNewContext(`${addresses}\n${decksLine}\n;PRESENTATION_DECKS`, { location: { protocol, hostname, port: '', origin: protocol + '//' + hostname }, window: { GFM_SITE: { publicDomain: PUBLIC } } });
  eq(decksFor('https:', PUBLIC), DECKS, 'the deck address on the public address: ' + DECKS);
  eq(decksFor('https:', 'www.' + PUBLIC), DECKS, 'www.: the same');
  eq(decksFor('http:', '192.168.1.20'), 'http://192.168.1.20:8089', 'the office address: port 8089 as before');

  // ---- The shell on the office addresses: nothing changes --------------------------------------------------------
  for (const [protocol, hostname, port] of [['http:', 'localhost', '8070'], ['http:', '192.168.1.20', '8070']]) {
    const w = world({ protocol, hostname, port });
    signInAs(w, AP);
    const dashboards = await open(w, 'insights');
    ok(dashboards.fetches.some(url => url.endsWith('/api/dataease/session')), `${hostname}: Dashboards signs in to DataEase`);
    eq(dashboards.opened, ['insights'], `${hostname}: Dashboards opens DataEase`);
    ok(dashboards.src.startsWith(`${protocol}//${hostname}:8088/gfm-start`), `${hostname}: ... on port 8088`);
    const presentations = await open(w, 'presentations');
    ok(presentations.fetches.includes(`${protocol}//${hostname}:3030/api/session`), `${hostname}: Presentations signs in on port 3030`);
    eq(presentations.opened, ['presentations'], `${hostname}: Presentations opens`);
    const management = await open(w, 'management');
    eq(management.opened, ['management'], `${hostname}: DA Management opens`);
    ok(management.src === `${protocol}//${hostname}:8090/`, `${hostname}: ... on port 8090`);
    w.log.fetches.length = 0;
    for (const fn of w.log.listeners['logoutButton:click'] || []) fn({ target: w.byId('logoutButton') });
    await settle();
    ok(w.log.fetches.some(f => f.url === `${protocol}//${hostname}:8090/logout`), `${hostname}: Sign Out also ends DA Management`);
    ok(w.log.fetches.some(f => f.url === `${protocol}//${hostname}:3030/api/logout`), `${hostname}: ... and Presentations`);
    ok(w.log.fetches.some(f => f.url === `${protocol}//${hostname}:8088/gfm-signout`), `${hostname}: ... and Dashboards`);
  }

  // ---- The shell on the public address ---------------------------------------------------------------------------
  for (const hostname of [PUBLIC, 'www.' + PUBLIC]) {
    const w = world({ protocol: 'https:', hostname });
    ok(vm.runInContext('SUPABASE_URL', w) === 'https://' + hostname, `${hostname}: the shell's Supabase address is the portal's own`);
    signInAs(w, AP);
    const dashboards = await open(w, 'insights');
    ok(dashboards.fetches.includes('/api/dataease/session'), `${hostname}: Dashboards sign in through the portal's own address`);
    eq(dashboards.opened, ['insights'], `${hostname}: Dashboards open DataEase`);
    ok(dashboards.src.startsWith(DASHBOARDS + '/gfm-start?gfmLang='), `${hostname}: ... at ${DASHBOARDS}/gfm-start`);
    eq(dashboards.fetches.filter(otherPort), [], `${hostname}: Dashboards: no request to another port`);
    ok(!String(dashboards.src).includes('portal_token'), `${hostname}: Dashboards: no sign-in token in the address`);
    ok(w.log.timers.some(t => t.ms === 600000), `${hostname}: Dashboards: the sign-in is renewed while they are open`);
    // DataEase's "Please open Dashboards" page in the frame asks for a renewal: answered only for the public name.
    const renewals = () => w.log.fetches.filter(f => f.url === '/api/dataease/session').length;
    const frameWindow = w.byId('appFrame').contentWindow;
    for (const [origin, answered] of [[DASHBOARDS, true], ['https://evil.example', false], ['http://' + hostname + ':8088', false]]) {
      const before = renewals();
      for (const fn of w.log.listeners['window:message'] || []) fn({ origin, source: frameWindow, data: { type: 'dataease-session-request' } });
      await settle();
      eq(renewals() > before, answered, `${hostname}: a renewal asked by ${origin}: ${answered ? 'answered' : 'ignored'}`);
    }
    ok(w.log.messages.some(m => m.origin === DASHBOARDS && m.message.type === 'dataease-session-refreshed'), `${hostname}: ... and the answer goes only to ${DASHBOARDS}`);
    // Round 10: Presentations and DA Management open at their own public names, like Dashboards.
    const presentations = await open(w, 'presentations');
    eq(presentations.opened, ['presentations'], `${hostname}: Presentations open their program`);
    ok(presentations.src === PRESENTATIONS, `${hostname}: ... at ${PRESENTATIONS}`);
    ok(presentations.fetches.includes(PRESENTATIONS + '/api/session'), `${hostname}: Presentations sign in at ${PRESENTATIONS}/api/session`);
    eq(presentations.fetches.filter(otherPort), [], `${hostname}: Presentations: no request to another port`);
    ok(!String(presentations.src).includes('portal_token'), `${hostname}: Presentations: no sign-in token in the address`);
    eq(vm.runInContext('portalPresentationsUrl()', w), PRESENTATIONS, `${hostname}: the Whiteboard gets ${PRESENTATIONS}`);
    const management = await open(w, 'management');
    eq(management.opened, ['management'], `${hostname}: DA Management opens its program`);
    ok(management.src === MANAGEMENT + '/', `${hostname}: ... at ${MANAGEMENT}/`);
    eq(management.fetches.filter(otherPort), [], `${hostname}: DA Management: no request to another port`);
    for (const [page, name] of [['presentations', 'Presentations'], ['management', 'DA Management']]) {
      eq(vm.runInContext('TITLES[' + JSON.stringify(page) + ']', w), name, `${hostname}: ${name}: the header keeps its name`);
    }
    for (const page of ['overview', 'planning', 'calendar', 'callins', 'whiteboard', 'archetypes']) {
      const result = await open(w, page);
      eq(result.opened, [page], `${hostname}: ${page} opens as before`);
    }
    w.log.fetches.length = 0;
    for (const fn of w.log.listeners['logoutButton:click'] || []) fn({ target: w.byId('logoutButton') });
    await settle();
    eq(w.log.fetches.map(f => f.url).filter(otherPort), [], `${hostname}: Sign Out sends nothing to another port`);
    ok(w.log.fetches.some(f => f.url === DASHBOARDS + '/gfm-signout'), `${hostname}: Sign Out ends Dashboards at ${DASHBOARDS}/gfm-signout`);
    ok(w.log.fetches.some(f => f.url === PRESENTATIONS + '/api/logout'), `${hostname}: ... Presentations at ${PRESENTATIONS}/api/logout`);
    ok(w.log.fetches.some(f => f.url === MANAGEMENT + '/logout'), `${hostname}: ... and DA Management at ${MANAGEMENT}/logout`);
    // A person who may not open Dashboards: a leftover Dashboards cookie is cleared at the public name, and nothing
    // goes to port 8088.
    const dl = world({ protocol: 'https:', hostname });
    signInAs(dl, { ...AP, app_role: 'MISSIONARY', leadership_role: 'DL' });
    await settle();
    eq(dl.log.fetches.map(f => f.url).filter(otherPort), [], `${hostname}: a DL's sign-in sends nothing to another port`);
    ok(dl.log.fetches.some(f => f.url === DASHBOARDS + '/gfm-signout'), `${hostname}: ... and clears a leftover Dashboards cookie`);
    const dlDashboards = await open(dl, 'insights');
    eq(dlDashboards.opened, ['overview'], `${hostname}: a DL asking for Dashboards still gets the Overview`);
  }

  // ---- nginx.conf ------------------------------------------------------------------------------------------------
  const conf = nginx.replace(/^\s*#.*$/gm, '');
  ok(/location ~ \^\/auth\/v1\/\(token\|user\|logout\|verify\|health\)\$ \{/.test(conf), 'nginx: only token, user, logout, verify and health of /auth/v1/');
  ok(/location = \/rest\/v1\/current_user_context \{[^}]*limit_except GET \{ deny all; \}[^}]*if \(\$args != "select=\*"\) \{ return 403; \}/.test(conf),
    'nginx: /rest/v1/ only current_user_context, read only, exactly ?select=*');
  ok(/location \/auth\/v1\/ \{[^}]*return 403/.test(conf) && /location \/rest\/v1\/ \{[^}]*return 403/.test(conf), 'nginx: every other Supabase route is refused');
  eq((conf.match(/gfm-beta-supabase-kong-1:8000/g) || []).length, 2, 'nginx: the Beta Kong, in the two places only');
  ok(!/\$request_uri/.test(conf.split('location ~ ^/auth/v1/')[1].split('location /auth/v1/')[0]), 'nginx: Kong gets the checked path, not the raw address');
  ok(!/storage\/v1|realtime\/v1|functions\/v1|graphql\/v1|\/pg\/|:13000|:3000|supabase-studio|supabase-db|:5432/.test(conf), 'nginx: no storage, realtime, functions, Studio or database');

  // ---- office-only.html ------------------------------------------------------------------------------------------
  ok(/<script src="i18n.js\?v=\d+"><\/script>/.test(officeOnly), 'office-only.html is translated (i18n.js)');
  ok(!/<script[^>]+src="https?:/.test(officeOnly) && !/fetch\(/.test(officeOnly), 'office-only.html loads nothing from elsewhere and asks nothing');
  ok(/event\.origin !== location\.origin/.test(officeOnly), 'office-only.html takes the theme only from the portal');
  for (const language of ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar']) {
    const catalog = JSON.parse(read(`i18n/${language}.json`));
    ok(['officeOnly.eyebrow', 'officeOnly.intro', 'officeOnly.howTo'].every(key => catalog[key]), `office-only.html in ${language}`);
  }

  console.log(`public domain: ${passed} checks passed (Supabase address per host, Dashboards, Presentations and DA Management at their public names, nothing changes on the office addresses, nginx routes)`);
})().catch(error => { console.error(error); process.exit(1); });
