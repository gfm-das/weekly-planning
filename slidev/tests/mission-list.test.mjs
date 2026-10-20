// Lists in slides (<MissionList>, lib/list-core.mjs): typed rows, live mission numbers through the chart path, columns,
// sort, limit, groups, pages, clicks; the words in 14 languages (lib/deck-words.mjs); the component's wiring. Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { cellText, isNumberish, listClicks, listFromRows, listFromTable, listView, pageOf, pickColumns, readSort, splitRow } from '../manager/gfm-addon/lib/list-core.mjs';
import { deckLanguage, word, WORDS } from '../manager/gfm-addon/lib/deck-words.mjs';
import { answerTable } from '../manager/gfm-addon/lib/chart-engine.mjs';
import { querySpecs } from '../manager/gfm-addon/lib/chart-spec.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const NAMES = listFromRows(['Name, Zone, Baptisms', 'Elder Sample, Mainz, 3', 'Sister Example, Frankfurt, 12', 'Elder Demo, Mainz, 2', 'Sister Test, Frankfurt, 5', 'Elder Mock, Darmstadt, 4']);

test('typed rows: headings, cells as text, tabs and semicolons, ragged rows', () => {
  assert.deepEqual(NAMES.columns, ['Name', 'Zone', 'Baptisms']);
  assert.deepEqual(NAMES.rows[0], ['Elder Sample', 'Mainz', '3']);
  assert.deepEqual(splitRow('a\tb, c'), ['a', 'b, c']);
  assert.deepEqual(splitRow('a; b'), ['a', 'b']);
  assert.deepEqual(listFromRows('Name\nOnly one').rows, [['Only one']]);
  assert.deepEqual(listFromRows(['A, B', 'x']).rows, [['x', '']]);
  assert.deepEqual(listFromRows([]), { columns: [], rows: [], problem: '' });
});

test('live numbers: a row per unit or week, a column per number (goal kept)', () => {
  const table = answerTable({ table: { labels: ['Frankfurt', 'Mainz'], series: [{ name: 'New people being taught', values: [31, 22] }, { name: 'Goal', values: [28, 20], role: 'goal' }] }, meta: { by: 'unit', level: 'zone' } });
  const list = listFromTable(table);
  assert.deepEqual(list.columns, ['Zone', 'New people being taught', 'Goal']);
  assert.deepEqual(list.rows, [['Frankfurt', 31, 28], ['Mainz', 22, 20]]);
  assert.deepEqual(listFromTable(null).rows, []);
});

test('columns, sort (numbers as numbers, text by name), limit', () => {
  assert.deepEqual(pickColumns(NAMES, 'baptisms, name, nope'), [2, 0]);
  assert.deepEqual(pickColumns(NAMES, []), [0, 1, 2]);
  assert.deepEqual(readSort(NAMES, 'Baptisms:desc'), { index: 2, desc: true });
  assert.equal(readSort(NAMES, 'Nope'), null);
  const v = listView(NAMES, { sort: 'Baptisms:desc', limit: 3, columns: ['Name', 'Baptisms'] });
  assert.deepEqual(v.groups[0].rows.map(r => r.cells), [['Sister Example', '12'], ['Sister Test', '5'], ['Elder Mock', '4']]);
  assert.equal(v.total, 5);
  assert.equal(v.shown, 3);
  assert.deepEqual(listView(NAMES, { sort: 'Name' }).groups[0].rows.map(r => r.cells[0])[0], 'Elder Demo');
});

test('groups: in sorted order, the group column left out, rows numbered across groups', () => {
  const v = listView(NAMES, { groupBy: 'zone', sort: 'Zone' });
  assert.equal(v.grouped, true);
  assert.deepEqual(v.groups.map(g => g.name), ['Darmstadt', 'Frankfurt', 'Mainz']);
  assert.deepEqual(v.columns, ['Name', 'Baptisms']);
  assert.deepEqual(v.groups.flatMap(g => g.rows.map(r => r.n)), [0, 1, 2, 3, 4]);
});

test('pages and clicks: page size, the rows of a page, one click per row or per page', () => {
  const v = listView(NAMES, { pageSize: 2 });
  assert.equal(v.pages, 3);
  assert.deepEqual(pageOf(v, 1)[0].rows.map(r => r.n), [2, 3]);
  assert.deepEqual(pageOf(v, 9)[0].rows.map(r => r.n), [4], 'past the end: the last page');
  assert.equal(listClicks(v, { paging: 'click' }), 2);
  assert.equal(listClicks(v, { paging: 'auto' }), 0);
  assert.equal(listClicks(v, { reveal: true }), 5);
  assert.equal(listView(NAMES, {}).pages, 1);
  assert.equal(cellText(1234.5, 'en'), '1,234.5');
  assert.equal(cellText(null), '');
  assert.ok(isNumberish('40%') && isNumberish(3) && !isNumberish('Mainz'));
});

test('the words: 14 languages with the same keys, the deck language first, English as the fallback', () => {
  const portal = fs.readdirSync(path.join(here, '../../portal/i18n')).filter(f => /^[a-z]{2}\.json$/.test(f)).map(f => f.slice(0, 2)).sort();
  assert.deepEqual(Object.keys(WORDS).sort(), portal);
  for (const [lang, words] of Object.entries(WORDS)) assert.deepEqual(Object.keys(words).sort(), Object.keys(WORDS.en).sort(), lang);
  assert.equal(deckLanguage(['de-DE']), 'de');
  assert.equal(deckLanguage(['xx', 'fr-CA']), 'fr');
  assert.equal(deckLanguage([]), 'en');
  assert.equal(word('de', 'page', { n: 2, m: 5 }), 'Seite 2 von 5');
});

test('<MissionList>: the same live path as charts (pinned by its :query), sample fallback, clicks registered', () => {
  const vue = fs.readFileSync(path.join(here, '../manager/gfm-addon/components/MissionList.vue'), 'utf8');
  assert.match(vue, /fetchChartData\(deck, value, key\)/);
  assert.match(vue, /usingSample/);
  assert.match(vue, /clicks\.register\(clickId/);
  assert.match(vue, /<studio>/);
  assert.equal(querySpecs(`<MissionList :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit"}' />`).length, 1, 'the manager pins a list query like a chart query');
});
