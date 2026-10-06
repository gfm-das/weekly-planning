// The round-6 chart engine (lib/chart-engine.mjs): a chart is its numbers plus
// an ECharts option. Every series type is drawn with the vendored ECharts in
// server-side mode (no browser), so an option that ECharts cannot draw fails
// here. Run from slidev/:  node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as core from '../manager/gfm-addon/lib/chart-core.mjs';
import * as engine from '../manager/gfm-addon/lib/chart-engine.mjs';
import { canonical, cases, CSV, digest, OLD_CHART_DEFAULTS } from './chart-cases.mjs';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const echarts = require('../manager/vendor/echarts.min.js');
const ecStat = require('../manager/vendor/ecStat.min.js');
for (const t of Object.values(ecStat.transform)) echarts.registerTransform(t);
const ctx = { dark: false, font: 'Inter, sans-serif', animate: false, ecStat, width: 900, height: 360 };
const golden = new Map(JSON.parse(readFileSync(fileURLToPath(new URL('./fixtures/chart-golden.json', import.meta.url)), 'utf8')).cases.map(c => [c.name, c.digest]));

/** Draws an option with ECharts (SVG, server side) and answers the SVG. */
function draw(option) {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 360 });
  try {
    chart.setOption(option);
    return chart.renderToSVGString();
  }
  finally { chart.dispose(); }
}
const paths = svg => (svg.match(/<(path|polygon|polyline|rect|circle) /g) || []).length;
const compose = (rows, option, c = ctx) => engine.chartOption({ rows, option }, c);

const WEEKS = ['Week, New people being taught, Baptismal dates', 'Aug 3, 12, 4', 'Aug 10, 15, 5', 'Aug 17, 14, 7', 'Aug 24, 19, 6', 'Aug 31, 22, 9'];

test('which way a chart is drawn: a type means the older settings, typed series without one mean the option', () => {
  assert.equal(engine.isOptionChart({ type: 'bar', option: { series: [{ type: 'line' }] } }), false);
  assert.equal(engine.isOptionChart({ option: { yAxis: { min: 0 } } }), false, 'an override alone is the older way (a line chart)');
  assert.equal(engine.isOptionChart({ option: { series: [{ smooth: true }] } }), false, 'series without types change an older chart');
  assert.equal(engine.isOptionChart({ option: '{"series":[{"type":"bar"}]}' }), true);
  assert.equal(engine.isOptionChart({ option: { gfm: { kind: 'tile' } } }), true);
  assert.equal(engine.isOptionChart({ option: '{not json' }), false);
});

test('older charts draw exactly as before through the engine (the golden fingerprints)', () => {
  const failures = [];
  for (const c of cases().filter(x => x.kind === 'chart')) {
    const props = { ...OLD_CHART_DEFAULTS, ...c.props };
    const view = engine.chartView(props);
    const option = view.problem ? null : engine.viewOption(view, { font: 'Inter, sans-serif', ecStat, ...c.ctx });
    // The golden digest covers the table and the option, as the component would draw them.
    const table = core.parseRows(props.rows) ?? core.parseCsv(props.csv) ?? core.parseData(props.data);
    if (digest({ table, option: option ?? core.buildOption(table, props, { font: 'Inter, sans-serif', ecStat, ...c.ctx }) }) !== golden.get(c.name)) failures.push(c.name);
  }
  assert.deepEqual(failures, []);
});

