// Round 8 review: charts drawn on the manager address (manager/safe-chart-option.mjs).
//
// A chart's settings are written in a slide, and Zone Leaders and Sister Training Leaders write slides. The chart
// builder of /studio (and the Whiteboard frames) draw them on the manager address, where the manager is signed in.
// ECharts writes a tooltip "formatter" text into the page as HTML, so a Zone Leader could put
// <img src=x onerror="…"> there and have it run with the manager's sign-in when the manager clicks Edit chart and
// points at the chart. These tests check that no such text reaches what the manager address draws:
//   1. the review's own case: a slide as a ZL could write it, read and composed exactly as the builder does;
//   2. every setting the file changes (tooltips anywhere, links, the data view), and that nothing else changes;
//   3. the builder and the Whiteboard frame really draw through it, and ECharts still draws the result.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import { plainTooltipText, safeChartOption } from '../manager/safe-chart-option.mjs';
import { locateChart, readChart } from '../manager/gfm-addon/lib/chart-builder-core.mjs';
import { chartView, viewOption } from '../manager/gfm-addon/lib/chart-engine.mjs';

const require = createRequire(import.meta.url);
const echarts = require('../manager/vendor/echarts.min.js');
const MANAGER = new URL('../manager/', import.meta.url);

const EVIL = '<img src=x onerror="document.title=\'PWNED:\'+document.domain">';

/** Every tooltip formatter text anywhere in an option. */
function formatters(value, found = []) {
  if (Array.isArray(value)) value.forEach(v => formatters(v, found));
  else if (value && typeof value === 'object') {
    for (const [key, v] of Object.entries(value)) {
      if (key === 'tooltip') for (const t of [].concat(v)) if (t && typeof t.formatter === 'string') found.push(t.formatter);
      formatters(v, found);
    }
  }
  return found;
}

test("the review's case: a ZL's tooltip text never reaches the builder's chart as HTML", () => {
  // A slide as a ZL could write it (the builder's own table form, with an advanced tooltip setting).
  const option = { title: { text: 'Baptisms' }, series: [{ type: 'bar', tooltip: { formatter: EVIL } }], tooltip: { formatter: EVIL, extraCssText: 'background:url(//x)' } };
  const content = `# Zone\n\n<MissionChart chart-id="c1" :rows='[["Week","Baptisms"],["1",3],["2",5]]' :option='${JSON.stringify(option).replace(/'/g, '&#39;')}' />\n`;
  const located = locateChart(content, { id: 'c1' });
  assert.ok(located.found, located.problem);
  const model = readChart(located.found);
  const view = chartView({ option: model.option, rows: model.rows, height: 360, chartId: 'c1' });
  const composed = viewOption(view, { dark: false, font: 'sans-serif', animate: false, width: 980, height: 360 });
  assert.ok(formatters(composed).some(f => f.includes('<img')), 'the engine passes the text on as written (it is also used on the deck address)');
  const drawn = safeChartOption(composed);
  const texts = formatters(drawn);
  assert.equal(texts.length, 2, 'the chart and series formatters are still there, as text');
  for (const text of texts) assert.doesNotMatch(text, /[<>]/, text);
  assert.equal(drawn.tooltip.renderMode, 'richText', 'ECharts draws the box as text itself, never as HTML');
  assert.equal(drawn.tooltip.extraCssText, undefined);
  assert.ok(texts.every(t => t === ''), 'the text was nothing but a tag, so nothing is left of it');
  assert.doesNotMatch(JSON.stringify(drawn), /<img/);
});

test('tooltips anywhere: text only, line breaks kept, no extra CSS', () => {
  assert.equal(plainTooltipText('{b}<br/>{c}<BR>{d}<br />x'), '{b}\n{c}\n{d}\nx');
  assert.equal(plainTooltipText('<b>{a}</b>: {c} <span style="color:red">!</span>'), '{a}: {c} !');
  assert.equal(plainTooltipText('<img src=x onerror=alert(1)'), 'img src=x onerror=alert(1)', 'an unclosed tag loses its <');
  assert.equal(plainTooltipText('{c} > 5 < 9'), '{c}  5  9');
  const option = {
    tooltip: [{ formatter: '{b}<br/>{c}' }],
    legend: { tooltip: { show: true, formatter: '<i>{name}</i>' } },
    toolbox: { tooltip: { formatter: '<u>x</u>', extraCssText: 'x' } },
    series: [{ type: 'pie', tooltip: { formatter: '<b>{b}</b>' }, data: [{ name: 'a', value: 1, tooltip: { formatter: '<script>x</script>' } }] }],
  };
  const safe = safeChartOption(option);
  assert.deepEqual(safe.tooltip, [{ formatter: '{b}\n{c}', renderMode: 'richText' }]);
  assert.deepEqual(safe.legend.tooltip, { show: true, formatter: '{name}' });
  assert.deepEqual(safe.toolbox.tooltip, { formatter: 'x' });
  assert.equal(safe.series[0].tooltip.formatter, '{b}');
  assert.equal(safe.series[0].data[0].tooltip.formatter, 'x');
  assert.equal(option.series[0].tooltip.formatter, '<b>{b}</b>', 'the option given is not changed');
  // A function (the engine's own number formats) stays as it is.
  const valueFormatter = v => `${v}%`;
  assert.equal(safeChartOption({ tooltip: { valueFormatter } }).tooltip.valueFormatter, valueFormatter);
});

