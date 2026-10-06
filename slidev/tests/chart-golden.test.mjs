// Existing decks must draw exactly as before: every case in chart-cases.mjs
// is drawn with the new chart-core and compared with the fingerprint of what
// the old chart code drew (fixtures/chart-golden.json), once with the old
// components' defaults and once with the new components' defaults (which add
// every new setting, switched off).
//
// Run from slidev/:  node --test tests/
// With OLD_CHARTS=<old charts.ts> the old code is loaded too and the first
// difference of a failing case is printed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import * as core from '../manager/gfm-addon/lib/chart-core.mjs';
import { canonical, cases, componentDefaults, digest, firstDifference, OLD_CHART_DEFAULTS, OLD_KPI_DEFAULTS, render } from './chart-cases.mjs';
import { loadOldCharts, newKpi, oldKpi } from './old-charts.mjs';

const here = p => fileURLToPath(new URL(p, import.meta.url));
const ecStat = createRequire(import.meta.url)('../manager/vendor/ecStat.min.js');
const golden = JSON.parse(readFileSync(here('./fixtures/chart-golden.json'), 'utf8'));
const byName = new Map(golden.cases.map(c => [c.name, c.digest]));
const NEW_CHART_DEFAULTS = componentDefaults(here('../manager/gfm-addon/components/MissionChart.vue'));
const NEW_KPI_DEFAULTS = componentDefaults(here('../manager/gfm-addon/components/MissionKpiChart.vue'));
const old = process.env.OLD_CHARTS ? await loadOldCharts(process.env.OLD_CHARTS) : null;

function explain(c, drawn) {
  if (!old) return 'set OLD_CHARTS to the old charts.ts to see the difference';
  const before = render(old, c, c.kind === 'kpi' ? OLD_KPI_DEFAULTS : OLD_CHART_DEFAULTS, ecStat, oldKpi);
  return firstDifference(canonical(before), canonical(drawn));
}

test('the golden file was made in the same locale', () => {
  assert.equal(golden.locale, Intl.DateTimeFormat().resolvedOptions().locale);
  assert.equal(golden.cases.length, cases().length, 'the golden file does not match the case list; run make-chart-golden.mjs');
});

for (const [label, chartDefaults, kpiDefaults] of [['old component defaults', OLD_CHART_DEFAULTS, OLD_KPI_DEFAULTS], ['new component defaults', NEW_CHART_DEFAULTS, NEW_KPI_DEFAULTS]]) {
  test(`existing charts draw exactly as before (${label})`, () => {
    const failures = [];
    for (const c of cases()) {
      const drawn = render(core, c, c.kind === 'kpi' ? kpiDefaults : chartDefaults, ecStat, newKpi);
      if (digest(drawn) !== byName.get(c.name)) failures.push(`${c.name}\n    ${explain(c, drawn)}`);
    }
    assert.deepEqual(failures, [], `${failures.length} of ${cases().length} cases differ`);
  });
}

test('the new defaults switch every new setting off', () => {
  // Spot check: the new components add these settings, all neutral.
  for (const key of ['trendColor', 'trendLabel', 'goal', 'goalColor', 'targetColor', 'averageColor', 'xTitle', 'yTitle', 'prefix', 'suffix']) assert.equal(NEW_CHART_DEFAULTS[key], '', key);
  for (const key of ['average', 'stack', 'horizontal', 'smooth', 'multiples', 'dataZoom', 'showValues']) assert.equal(NEW_CHART_DEFAULTS[key], false, key);
  assert.equal(NEW_CHART_DEFAULTS.forecast, 0);
  assert.equal(NEW_CHART_DEFAULTS.trendWidth, 2);
  assert.equal(NEW_CHART_DEFAULTS.trendStyle, 'dashed');
  assert.equal(NEW_CHART_DEFAULTS.legend, 'auto');
  assert.equal(NEW_CHART_DEFAULTS.format, 'auto');
  assert.equal(NEW_CHART_DEFAULTS.target, undefined);
  assert.equal(NEW_CHART_DEFAULTS.option, undefined);
  assert.equal(NEW_KPI_DEFAULTS.trend, 'linear');
  assert.equal(NEW_KPI_DEFAULTS.chart, 'bar');
});
