// Unit tests of the chart engine (manager/gfm-addon/lib/chart-core.mjs).
// Plain Node, no packages: run from slidev/ with  node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as core from '../manager/gfm-addon/lib/chart-core.mjs';
import { FAVICON_DATA_URL, localFavicon, SLIDEV_DEFAULT_FAVICON } from '../manager/gfm-addon/lib/favicon.mjs';

const ecStat = createRequire(import.meta.url)('../manager/vendor/ecStat.min.js');
const ctx = { dark: false, font: 'Inter', animate: true, ecStat };
const one = core.parseCsv('Week,Friends; 1,12; 2,15; 3,14; 4,19; 5,22');
const two = core.parseCsv('Week,North,South; Aug 3,12,9; Aug 10,15,11; Aug 17,14,12; Aug 24,19,15; Aug 31,22,14');
const draw = (table, settings, extra = {}) => core.buildOption(table, settings, { ...ctx, ...extra });
const near = (a, b, digits = 2) => assert.ok(Math.abs(a - b) < 10 ** -digits, `${a} is not ${b}`);
const trendOf = option => option.series.find(s => s.symbol === 'none');

test('trend methods: names and old behaviour for unknown words', () => {
  assert.equal(core.trendMethod(''), 'none');
  assert.equal(core.trendMethod('None'), 'none');
  assert.equal(core.trendMethod('Polynomial'), 'polynomial');
  assert.equal(core.trendMethod('exponential'), 'exponential');
  assert.equal(core.trendMethod('log'), 'logarithmic');
  assert.equal(core.trendMethod('moving average'), 'moving-average');
  assert.equal(core.trendMethod('rolling'), 'moving-average');
  // Before, any other word drew a straight trend; it still does.
  assert.equal(core.trendMethod('yes'), 'linear');
});

test('fitTrend: linear, polynomial, exponential, logarithmic and forecasts', () => {
  const points = [[0, 12], [1, 15], [2, 14], [3, 19], [4, 22]];
  const linear = core.fitTrend(ecStat, points, 'linear', 2, { future: [5, 6] });
  assert.equal(linear.label, 'linear');
  near(linear.points[0][1], 11.6);
  near(linear.future[0][1], 23.6); // 2.4 * 5 + 11.6
  near(linear.future[1][1], 26.0);
  const poly = core.fitTrend(ecStat, points, 'polynomial', 2, { future: [5] });
  assert.equal(poly.label, 'polynomial, degree 2');
  near(poly.future[0][1], 12.457142857 + 0.685714286 * 5 + 0.428571429 * 25);
  const exp = core.fitTrend(ecStat, points, 'exponential', 2, { future: [5] });
  assert.equal(exp.label, 'exponential');
  near(exp.future[0][1], 11.986016 * Math.exp(0.147164773 * 5), 3);
  // Category positions start at 0; a logarithm needs them moved up by one.
  const log = core.fitTrend(ecStat, points, 'logarithmic', 2, { future: [5], shift: 1 });
  assert.equal(log.label, 'logarithmic');
  assert.deepEqual(log.points.map(p => p[0]), [0, 1, 2, 3, 4]);
  near(log.points[0][1], 11.0597, 3);
  near(log.future[0][1], 5.577346658 * Math.log(6) + 11.059699785, 3);
  assert.equal(core.fitTrend(ecStat, [[0, 3], [1, 0], [2, 5]], 'exponential', 2), null, 'exponential needs numbers above 0');
  assert.equal(core.fitTrend(ecStat, [[0, 3], [1, 4]], 'logarithmic', 2), null, 'x = 0 without a shift');
  assert.equal(core.fitTrend(ecStat, [[0, 3]], 'linear', 2), null, 'one point');
  assert.equal(core.fitTrend(ecStat, points, 'none', 2), null);
});

test('moving average: trailing window, forecast holds the last average', () => {
  const points = [[0, 10], [1, 20], [2, 30], [3, 40], [4, 50]];
  const ma = core.fitTrend(ecStat, points, 'moving-average', 2, { window: 3, future: [5, 6] });
  assert.equal(ma.label, 'moving average of 3');
  assert.deepEqual(ma.points, [[2, 20], [3, 30], [4, 40]]);
  assert.deepEqual(ma.future, [[5, 40], [6, 40]]);
  assert.equal(core.fitTrend(ecStat, points.slice(0, 2), 'moving-average', 2, { window: 3 }), null);
  assert.equal(core.fitTrend(ecStat, points, 'moving-average', 2, { window: 99 }), null, 'window above the points');
  assert.equal(core.fitTrend(ecStat, points, 'moving-average', 2, { window: 1 }).label, 'moving average of 2', 'at least 2');
});

