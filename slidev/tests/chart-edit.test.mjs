// Round 6: editing charts by their chart-id (the builder always changes the
// chart it opened), writing a chart as numbers plus an ECharts option, the type
// picker, and the setting paths the builder's form writes. Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as core from '../manager/gfm-addon/lib/chart-builder-core.mjs';
import * as engine from '../manager/gfm-addon/lib/chart-engine.mjs';
import { checkOption, optionSchema, TOP_LEVEL } from '../manager/gfm-addon/lib/chart-schema.mjs';
import { normalizeSpec, pinnedKeys, specKey } from '../manager/gfm-addon/lib/chart-spec.mjs';

const require = createRequire(import.meta.url);
const echarts = require('../manager/vendor/echarts.min.js');
const ecStat = require('../manager/vendor/ecStat.min.js');
const ctx = { dark: false, font: 'Inter', animate: false, ecStat, width: 900, height: 360 };

const SPEC = normalizeSpec({ measures: ['friends_found.actual', 'friends_found.previous_goal'], weeks: 12 });
const model = extra => ({ chartId: 'c1a2b3c', source: 'mission', spec: SPEC, option: { title: { text: 'New people being taught' }, series: [{ type: 'bar', gfm: { trend: { method: 'linear' } } }] }, height: 300, keep: ['class="mt-4"', 'v-click'], ...extra });

test('chart-ids: seven letters, never one the slide already has', () => {
  let n = 0;
  const seq = () => [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07][n++ % 7];
  const first = core.newChartId([], seq);
  assert.match(first, /^c[0-9a-z]{6}$/);
  n = 0;
  const other = core.newChartId([first], () => Math.random());
  assert.notEqual(other, first);
  assert.deepEqual(core.chartIds('<MissionChart chart-id="c111111" /> <MissionChart /> <MissionKpiChart chart-id="c222222" />'), ['c111111', 'c222222']);
});

test('writing and reading a chart: the chart-id first, the query pinned as written, the option, unknown attributes kept', () => {
  const tag = core.writeChart(model());
  assert.ok(tag.startsWith('<MissionChart chart-id="c1a2b3c" :height="300" :query=\''));
  assert.ok(tag.includes(':option=\'{"title":{"text":"New people being taught"},"series":[{"type":"bar","gfm":{"trend":{"method":"linear"}}}]}\''));
  assert.ok(tag.endsWith('class="mt-4" v-click />'));
  // Viewers see it: the manager pins exactly this query.
  assert.ok(pinnedKeys(`# Slide\n\n${tag}\n`).has(specKey(SPEC)));
  const back = core.readChart(core.findChartTag(tag));
  assert.equal(back.chartId, 'c1a2b3c');
  assert.equal(back.legacy, false);
  assert.deepEqual(back.option, model().option);
  assert.equal(specKey(back.spec), specKey(SPEC));
  assert.equal(back.height, 300);
  assert.deepEqual(back.keep, ['class="mt-4"', 'v-click']);
  assert.equal(core.writeChart(back), tag, 'reading and writing again changes nothing');
  // A pasted table is written as rows; quotes and tags in cells and the option cannot break the slide.
  const table = core.writeChart({ chartId: 'c9', source: 'table', rows: ['Week\tA\'s', '1\t<b>'], option: { title: { text: 'It\'s "x" & <y>' }, series: [{ type: 'line' }] } });
  assert.ok(!/<b>|<y>/.test(table.replace(/^<MissionChart|\/>$/g, '')));
  const again = core.readChart(core.findChartTag(table));
  assert.deepEqual(again.rows, ['Week\tA\'s', '1\t<b>']);
  assert.equal(again.option.title.text, 'It\'s "x" & <y>');
});

