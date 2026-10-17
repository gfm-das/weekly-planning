// Round 19: Vollzogen "Group by" year / quarter / month (portal/vollzogen.html). Takes the page's own period() and
// bodyRows() out of its script and runs them in a Node vm: newest first by default, the order choice reverses it,
// every period has a heading with its total, and people without a baptism date come last under "No date".
// Run: node portal/tests/vollzogen-groups-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'vollzogen.html'), 'utf8');
const grab = (name) => {
  const start = html.indexOf(`function ${name}(`);
  assert.ok(start > 0, name);
  return html.slice(start, html.indexOf('\n      }\n', start) + 8);
};
for (const id of ['id="group"', 'value="year"', 'value="quarter"', 'value="month"', 'id="order"', 'value="oldest"']) assert.ok(html.includes(id), id);
assert.match(html, /\[data-theme="dark"\]|var\(--soft\)/); // the period rows use the theme's colours

const texts = { 'vollzogen.noDate': 'No date', 'vollzogen.quarterLabel': 'Q{q} {year}', 'vollzogen.periodTotal': 'Total: {n}' };
const sandbox = {
  state: { oldestFirst: false },
  document: { documentElement: { lang: 'en' } },
  Intl, Date, Math, Number, String,
  T: (key, values = {}) => (texts[key] || key).replace(/\{(\w+)\}/g, (_, k) => values[k]),
  esc: (s) => String(s),
  day: (iso) => (iso ? String(iso).slice(0, 10) : ''),
  text: (v) => (v == null ? '' : String(v)),
  COLUMNS: [['name', 'name', (i) => i.full_name], ['date', 'date', (i) => i.baptism_date || '']],
};
vm.createContext(sandbox);
vm.runInContext(grab('period') + grab('bodyRows'), sandbox);

const people = [
  { full_name: 'Anna', baptism_date: '2026-08-09' }, { full_name: 'Ben', baptism_date: '2026-02-01' },
  { full_name: 'Cara', baptism_date: '2025-12-28' }, { full_name: 'Dora', baptism_date: null },
  { full_name: 'Emil', baptism_date: '2026-08-02' },
];
const headings = (out) => [...out.matchAll(/scope="rowgroup">([^<]*)<span class="total">([^<]*)/g)].map((m) => `${m[1]} (${m[2]})`);
const names = (out) => [...out.matchAll(/<td class="name"[^>]*>([^<]*)/g)].map((m) => m[1]);

assert.deepEqual(names(sandbox.bodyRows(people, '')), ['Anna', 'Emil', 'Ben', 'Cara', 'Dora']);
assert.deepEqual(headings(sandbox.bodyRows(people, '')), []);
assert.deepEqual(headings(sandbox.bodyRows(people, 'year')), ['2026 (Total: 3)', '2025 (Total: 1)', 'No date (Total: 1)']);
assert.deepEqual(headings(sandbox.bodyRows(people, 'quarter')), ['Q3 2026 (Total: 2)', 'Q1 2026 (Total: 1)', 'Q4 2025 (Total: 1)', 'No date (Total: 1)']);
assert.deepEqual(headings(sandbox.bodyRows(people, 'month')), ['August 2026 (Total: 2)', 'February 2026 (Total: 1)', 'December 2025 (Total: 1)', 'No date (Total: 1)']);
sandbox.state.oldestFirst = true; // the order choice
assert.deepEqual(headings(sandbox.bodyRows(people, 'year')), ['2025 (Total: 1)', '2026 (Total: 3)', 'No date (Total: 1)']);
assert.deepEqual(names(sandbox.bodyRows(people, 'month')), ['Cara', 'Ben', 'Emil', 'Anna', 'Dora']);
sandbox.document.documentElement.lang = 'de';
assert.match(sandbox.bodyRows(people, 'month'), /Dezember 2025/);
console.log('vollzogen-groups-check: all checks passed');
