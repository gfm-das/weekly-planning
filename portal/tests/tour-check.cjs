// Round 13: the guided tour (portal/tour.js, tour.css). Runs the real tour.js in a Node vm with a small stand-in page
// and checks: the steps each role gets (the menu decides, the tour only reads it), the English fallback against
// en.json, every text of every step in all 14 catalogs, the memory ("done" per person; a browser without storage keeps
// working), the card (Next, Back, Skip, Done, Esc, arrow keys, right to left, phone drawer), and that the shell loads
// the script and the style and offers the tour once.
// Run: node portal/tests/tour-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..', '..');
const read = file => fs.readFileSync(path.join(ROOT, file), 'utf8');
const CODES = ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar'];
const catalogs = Object.fromEntries(CODES.map(code => [code, JSON.parse(read(`portal/i18n/${code}.json`))]));
let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };
const eq = (actual, expected, message) => { assert.deepEqual(actual, expected, message); passed++; };

// ---- A stand-in page ------------------------------------------------------------------------------------------
function fakeElement(tag, id) {
  const listeners = {};
  const classes = new Set();
  const self = {
    tag, id: id || '', children: [], parent: null, style: {}, hidden: false, textContent: '', attributes: {}, type: '',
    offsetWidth: 100, offsetHeight: 30, rect: { top: 100, left: 20, right: 220, bottom: 140, width: 200, height: 40 },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) },
    set className(value) { classes.clear(); String(value).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
    get className() { return [...classes].join(' '); },
    append(...nodes) { for (const n of nodes) { n.parent = self; self.children.push(n); } },
    remove() { if (self.parent) self.parent.children = self.parent.children.filter(c => c !== self); self.parent = null; },
    setAttribute(k, v) { self.attributes[k] = String(v); },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    removeEventListener(type, fn) { listeners[type] = (listeners[type] || []).filter(f => f !== fn); },
    click() { (listeners.click || []).forEach(fn => fn({})); },
    focus() { self.focused = true; },
    scrollIntoView() {},
    getBoundingClientRect: () => self.rect,
    getClientRects: () => (self.hidden || self.offsetWidth === 0 ? [] : [self.rect]),
    listeners,
  };
  return self;
}

// menuVisible: the ids of the entries that show for this person (the menu decides; see portal-menu-check.cjs).
function page({ menuVisible, rtl = false, phone = false, storage = 'ok', innerWidth = 1280 } = {}) {
  const byId = new Map(), bySelector = new Map(), keyListeners = [];
  const get = id => { if (!byId.has(id)) byId.set(id, fakeElement('div', id)); return byId.get(id); };
  const SELECTORS = {
    '#groupWeekly': 'groupWeekly', '#navPlanning': 'navPlanning', '#navCallIns': 'navCallIns', '#navOverview': 'navOverview',
    '#groupInformation': 'groupInformation', '#navCalendar': 'navCalendar', '#navAnnouncements': 'navAnnouncements',
    '#navWhiteboard': 'navWhiteboard', '#insightsGroupTitle': 'insightsGroupTitle', '#navInsights': 'navInsights',
    '#navArchetypes': 'navArchetypes', '#navVollzogen': 'navVollzogen', '#navPresentations': 'navPresentations', '#managerGroupTitle': 'managerGroupTitle',
    '.portal-language': 'portalLanguage', '#portalCustomize': 'portalCustomize', '#portalTourButton': 'portalTourButton',
  };
  const always = ['groupWeekly', 'navPlanning', 'navOverview', 'groupInformation', 'navCalendar', 'navAnnouncements', 'portalLanguage', 'portalCustomize', 'portalTourButton'];
  const shown = new Set([...always, ...menuVisible]);
  for (const [selector, id] of Object.entries(SELECTORS)) {
    const element = get(id);
    if (!shown.has(id)) { element.hidden = true; element.offsetWidth = 0; element.offsetHeight = 0; }
    bySelector.set(selector, element);
  }
  const body = fakeElement('body');
  const store = new Map();
  const storageApi = storage === 'ok'
    ? { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) }
    : { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  const documentElement = { dir: rtl ? 'rtl' : 'ltr' };
  const timers = [];
  const win = {
    innerWidth, innerHeight: 800, MissionI18n: null,
    matchMedia: () => ({ matches: phone }),
    addEventListener() {}, removeEventListener() {},
  };
  const context = {
    window: win, console, Promise, Date, Math, JSON, Set, Map, Object, Array, String, Number, Error,
    localStorage: storageApi,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    document: {
      body, documentElement,
      createElement: tag => fakeElement(tag),
      querySelector: selector => bySelector.get(selector) || null,
      getElementById: id => byId.get(id) || null,
      addEventListener: (type, fn) => { if (type === 'keydown') keyListeners.push(fn); },
      removeEventListener: (type, fn) => { const i = keyListeners.indexOf(fn); if (i >= 0) keyListeners.splice(i, 1); },
    },
  };
  win.window = win;
  vm.createContext(context);
  vm.runInContext(read('portal/tour.js'), context, { filename: 'tour.js' });
  const tour = context.window.GfmTour;
  const press = key => { const event = { key, preventDefault() {}, stopPropagation() {} }; [...keyListeners].forEach(fn => fn(event)); };
  const root = () => body.children[0];
  const find = cls => { const walk = n => (n.classList.contains(cls) ? n : n.children.map(walk).find(Boolean)); return walk(root()); };
  return { tour, get, body, store, timers, press, root, find, win, documentElement, keyListeners };
}