test('future labels carry on numbers and dates, else +1, +2', () => {
  assert.deepEqual(core.futureLabels(['1', '2', '3'], 2), ['4', '5']);
  assert.deepEqual(core.futureLabels(['2024', '2025'], 1), ['2026']);
  assert.deepEqual(core.futureLabels(['2026-09-13', '2026-09-20'], 2), ['2026-09-27', '2026-10-04']);
  assert.deepEqual(core.futureLabels(['Aug 3', 'Aug 10'], 2), ['+1', '+2']);
  assert.deepEqual(core.futureLabels(['a'], 0), []);
  assert.deepEqual(core.nextWeeks(['2026-12-20', '2026-12-27'], 2), ['2027-01-03', '2027-01-10']);
});

test('number formats with prefix and suffix', () => {
  const plain = core.numberFormat({ format: 'plain' });
  assert.equal(plain.value(1234567.891), '1,234,567.89');
  assert.equal(plain.axis(25000), '25,000');
  assert.equal(core.numberFormat({ format: 'percent' }).value(45), '45%');
  assert.equal(core.numberFormat({ format: 'percent', decimals: 1 }).value(45), '45.0%');
  assert.equal(core.numberFormat({ format: 'compact' }).value(12500), '12.5K');
  assert.equal(core.numberFormat({ format: 'decimals', decimals: 2 }).value(3), '3.00');
  assert.equal(core.numberFormat({ format: 'decimals' }).value(3), '3.0');
  const money = core.numberFormat({ prefix: '€', suffix: ' total' });
  assert.equal(money.value(12.5), '€12.5 total');
  assert.equal(money.axis(15000), '€15K total');
  assert.equal(money.value(null), '–');
  // Auto without extras is exactly the old formatting.
  assert.equal(core.numberFormat({}).value, core.formatNumber);
});

test('trend line style: colour, width, dash, name', () => {
  const option = draw(one, { type: 'line', trend: 'polynomial', trendColor: '#ff0000', trendWidth: 4, trendStyle: 'dotted', trendLabel: 'Direction' });
  const trend = trendOf(option);
  assert.equal(trend.name, 'Direction');
  assert.equal(trend.color, '#ff0000');
  assert.equal(trend.lineStyle.color, '#ff0000');
  assert.equal(trend.lineStyle.width, 4);
  assert.deepEqual(trend.lineStyle.type, [2, 4]);
  assert.equal(trendOf(draw(one, { trend: 'linear', trendStyle: 'solid' })).lineStyle.type, 'solid');
  assert.equal(trendOf(draw(one, { trend: 'linear', trendWidth: 40 })).lineStyle.width, 8, 'width is capped');
  const both = draw(two, { type: 'bar', trend: 'linear', trendLabel: 'trend' });
  assert.deepEqual(both.series.filter(s => s.symbol === 'none').map(s => s.name), ['North – trend', 'South – trend']);
  // The legend key of a trend is the line alone.
  assert.deepEqual(both.legend.data.find(d => d.name === 'North – trend').itemStyle, { opacity: 0 });
});

test('forecast: more categories, padded data, a shaded band', () => {
  const option = draw(two, { type: 'line', trend: 'linear', forecast: 3 });
  assert.deepEqual(option.xAxis.data.slice(-4), ['Aug 31', '+1', '+2', '+3']);
  const north = option.series.find(s => s.name === 'North');
  assert.equal(north.data.length, 8);
  assert.deepEqual(north.data.slice(-3), [null, null, null]);
  const trend = option.series.find(s => s.name === 'North trend (linear)');
  assert.equal(trend.data.length, 8);
  assert.ok(trend.data.every(v => typeof v === 'number'));
  assert.deepEqual(trend.markArea.data, [[{ xAxis: 4 }, { xAxis: 7 }]]);
  assert.match(option.aria.label.description, /Forecast for 3 more periods/);
  // No trend, no forecast.
  assert.equal(draw(two, { type: 'line', forecast: 3 }).xAxis.data.length, 5);
  // KPI charts give their own labels (the next Sundays).
  const kpi = draw(one, { type: 'bar', trend: 'linear', forecast: 2, futureLabels: ['Sep 27', 'Oct 4'] });
  assert.deepEqual(kpi.xAxis.data.slice(-2), ['Sep 27', 'Oct 4']);
});

