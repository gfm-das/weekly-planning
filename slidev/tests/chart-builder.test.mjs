// The chart builder's non-visual parts (manager/gfm-addon/lib/chart-builder-core.mjs)
// and database charts in the chart engine (queryChart). Plain Node, no packages.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as core from '../manager/gfm-addon/lib/chart-builder-core.mjs';
import { buildOption, parseRows, queryChart, queryProblem } from '../manager/gfm-addon/lib/chart-core.mjs';
import { normalizeSpec, pinnedKeys, specKey } from '../manager/gfm-addon/lib/chart-spec.mjs';
import transformers from '../manager/gfm-addon/setup/transformers.ts';

const ecStat = createRequire(import.meta.url)('../manager/vendor/ecStat.min.js');
const ctx = { dark: false, font: 'Inter', animate: false, ecStat };

test('chartTag writes a database chart: defaults left out, the query pinned as written', () => {
  const spec = normalizeSpec({ measures: ['friends_found.actual', 'friends_found.previous_goal'], level: 'zone', weeks: 8 });
  const tag = core.chartTag({ props: { type: 'bar', title: 'Friends "found" & kept', trend: 'polynomial', degree: 3, trendColor: '#d96b2b', showValues: true, height: 360, legend: 'auto', colors: ['#00869e', "#it's"], stack: false, forecast: 2 }, spec, option: '{"yAxis":{"name":"<People>"}}' });
  assert.equal(tag, `<MissionChart type="bar" title="Friends &quot;found&quot; &amp; kept" trend="polynomial" :degree="3" trend-color="#d96b2b" :colors="['#00869e', '#it\\'s']" show-values :forecast="2" :query='${specKey(spec)}' :option='{"yAxis":{"name":"\\u003cPeople\\u003e"}}' />`);
  // What the tag holds is exactly what a viewer's chart may ask for.
  assert.ok(pinnedKeys(tag).has(specKey(spec)));
});

test('chartTag writes a pasted table as rows Studio can edit', () => {
  const rows = core.tableRows('Week\tFriends\nAug 3\t12,5\n\nAug 10\t15');
  assert.deepEqual(rows, ['Week\tFriends', 'Aug 3\t12,5', 'Aug 10\t15']);
  const tag = core.chartTag({ props: { type: 'line' }, rows });
  assert.equal(tag, `<MissionChart type="line" :rows="['Week\\tFriends', 'Aug 3\\t12,5', 'Aug 10\\t15']" />`);
  assert.deepEqual(core.tableRows('Week,A; 1,2; 2,3'), ['Week,A', '1,2', '2,3']);
  assert.equal(core.tableRows('Week,A'), null);
  // The rows draw the same table as the pasted text.
  assert.deepEqual(parseRows(rows).series[0].values, [12.5, 15]);
});

test('reading a chart back: the same tag, unknown attributes kept', () => {
  const spec = normalizeSpec({ measures: ['sacrament_attendance.actual'], level: 'district', by: 'unit', weeks: 4, sort: 'desc', top: 5 });
  const written = core.chartTag({ props: { type: 'bar', title: 'Sacrament', horizontal: true, target: 40, colors: ['#123456'] }, spec, keep: ['v-click', 'class="mt-4"'] });
  const found = core.findChartTag(`<div v-drag="[1,2,3,4]">\n${written}\n</div>`);
  assert.equal(found.tag, 'MissionChart');
  const { model, notes } = core.tagToModel(found);
  assert.deepEqual(notes, []);
  assert.deepEqual(model.spec, spec);
  assert.deepEqual(model.keep, ['v-click', 'class="mt-4"']);
  assert.equal(core.chartTag(model), written);
});

test('reading a chart written by hand: csv, bound numbers, kebab and camel case', () => {
  const found = core.findChartTag(`<MissionChart type="line" title="Lessons" trend="linear" :height="440" showValues trend-style="dotted" csv="\nWeek,Lessons\nAug 3,12\nAug 10,15\n" />`);
  const { model } = core.tagToModel(found);
  assert.equal(model.source, 'table');
  assert.deepEqual(model.rows, ['Week,Lessons', 'Aug 3,12', 'Aug 10,15']);
  assert.equal(model.props.height, 440);
  assert.equal(model.props.showValues, true);
  assert.equal(model.props.trendStyle, 'dotted');
});

