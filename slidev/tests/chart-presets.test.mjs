// Chart presets (lib/chart-presets.mjs) and calculated fields (lib/formula.mjs) inside the chart engine: every preset
// is drawn with the vendored ECharts (server side, no browser), the table reshaping of each is checked, and a chart with
// calc and preset goes through chartView exactly as the component draws it. Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as engine from '../manager/gfm-addon/lib/chart-engine.mjs';
import { PRESET_IDS, PRESETS, presetOf, presetOption } from '../manager/gfm-addon/lib/chart-presets.mjs';

const require = createRequire(import.meta.url);
const echarts = require('../manager/vendor/echarts.min.js');
const ecStat = require('../manager/vendor/ecStat.min.js');
for (const t of Object.values(ecStat.transform)) echarts.registerTransform(t);
const ctx = { dark: false, font: 'Inter, sans-serif', animate: false, ecStat, width: 900, height: 360 };

function draw(option) {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 360 });
  try {
    chart.setOption(option);
    return chart.renderToSVGString();
  }
  finally { chart.dispose(); }
}
const marks = svg => (svg.match(/<(path|polygon|polyline|rect|circle) /g) || []).length;
const view = props => engine.chartView(props);
const drawn = props => {
  const v = view(props);
  const option = engine.viewOption(v, ctx);
  return { v, option, svg: option ? draw(option) : '' };
};

const ZONES = ['Zone, Referrals Received, Successfully Contacted, Goal', 'Frankfurt, 40, 30, 35', 'Mannheim, 25, 12, 30', 'Wiesbaden, 31, 25, 28', 'Darmstadt, 18, 9, 20', 'Giessen, , 7, 15'];
const WEEKS = ['Week, Received, Attempted, Successful, Goal', 'Aug 3, 12, 9, 6, 8', 'Aug 10, 15, 11, 7, 8', 'Aug 17, 14, 12, 9, 8', 'Aug 24, 19, 14, 10, 12', 'Aug 31, 22, 15, 12, 12'];

test('the preset list: every preset has a label, a description and what it needs', () => {
  assert.deepEqual(PRESET_IDS.slice(0, 11), ['trend', 'goal-vs-actual', 'ranked-bar', 'comparison', 'big-number', 'progress', 'cumulative-goal', 'funnel', 'conversion-funnel', 'leaderboard', 'small-multiples']);
  assert.equal(PRESET_IDS.filter(id => PRESETS[id].group === 'kind').length, 11, 'the curated kinds');
  assert.ok(PRESET_IDS.filter(id => PRESETS[id].group === 'type').length >= 28, 'and every chart type besides');
  for (const [id, p] of Object.entries(PRESETS)) assert.ok(p.label && p.description.length > 15 && p.needs, id);
  assert.equal(presetOf({ preset: 'trend' }), 'trend');
  assert.equal(presetOf({ preset: 'constructor' }), '', 'only the presets of the list');
  assert.equal(presetOf({ preset: ' ranked-bar ' }), 'ranked-bar');
  assert.equal(presetOf({}), '');
});

test('every preset draws a chart with real marks, from the chart\'s own numbers', () => {
  for (const id of PRESET_IDS) {
    if (id.startsWith('type-')) continue; // the plain chart types have their own test below
    const rows = ['trend', 'cumulative-goal', 'funnel', 'conversion-funnel', 'small-multiples', 'comparison'].includes(id) ? WEEKS : ZONES;
    const { v, option, svg } = drawn({ preset: id, rows });
    assert.equal(v.problem, '', `${id}: ${v.problem}`);
    assert.ok(option, `${id}: an option`);
    assert.ok(marks(svg) > 6, `${id}: drawn (${marks(svg)} marks)`);
  }
});

test('a preset chart is an option chart, a chart with a type stays the older way', () => {
  assert.equal(engine.isOptionChart({ preset: 'trend', rows: WEEKS }), true);
  assert.equal(engine.isOptionChart({ preset: 'trend', type: 'bar' }), false);
  assert.equal(engine.isOptionChart({ preset: 'nonsense', rows: WEEKS }), false);
});

test('ranked bar: highest first, rows without a number last or left out, cut to the top, horizontal', () => {
  const { v, option } = drawn({ preset: 'ranked-bar', rows: ZONES, presetTop: 3 });
  assert.deepEqual(v.table.labels, ['Frankfurt', 'Wiesbaden', 'Mannheim']);
  assert.deepEqual(v.table.series[0].values, [40, 31, 25]);
  assert.equal(option.yAxis[0].type, 'category');
  assert.equal(option.yAxis[0].inverse, true);
  assert.equal(option.xAxis[0].type, 'value');
  assert.equal(option.series[0].type, 'bar');
  const all = view({ preset: 'ranked-bar', rows: ZONES, presetTop: 0 });
  assert.equal(all.table.labels.length, 4, 'a zone with no number for the ranked column is left out');
});