test('binding: every column is drawn, the last series repeats, goal columns become the goal line', () => {
  const o = compose(WEEKS, { series: [{ type: 'bar' }] });
  assert.equal(o.dataset[0].source.length, 5);
  assert.deepEqual(o.dataset[0].dimensions.map(d => d.name), ['Week', 'New people being taught', 'Baptismal dates']);
  assert.deepEqual(o.series.map(s => [s.type, s.name, s.encode.y]), [['bar', 'New people being taught', 1], ['bar', 'Baptismal dates', 2]]);
  assert.ok(o.legend.length === 1, 'two series get a legend');
  assert.equal(o.xAxis[0].type, 'category');
  assert.ok(paths(draw(o)) > 10);
  // Mission numbers: the goal column is drawn as the goal line under a bar template.
  const answer = { table: { labels: ['2026-08-02', '2026-08-09', '2026-08-16'], series: [{ name: 'Actual', values: [3, 5, 4] }, { name: 'Goal set the week before', values: [4, 4, 5], role: 'goal' }] }, meta: { by: 'week', unit: 'count' } };
  const live = engine.chartOption({ query: { measures: ['friends_found.actual'] }, option: { series: [{ type: 'bar' }] } }, ctx, answer);
  assert.deepEqual(live.series.map(s => s.type), ['bar', 'line']);
  assert.equal(live.series[1].symbol, 'rect');
  assert.equal(live.xAxis[0].axisLabel.showMaxLabel, true, 'the latest week keeps its label');
  // A pasted column named as the goal (any capitalisation) is the goal line, not a second series for the trend's name.
  const goal = compose(['Week, Taught, Goal', 'Aug 3, 12, 14', 'Aug 10, 15, 14', 'Aug 17, 14, 16'], { gfm: { goal: { column: 'goal', lineStyle: { color: '#cf4545' } } }, series: [{ type: 'bar', gfm: { trend: { method: 'linear' } } }] });
  assert.deepEqual(goal.series.map(s => [s.type, s.name]), [['bar', 'Taught'], ['line', 'Goal'], ['line', 'Trend (linear)']]);
  assert.equal(goal.series[1].lineStyle.color, '#cf4545');
  // Horizontal bars: a category y axis reads the labels from y.
  const side = compose(WEEKS, { yAxis: { type: 'category' }, xAxis: { type: 'value' }, series: [{ type: 'bar' }] });
  assert.deepEqual(side.series[0].encode, { y: 0, x: 1, tooltip: [1] });
  // A series that names its column by heading takes that column only.
  const named = compose(WEEKS, { series: [{ type: 'line', encode: { x: 'Week', y: 'Baptismal dates' } }] });
  assert.equal(named.series.length, 1);
  assert.equal(named.series[0].name, 'Baptismal dates');
});

test('trend lines, reference lines and the number format', () => {
  const o = compose(WEEKS.slice(0, 1).map(r => r.replace(', Baptismal dates', '')).concat(WEEKS.slice(1).map(r => r.replace(/, \d+$/, ''))), {
    gfm: { format: { style: 'decimals', decimals: 1, suffix: ' people' } },
    series: [{ type: 'line', gfm: { trend: { method: 'polynomial', degree: 2, forecast: 2, color: '#d96b2b', style: 'dotted' } }, markLine: { data: [{ yAxis: 20, name: 'Goal' }, { type: 'average' }] } }],
  });
  const trend = o.series.find(s => /Trend/.test(s.name));
  assert.equal(trend.name, 'Trend (polynomial, degree 2)');
  assert.equal(trend.lineStyle.color, '#d96b2b');
  assert.deepEqual(trend.lineStyle.type, [2, 4]);
  const trendSet = o.dataset[trend.datasetIndex];
  assert.equal(trendSet.source.length, 7, 'five weeks and two forecast periods');
  assert.equal(trendSet.source[6][0], '+2');
  assert.equal(trend.markArea.label.formatter, 'Forecast');
  assert.equal(o.series[0].markLine.label.formatter({ name: 'Goal', value: 20 }), 'Goal 20.0 people');
  assert.equal(o.tooltip.valueFormatter(12), '12.0 people');
  assert.equal(o.yAxis[0].axisLabel.formatter(10), '10.0 people');
  assert.ok(o.legend[0].data.some(d => d.name.startsWith('Trend') && d.itemStyle.opacity === 0), 'the trend key is its dashed line');
  assert.ok(paths(draw(o)) > 5);
});