test('a live key indicator chart becomes the same chart from mission numbers', () => {
  const found = core.findChartTag(`<MissionKpiChart kpi="Friends found" :weeks="16" chart="line" trend="polynomial" :degree="2" :height="312" trend-color="#ff0000" v-click />`);
  assert.equal(found.tag, 'MissionKpiChart');
  const { model, notes } = core.tagToModel(found);
  assert.equal(notes.length, 1);
  assert.deepEqual(model.spec.measures, ['friends_found.actual', 'friends_found.previous_goal']);
  assert.equal(model.spec.weeks.last, 16);
  assert.equal(model.props.type, 'line');
  assert.equal(model.props.trend, 'polynomial');
  assert.equal(model.props.trendColor, '#ff0000');
  assert.deepEqual(model.keep, ['v-click']);
  const noGoal = core.tagToModel(core.findChartTag('<MissionKpiChart kpi="sacrament_attendance" :show-goal="false" />')).model;
  assert.deepEqual(noGoal.spec.measures, ['sacrament_attendance.actual']);
  assert.equal(noGoal.props.type, 'bar');
  assert.equal(noGoal.props.trend, 'linear', 'the key indicator chart draws a trend unless told not to');
});

test('changing a slide: only the chart, and only where it still is', () => {
  const content = ['# Title', '', 'Some text', '', '<div class="x">', '  <MissionChart type="bar" csv="A,B; 1,2" />', '</div>', '', 'After'].join('\n');
  const range = [4, 7];
  const block = core.blockAt(content, range);
  const next = core.replaceChart(content, range, '<MissionChart type="line" />');
  assert.equal(next, ['# Title', '', 'Some text', '', '<div class="x">', '  <MissionChart type="line" />', '</div>', '', 'After'].join('\n'));
  // Lines added above the chart meanwhile: found again by its text.
  const moved = `New line\n${content}`;
  assert.deepEqual(core.locateBlock(moved, range, block), [5, 8]);
  // The chart itself changed meanwhile: not found, nothing is replaced.
  assert.equal(core.locateBlock(content.replace('bar', 'area'), range, block), null);
  // Two copies: ambiguous, so not found.
  assert.equal(core.locateBlock(`${content}\n${block}`, [0, 3], block), null);
  assert.equal(core.replaceChart(content, [0, 3], '<MissionChart />'), null, 'no chart in those lines');
  assert.equal(core.insertChart('# A\n\ntext\n\n', '<MissionChart type="bar" />'), '# A\n\ntext\n\n<MissionChart type="bar" />');
  assert.equal(core.insertChart('# A\nx\ny', '<C />', [1, 2]), '# A\nx\n\n<C />\ny');
});

// Fingerprints computed by slidev-addon-studio 0.3.1 itself (node/html-scan.ts
// + shared/signature.ts, the data-studio-sig it stamps on each tag).
const SIDE_BY_SIDE = '<div class="grid grid-cols-2 gap-4"><MissionChart type="bar" title="Left chart" csv="W,A; 1,2; 2,3" /><MissionChart type="line" title="Right chart" csv="W,B; 1,5; 2,6" /></div>';
const STUDIO_SIGS = [
  [SIDE_BY_SIDE, ['17htkwc', '1k00f5n']],
  [`<MissionChart type="bar" title="Sacrament"\n  :query='{"level":"zone","measures":["sacrament_attendance.actual"],"sort":"desc","weeks":{"last":4},"x":">"}'\n  :colors="['#00869e', '#d96b2b']" />`, ['iwmmjs']],
  ['<div v-drag="[10,20,300,200]" class="x"><MissionChart v-drag="[1,2,3,4]" type="pie" :pos="[1,2]" csv="A,B; x,1" /> <mission-chart type="bar" csv="A,B; y,2"/></div>', ['1iklhd0', '470ks2']],
];