test('Edit chart finds the chart by its chart-id, wherever the lines moved; only that chart changes', () => {
  const left = core.writeChart(model({ chartId: 'cleft01', option: { title: { text: 'Left' }, series: [{ type: 'bar' }] } }));
  const right = core.writeChart(model({ chartId: 'cright1', option: { title: { text: 'Right' }, series: [{ type: 'line' }] } }));
  const slide = `# Zones\n\n<div class="grid grid-cols-2">${left}${right}</div>\n`;
  // Studio's selection said line 2; since then two lines were added above (another edit, another person).
  const moved = `# Zones\n\nA new sentence.\n\n${slide.split('\n').slice(2).join('\n')}`;
  const found = core.locateChart(moved, { id: 'cright1', range: [2, 3], sig: 'stale' });
  assert.equal(found.duplicate, false);
  const next = core.replaceTag(moved, found.found, core.writeChart(model({ chartId: 'cright1', option: { title: { text: 'Right, changed' }, series: [{ type: 'bar' }] } })));
  assert.ok(next.includes(left), 'the chart beside it is untouched, byte for byte');
  assert.ok(next.includes('Right, changed'));
  assert.equal(next.replace(/<MissionChart[^\n]*?\/>/g, '').trim(), moved.replace(/<MissionChart[^\n]*?\/>/g, '').trim(), 'everything around the chart stays');
  // Deleted meanwhile: nothing is written, and the builder says why.
  const gone = core.locateChart(slide.replace(right, ''), { id: 'cright1', range: [2, 3] });
  assert.equal(gone.problem, 'missing');
  assert.match(core.LOCATE_PROBLEMS[gone.problem], /not on the slide any more/);
});

test('a copied chart that kept its chart-id: the one on the opened lines with Studio fingerprint, and it gets a new id', () => {
  const tag = core.writeChart(model());
  const slide = `${tag}\n\nText\n\n${tag.replace('v-click', 'v-click="2"')}\n`;
  const second = core.findChartTags(slide)[1];
  const found = core.locateChart(slide, { id: 'c1a2b3c', range: [4, 5], sig: second.sig });
  assert.equal(found.duplicate, true);
  assert.equal(found.found.start, second.start);
  const fresh = core.newChartId(core.chartIds(slide));
  assert.notEqual(fresh, 'c1a2b3c');
  const next = core.replaceTag(slide, found.found, core.writeChart(model({ chartId: fresh })));
  assert.deepEqual(core.chartIds(next), ['c1a2b3c', fresh]);
});

