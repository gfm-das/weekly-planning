// Data stories (lib/chart-story.mjs) and the table shaping a step uses (chart-presets.mjs shapeTable): reading a story,
// the settings of each step, the motion, the stable ids that let one chart move between steps, and a whole story drawn
// step by step with the vendored ECharts (server side) on ONE chart instance. Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as engine from '../manager/gfm-addon/lib/chart-engine.mjs';
import { shapeTable } from '../manager/gfm-addon/lib/chart-presets.mjs';
import { MAX_STEPS, parseStory, REPLACE_MERGE, stabilize, stepLabel, stepSettings, storyMotion } from '../manager/gfm-addon/lib/chart-story.mjs';

const require = createRequire(import.meta.url);
const echarts = require('../manager/vendor/echarts.min.js');
const ctx = { dark: false, font: 'Inter, sans-serif', animate: true, ecStat: require('../manager/vendor/ecStat.min.js'), width: 900, height: 360 };

const TABLE = {
  labels: ['W1', 'W2', 'W3'],
  series: [{ name: 'Received', values: [10, 20, 30] }, { name: 'Attempted', values: [8, 12, 25] }, { name: 'Goal', values: [9, 9, 9], role: 'goal' }],
  head: 'Week', unit: 'count',
};
const ROWS = ['Week, Received, Attempted, Successful', 'W1, 10, 8, 5', 'W2, 20, 12, 9', 'W3, 30, 25, 20'];

test('reading a story: a list or JSON text, limits and friendly mistakes', () => {
  assert.deepEqual(parseStory(undefined), { steps: [], problem: '' });
  assert.deepEqual(parseStory(''), { steps: [], problem: '' });
  assert.equal(parseStory('[{"label":"A"},{"label":"B"}]').steps.length, 2);
  assert.equal(parseStory([{ label: 'A' }]).steps.length, 1);
  assert.match(parseStory('{not json').problem, /not valid JSON/);
  assert.match(parseStory({ a: 1 }).problem, /list of steps/);
  assert.match(parseStory([1]).problem, /Step 1 of the story must be a list of settings/);
  assert.match(parseStory([{ query: {} }]).problem, /Step 1 of the story has an unknown setting: query/);
  assert.match(parseStory(new Array(MAX_STEPS + 1).fill({})).problem, /up to 12 steps/);
  assert.deepEqual(parseStory([{ query: {} }]).steps, [], 'a step can never change the chart\'s numbers query');
});

test('the settings of a step: replace, merge shape and option, the rest untouched', () => {
  const props = { query: { v: 1 }, preset: 'trend', option: { yAxis: { min: 0 } }, shape: { sort: 'desc' }, height: 300, title: 'T' };
  const steps = [{ label: 'One', shape: { only: ['Received'] } }, { preset: 'ranked-bar', option: { xAxis: { max: 50 } }, title: 'Two', shape: { top: 2 } }];
  const a = stepSettings(props, steps, 0);
  assert.deepEqual(a.shape, { sort: 'desc', only: ['Received'] });
  assert.equal(a.preset, 'trend');
  assert.equal(a.height, 300);
  assert.deepEqual(a.query, { v: 1 });
  const b = stepSettings(props, steps, 1);
  assert.equal(b.preset, 'ranked-bar');
  assert.equal(b.title, 'Two');
  assert.deepEqual(b.shape, { sort: 'desc', top: 2 });
  assert.deepEqual(b.option, { yAxis: { min: 0 }, xAxis: { max: 50 } }, 'the step\'s option is merged over the chart\'s');
  assert.equal(stepSettings(props, steps, 99).preset, 'ranked-bar', 'past the end: the last step');
  assert.equal(stepSettings(props, steps, -3).shape.only[0], 'Received', 'before the start: the first step');
  assert.equal(stepSettings(props, [], 0), props);
  assert.equal(stepLabel(steps, 0), 'One');
  assert.equal(stepLabel(steps, 1), 'Step 2');
});

test('the motion: defaults, limits, "none" has no duration', () => {
  assert.deepEqual(storyMotion({}), { kind: 'morph', duration: 700, easing: 'cubicInOut' });
  assert.deepEqual(storyMotion({ storyTransition: 'fade', storyDuration: 400, storyEasing: 'linear' }), { kind: 'fade', duration: 400, easing: 'linear' });
  assert.equal(storyMotion({ storyTransition: 'none', storyDuration: 900 }).duration, 0);
  assert.equal(storyMotion({ storyDuration: 99999 }).duration, 3000);
  assert.equal(storyMotion({ storyDuration: -5 }).duration, 0);
  assert.equal(storyMotion({ storyTransition: 'spin', storyEasing: 'bad' }).kind, 'morph');
  assert.equal(storyMotion({ storyTransition: 'spin', storyEasing: 'bad' }).easing, 'cubicInOut');
});