// ---- 1. The steps each role gets ------------------------------------------------------------------------------
// The menu entries each person sees (portal-menu-check.cjs): Call-ins for managers, DL, ZL; Presentations also for STL;
// the rest for managers only.
const MANAGER_ONLY = ['navWhiteboard', 'insightsGroupTitle', 'navInsights', 'navArchetypes', 'navVollzogen', 'navPresentations', 'managerGroupTitle', 'navCallIns'];
const PEOPLE = {
  missionary: { roles: ['MISSIONARY'], menu: [] },
  stl: { roles: ['STL'], menu: ['navPresentations', 'insightsGroupTitle'] },
  dl: { roles: ['DL'], menu: ['navCallIns', 'navPresentations', 'insightsGroupTitle'] },
  zl: { roles: ['ZL'], menu: ['navCallIns', 'navPresentations', 'insightsGroupTitle'] },
  // Office is not a manager: it sees the Insights heading and Vollzogen, nothing else of Insights.
  office: { roles: ['OFFICE'], menu: ['insightsGroupTitle', 'navVollzogen'] },
  missionaryOffice: { roles: ['MISSIONARY', 'OFFICE'], menu: ['insightsGroupTitle', 'navVollzogen'] },
  ap: { roles: ['AP'], menu: MANAGER_ONLY },
  president: { roles: ['PRESIDENT'], menu: MANAGER_ONLY },
  dataAdmin: { roles: ['DATA_ADMIN'], menu: MANAGER_ONLY },
  dlDataAdmin: { roles: ['DL', 'DATA_ADMIN'], menu: MANAGER_ONLY },
};
const ids = who => { const p = page({ menuVisible: PEOPLE[who].menu }); return [...p.tour.stepsFor([...PEOPLE[who].roles]).map(s => s.id)]; };
const BASE = ['welcome', 'weekly', 'planning', 'overview', 'information', 'calendar', 'announcements', 'language', 'customize', 'tour'];
eq(ids('missionary'), BASE, 'missionary: weekly, information, no call-ins, no insights, no manager tools');
eq(ids('stl'), ['welcome', 'weekly', 'planning', 'overview', 'information', 'calendar', 'announcements', 'insights', 'presentations', 'language', 'customize', 'tour'], 'STL: presentations, no call-ins');
for (const who of ['dl', 'zl']) {
  eq(ids(who), ['welcome', 'weekly', 'planning', 'callins', 'overview', 'information', 'calendar', 'announcements', 'insights', 'presentations', 'language', 'customize', 'tour'], who + ': call-ins and presentations');
}
for (const who of ['office', 'missionaryOffice']) {
  eq(ids(who), ['welcome', 'weekly', 'planning', 'overview', 'information', 'calendar', 'announcements', 'office', 'insights', 'vollzogen', 'language', 'customize', 'tour'], who + ': the Office step after announcements, then Insights with only Vollzogen');
}
const MANAGER_STEPS = ['welcome', 'weekly', 'planning', 'callins', 'overview', 'information', 'calendar', 'announcements', 'whiteboard', 'insights', 'dashboards', 'archetypes', 'vollzogen', 'presentations', 'manager', 'language', 'customize', 'tour'];
// Dashboards hang on #navInsights; the fake page has no "dashboards" id, so check the manager list below by the menu.
for (const who of ['ap', 'president', 'dataAdmin', 'dlDataAdmin']) {
  const got = ids(who);
  ok(got.includes('whiteboard') && got.includes('manager') && got.includes('archetypes') && got.includes('callins'), who + ': manager steps');
  ok(!got.includes('office'), who + ': no Office step');
  eq(got.filter(id => !['dashboards'].includes(id)), MANAGER_STEPS.filter(id => id !== 'dashboards'), who + ': the manager order');
}
{
  // A step whose part is not on screen is left out, whatever the role.
  const p = page({ menuVisible: [] });
  const withoutLanguage = p.tour.stepsFor(['MISSIONARY']).map(s => s.id);
  p.get('portalLanguage').hidden = true;
  ok(withoutLanguage.includes('language') && !p.tour.stepsFor(['MISSIONARY']).some(s => s.id === 'language'), 'the language step goes while the list is hidden');
  eq(p.tour.kindOf(['MISSIONARY']), 'missionary', 'kind missionary');
  eq(p.tour.kindOf(['DL']), 'leader', 'kind leader');
  eq(p.tour.kindOf(['MISSIONARY', 'OFFICE']), 'office', 'kind office');
  eq(p.tour.kindOf(['DL', 'DATA_ADMIN']), 'manager', 'kind manager');
  eq(p.tour.kindOf([]), 'missionary', 'no roles: missionary');
  const welcome = kind => p.tour.stepsFor({ missionary: ['MISSIONARY'], leader: ['ZL'], office: ['OFFICE'], manager: ['AP'] }[kind])[0].text;
  eq(['missionary', 'leader', 'office', 'manager'].map(welcome), ['tour.welcomeMissionary', 'tour.welcomeLeader', 'tour.welcomeOffice', 'tour.welcomeManager'], 'welcome text per kind');
}