test('an older chart without a chart-id: found by its lines and fingerprint as before, opened as an option, saved with an id', () => {
  const old = '<MissionChart type="bar" title="Baptismal dates" trend="polynomial" :degree="3" show-values target="30" target-label="Goal" class="w-full" :query=\'{"measures":["baptismal_dates.actual"],"level":"zone","by":"unit","weeks":4}\' />';
  const slide = `# Dates\n\n${old}\n`;
  const [chart] = core.findChartTags(slide);
  const found = core.locateChart(slide, { id: '', range: [2, 3], sig: chart.sig });
  assert.ok(found.found);
  const m = core.readChart(found.found);
  assert.equal(m.legacy, true);
  assert.match(m.notes[0], /older way/);
  assert.equal(m.option.series[0].type, 'bar');
  assert.equal(m.option.series[0].gfm.trend.degree, 3);
  assert.deepEqual(m.option.series[0].label, { show: true });
  assert.deepEqual(m.option.series[0].markLine.data[0], { yAxis: 30, name: 'Goal', lineStyle: { type: 'solid' } });
  assert.deepEqual(m.keep, ['class="w-full"']);
  const saved = core.replaceTag(slide, found.found, core.writeChart({ ...m, chartId: core.newChartId(core.chartIds(slide)) }));
  assert.match(saved, /^# Dates\n\n<MissionChart chart-id="c[0-9a-z]{6}" :query=/);
  // Lines changed while editing an older chart: refused, nothing written.
  assert.equal(core.locateChart(`Added\n${slide}`, { id: '', range: [2, 3], block: old, sig: chart.sig }).problem, undefined, 'the same lines found once elsewhere');
  assert.equal(core.locateChart(slide.replace('Baptismal', 'Other'), { id: '', range: [2, 3], block: old, sig: chart.sig }).problem, 'changed');
});

test('a chart-id keeps a chart drawn from its option even when Studio panel adds a type', () => {
  assert.equal(engine.isOptionChart({ type: 'line', option: { series: [{ type: 'pie' }] } }), false, 'without an id the type decides (older charts)');
  assert.equal(engine.isOptionChart({ type: 'line', chartId: 'c1a2b3c', option: { series: [{ type: 'pie' }] } }), true);
});

test('the type picker: every kind round-trips and draws; the whole-chart settings stay', () => {
  const base = { title: { text: 'Kept' }, color: ['#111111', '#222222'], toolbox: { feature: { saveAsImage: {} } }, legend: { bottom: 0 }, xAxis: { type: 'category', name: 'Week' }, yAxis: { type: 'value', max: 50 }, series: [{ type: 'bar', label: { show: true }, gfm: { trend: { method: 'linear' } } }] };
  const tables = {
    default: ['Week, North, South', 'Aug 3, 4, 3', 'Aug 10, 6, 4', 'Aug 17, 5, 6', 'Aug 24, 8, 5'],
    candlestick: ['Day, Open, Close, Low, High', 'Mon, 10, 12, 9, 13', 'Tue, 12, 11, 10, 14'],
    range: ['Week, Low, High', 'Aug 3, 4, 9', 'Aug 10, 5, 8'],
    sankey: ['From, To, People', 'Finding, Taught, 40', 'Taught, Date, 12'],
    chord: ['From, To, People', 'Finding, Taught, 40', 'Taught, Date, 12'],
    graph: ['From, To, People', 'Finding, Taught, 40', 'Taught, Date, 12'],
    lines: ['Name, x1, y1, x2, y2', 'A, 0, 0, 1, 1', 'B, 1, 0, 0, 1'],
    calendar: ['Day, Lessons', '2026-08-03, 5', '2026-08-10, 8'],
    treemap: ['Unit, People', 'North / A, 4', 'North / B, 6', 'South / C, 5'],
    sunburst: ['Unit, People', 'North / A, 4', 'North / B, 6', 'South / C, 5'],
    tree: ['Unit, People', 'North / A, 4', 'North / B, 6', 'South / C, 5'],
  };
  for (const { id } of core.CHART_KINDS) {
    const option = core.applyKind(base, id);
    assert.equal(core.kindOf(option), id, id);
    assert.deepEqual(option.title, base.title, `${id} keeps the title`);
    assert.deepEqual(option.color, base.color, `${id} keeps the colours`);
    assert.deepEqual(option.toolbox, base.toolbox, `${id} keeps the toolbox`);
    assert.equal(checkOption(option).errors.length, 0, `${id} is a valid option`);
    const drawn = engine.chartOption({ rows: tables[id] ?? tables.default, option }, ctx);
    assert.ok(drawn, `${id} draws`);
    const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 360 });
    try { chart.setOption(drawn); assert.ok(chart.renderToSVGString().length > 500, id); }
    finally { chart.dispose(); }
  }
  const sideways = core.applyKind(base, 'sideways');
  assert.deepEqual([sideways.xAxis.type, sideways.xAxis.max, sideways.yAxis.type, sideways.yAxis.name], ['value', 50, 'category', 'Week']);
  assert.deepEqual(core.applyKind(sideways, 'line').xAxis, { name: 'Week', type: 'category' }, 'the axes turn back');
  assert.equal(core.applyKind(base, 'line').series[0].gfm.trend.method, 'linear', 'the trend line stays on charts with axes');
  assert.equal(core.applyKind(base, 'pie').series[0].gfm, undefined);
});

test('setting paths: lists and objects made on the way, empty ones removed, meaningful empties kept', () => {
  assert.deepEqual(core.setPath({}, 'series.1.label.show', true), { series: [{}, { label: { show: true } }] });
  assert.deepEqual(core.setPath({ title: { text: 'a' } }, 'title.text', undefined), {});
  assert.deepEqual(core.setPath({ series: [{ type: 'line', areaStyle: { opacity: 0.5 } }] }, 'series.0.areaStyle.opacity', undefined), { series: [{ type: 'line', areaStyle: {} }] });
  const o = { a: { b: 1 } };
  core.setPath(o, 'a.b', 2);
  assert.deepEqual(o, { a: { b: 1 } }, 'the option given is not changed');
  assert.equal(core.getPath({ series: [{ gfm: { trend: { method: 'linear' } } }] }, 'series.0.gfm.trend.method'), 'linear');
  assert.equal(core.getPath({}, 'x.y.z'), undefined);
});