test("Studio's fingerprint of each chart tag, as Studio computes it", () => {
  for (const [block, sigs] of STUDIO_SIGS)
    assert.deepEqual(core.findChartTags(block).map(t => t.sig), sigs);
  // Comments are not charts (Studio does not stamp them either).
  const commented = '<!-- <MissionChart type="bar" csv="A,B; old,1" /> --><MissionChart type="bar" csv="A,B; new,1" />';
  assert.deepEqual(core.findChartTags(commented).map(t => t.attrs[1].value), ['A,B; new,1']);
  // Moving a chart (v-drag / pos) does not change its fingerprint.
  assert.equal(core.tagSignature('<MissionChart type="bar" v-drag="[1,2,3,4]" :pos="[5,6]" />'), core.tagSignature('<MissionChart type="bar"'));
});

test('Edit chart on two charts side by side: the clicked one is opened and saved', () => {
  const content = ['# Two charts', '', SIDE_BY_SIDE, '', 'After'].join('\n');
  // Studio gives both charts the same lines; only the fingerprint differs.
  const right = { no: 1, range: [2, 3], sig: '1k00f5n' };
  const block = core.blockAt(content, right.range);
  const picked = core.pickChartTag(block, right.sig);
  assert.equal(picked.index, 1);
  assert.equal(picked.count, 2);
  const { model } = core.tagToModel(picked.found);
  assert.equal(model.props.title, 'Right chart');
  assert.equal(core.chartName(model.props.title, picked.index, picked.count), '“Right chart” (the second of two charts on that line)');
  assert.equal(core.chartName('', 0, 2), 'the selected chart (the first of two charts on that line)');
  assert.equal(core.chartName('', 0, 1), 'the selected chart');
  assert.equal(core.chartName('Big', 8, 9), '“Big” (chart 9 of 9 on that line)');
  // Saved the way the builder saves: the lines are unchanged, the fingerprint picks the chart.
  const tag = core.chartTag({ ...model, props: { ...model.props, type: 'pie', title: 'Edited' } });
  const at = core.locateBlock(content, right.range, block);
  const next = core.replaceChart(content, at, tag, picked.found.sig);
  const line = core.toLines(next)[2];
  assert.match(line, /<MissionChart type="bar" title="Left chart" csv="W,A; 1,2; 2,3" \/>/, 'the left chart is untouched');
  assert.match(line, /<MissionChart type="pie" title="Edited" :rows="\['W,B', '1,5', '2,6'\]" \/><\/div>$/, 'the right chart is the one changed (its table kept)');
  assert.equal(core.toLines(next).length, 5);
  // The left chart the same way.
  const left = core.pickChartTag(block, '17htkwc');
  assert.equal(core.tagToModel(left.found).model.props.title, 'Left chart');
  assert.equal(left.index, 0);
});

test('Edit chart refuses when it cannot tell which chart was clicked', () => {
  const content = ['# Two charts', '', SIDE_BY_SIDE].join('\n');
  const block = core.blockAt(content, [2, 3]);
  // No fingerprint (an older Studio): one chart is fine, two are not.
  assert.equal(core.pickChartTag(block).problem, 'several');
  assert.equal(core.replaceChart(content, [2, 3], '<MissionChart />'), null, 'nothing is replaced');
  assert.equal(core.pickChartTag('<MissionChart type="bar" />').found.tag, 'MissionChart');
  // A fingerprint no chart there has (the slide changed meanwhile): refused.
  assert.equal(core.pickChartTag(block, 'zzzz').problem, 'gone');
  assert.equal(core.replaceChart(content, [2, 3], '<MissionChart />', 'zzzz'), null);
  // Two identical charts on one line: the same fingerprint twice.
  const twins = '<MissionChart type="bar" title="Twin" csv="A,B; q,1" /><MissionChart type="bar" title="Twin" csv="A,B; q,1" />';
  const sig = core.findChartTags(twins)[0].sig;
  assert.equal(core.pickChartTag(twins, sig).problem, 'twins');
  assert.equal(core.replaceChart(twins, [0, 1], '<MissionChart />', sig), null);
  assert.equal(core.pickChartTag('no chart here', sig).problem, 'none');
  for (const key of ['none', 'gone', 'twins', 'several']) assert.match(core.PICK_PROBLEMS[key], /\.$/);
});