test('new series types draw: sankey, chord, graph, candlestick, matrix, theme river, parallel, calendar heat map, tree, boxplot, waterfall', () => {
  const flows = ['From, To, People', 'Finding, Taught, 40', 'Taught, Baptismal date, 12', 'Taught, Stopped, 20', 'Baptismal date, Baptized, 9'];
  const sankey = compose(flows, { series: [{ type: 'sankey' }] });
  assert.equal(sankey.series[0].links.length, 4);
  assert.deepEqual(sankey.series[0].data.map(d => d.name), ['Finding', 'Taught', 'Baptismal date', 'Stopped', 'Baptized']);
  assert.ok(paths(draw(sankey)) >= 8);
  const graph = compose(flows, { series: [{ type: 'graph', layout: 'circular' }] });
  assert.ok(graph.series[0].data.every(d => d.symbolSize >= 12));
  assert.ok(paths(draw(graph)) >= 5);
  const chord = compose(flows, { series: [{ type: 'chord' }] });
  assert.equal(chord.series[0].links.length, 4);
  assert.ok(paths(draw(chord)) >= 5);
  assert.match(engine.chartView({ rows: WEEKS, option: { series: [{ type: 'sankey' }] } }).problem, /from, to and a number/);

  const prices = ['Day, Open, Close, Low, High', 'Mon, 10, 12, 9, 13', 'Tue, 12, 11, 10, 14', 'Wed, 11, 15, 11, 16'];
  const candle = compose(prices, { series: [{ type: 'candlestick' }] });
  assert.deepEqual(candle.series[0].encode.y, [1, 2, 3, 4]);
  assert.ok(paths(draw(candle)) >= 6);

  const river = compose(WEEKS, { series: [{ type: 'themeRiver' }] });
  assert.equal(river.series[0].data.length, 10);
  assert.deepEqual(river.singleAxis[0].data, ['Aug 3', 'Aug 10', 'Aug 17', 'Aug 24', 'Aug 31']);
  assert.ok(paths(draw(river)) >= 2);

  const parallel = compose(WEEKS, { series: [{ type: 'parallel' }] });
  assert.equal(parallel.parallelAxis.length, 2);
  assert.ok(paths(draw(parallel)) >= 5);

  const days = ['Day, Lessons', '2026-08-03, 5', '2026-08-10, 8', '2026-08-17, 3', '2026-09-07, 9'];
  const calendar = compose(days, { series: [{ type: 'heatmap', coordinateSystem: 'calendar' }] });
  assert.deepEqual(calendar.calendar[0].range, ['2026-08-03', '2026-09-07']);
  assert.ok(calendar.visualMap.length === 1);
  assert.ok(paths(draw(calendar)) > 20);

  const tree = compose(['Unit, People', 'North / Frankfurt 1, 4', 'North / Frankfurt 2, 6', 'South / Mainz, 5'], { title: { text: 'Mission' }, series: [{ type: 'tree' }] });
  assert.equal(tree.series[0].data[0].name, 'Mission');
  assert.ok(paths(draw(tree)) >= 3);

  const matrix = compose(WEEKS, { series: [{ type: 'heatmap', coordinateSystem: 'matrix' }] });
  assert.deepEqual(matrix.matrix.y.data, ['New people being taught', 'Baptismal dates']);
  assert.ok(paths(draw(matrix)) > 5);

  const box = compose(['Week, North, South', '1, 4, 9', '2, 6, 8', '3, 5, 30', '4, 7, 7', '5, 6, 9'], { series: [{ type: 'boxplot' }] });
  assert.deepEqual(box.xAxis[0].data, ['North', 'South']);
  assert.equal(box.series[1].name, 'Unusual values');
  assert.ok(paths(draw(box)) >= 4);

  const fall = compose(['Step, People', 'Last month, 40', 'Found, 12', 'Moved, -5', 'Baptized, -3'], { series: [{ type: 'custom', renderItem: 'waterfall', label: { show: true } }] });
  assert.deepEqual(fall.xAxis[0].data, ['Last month', 'Found', 'Moved', 'Baptized', 'Total']);
  assert.equal(typeof fall.series[0].renderItem, 'function');
  assert.ok(draw(fall).includes('+12'));
});