test('the All options check: unknown names are warnings, wrong types and maps are mistakes; the schema knows ECharts 6', () => {
  assert.deepEqual(checkOption({ title: { text: 'x' }, series: [{ type: 'bar' }] }), { errors: [], warnings: [] });
  const bad = checkOption({ titel: {}, series: [{ type: 'map' }, { typ: 'bar' }, { type: 'barz', smoth: true }] });
  assert.deepEqual(bad.warnings, ['“titel” is not an ECharts setting; it is ignored.', 'Series 2: “typ” is not a series setting; it is ignored.', 'Series 3: “smoth” is not a series setting; it is ignored.']);
  assert.equal(bad.errors.length, 3);
  for (const key of ['dataset', 'dataZoom', 'visualMap', 'toolbox', 'brush', 'timeline', 'calendar', 'polar', 'singleAxis', 'parallel', 'parallelAxis', 'graphic', 'aria', 'matrix', 'thumbnail', 'gfm']) assert.ok(TOP_LEVEL.includes(key), key);
  const schema = optionSchema();
  assert.deepEqual(schema.properties.series.items.properties.type.enum, engine.SERIES_TYPES);
  assert.ok(!engine.SERIES_TYPES.includes('map'));
  assert.ok(JSON.stringify(schema).length < 200000, 'small enough to hand to Monaco');
});

test('a pasted table with commas and colons inside its cells is read as it is, never as mission numbers', () => {
  assert.deepEqual(core.parseLiteral("['Week\tNew people, goal: 10', 'W1\t3',]"), ['Week\tNew people, goal: 10', 'W1\t3']);
  assert.deepEqual(core.parseLiteral("{a: 1, b: ['x, y: z', \"q,}\"],}"), { a: 1, b: ['x, y: z', 'q,}'] });
  const tag = `<MissionChart chart-id="c7a7a7a" :rows="['Week\tNew people, goal: 10', 'W1\t3']" :option='{"series":[{"type":"bar"}]}' />`;
  const read = core.readChart(core.findChartTag(tag));
  assert.equal(read.source, 'table');
  assert.deepEqual(read.rows, ['Week\tNew people, goal: 10', 'W1\t3']);
  const out = core.writeChart(read);
  assert.ok(!out.includes(':query'));
  assert.deepEqual(core.readChart(core.findChartTag(out)).rows, read.rows);
  // Numbers the builder cannot read stop Edit chart instead of becoming mission numbers.
  assert.throws(() => core.readChart(core.findChartTag(`<MissionChart chart-id="c7a7a7b" :rows="someTable" :option='{"series":[{"type":"bar"}]}' />`)), /cannot read this chart's numbers/);
});

test("Studio's Title and Colours on an option chart are kept when the builder saves it", () => {
  const tag = `<MissionChart chart-id="c8b8b8b" title="From Studio" :colors="['#ff0000']" :rows="['Week\tN', 'W1\t3']" :option='{"series":[{"type":"bar"}]}' />`;
  const read = core.readChart(core.findChartTag(tag));
  assert.deepEqual(read.option.title, { text: 'From Studio' });
  assert.deepEqual(read.option.color, ['#ff0000']);
  const again = core.readChart(core.findChartTag(core.writeChart(read)));
  assert.deepEqual(again.option.title, { text: 'From Studio' });
  assert.deepEqual(again.option.color, ['#ff0000']);
  // The option's own title and colours win, as MissionChart.vue draws it.
  const own = core.readChart(core.findChartTag(`<MissionChart chart-id="c8b8b8c" title="Studio" :colors="['#ff0000']" :option='{"title":{"text":"Own"},"color":["#00ff00"],"series":[{"type":"bar"}]}' />`));
  assert.deepEqual(own.option.title, { text: 'Own' });
  assert.deepEqual(own.option.color, ['#00ff00']);
});