test('stable ids: the same series keeps its id from step to step, morph turns universal transition on', () => {
  const option = { series: [{ type: 'bar', name: 'Received' }, { type: 'bar', name: 'Attempted' }, { type: 'bar' }, { type: 'line', name: 'Received' }], xAxis: { type: 'category' }, yAxis: [{ type: 'value' }] };
  const out = stabilize(option, { kind: 'morph', duration: 700, easing: 'cubicInOut' });
  assert.deepEqual(out.series.map(s => s.id), ['series:Received', 'series:Attempted', 'series:2', 'series:Received_']);
  assert.ok(out.series.every(s => s.universalTransition.enabled === true));
  assert.equal(out.animationDurationUpdate, 700);
  assert.equal(out.animationEasingUpdate, 'cubicInOut');
  assert.equal(out.xAxis[0].id, 'xAxis:0');
  assert.equal(out.yAxis[0].id, 'yAxis:0');
  assert.equal(option.series[0].id, undefined, 'the option given is not changed');
  const fade = stabilize(option, { kind: 'fade', duration: 600, easing: 'linear' });
  assert.equal(fade.series[0].universalTransition, undefined);
  assert.equal(fade.animationDurationUpdate, 300);
  assert.equal(stabilize(option, { kind: 'none', duration: 0, easing: 'linear' }).animation, false);
  assert.deepEqual(stabilize({ series: [{ type: 'bar', id: 'mine' }] }, { kind: 'morph', duration: 1, easing: 'linear' }).series[0].id, 'mine', 'an id written in the chart is kept');
  assert.deepEqual(REPLACE_MERGE.slice(0, 2), ['series', 'xAxis']);
});

test('shaping the table: only, hide, sort, top; goal columns follow; unknown names change nothing', () => {
  assert.deepEqual(shapeTable(TABLE, { only: ['received'] }).series.map(s => s.name), ['Received', 'Goal']);
  assert.deepEqual(shapeTable(TABLE, { only: 'Attempted, Received' }).series.map(s => s.name), ['Received', 'Attempted', 'Goal'], 'the order of the chart, not of the list');
  assert.deepEqual(shapeTable(TABLE, { hide: ['Attempted', 'Goal'] }).series.map(s => s.name), ['Received']);
  assert.equal(shapeTable(TABLE, { only: ['Nope'] }), TABLE, 'an only that names nothing leaves the table alone');
  const desc = shapeTable(TABLE, { sort: 'desc' });
  assert.deepEqual(desc.labels, ['W3', 'W2', 'W1']);
  assert.deepEqual(desc.series[1].values, [25, 12, 8], 'every column follows the rows');
  assert.deepEqual(shapeTable(TABLE, { sort: 'asc' }).labels, ['W1', 'W2', 'W3']);
  assert.deepEqual(shapeTable(TABLE, { sort: 'desc', top: 2 }).labels, ['W3', 'W2']);
  assert.equal(shapeTable(TABLE, null), TABLE);
  assert.equal(shapeTable(TABLE, []), TABLE);
  assert.equal(shapeTable(null, { only: ['a'] }), null);
  assert.equal(TABLE.series.length, 3, 'the given table is not changed');
});

test('a whole story on one chart instance: every step draws, the instance lives, series move instead of restarting', () => {
  const steps = [
    { label: 'Received', shape: { only: ['Received'] } },
    { label: 'Attempted', shape: { only: ['Received', 'Attempted'] } },
    { label: 'All', shape: {} },
    { label: 'Ranking', preset: 'ranked-bar', shape: { only: ['Attempted'] } },
  ];
  const props = { rows: ROWS, option: { series: [{ type: 'bar' }] } };
  const motion = storyMotion({ storyDuration: 0, storyTransition: 'morph' });
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 360 });
  const counts = [];
  try {
    steps.forEach((step, i) => {
      const settings = stepSettings(props, steps, i);
      const view = engine.chartView(settings);
      assert.equal(view.problem, '', `step ${i + 1}: ${view.problem}`);
      const option = engine.viewOption(view, ctx);
      assert.ok(option, `step ${i + 1}: an option`);
      chart.setOption(stabilize(option, motion), i === 0 ? { notMerge: true } : { notMerge: false, replaceMerge: REPLACE_MERGE });
      counts.push(chart.getOption().series.filter(Boolean).length); // removed series leave empty places in ECharts' answer
      const svg = chart.renderToSVGString();
      assert.ok((svg.match(/<(path|rect) /g) || []).length > 3, `step ${i + 1}: something is drawn`);
    });
    assert.deepEqual(counts, [1, 2, 3, 1], 'the series of each step: one, two, three, then the ranked one');
    assert.ok(chart.getOption(), 'the same instance still answers');
  }
  finally { chart.dispose(); }
});