test('scatter forecast continues the x steps', () => {
  const table = core.parseCsv('Lessons,Dates; 20,2; 30,4; 40,5');
  const option = draw(table, { type: 'scatter', trend: 'linear', forecast: 2 });
  const trend = trendOf(option);
  assert.deepEqual(trend.data.map(p => p[0]), [20, 30, 40, 50, 60]);
});

test('target and average lines', () => {
  const option = draw(two, { type: 'bar', target: 30, targetLabel: 'Goal for the month', targetColor: '#123456', average: true, averageColor: '#654321' });
  const first = option.series[0].markLine.data;
  assert.equal(first[0].yAxis, 30);
  assert.equal(first[0].lineStyle.color, '#123456');
  assert.equal(first[0].label.formatter, 'Goal for the month 30');
  assert.equal(first[1].type, 'average');
  assert.equal(first[1].lineStyle.color, '#654321');
  assert.equal(option.series[1].markLine.data.length, 1, 'the target is drawn once');
  assert.equal(first[1].label.position, undefined, 'the first average is labelled at the end');
  assert.equal(option.series[1].markLine.data[0].label.position, 'insideStartTop', 'the next one at the start');
  assert.equal(option.yAxis.max, 40, 'room for a target above every value');
  assert.equal(draw(two, { type: 'bar', target: 10 }).yAxis.max, undefined);
  assert.equal(draw(two, { type: 'bar', target: 30, yMax: 50 }).yAxis.max, 50);
});

test('a goal column is drawn as the goal line', () => {
  const table = core.parseCsv('Week,Actual,Goal; 1,10,12; 2,11,12; 3,13,14');
  const option = draw(table, { type: 'bar', goal: 'goal', goalColor: '#ff00ff', trend: 'linear' });
  const goal = option.series.find(s => s.name === 'Goal');
  assert.equal(goal.type, 'line');
  assert.equal(goal.symbol, 'rect');
  assert.equal(goal.color, '#ff00ff');
  assert.equal(option.series.filter(s => s.symbol === 'none').length, 1, 'no trend for the goal');
  assert.equal(draw(table, { type: 'bar', goal: 'Budget' }).series.find(s => s.name === 'Goal').type, 'bar', 'unknown column');
});

test('stack, horizontal, smooth and one type per series', () => {
  const stacked = draw(two, { type: 'bar', stack: true, trend: 'linear' });
  assert.deepEqual(stacked.series.filter(s => s.type === 'bar').map(s => s.stack), ['total', 'total']);
  const trends = stacked.series.filter(s => s.symbol === 'none');
  assert.equal(trends.length, 1);
  assert.equal(trends[0].name, 'Total trend (linear)');
  const sideways = draw(two, { type: 'bar', horizontal: true, showValues: true });
  assert.equal(sideways.xAxis.type, 'value');
  assert.equal(sideways.yAxis.type, 'category');
  assert.equal(sideways.yAxis.inverse, true);
  assert.equal(sideways.series[0].label.position, 'right');
  assert.equal(draw(two, { type: 'line', horizontal: true }).xAxis.type, 'category', 'horizontal is for bars');
  assert.equal(draw(two, { type: 'line', smooth: true }).series[0].smooth, true);
  const combo = draw(two, { type: 'line', seriesTypes: ['bar', 'line'] });
  assert.deepEqual(combo.series.map(s => s.type), ['bar', 'line']);
  assert.equal(combo.xAxis.boundaryGap, true);
  assert.equal(combo.tooltip.axisPointer.type, 'shadow');
  assert.deepEqual(draw(two, { type: 'bar', seriesTypes: 'bar, area' }).series.map(s => s.areaStyle ? 'area' : s.type), ['bar', 'area']);
});