test('leaderboard: the same, with place numbers', () => {
  const { v } = drawn({ preset: 'leaderboard', rows: ZONES });
  assert.deepEqual(v.table.labels.slice(0, 3), ['1. Frankfurt', '2. Wiesbaden', '3. Mannheim']);
});

test('goal vs actual: the goal column becomes the goal line; without a goal the chart says what is missing', () => {
  const { v, option } = drawn({ preset: 'goal-vs-actual', rows: ZONES });
  assert.equal(v.problem, '');
  assert.ok(option.series.some(s => s.gfmGoal || /goal/i.test(s.name || '')), 'a goal series');
  const none = view({ preset: 'goal-vs-actual', rows: ['Week, Value', 'A, 1', 'B, 2'] });
  assert.match(none.problem, /needs a goal column/);
});

test('progress: percent of the goal, ranked, with a percent axis', () => {
  const { v, option } = drawn({ preset: 'progress', rows: ZONES });
  assert.equal(v.table.unit, 'percent');
  assert.match(v.table.series[0].name, /% of goal/);
  assert.equal(Math.round(v.table.series[0].values[0] * 10) / 10, 114.3, 'Frankfurt: 40 of a goal of 35, first');
  const values = v.table.series[0].values.filter(x => x !== null);
  assert.deepEqual([...values].sort((a, b) => b - a), values);
  assert.equal(option.xAxis[0].max, 120);
});

test('cumulative goal: running totals for every column, goal included', () => {
  const { v } = drawn({ preset: 'cumulative-goal', rows: WEEKS });
  assert.deepEqual(v.table.series.find(s => s.name === 'Received').values, [12, 27, 41, 60, 82]);
  assert.deepEqual(v.table.series.find(s => s.name === 'Goal').values, [8, 16, 24, 36, 48]);
});

test('funnels: the steps are the numbers, the latest week (or the total) is each step\'s value; conversion in the labels', () => {
  const f = view({ preset: 'funnel', rows: WEEKS, presetAggregate: 'last' });
  assert.deepEqual(f.table.labels, ['Received', 'Attempted', 'Successful', 'Goal']);
  assert.deepEqual(f.table.series[0].values, [22, 15, 12, 12]);
  const sum = view({ preset: 'funnel', rows: WEEKS, presetAggregate: 'sum' });
  assert.deepEqual(sum.table.series[0].values, [82, 61, 44, 48]);
  const c = view({ preset: 'conversion-funnel', rows: WEEKS });
  assert.equal(c.table.labels[0], 'Received');
  assert.equal(c.table.labels[1], 'Attempted (68% of the step before)');
  assert.equal(c.table.labels[2], 'Successful (80% of the step before)');
  assert.match(view({ preset: 'funnel', rows: ['Week, One', 'A, 1'] }).problem, /at least two steps/);
});

test('big number and small multiples are the engine\'s own kinds', () => {
  assert.equal(presetOption('big-number', { labels: ['a'], series: [{ name: 'x', values: [1] }] }, { target: 5 }).option.gfm.target, 5);
  assert.equal(presetOption('small-multiples', { labels: ['a'], series: [{ name: 'x', values: [1] }] }).option.gfm.kind, 'multiples');
  assert.equal(drawn({ preset: 'big-number', rows: WEEKS }).v.problem, '');
});

test('the chart\'s own option goes on top of the preset', () => {
  const { option } = drawn({ preset: 'trend', rows: WEEKS, option: { series: [{ smooth: true }], yAxis: { min: 0 } } });
  assert.equal(option.series[0].smooth, true);
  assert.equal(option.yAxis[0].min, 0);
  assert.equal(option.series[0].type, 'line');
});

test('an unknown or unsuitable preset never draws a misleading chart', () => {
  assert.match(presetOption('nope', { labels: [], series: [] }).problem, /no chart kind called/);
  assert.match(view({ preset: 'comparison', rows: ['Week, One', 'A, 1'] }).problem, /at least two numbers/);
  assert.equal(presetOption('trend', null).problem, '', 'nothing to draw yet is not a mistake');
});

test('calculated fields reach the chart: drawn as another series, percent unit and mistakes listed', () => {
  const calc = [
    { name: 'Successful Contact Rate', formula: '[Successfully Contacted] / [Referrals Received]', format: 'percent' },
    { name: 'Oops', formula: '[Missing] + 1' },
  ];
  const { v, option, svg } = drawn({ rows: ZONES, option: { series: [{ type: 'bar' }] }, calc });
  assert.deepEqual(v.table.series.map(s => s.name), ['Referrals Received', 'Successfully Contacted', 'Goal', 'Successful Contact Rate']);
  assert.deepEqual(v.table.series[3].values.map(x => (x === null ? null : Math.round(x))), [75, 48, 81, 50, null]);
  assert.equal(v.calc.problems.length, 1);
  assert.match(v.calc.problems[0].message, /no field called \[Missing\]/);
  assert.equal(v.problem, '', 'the chart still draws');
  assert.ok(option.series.length >= 4);
  assert.ok(marks(svg) > 10);
  // calc as JSON text (how a slide writes it) works the same.
  assert.equal(view({ rows: ZONES, option: { series: [{ type: 'bar' }] }, calc: JSON.stringify(calc) }).table.series.length, 4);
  // no calc: nothing changes.
  assert.equal(view({ rows: ZONES, option: { series: [{ type: 'bar' }] } }).table.series.length, 3);
});