// ---- 2. Texts: the English fallback and 14 catalogs ------------------------------------------------------------
{
  const { tour } = page({ menuVisible: MANAGER_ONLY });
  const keys = new Set(['tour.button', 'tour.buttonHelp', 'tour.label', 'tour.next', 'tour.back', 'tour.skip', 'tour.done', 'tour.step']);
  for (const step of tour.STEPS) {
    keys.add(step.title);
    for (const kind of ['missionary', 'leader', 'office', 'manager']) keys.add(step.text(kind));
  }
  for (const key of keys) {
    ok(tour.EN[key] === catalogs.en[key], `tour.js English fallback = en.json for ${key}`);
    for (const code of CODES) ok(typeof catalogs[code][key] === 'string' && catalogs[code][key].trim(), `${code} has ${key}`);
  }
  for (const key of Object.keys(tour.EN)) ok(key in catalogs.en, 'every fallback text has its key: ' + key);
  for (const code of CODES.filter(c => c !== 'en')) {
    ok(catalogs[code]['tour.step'].includes('{n}') && catalogs[code]['tour.step'].includes('{total}'), code + ': "Step {n} of {total}" keeps both values');
    ok(catalogs[code]['tour.welcomeTitle'] !== catalogs.en['tour.welcomeTitle'], code + ': the welcome title is translated');
  }
  eq(tour.say('tour.step', { n: 2, total: 9 }), 'Step 2 of 9', 'say() fills the values (fallback)');
}

// ---- 3. The memory --------------------------------------------------------------------------------------------
{
  const p = page({ menuVisible: [] });
  eq(p.tour.isDone('u1'), false, 'new person: not done');
  eq(p.tour.offerOnce(['MISSIONARY'], 'u1', 0), true, 'first sign-in: offered');
  eq(p.tour.isDone('u1'), true, 'marked at once');
  eq(p.tour.offerOnce(['MISSIONARY'], 'u1', 0), false, 'second sign-in: not offered again');
  eq(p.tour.offerOnce(['MISSIONARY'], 'u2', 0), true, 'another person on the same device is offered');
  eq(p.timers.length, 2, 'the offer waits for a moment (a timer), it does not start inside the sign-in');
  p.timers[0].fn();
  ok(p.root() && p.root().classList.contains('tour-root'), 'the offered tour opens');
  const blocked = page({ menuVisible: [], storage: 'blocked' });
  eq(blocked.tour.isDone('u1'), false, 'blocked storage: no error, not done');
  eq(blocked.tour.markDone('u1'), false, 'blocked storage: marking says no, does not throw');
  eq(blocked.tour.offerOnce(['MISSIONARY'], 'u1', 0), true, 'blocked storage: still offered');
}