test('legend positions', () => {
  assert.equal(draw(one, { type: 'line' }).legend, undefined, 'auto: one series, no legend');
  assert.equal(draw(one, { type: 'line', legend: 'top' }).legend.top, 0);
  const bottom = draw(two, { type: 'line', legend: 'bottom' });
  assert.equal(bottom.legend.bottom, 0);
  assert.equal(bottom.grid.bottom, 32);
  const right = draw(two, { type: 'line', legend: 'right' });
  assert.equal(right.legend.orient, 'vertical');
  assert.equal(right.grid.right, '24%');
  assert.equal(draw(two, { type: 'line', legend: 'none' }).legend, undefined);
  assert.equal(draw(core.parseCsv('A,B; x,1; y,2'), { type: 'pie', legend: 'bottom' }).legend.bottom, 0);
  assert.equal(draw(core.parseCsv('A,B; x,1; y,2'), { type: 'pie' }).legend, undefined);
});

test('axes: titles, limits, turned labels; value labels; zoom', () => {
  const option = draw(two, { type: 'line', xTitle: 'Week', yTitle: 'People', yMin: 5, yMax: 30, labelRotate: 45 });
  assert.equal(option.xAxis.name, 'Week');
  assert.equal(option.yAxis.name, 'People');
  assert.equal(option.yAxis.min, 5);
  assert.equal(option.yAxis.max, 30);
  assert.equal(option.xAxis.axisLabel.rotate, 45);
  assert.equal(option.xAxis.axisLabel.alignMinLabel, undefined);
  const inside = draw(two, { type: 'bar', showValues: true, valuePosition: 'inside' });
  assert.equal(inside.series[0].label.position, 'inside');
  assert.equal(inside.series[0].label.color, '#ffffff');
  const zoom = draw(two, { type: 'line', dataZoom: true });
  assert.deepEqual(zoom.dataZoom.map(z => z.type), ['inside', 'slider']);
  assert.equal(draw(two, { type: 'line', dataZoom: true }, { animate: false }).dataZoom, undefined, 'not in print');
});

test('new chart types', () => {
  const heat = draw(two, { type: 'heatmap', showValues: true });
  assert.equal(heat.series[0].data.length, 10);
  assert.deepEqual([heat.visualMap.min, heat.visualMap.max], [9, 22]);
  assert.deepEqual(heat.yAxis.data, ['North', 'South']);
  const radar = draw(two, { type: 'radar' });
  assert.equal(radar.radar.indicator.length, 5);
  assert.equal(radar.radar.indicator[4].max, 25, 'nice maximum per spoke');
  assert.equal(draw(two, { type: 'radar', max: 50 }).radar.indicator[0].max, 50);
  const funnel = draw(core.parseCsv('Stage,People; Found,40; Taught,25; Date,0; Baptized,6'), { type: 'funnel' });
  assert.deepEqual(funnel.series[0].data.map(d => d.name), ['Found', 'Taught', 'Baptized']);
  assert.equal(funnel.series[0].sort, 'none');
  const table = core.parseCsv('Area,Friends; North / Frankfurt 1,5; North / Frankfurt 2,3; South > Mainz,4; South,2');
  const tree = draw(table, { type: 'treemap' }).series[0].data;
  assert.deepEqual(tree.map(n => [n.name, n.value]), [['North', 8], ['South', 6]]);
  assert.equal(tree[0].children.length, 2);
  assert.equal(draw(table, { type: 'sunburst' }).series[0].type, 'sunburst');
  const box = core.boxStats([1, 2, 3, 4, 5, 6, 7, 8, 100]);
  assert.deepEqual([box.q1, box.median, box.q3], [3, 5, 7]);
  assert.deepEqual(box.outliers, [100]);
  assert.equal(box.high, 8);
  const boxplot = draw(two, { type: 'boxplot' });
  assert.deepEqual(boxplot.series[0].data[0].value, [12, 14, 15, 19, 22]);
  const fall = draw(core.parseCsv('Step,Change; Start,10; Found,5; Moved,-3; Baptized,2'), { type: 'waterfall', showValues: true });
  assert.deepEqual(fall.xAxis.data, ['Start', 'Found', 'Moved', 'Baptized', 'Total']);
  assert.deepEqual(fall.series[0].data.map(d => d.value.slice(1, 3)), [[0, 10], [10, 15], [15, 12], [12, 14], [0, 14]]);
  assert.equal(typeof fall.series[0].renderItem, 'function');
  // The first bar is where it starts: no sign, the start colour (as the total).
  const colors = fall.series[0].data.map(d => d.itemStyle.color);
  assert.equal(colors[0], colors[4]);
  assert.notEqual(colors[1], colors[2], 'rises and falls differ');
  const tip = i => fall.tooltip.formatter({ dataIndex: i, name: fall.xAxis.data[i], data: fall.series[0].data[i] });
  assert.equal(tip(0), 'Start<br><b>10</b>');
  assert.equal(tip(2), 'Moved<br><b>−3</b> (now 12)');
  assert.equal(tip(4), 'Total<br><b>14</b>');
  assert.equal(fall.xAxis.axisLabel.interval, 0, 'every label is shown');
  assert.equal(fall.xAxis.axisLabel.formatter('Came back to church'), 'Came back to\nchurch', 'long labels over two lines, between words');
  // Long spoke names wrap instead of being cut off at the chart's edge.
  assert.equal(radar.radar.axisName.formatter('New members at sacrament meeting'), 'New members at\nsacrament\nmeeting');
  assert.equal(core.wrapWords('Friends found', 16), 'Friends found');
});

