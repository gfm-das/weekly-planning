// Round 6: the mission glimpse's verdicts (portal/glimpse.js). "Goal reached" (green with a tick) must follow the
// numbers themselves, never a rounded percentage: 311 of a goal of 312 is 99.7%, and that is not reached. Runs the real
// glimpse.js in a Node vm with a small stand-in page (elements by id that keep their text and markup), a stand-in
// ECharts and a stand-in /api/dashboard answer, then reads the tiles, the summary and the table.
// Run: node portal/tests/glimpse-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'glimpse.js'), 'utf8');

const KEYS = [
  ['friends_found', 'New people being taught'],
  ['baptisms_confirmations', 'Baptisms and confirmations'],
  ['baptismal_dates', 'People with a baptismal date'],
  ['sacrament_attendance', 'Sacrament attendance'],
  ['members_at_lessons', 'Lessons with members'],
  ['new_member_sacrament', 'New members at sacrament meeting'],
];

// Two finished weeks; the second (the latest) has `figures` = {key: [actual, goal set the week before]}.
function answer(figures) {
  const week = (sunday, pairs) => {
    const actual = {}, previous = {};
    for (const [key] of KEYS) [actual[key], previous[key]] = pairs[key] || [null, null];
    const cell = { reports: 10, submitted: 9, actual, previous_goal: previous, goal: {} };
    return { sunday, mission: cell, zones: { 1: cell } };
  };
  const before = Object.fromEntries(KEYS.map(([key]) => [key, [100, null]]));
  return {
    mission: 'Test Mission', current_week: '2026-09-27', weeks_shown: 12, finished_weeks: 2, max_weeks: 26,
    read_at: '2026-09-28T08:00:00+00:00',
    indicators: KEYS.map(([key, label]) => ({ key, label, key_indicator: key === 'friends_found' })),
    zones: [{ id: 1, name: 'Zone A' }],
    weeks: [week('2026-09-13', before), week('2026-09-20', figures)],
  };
}

function element(id) {
  const listeners = {};
  const self = {
    id, innerHTML: '', textContent: '', hidden: false, disabled: false, value: '', style: {}, dataset: {}, attributes: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setAttribute(name, value) { self.attributes[name] = String(value); },
    getAttribute: name => self.attributes[name] ?? null,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelector: selector => element(`query:${selector}`),
    querySelectorAll: () => [],
    closest: () => null,
    replaceChildren(...nodes) { self.textContent = nodes.map(n => n.textContent ?? '').join(''); },
    append(...nodes) { self.textContent += nodes.map(n => n.textContent ?? '').join(''); },
    remove() {},
  };
  return self;
}

