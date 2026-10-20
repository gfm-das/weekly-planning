// Real morphs between chart kinds (lib/chart-story.mjs morphKeys, used by stabilize): the keys ECharts' universal
// transition needs so a line becomes bars, bars melt into a funnel, a funnel bends into a pie, and back again; the
// `steps` prop of <MissionChart>; and the showcase deck's two morph slides run forwards and backwards on ONE vendored
// ECharts instance with notMerge (what charts.ts does), which must never throw. Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import * as engine from '../manager/gfm-addon/lib/chart-engine.mjs';
import { morphKeys, parseStory, PART_TYPES, stabilize, stepSettings } from '../manager/gfm-addon/lib/chart-story.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const echarts = require('../manager/vendor/echarts.min.js');
const ctx = { dark: false, font: 'Inter', animate: true, ecStat: require('../manager/vendor/ecStat.min.js'), width: 900, height: 360 };
const MORPH = { kind: 'morph', duration: 0, easing: 'linear' };
const lines = [{ type: 'line', name: 'A' }, { type: 'line', name: 'B' }];
const funnel = [{ type: 'funnel', name: 'Value', data: [{ name: 'A', value: 3 }, { name: 'B', value: 2 }, { name: 'Other', value: 1 }] }];

test('every series gets a morph and a group: series by name, parts of a funnel or pie one by one', () => {
  const out = stabilize({ series: lines }, MORPH);
  assert.deepEqual(out.series.map(s => [s.id, s.dataGroupId, s.universalTransition.enabled, s.universalTransition.divideShape]), [['series:A', 'A', true, 'clone'], ['series:B', 'B', true, 'clone']]);
  const f = stabilize({ series: funnel }, MORPH);
  assert.equal(f.series[0].dataGroupId, undefined, 'a series of parts is matched part by part');
  assert.deepEqual(f.series[0].data.map(d => d.groupId), ['A', 'B', 'Other']);
  assert.deepEqual(PART_TYPES, ['pie', 'funnel', 'treemap', 'sunburst']);
  assert.equal(stabilize({ series: lines }, { kind: 'fade', duration: 1, easing: 'linear' }).series[0].universalTransition, undefined, 'fade does not morph');
});

test('many series -> one series of parts: seriesKey lists the old series whose names are parts (and only those)', () => {
  const before = stabilize({ series: [...lines, { type: 'line', name: 'Not a part' }] }, MORPH);
  const after = stabilize({ series: funnel }, MORPH, before);
  assert.deepEqual(after.series[0].universalTransition.seriesKey, ['series:A', 'series:B']);
  assert.equal(stabilize({ series: funnel }, MORPH, stabilize({ series: [{ type: 'line', name: 'X' }, { type: 'line', name: 'Y' }] }, MORPH)).series[0].universalTransition.seriesKey, undefined, 'no shared names: a cross-fade, no key ECharts cannot find');
});

test('one -> one carries the key on (funnel -> pie), keeps a plain old id, and same ids need nothing', () => {
  const f = stabilize({ series: funnel }, MORPH, stabilize({ series: lines }, MORPH));
  const pie = stabilize({ series: [{ ...funnel[0], type: 'pie' }] }, MORPH, f);
  assert.deepEqual(pie.series[0].universalTransition.seriesKey, ['series:A', 'series:B']);
  const back = stabilize({ series: funnel }, MORPH, pie);
  assert.deepEqual(back.series[0].universalTransition.seriesKey, ['series:A', 'series:B'], 'back again: the same key');
  const plainPie = stabilize({ series: [{ type: 'pie', name: 'Other', data: [{ name: 'A', value: 1 }] }] }, MORPH, stabilize({ series: funnel }, MORPH));
  assert.equal(plainPie.series[0].id, 'series:Value', 'without a key, one -> one takes the old id');
  const bars = stabilize({ series: lines.map(s => ({ ...s, type: 'bar' })) }, MORPH, stabilize({ series: lines }, MORPH));
  assert.deepEqual(bars.series.map(s => s.universalTransition.seriesKey), [undefined, undefined], 'line -> bar: the same ids morph by themselves');
  assert.deepEqual(morphKeys([{ type: 'pie', id: 'p', universalTransition: { seriesKey: 'mine' } }], [{ id: 'q' }])[0].universalTransition.seriesKey, 'mine', 'a key written in the chart is kept');
});

test('<MissionChart> takes `steps` (the same as `story`) and `sample`; charts.ts morphs with notMerge from the last step', () => {
  const vue = fs.readFileSync(path.join(here, '../manager/gfm-addon/components/MissionChart.vue'), 'utf8');
  assert.match(vue, /parseStory\(props\.steps \?\? props\.story\)/);
  assert.match(vue, /usingSample/);
  const charts = fs.readFileSync(path.join(here, '../manager/gfm-addon/lib/charts.ts'), 'utf8');
  assert.match(charts, /stabilize\(option, story, lastStory\)/);
  assert.match(charts, /story\.kind === 'morph' \? \{ notMerge: true \}/);
});

function deckStory(id) {
  const md = fs.readFileSync(path.join(here, '../manager/shipped-decks/gfm-showcase/slides.md'), 'utf8');
  const tag = md.slice(md.indexOf(`chart-id="${id}"`)).split('/>')[0];
  const rows = JSON.parse(/:(?:rows|sample)="(\[[^"]*\])"/.exec(tag)[1].replace(/'/g, '"'));
  return { rows, steps: parseStory(/:steps='([^']*)'/.exec(tag)[1]).steps, live: /:query=/.test(tag) };
}

for (const id of ['story', 'story-live']) {
  test(`showcase "${id}": lines -> bars -> funnel -> pie and back on one instance, with the morph keys at each step`, () => {
    const { rows, steps, live } = deckStory(id);
    assert.equal(live, id === 'story-live');
    const kinds = [];
    const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 360 });
    try {
      let prev = null;
      const order = [...steps.keys(), ...[...steps.keys()].reverse().slice(1)];
      for (const i of order) {
        const view = engine.chartView(stepSettings({ preset: 'trend', rows }, steps, i));
        assert.equal(view.problem, '', `step ${i + 1}`);
        const next = stabilize(engine.viewOption(view, ctx), MORPH, prev);
        assert.doesNotThrow(() => chart.setOption(next, { notMerge: true }), `step ${i + 1}`);
        kinds.push(next.series.map(s => s.type)[0]);
        if (next.series[0].type === 'funnel' || next.series[0].type === 'pie') {
          assert.equal(next.series.length, 1);
          assert.equal(next.series[0].universalTransition.seriesKey.length, 3, `step ${i + 1}: the three series melt into it`);
        }
        else assert.ok(next.series.every(s => s.dataGroupId === s.name), `step ${i + 1}: each series can be found again`);
        prev = next;
      }
      for (const k of ['line', 'bar', 'funnel', 'pie']) assert.ok(kinds.includes(k), k);
      assert.equal(kinds.at(-1), 'line', 'back at the start');
    }
    finally { chart.dispose(); }
  });
}