test('tooltips written as HTML escape every name and number (unit names come from the database)', () => {
  const bad = '<img src=x onerror=alert(1)>';
  const safe = '&lt;img src=x onerror=alert(1)&gt;';
  const clean = (out, what) => {
    assert.equal(typeof out, 'string', what);
    assert.ok(!out.includes('<img'), `${what}: ${out}`);
    assert.ok(out.includes(safe), `${what}: the name is still shown, escaped: ${out}`);
  };
  assert.equal(core.escapeHtml(`${bad} & "it's"`), `${safe} &amp; &quot;it&#39;s&quot;`);
  assert.equal(core.escapeHtml(null), '');
  const grid = core.parseCsv(`Week,${bad},South; ${bad},12,9; Aug 10,15,11; Aug 17,14,12`);
  const heat = draw(grid, { type: 'heatmap', prefix: '<i>', suffix: '"&' });
  clean(heat.tooltip.formatter({ value: [0, 0, 12] }), 'heatmap');
  assert.ok(heat.tooltip.formatter({ value: [1, 1, 11] }).includes('&lt;i&gt;11&quot;&amp;'), 'prefix and suffix escaped too');
  const funnel = draw(core.parseCsv(`Stage,People; ${bad},40; Taught,25; Baptized,6`), { type: 'funnel' });
  clean(funnel.tooltip.formatter({ name: bad, value: 40 }), 'funnel');
  clean(funnel.tooltip.formatter({ name: 'Taught', value: 25 }), 'funnel, the first stage in "% of"');
  for (const type of ['treemap', 'sunburst']) {
    const option = draw(core.parseCsv(`Area,Friends; ${bad} / One,5; South,2`), { type });
    clean(option.tooltip.formatter({ name: 'One', value: 5, treePathInfo: [{ name: '' }, { name: bad }, { name: 'One' }] }), type);
    clean(option.tooltip.formatter({ name: bad, value: 5 }), `${type} without a path`);
  }
  const box = draw(core.parseCsv(`Week,${bad},South; 1,1,2; 2,2,3; 3,3,4; 4,4,5; 5,100,6`), { type: 'boxplot' });
  clean(box.tooltip.formatter({ seriesType: 'boxplot', name: bad, data: { value: [1, 2, 3, 4, 5] } }), 'boxplot');
  clean(box.tooltip.formatter({ seriesType: 'scatter', name: bad, value: [0, 100] }), 'boxplot, unusual value');
  const fall = draw(core.parseCsv(`Step,Change; ${bad},10; ${bad} 2,5; Moved,-3`), { type: 'waterfall' });
  for (const i of [0, 1]) clean(fall.tooltip.formatter({ dataIndex: i, name: fall.xAxis.data[i], data: fall.series[0].data[i] }), `waterfall ${i}`);
  // The other types keep ECharts' own tooltip, which escapes names and values itself.
  for (const settings of [{ type: 'bar' }, { type: 'line' }, { type: 'area' }, { type: 'scatter' }, { type: 'pie' }, { type: 'donut' }, { type: 'radar' }, { type: 'line', multiples: true }]) {
    const option = draw(grid, settings);
    assert.equal(option.tooltip?.formatter, undefined, `${JSON.stringify(settings)} uses the escaping default tooltip`);
  }
});