test('queryChart: weeks as dates, forecast Sundays, % of goal and units', () => {
  const answer = {
    table: { labels: ['2026-09-06', '2026-09-13', '2026-09-20'], series: [{ name: 'Friends found', values: [10, 12, '14'] }, { name: 'Goal set last week', values: [11, 11, null], role: 'goal' }] },
    meta: { by: 'week', unit: 'count', weeks: ['2026-09-06', '2026-09-13', '2026-09-20'] },
  };
  const { table, settings } = queryChart(answer, { type: 'bar', trend: 'linear', forecast: 2, rows: [], query: {} });
  assert.equal(table.labels.length, 3);
  assert.deepEqual(table.series[0].values, [10, 12, 14]);
  assert.equal(table.series[1].role, 'goal');
  assert.equal(settings.forecast, 2);
  assert.equal(settings.futureLabels.length, 2);
  assert.equal(settings.rows, undefined, 'data settings are not handed to the chart');
  assert.ok(buildOption(table, settings, ctx));
  const pct = queryChart({ table: { labels: ['North', 'South'], series: [{ name: 'Baptismal dates', values: [80, 120] }] }, meta: { by: 'unit', unit: 'percent' } }, { type: 'bar', targetLabel: 'Target' });
  assert.deepEqual(pct.table.labels, ['North', 'South']);
  assert.equal(pct.settings.format, 'percent');
  assert.equal(pct.settings.target, 100);
  assert.equal(pct.settings.targetLabel, 'Goal');
  const own = queryChart({ table: { labels: ['A'], series: [{ name: 'x', values: [1] }] }, meta: { by: 'unit', unit: 'percent' } }, { type: 'bar', format: 'decimals', target: 90 });
  assert.equal(own.settings.format, 'decimals');
  assert.equal(own.settings.target, 90);
  assert.equal(queryChart(null, {}).table, null);
});

test('queryProblem: empty, hidden and outside the stewardship', () => {
  assert.equal(queryProblem({ table: { labels: ['a'], series: [{ name: 'x', values: [1] }] }, meta: {} }), '');
  assert.match(queryProblem({ table: { labels: ['a'], series: [{ name: 'x', values: [null] }] }, meta: {} }), /No numbers/);
  assert.match(queryProblem({ table: { labels: ['a'], series: [{ name: 'x', values: [null] }] }, meta: { suppressed: true } }), /Fewer than 3/);
  assert.match(queryProblem({ table: { labels: [], series: [] }, meta: { stewardship: true, units: 0 } }), /your stewardship/);
});

test('the chart block passes a query on', () => {
  const [block] = transformers().codeblocks;
  const html = block({ info: `chart type=bar query='{"measures":["friends_found.actual"],"weeks":4}'`, code: 'Week,A\n1,2' });
  const props = JSON.parse(html.match(/v-bind='(.*)' \/>$/)[1]);
  assert.equal(props.query, '{"measures":["friends_found.actual"],"weeks":4}');
  assert.equal(specKey(props.query), specKey({ measures: ['friends_found.actual'], weeks: 4 }));
});