// ---- 4. The card ----------------------------------------------------------------------------------------------
{
  const p = page({ menuVisible: [] });
  eq(p.tour.start(['MISSIONARY'], 'u1'), true, 'start');
  const total = BASE.length;
  eq(p.find('tour-count').textContent, `Step 1 of ${total}`, 'step counter');
  ok(p.find('tour-back').hidden, 'no Back on the first step');
  ok(p.root().attributes['aria-label'] === 'Guided tour' && p.root().attributes.role === 'dialog', 'a labelled dialog');
  eq(p.find('tour-title').textContent, 'Welcome to the portal', 'welcome title');
  ok(p.find('tour-spot').hidden, 'the welcome step lights nothing and sits in the middle');
  p.find('tour-next').click();
  eq(p.find('tour-title').textContent, 'WEEKLY', 'step 2 is the Weekly section');
  ok(!p.find('tour-back').hidden, 'Back from step 2');
  ok(!p.find('tour-spot').hidden, 'a part is lit');
  eq(p.find('tour-spot').style.top, '94px', 'the spotlight surrounds the part (6px)');
  p.find('tour-back').click();
  eq(p.find('tour-count').textContent, `Step 1 of ${total}`, 'Back');
  p.press('ArrowRight');
  eq(p.find('tour-count').textContent, `Step 2 of ${total}`, 'arrow key: next');
  p.press('ArrowLeft');
  eq(p.find('tour-count').textContent, `Step 1 of ${total}`, 'arrow key: back');
  for (let i = 1; i < total; i++) p.find('tour-next').click();
  eq(p.find('tour-next').textContent, 'Done', 'the last step says Done');
  ok(p.find('tour-skip').hidden, 'no Skip on the last step');
  p.find('tour-next').click();
  eq(p.body.children.length, 0, 'Done closes the tour');
  eq(p.tour.isDone('u1'), true, 'Done is remembered');
  eq(p.keyListeners.length, 0, 'the key listener is gone');

  const q = page({ menuVisible: [] });
  q.tour.start(['MISSIONARY'], 'u9');
  q.find('tour-skip').click();
  eq([q.body.children.length, q.tour.isDone('u9')], [0, true], 'Skip closes and remembers');
  q.tour.start(['MISSIONARY'], 'u9');
  q.press('Escape');
  eq(q.body.children.length, 0, 'Esc closes');
  eq(q.tour.start(['MISSIONARY'], 'u9') && q.tour.start(['MISSIONARY'], 'u9'), true, 'starting twice keeps one layer');
  eq(q.body.children.length, 1, 'one layer only');
}

// ---- 5. Right to left and phones ---------------------------------------------------------------------------------
{
  const ltr = page({ menuVisible: [] });
  ltr.tour.start(['MISSIONARY'], 'u1'); ltr.find('tour-next').click();
  ok(parseFloat(ltr.find('tour-card').style.left) > 220, 'left to right: the card is to the right of the menu entry');
  const rtl = page({ menuVisible: [], rtl: true });
  for (const name of ['groupWeekly']) { rtl.get(name).rect = { top: 100, left: 1000, right: 1260, bottom: 140, width: 260, height: 40 }; }
  rtl.tour.start(['MISSIONARY'], 'u1'); rtl.find('tour-next').click();
  ok(parseFloat(rtl.find('tour-card').style.left) + rtl.find('tour-card').offsetWidth <= 1000, 'right to left: the card is to the left of the menu entry');
  rtl.press('ArrowRight');
  eq(rtl.find('tour-count').textContent, 'Step 1 of ' + BASE.length, 'right to left: the right arrow goes back');

  const ph = page({ menuVisible: [], phone: true, innerWidth: 390 });
  const sidebar = ph.get('sidebar'), overlay = ph.get('overlay');
  ph.tour.start(['MISSIONARY'], 'u1');
  ok(!sidebar.classList.contains('open'), 'phone: the welcome step leaves the drawer closed');
  ph.find('tour-next').click();
  ok(sidebar.classList.contains('open') && overlay.classList.contains('open'), 'phone: a menu step opens the drawer');
  ok(ph.timers.length >= 1, 'phone: it measures again when the drawer has slid in');
  ph.press('Escape');
  ok(!sidebar.classList.contains('open') && !overlay.classList.contains('open'), 'phone: the drawer closes at the end');
}

// ---- 6. The shell loads it ---------------------------------------------------------------------------------------
{
  const template = read('portal/index.template.html');
  ok(/<link rel="stylesheet" href="\/tour\.css\?v=\d+">/.test(template), 'index.template.html loads tour.css');
  const tourAt = template.indexOf('<script src="/tour.js'), shellAt = template.indexOf('<script src="/portal-enhancements.js');
  ok(tourAt > 0 && tourAt < shellAt, 'tour.js loads before portal-enhancements.js');
  const shell = read('portal/portal-enhancements.js');
  ok(/settingsButton\('Tour'/.test(shell) && /portalTourButton/.test(shell) && /portalCustomize/.test(shell), 'the Settings menu has a Tour entry (round 14)');
  ok(/GfmTour\.offerOnce\(roles, currentPerson\)/.test(shell), 'the shell offers the tour once, after sign-in');
  ok(/GfmTour\.start\(currentRoles, currentPerson\)/.test(shell), 'the Tour button starts it');
  const css = read('portal/tour.css');
  for (const selector of ['.tour-root', '.tour-spot', '.tour-card', '@media (max-width: 780px)', 'margin-inline-start', 'text-align: start','prefers-reduced-motion']) ok(css.includes(selector), 'tour.css has ' + selector);
  ok(!/(^|\s)(left|right):\s*-?\d+px/.test(css.replace(/\.tour-card\.tour-center[\s\S]*?\}/, '')), 'tour.css uses logical sides (inset-inline, margin-inline) for text direction');
}

console.log(`tour: ${passed} checks passed (steps per role, texts in 14 languages, memory, card, right to left, phone, shell)`);