test('links and the data view are left out; a chart without a tooltip gets none', () => {
  const safe = safeChartOption({
    title: [{ text: 'A', link: 'javascript:alert(1)', sublink: 'javascript:alert(2)', target: 'self' }, { text: 'B' }],
    toolbox: { feature: { saveAsImage: {}, dataView: { title: '<img src=x onerror=alert(1)>', lang: ['<b>x</b>'] } } },
    series: [{ type: 'treemap', nodeClick: 'link', data: [{ name: 'a', value: 1, link: 'javascript:alert(3)' }] }, { type: 'sunburst', nodeClick: 'rootToNode' }],
  });
  assert.deepEqual(safe.title, [{ text: 'A', target: 'self' }, { text: 'B' }]);
  assert.deepEqual(safe.toolbox, { feature: { saveAsImage: {} } }, 'saving as a picture stays; the data view (written as HTML) goes');
  assert.equal(safe.series[0].nodeClick, undefined, 'a treemap no longer opens a link on click');
  assert.equal(safe.series[1].nodeClick, 'rootToNode', 'other click behaviour stays');
  assert.equal('tooltip' in safe, false, 'no tooltip was asked for, none is added');
  assert.equal(safeChartOption(null), null);
  assert.equal(safeChartOption(undefined), undefined);
  const proto = safeChartOption(JSON.parse('{"__proto__":{"polluted":1},"series":[]}'));
  assert.equal(({}).polluted, undefined);
  assert.equal(Object.getPrototypeOf(proto), Object.prototype);
});

test('everything else draws exactly as written', () => {
  const option = {
    color: ['#00869e'], title: { text: 'Baptisms', subtext: 'Last 4 weeks', textStyle: { color: '#17394b' } },
    legend: { formatter: '{name} (weekly)' }, xAxis: { type: 'category', axisLabel: { formatter: '{value} wk' } }, yAxis: { type: 'value' },
    series: [{ type: 'bar', name: 'Baptisms', label: { show: true, formatter: '{c}' }, data: [3, 5, 4] }],
    graphic: [{ type: 'text', style: { text: 'Note' } }],
  };
  assert.deepEqual(safeChartOption(option), option);
});

test('the builder and the Whiteboard frame draw through it, and ECharts still draws the result', async () => {
  const builder = await fs.readFile(new URL('chart-builder.mjs', MANAGER), 'utf8');
  assert.match(builder, /import \{ safeChartOption \} from '\.\/safe-chart-option\.mjs'/);
  assert.match(builder, /const option = safeChartOption\(viewOption\(view, /);
  assert.match(builder, /if \(option\) this\.chart\.setOption\(option, \{ notMerge: true \}\)/);
  assert.equal((builder.match(/chart\.setOption\(/g) || []).length, 1, 'ECharts is given settings in that one place only');
  const whiteboard = await fs.readFile(new URL('whiteboard-chart.mjs', MANAGER), 'utf8');
  assert.match(whiteboard, /return safeChartOption\(viewOption\(view, ctx\)\)/);
  assert.match(whiteboard, /option = frameOption\(view, /);
  // ECharts accepts what is left and draws it (server-side drawing; tooltips are not part of it).
  const safe = safeChartOption({ tooltip: { trigger: 'axis', formatter: EVIL }, xAxis: { type: 'category', data: ['1', '2'] }, yAxis: { type: 'value' }, series: [{ type: 'bar', data: [3, 5] }] });
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 400, height: 240 });
  chart.setOption(safe);
  const svg = chart.renderToSVGString();
  chart.dispose();
  assert.match(svg, /<svg/);
  assert.doesNotMatch(svg, /<img|onerror/);
});
