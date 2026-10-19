// The deck that ships with the product (manager/shipped-decks/gfm-showcase, "Everything a deck can do") and how it
// reaches the library (manager/shipped-decks.mjs): once, never over a person's deck, never again after a delete.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { normalizeSpec, querySpecs } from '../manager/gfm-addon/lib/chart-spec.mjs';
import { offerShippedDecks, SHIPPED_DIR } from '../manager/shipped-decks.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const deck = fs.readFileSync(path.join(SHIPPED_DIR, 'gfm-showcase', 'slides.md'), 'utf8');
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'shipped-'));
const read = (...p) => fs.readFileSync(path.join(...p), 'utf8');

test('a fresh install gets the showcase deck once; deleting it keeps it deleted', async () => {
  const to = tmp();
  assert.deepEqual(await offerShippedDecks({ to }), { added: ['gfm-showcase'], kept: [] });
  assert.equal(read(to, 'gfm-showcase', 'slides.md'), deck);
  assert.deepEqual(JSON.parse(read(to, '.gfm-shipped.json')), ['gfm-showcase']);
  assert.deepEqual(await offerShippedDecks({ to }), { added: [], kept: [] }, 'the next start adds nothing');
  fs.rmSync(path.join(to, 'gfm-showcase'), { recursive: true });
  assert.deepEqual(await offerShippedDecks({ to }), { added: [], kept: [] }, 'deleted in the library: not brought back');
  assert.equal(fs.existsSync(path.join(to, 'gfm-showcase')), false);
});

test('an install with a deck of the same name keeps it exactly; other decks are never touched', async () => {
  const to = tmp();
  for (const slug of ['gfm-showcase', 'zone-council']) { fs.mkdirSync(path.join(to, slug)); fs.writeFileSync(path.join(to, slug, 'slides.md'), `# mine ${slug}\n`); }
  assert.deepEqual(await offerShippedDecks({ to }), { added: [], kept: ['gfm-showcase'] });
  assert.equal(read(to, 'gfm-showcase', 'slides.md'), '# mine gfm-showcase\n');
  assert.equal(read(to, 'zone-council', 'slides.md'), '# mine zone-council\n');
  assert.deepEqual(fs.readdirSync(to).sort(), ['.gfm-shipped.json', 'gfm-showcase', 'zone-council']);
});

test('no shipped folder, or a folder without slides.md: nothing happens', async () => {
  const to = tmp(), from = tmp();
  fs.mkdirSync(path.join(from, 'half'));
  assert.deepEqual(await offerShippedDecks({ from, to }), { added: [], kept: [] });
  assert.deepEqual(await offerShippedDecks({ from: path.join(from, 'none'), to }), { added: [], kept: [] });
  assert.deepEqual(fs.readdirSync(to), []);
});

test('the server offers the shipped decks at start, unless SLIDEV_SHIPPED_DECKS=0', () => {
  const server = read(HERE, '..', 'manager', 'server.mjs');
  assert.match(server, /if \(process\.env\.SLIDEV_SHIPPED_DECKS !== '0'\) \{[\s\S]*await offerShippedDecks\(\)/);
});

test('the showcase shows every chart type, every kind and every way to bring a slide to life', () => {
  for (const type of ['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar', 'pie', 'funnel', 'gauge', 'radar', 'heatmap', 'tree', 'treemap', 'sunburst', 'boxplot', 'candlestick', 'graph', 'sankey', 'chord', 'themeRiver', 'parallel', 'custom'])
    assert.match(deck, new RegExp(`"type":"${type}"`), type);
  for (const bit of ['"areaStyle"', '"stack":"all"', '"radius":["45%"', '"coordinateSystem":"calendar"', '"coordinateSystem":"polar"', '"renderItem":"waterfall"', '"renderItem":"errorbar"', 'multiples', '"forecast":3',
    'preset="ranked-bar"', 'preset="goal-vs-actual"', 'preset="cumulative-goal"', 'preset="leaderboard"', ':calc=', ':shape=', ':story=', 'storyTransition="morph"',
    '<v-clicks>', 'v-click', 'v-mark', 'v-motion', '<LightOrDark>', '```js {1|2-3|all}', '<MissionKpiChart', '<GfmKpiGrid', ':query=',
    'GfmBigNumber', 'GfmProgress', 'GfmComparison', 'GfmCallout', 'GfmInsight', 'GfmQuote',
    'layout: gfm-cover', 'layout: gfm-section', 'layout: gfm-full-chart', 'layout: gfm-two-chart', 'layout: gfm-chart-insight', 'layout: gfm-three-column', 'layout: gfm-comparison', 'layout: gfm-image-message', 'layout: gfm-hero', 'layout: two-cols', 'layout: quote', 'layout: end',
    'Presenter view', 'timer', 'pen', 'Download PDF'])
    assert.ok(deck.includes(bit), bit);
});

test('live charts ask only for finished weeks, every one written in the deck; names are made up', () => {
  const specs = querySpecs(deck).map(q => normalizeSpec(q));
  assert.ok(specs.length >= 1);
  for (const s of specs) assert.equal(s.includeCurrent, false);
  for (const name of ['Elder Sample', 'Sister Example', 'Elder Demo', 'Anna Beispiel']) assert.ok(deck.includes(name));
  assert.doesNotMatch(deck, /https?:\/\//, 'nothing loaded from the internet');
  const ids = [...deck.matchAll(/chart-id="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length, 'every chart has its own id');
});