test('titles under More options: the names of the numbers, the level, the transform and the weeks', () => {
  assert.equal(core.numbersName(['New members at church']), 'New members at church');
  assert.equal(core.numbersName(['New people being taught', 'Lessons with friends']), 'New people being taught and lessons with friends');
  assert.equal(core.numbersName(['New members', 'New members at church', 'New members discussed in GEMIKO']), 'New members, new members at church and new members discussed in GEMIKO');
  assert.equal(core.numbersName(['Plans started', 'GEMIKO meetings']), 'Plans started and GEMIKO meetings', 'an abbreviation keeps its capitals');
  assert.equal(core.numbersName(['A', 'B', 'C', 'D']), '', 'more than three names make no title');
  assert.equal(core.numbersName([]), '');
  assert.equal(core.numbersName(['A', '']), '', 'a number without a name makes no title');
  const spec = extra => normalizeSpec({ measures: ['new_members.at_church'], ...extra });
  assert.equal(core.chartTitle(spec({ level: 'zone', by: 'unit', weeks: 8 }), 'New members at church'), 'New members at church by zone, last 8 weeks');
  assert.equal(core.chartTitle(spec({ transform: 'cumulative' }), 'New members at church'), 'New members at church: running total');
  assert.equal(core.chartTitle(spec({ transform: 'rolling4' }), 'New members at church'), 'New members at church: average of 4 weeks');
  assert.equal(core.chartTitle(spec({ level: 'zone', by: 'unit', transform: 'per_area', weeks: 4 }), 'New members at church'), 'New members at church by zone, per area, last 4 weeks');
  // The simple titles are unchanged.
  assert.equal(core.chartTitle(normalizeSpec({ measures: ['friends_found.actual'], weeks: 16 }), 'New people being taught'), 'New people being taught');
});

test('the rename is a label: New people being taught, queries keep friends_found; no ready-made charts are left', () => {
  assert.equal(core.PRESETS, undefined);
  assert.equal(core.STARTS, undefined);
  assert.deepEqual(core.KEY_INDICATORS, ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament']);
  const kpi = core.readChart(core.findChartTag('<MissionKpiChart kpi="Friends found" :weeks="12" />'));
  assert.equal(kpi.option.title.text, 'New people being taught');
  // A <MissionKpiChart> written before the rename becomes the same query as before.
  const found = core.findChartTag('<MissionKpiChart kpi="Friends found" :weeks="12" />');
  assert.deepEqual(core.tagToModel(found).model.spec.measures, ['friends_found.actual', 'friends_found.previous_goal']);
});

test('labelWrap (charts per unit) shows every name, turning long ones; off by default', () => {
  const table = { labels: ['North', 'South', 'East'], series: [{ name: 'Friends', values: [1, 2, 3] }] };
  const wrapped = buildOption(table, { type: 'bar', labelWrap: true }, { ...ctx, width: 600 });
  assert.equal(wrapped.xAxis.axisLabel.interval, 0);
  assert.equal(wrapped.xAxis.axisLabel.overflow, 'break');
  assert.equal(wrapped.xAxis.axisLabel.hideOverlap, false);
  const long = { labels: ['Heidelberg', 'Friedrichsdorf', 'Frankfurt', 'Stuttgart', 'Nürnberg'], series: [{ name: 'x', values: [1, 2, 3, 4, 5] }] };
  const turned = buildOption(long, { type: 'bar', labelWrap: true }, { ...ctx, width: 440 });
  assert.equal(turned.xAxis.axisLabel.rotate, 30);
  assert.equal(turned.xAxis.axisLabel.interval, 0);
  const many = { labels: Array.from({ length: 40 }, (_, i) => `Area ${i}`), series: [{ name: 'x', values: Array(40).fill(1) }] };
  assert.equal(buildOption(many, { type: 'bar', labelWrap: true }, ctx).xAxis.axisLabel.rotate, 45);
  const plain = buildOption(table, { type: 'bar' }, ctx);
  assert.equal(plain.xAxis.axisLabel.interval, undefined);
  assert.equal(plain.xAxis.axisLabel.hideOverlap, true);
  const sideways = buildOption(table, { type: 'bar', horizontal: true, labelWrap: true }, ctx);
  assert.equal(sideways.yAxis.axisLabel.rotate, undefined, 'sideways bars have room for names');
  assert.equal(queryChart({ table, meta: { by: 'unit' } }, { type: 'bar' }).settings.labelWrap, true);
  assert.equal(queryChart({ table: { labels: ['2026-09-20'], series: [] }, meta: { by: 'week' } }, { type: 'bar' }).settings.labelWrap, undefined);
});