test('key number tile: latest value, change, share of the goal, sparkline', () => {
  const table = core.parseCsv('Week,Actual,Goal; Sep 6,400,440; Sep 13,398,440; Sep 20,412,450');
  const option = draw(table, { type: 'tile', title: 'Sacrament attendance' }, { height: 300 });
  assert.equal(option.title[1].text, '412');
  assert.equal(option.title[2].text, '▲ 14 from Sep 13   ·   92% of the goal (450)');
  assert.equal(option.series[0].data.length, 3);
  assert.match(option.aria.label.description, /Up 14 from Sep 13/);
  const noGoal = draw(core.parseCsv('W,Friends; 1,5; 2,5'), { type: 'tile' });
  assert.equal(noGoal.title[1].text, 'Same as 1');
  assert.equal(draw(core.parseCsv('W,Friends; 1,5'), { type: 'tile', target: 10 }).title[1].text, '50% of the goal (10)');
});

test('small multiples: one panel per series on one scale', () => {
  const table = core.parseCsv('Week,A,B,C; 1,5,9,12; 2,6,8,14; 3,7,10,13');
  const option = draw(table, { type: 'bar', multiples: true, trend: 'linear' });
  assert.equal(option.grid.length, 3);
  assert.equal(option.xAxis.length, 3);
  assert.deepEqual(option.yAxis.map(y => y.max), [15, 15, 15]);
  assert.deepEqual(option.series.map(s => s.xAxisIndex), [0, 0, 1, 1, 2, 2]);
  assert.equal(draw(one, { type: 'line', multiples: true }).grid.left, 4, 'one series: an ordinary chart');
  const lines = draw(table, { type: 'line', multiples: true });
  assert.equal(lines.xAxis[0].axisLabel.alignMaxLabel, 'right', 'labels stay inside their own panel');
  assert.equal(option.xAxis[0].axisLabel.alignMaxLabel, undefined, 'bars are centred already');
});

test('chart problems for the new types', () => {
  const zero = core.parseCsv('A,B; x,0; y,-1');
  for (const type of ['funnel', 'treemap', 'sunburst']) assert.equal(core.chartProblem(zero, type), 'Add numbers above 0 to show this chart.');
  assert.equal(core.chartProblem(zero, 'waterfall'), '');
  assert.equal(core.chartProblem(core.parseCsv('A,B; x,; y,'), 'tile'), 'Add numbers to show this chart.');
  assert.equal(core.chartType('HEATMAP'), 'heatmap');
  assert.equal(core.chartType('sparkline'), 'line');
});

test('the advanced override is checked and merged last', () => {
  assert.deepEqual(core.readOverride('{"yAxis":{"min":0}}'), { value: { yAxis: { min: 0 } }, problem: '' });
  assert.match(core.readOverride('{yAxis:').problem, /not valid JSON/);
  assert.match(core.readOverride('[1,2]').problem, /must be a list of settings/);
  assert.deepEqual(core.readOverride(''), { value: null, problem: '' });
  const polluted = core.readOverride('{"__proto__":{"hacked":true},"a":{"constructor":{"x":1},"b":2}}');
  assert.deepEqual(polluted.value, { a: { b: 2 } });
  assert.equal({}.hacked, undefined);
  let deep = {};
  const root = deep;
  for (let i = 0; i < 20; i++) deep = deep.x = {};
  assert.match(core.readOverride(root).problem, /nested too deeply/);
  const option = draw(two, { type: 'line', option: { yAxis: { min: 0, splitLine: { show: false } }, series: [{ smooth: true }], legend: null } });
  assert.equal(option.yAxis.min, 0);
  assert.equal(option.yAxis.splitLine.show, false);
  assert.equal(option.yAxis.axisLabel.fontSize, 12, 'other settings stay');
  assert.equal(option.series[0].smooth, true);
  assert.equal(option.series[1].smooth, undefined);
  assert.equal('legend' in option, false, 'null removes');
  assert.equal(draw(two, { type: 'line', option: '{"broken' }).series.length, 2, 'a broken override is left out');
  const merged = core.mergeOption({ xAxis: [{ a: 1 }, { a: 2 }], color: ['#1'] }, { xAxis: { b: 3 }, color: ['#2', '#3'] });
  assert.deepEqual(merged, { xAxis: [{ a: 1, b: 3 }, { a: 2, b: 3 }], color: ['#2', '#3'] });
});