async function glimpse(figures) {
  const elements = new Map();
  const byId = id => (elements.has(id) ? elements.get(id) : (elements.set(id, element(id)), elements.get(id)));
  const stored = new Map();
  let draws = 0; // chart drawings (setOption calls)
  const document = {
    readyState: 'complete', getElementById: byId, createElement: tag => element(`new-${tag}`),
    createTextNode: text => ({ textContent: text }), addEventListener() {},
    head: element('head'), documentElement: { lang: 'en' },
  };
  const context = {
    console, Promise, Date, Math, JSON, Object, Array, String, Number, Error, RegExp, Map, Set, Intl, URLSearchParams,
    document, location: { search: '?glimpse=1', origin: 'http://portal.test', href: 'http://portal.test/home.html?glimpse=1' },
    localStorage: { getItem: k => (stored.has(k) ? stored.get(k) : null), setItem: (k, v) => stored.set(k, String(v)), removeItem: k => stored.delete(k) },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    matchMedia: () => ({ matches: false }),
    MutationObserver: class { observe() {} },
    addEventListener() {}, requestAnimationFrame: () => 0, cancelAnimationFrame() {}, setTimeout: () => 0, clearTimeout() {},
    portalAPI: async () => answer(figures),
    echarts: { init: el => ({ setOption() { draws++; }, getDom: () => el, dispose() {}, resize() {} }), graphic: { LinearGradient: class {} } },
  };
  context.window = context;
  context.parent = context;
  vm.createContext(context);
  // A drawing error would only show as "could not load" on the page; print it here instead.
  vm.runInContext(source.replace('const message = error.library', 'console.error(error); const message = error.library'), context, { filename: 'glimpse.js' });
  for (let n = 0; n < 5; n++) await new Promise(resolve => setImmediate(resolve));
  const html = byId('glTiles').innerHTML;
  const tiles = Object.fromEntries(html.split('<button').slice(1).map(tile => [tile.match(/data-key="([^"]+)"/)[1], tile]));
  return { tiles, summary: byId('glSummary').textContent, table: byId('glTrendTable').innerHTML, status: byId('glStatus').textContent,
    context, draws: () => draws };
}

let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };

(async () => {
  // 1. Just under, exactly at, and over the goal, side by side.
  let g = await glimpse({
    friends_found: [311, 312], baptisms_confirmations: [312, 312], baptismal_dates: [313, 312],
    sacrament_attendance: [299, 300], members_at_lessons: [199, 200], new_member_sacrament: [0, null],
  });
  ok(g.status === '', 'the glimpse drew without an error');
  ok(!g.tiles.friends_found.includes('Goal reached') && g.tiles.friends_found.includes('99% of the goal'),
    '311 of a goal of 312: not reached, 99% of the goal (not 100%)');
  ok(!g.tiles.sacrament_attendance.includes('Goal reached') && g.tiles.sacrament_attendance.includes('99% of the goal'),
    '299 of 300: not reached, 99%');
  ok(!g.tiles.members_at_lessons.includes('Goal reached') && g.tiles.members_at_lessons.includes('99% of the goal'),
    '199 of 200: not reached, 99%');
  ok(g.tiles.baptisms_confirmations.includes('Goal reached') && g.tiles.baptisms_confirmations.includes('gl-reached'),
    '312 of 312: Goal reached, with the tick');
  ok(g.tiles.baptismal_dates.includes('Goal reached'), '313 of 312: Goal reached');
  ok(g.tiles.new_member_sacrament.includes('No goal set') && !g.tiles.new_member_sacrament.includes('Goal reached'),
    'no goal set: no verdict');
  ok(g.summary.includes('New people being taught: 311, with a goal of 312 set the week before (99%).'),
    'the summary gives the key indicator as 99%');
  ok(g.summary.includes('Goal reached: Baptisms and confirmations, People with a baptismal date.'),
    'the summary names only the indicators that reached their goal');
  ok(!/Goal reached:[^.]*(New people|Sacrament|Lessons)/.test(g.summary), 'the summary never counts 311 of 312 as reached');
  ok(!g.summary.includes('Every key indicator reached'), 'not "every key indicator reached"');
  ok(/<td data-i18n-ignore>99%<\/td>/.test(g.table), 'the table shows 99% for 311 of 312');

  // 2. Everything a little under the goal: nothing reached, the closest is named, no "every indicator reached".
  // (The key indicator is further off, so the summary names another one as the closest.)
  g = await glimpse(Object.fromEntries(KEYS.map(([key], n) => [key, n === 0 ? [250, 312] : n === 3 ? [299, 300] : [311, 312]])));
  ok(!Object.values(g.tiles).some(tile => tile.includes('Goal reached')), 'all just under the goal: no tile says Goal reached');
  ok(!g.summary.includes('Goal reached') && !g.summary.includes('Every key indicator reached'), 'all just under: no verdict in the summary');
  ok(g.summary.includes('Closest to its goal: Baptisms and confirmations, 311 of 312 (99%).'), 'all just under: the closest indicator is named at 99%');

  // 3. Every indicator exactly at its goal: every tile reached, the summary says so.
  g = await glimpse(Object.fromEntries(KEYS.map(([key]) => [key, [312, 312]])));
  ok(Object.values(g.tiles).every(tile => tile.includes('Goal reached')), 'all at the goal: every tile says Goal reached');
  ok(g.summary.includes('Every key indicator reached the goal set for it.'), 'all at the goal: the summary says every key indicator reached');

  // 4. A goal but no result yet (plans saved, nothing reported): no "null%".
  g = await glimpse({ ...Object.fromEntries(KEYS.map(([key]) => [key, [5, 10]])), friends_found: [null, 312] });
  ok(!g.summary.includes('null') && g.summary.includes('New people being taught: no result yet, with a goal of 312 set the week before.'),
    'a goal without a result: the summary says no result yet (never "null%")');
  ok(g.tiles.friends_found.includes('No result yet') && !g.tiles.friends_found.includes('Goal reached'), 'a goal without a result: the tile says No result yet');

  // 5. home.html calls MissionGlimpse.update() after every /api/overview answer. A glimpse already on screen is not
  //    drawn again (on a phone that took about a second and held up the Overview's cards); after it stepped aside (a
  //    manager looking at another area's goals) it is drawn again when it comes back.
  g = await glimpse(Object.fromEntries(KEYS.map(([key]) => [key, [5, 10]])));
  const drawn = g.draws();
  ok(drawn > 0, 'the charts were drawn');
  g.context.MissionGlimpse.update({ allowed: true, viewingArea: false });
  ok(g.draws() === drawn, "the Overview's answer does not draw the glimpse on screen again");
  g.context.MissionGlimpse.update({ allowed: true, viewingArea: true });
  g.context.MissionGlimpse.update({ allowed: true, viewingArea: false });
  ok(g.draws() > drawn, 'back from another area, the glimpse is drawn again');

  console.log(`glimpse: ${passed} checks passed (Goal reached only when the result is at or over the goal; 99%, never a rounded 100%; drawn once)`);
})().catch(error => { console.error(error); process.exit(1); });