test('components: polar, radar, dataZoom, visualMap, toolbox, brush, graphic, markPoint, multiple grids, timeline', () => {
  const polar = compose(WEEKS, { series: [{ type: 'bar', coordinateSystem: 'polar' }] });
  assert.deepEqual(polar.series[0].encode, { angle: 0, radius: 1 });
  assert.ok(paths(draw(polar)) > 5);
  const radar = compose(WEEKS, { series: [{ type: 'radar' }] });
  assert.equal(radar.radar[0].indicator.length, 5);
  assert.ok(paths(draw(radar)) > 5);
  const busy = compose(WEEKS, {
    title: { text: 'Everything', subtext: 'at once' }, toolbox: { feature: { saveAsImage: {}, dataView: {}, magicType: { type: ['line', 'bar'] }, restore: {} } },
    brush: { toolbox: ['rect', 'clear'] }, dataZoom: [{ type: 'inside' }, { type: 'slider' }], visualMap: { dimension: 1, seriesIndex: 0 },
    graphic: [{ type: 'text', right: 10, bottom: 40, style: { text: 'Sample' } }],
    series: [{ type: 'line', markPoint: { data: [{ type: 'max' }, { type: 'min' }] }, universalTransition: true }],
  });
  assert.equal(busy.series[0].markPoint.data[0].name, 'Highest');
  assert.equal(busy.grid[0].bottom, 6 + 34 + 44, 'room for the slider and the colour scale');
  assert.ok(draw(busy).includes('Sample'));
  const grids = compose(WEEKS, { gfm: { kind: 'multiples' }, series: [{ type: 'bar' }] });
  assert.equal(grids.grid.length, 2);
  assert.deepEqual(grids.series.map(s => s.xAxisIndex), [0, 1]);
  assert.ok(paths(draw(grids)) > 10);
  const steps = compose(['Zone, Week 1, Week 2, Week 3', 'North, 4, 6, 5', 'South, 3, 5, 8'], { timeline: {}, series: [{ type: 'bar' }] });
  assert.deepEqual(steps.baseOption.timeline.data, ['North', 'South']);
  assert.deepEqual(steps.options[1].series[0].data, [3, 5, 8]);
  assert.ok(paths(draw(steps)) > 5);
});

test('key numbers, pies, funnels and gauges from an option', () => {
  const tile = compose(WEEKS, { title: { text: 'This week' }, gfm: { kind: 'tile', target: 25 }, series: [{ type: 'line' }] });
  assert.equal(tile.title[1].text, '22');
  assert.match(tile.title[2].text, /88% of the goal/);
  const pie = compose(['Source, Friends', 'Members, 18', 'Online, 9', 'Finding, 0'], { series: [{ type: 'pie', radius: ['40%', '62%'], label: { show: true } }] });
  assert.equal(pie.series[0].data.length, 2, 'slices above 0 only');
  assert.equal(pie.series[0].label.formatter({ name: 'Online', value: 9, percent: 33 }), 'Online: 9 (33%)');
  const gauge = compose(['Measure, Actual, Goal', 'This week, 412, 450'], { series: [{ type: 'gauge' }] });
  assert.equal(gauge.series[0].max, 450);
  assert.equal(gauge.series[0].data[0].value, 412);
  for (const o of [tile, pie, gauge]) assert.ok(paths(draw(o)) > 1);
});

test('mistakes are sentences: unknown types, maps, empty tables, custom drawings', () => {
  assert.match(engine.chartView({ rows: WEEKS, option: { series: [{ type: 'map' }] } }).problem, /map file/);
  assert.match(engine.chartView({ rows: WEEKS, option: { series: [{ type: 'barz' }] } }).problem, /not a chart type/);
  assert.match(engine.chartView({ rows: WEEKS, option: { series: [{ type: 'custom' }] } }).problem, /waterfall, range, errorbar/);
  assert.equal(engine.chartView({ option: { series: [{ type: 'bar' }] } }).problem, 'Add data to show this chart.');
  assert.equal(engine.chartView({ option: { xAxis: { data: ['a', 'b'] }, yAxis: {}, series: [{ type: 'bar', data: [1, 2] }] } }).problem, '', 'numbers written in the option need no table');
  assert.equal(engine.chartView({ option: '{"series":[{"type":"bar"}]' }).mode, 'legacy', 'JSON that cannot be read leaves the older way (a line chart of the table)');
});