test('live charts: table, chart types, forecast weeks, pass-through settings', () => {
  const list = [
    { week: '2026-09-06', friends_found: { actual: 40, goal: null } },
    { week: '2026-09-13', friends_found: { actual: 44, goal: 0 } },
    { week: '2026-09-20', friends_found: { actual: 47, goal: 50 } },
  ];
  const props = { kpi: 'Friends found', chart: 'tile', trend: 'linear', forecast: 2, showGoal: true, trendColor: '#ff0000', colors: ['#000000'], unknown: 1 };
  const { table, settings } = core.kpiChart(list, props, 'Friends found');
  assert.deepEqual(table.series[1].values, [null, null, 50], 'a goal of 0 is a gap');
  assert.equal(settings.type, 'tile');
  assert.equal(settings.trendColor, '#ff0000');
  assert.deepEqual(settings.colors, ['#000000']);
  assert.equal(settings.unknown, undefined);
  assert.deepEqual(settings.futureLabels, ['Sep 27', 'Oct 4']);
  assert.equal(core.kpiChart(list, { ...props, chart: 'area' }, '').settings.type, 'area');
  assert.equal(core.kpiChart(list, { ...props, chart: 'pie' }, '').settings.type, 'bar');
  assert.equal(core.kpiChart(list, { ...props, trend: 'none' }, '').settings.futureLabels, undefined);
  assert.equal(core.kpiChart([], props, '').table, null);
  assert.equal(core.kpiWeekCount('abc'), 12);
  assert.equal(core.kpiWeekCount(500), 104);
  assert.equal(core.KPI_FETCH_WEEKS, 104);
});

test('key indicator names: New people being taught, and decks written with the old name still work', () => {
  assert.equal(core.KPI_NAMES.friends_found, 'New people being taught');
  for (const name of ['Friends found', 'friends found', 'FRIENDS FOUND', ' Friends  found ', 'friends_found', 'New people being taught', 'new people being taught'])
    assert.equal(core.kpiId(name), 'friends_found', name);
  assert.equal(core.kpiId('Sacrament attendance'), 'sacrament_attendance');
  assert.equal(core.kpiId('nothing like it'), 'friends_found');
  // <MissionKpiChart kpi="Friends found"> without a title is headed with the new name.
  const heading = core.KPI_NAMES[core.kpiId('Friends found')];
  const { settings } = core.kpiChart([{ week: '2026-09-20', friends_found: { actual: 3, goal: 4 } }], { kpi: 'Friends found' }, heading);
  assert.equal(settings.title, 'New people being taught');
  assert.equal(core.queryProblem({ table: { labels: [], series: [] }, meta: {} }), 'No numbers for these weeks yet.');
});

test('one request of 104 weeks answers every chart (last N weeks)', () => {
  // portal-api answers the last N reported weeks, oldest first (ORDER BY sunday
  // DESC LIMIT N, reversed): the last N of the 104-week answer are the same.
  const all = Array.from({ length: 17 }, (_, i) => ({ week: `w${i}` }));
  const answer = n => all.slice(-Math.min(n, all.length));
  for (const n of [1, 12, 16, 26, 104]) assert.deepEqual(answer(104).slice(-n), answer(n));
});

test('local favicon replaces only Slidev\'s default', () => {
  const html = `<link rel="icon" href="${SLIDEV_DEFAULT_FAVICON}"><link rel="icon" href="/mine.png">`;
  const out = localFavicon(html);
  assert.ok(out.includes(FAVICON_DATA_URL));
  assert.ok(out.includes('/mine.png'));
  assert.ok(!out.includes('cdn.jsdelivr.net'));
  assert.ok(!/["'<>]/.test(FAVICON_DATA_URL), 'safe inside an attribute');
});