test('calc and preset together: the field is part of the ranking', () => {
  const calc = [{ name: 'Rate', formula: '[Successfully Contacted] / [Referrals Received]', format: 'percent' }];
  const { v } = drawn({ preset: 'ranked-bar', rows: ZONES, calc, presetTop: 2 });
  assert.equal(v.table.labels.length, 2);
  assert.equal(v.table.series.some(s => s.name === 'Rate'), true);
});

test('when only percentages are drawn the axis and tooltips say %, and the editor can list every field', () => {
  const calc = [{ name: 'Rate', formula: '[Successfully Contacted] / [Referrals Received]', format: 'percent' }];
  const v = view({ preset: 'ranked-bar', rows: ZONES, calc, shape: { only: ['Rate'] } });
  assert.equal(v.table.unit, 'percent');
  assert.deepEqual(v.table.series.map(s => s.name), ['Rate']);
  assert.deepEqual(v.source.series.map(s => s.name), ['Referrals Received', 'Successfully Contacted', 'Goal', 'Rate'], 'source: every field, for the formula editor');
  const o = engine.viewOption(v, ctx);
  assert.ok(draw(o).includes('%'), 'the drawn chart shows percent signs');
});

// Every chart type, as a kind of its own: each is drawn from a table that suits it.
const FLOWS = ['From, To, People', 'Finding, Taught, 40', 'Taught, Baptismal date, 12', 'Taught, Stopped, 20', 'Baptismal date, Baptized, 9'];
const PARTS = ['Source, Friends', 'Members, 18', 'Online, 9', 'Finding, 12', 'Service, 5'];
const SAMPLES = {
  'type-pie': PARTS, 'type-donut': PARTS, 'type-treemap': PARTS, 'type-sunburst': PARTS,
  'type-gauge': ['Measure, Actual, Goal', 'This week, 412, 450'],
  'type-calendar-heatmap': ['Day, Lessons', '2026-08-03, 5', '2026-08-10, 8', '2026-08-17, 3', '2026-09-07, 9'],
  'type-candlestick': ['Day, Open, Close, Low, High', 'Mon, 10, 12, 9, 13', 'Tue, 12, 11, 10, 14', 'Wed, 11, 15, 11, 16'],
  'type-waterfall': ['Step, People', 'Last month, 40', 'Found, 12', 'Moved, -5', 'Baptized, -3'],
  'type-range': ['Week, Low, High', 'Aug 3, 4, 9', 'Aug 10, 5, 11', 'Aug 17, 3, 8'],
  'type-errorbar': ['Week, Low, High', 'Aug 3, 4, 9', 'Aug 10, 5, 11', 'Aug 17, 3, 8'],
  'type-tree': ['Unit, People', 'North / Frankfurt 1, 4', 'North / Frankfurt 2, 6', 'South / Mainz, 5'],
  'type-graph': FLOWS, 'type-sankey': FLOWS, 'type-chord': FLOWS,
  'type-boxplot': ['Week, North, South', '1, 4, 9', '2, 6, 8', '3, 5, 30', '4, 7, 7', '5, 6, 9'],
};

test('every chart type is a kind: it draws from numbers that suit it', () => {
  const types = PRESET_IDS.filter(id => PRESETS[id].group === 'type');
  assert.ok(types.length >= 28);
  for (const id of types) {
    const rows = SAMPLES[id] ?? WEEKS;
    const { v, svg } = drawn({ preset: id, rows });
    assert.equal(v.problem, '', `${id}: ${v.problem}`);
    assert.ok(marks(svg) >= 3, `${id}: drawn (${marks(svg)} marks)`);
  }
});

test('the plain chart types change nothing about the numbers', () => {
  const v = view({ preset: 'type-bar', rows: ZONES });
  assert.deepEqual(v.table.labels, ['Frankfurt', 'Mannheim', 'Wiesbaden', 'Darmstadt', 'Giessen'], 'no sorting, no cutting');
  assert.equal(v.table.series.length, 3);
  assert.equal(presetOf({ preset: 'type-donut' }), 'type-donut');
  assert.equal(presetOf({ preset: 'type-nonsense' }), '');
  assert.deepEqual(engine.viewOption(view({ preset: 'type-donut', rows: PARTS }), ctx).series[0].radius, ['38%', '60%']);
});