test('the adapter: older settings as an option for the builder', () => {
  const o = engine.legacyToOption({ type: 'bar', title: 'Baptismal dates', trend: 'polynomial', degree: 3, trendColor: '#d96b2b', forecast: 2, stack: false, horizontal: true, showValues: true, target: 30, targetLabel: 'Goal', average: true, format: 'percent', legend: 'bottom', goalColor: '#cf4545', xTitle: 'Week', yMax: 50, dataZoom: true, colors: ['#111111'] });
  assert.deepEqual(o.title, { text: 'Baptismal dates' });
  assert.deepEqual(o.color, ['#111111']);
  assert.equal(o.series[0].type, 'bar');
  assert.deepEqual(o.series[0].gfm.trend, { method: 'polynomial', degree: 3, forecast: 2, color: '#d96b2b' });
  assert.deepEqual(o.series[0].markLine.data.map(d => d.xAxis ?? d.type), [30, 'average']);
  assert.equal(o.yAxis.type, 'category');
  assert.equal(o.yAxis.inverse, true);
  assert.equal(o.xAxis.max, 50);
  assert.deepEqual(o.legend, { bottom: 0, left: 'center' });
  assert.deepEqual(o.gfm.format, { style: 'percent' });
  assert.equal(o.gfm.goal.lineStyle.color, '#cf4545');
  assert.equal(o.dataZoom.length, 2);
  assert.deepEqual(engine.legacyToOption({ type: 'area', smooth: true }).series, [{ type: 'line', areaStyle: {}, smooth: true }]);
  assert.deepEqual(engine.legacyToOption({ type: 'donut' }).series, [{ type: 'pie', radius: ['38%', '60%'] }]);
  assert.deepEqual(engine.legacyToOption({ type: 'waterfall' }).series, [{ type: 'custom', renderItem: 'waterfall' }]);
  assert.equal(engine.legacyToOption({ type: 'tile', target: 20 }).gfm.kind, 'tile');
  assert.equal(engine.legacyToOption({ type: 'line', multiples: true }).gfm.kind, 'multiples');
  assert.deepEqual(engine.legacyToOption({ type: 'line', seriesTypes: ['bar', 'line'] }).series.map(s => s.type), ['bar', 'line']);
  // The older override stays on top.
  assert.equal(engine.legacyToOption({ type: 'line', option: { xAxis: { axisLabel: { showMaxLabel: true } } } }).xAxis.axisLabel.showMaxLabel, true);
  // Every older chart of the gallery converts to an option the engine draws.
  for (const type of core.CHART_TYPES) {
    const csv = { gauge: CSV.gauge, pie: CSV.pie, donut: CSV.pie, funnel: CSV.pie, treemap: CSV.pie, sunburst: CSV.pie }[type] ?? CSV.two;
    const option = engine.legacyToOption({ type, trend: 'linear' });
    const drawn = engine.chartOption({ csv, option }, ctx);
    assert.ok(drawn, type);
    assert.ok(paths(draw(drawn)) > 0, type);
  }
});

test('dark slides get the dark palette; print never animates', () => {
  const dark = compose(WEEKS, { series: [{ type: 'line' }] }, { ...ctx, dark: true, animate: true });
  assert.equal(dark.color[0], core.PALETTE.dark[0]);
  assert.equal(dark.animation, undefined);
  assert.equal(compose(WEEKS, { animation: true, series: [{ type: 'line' }] }).animation, false);
  assert.ok(!JSON.stringify(canonical(dark)).includes('gfm'), 'no GFM words reach ECharts');
});
