// Loads an older lib/charts.ts (before the chart-core split) in plain Node, for
// the golden comparison: the Vue, Slidev and `?url` imports are dropped (only
// the pure functions are used) and Node strips the TypeScript types.
// Get the old file with:  git show 0465b09:slidev/manager/gfm-addon/lib/charts.ts > old-charts.ts
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export async function loadOldCharts(file) {
  const source = readFileSync(file, 'utf8')
    .split(/\r?\n/)
    .filter(line => !/^import\s/.test(line) || /^import type\s/.test(line))
    .join('\n');
  const dir = mkdtempSync(path.join(os.tmpdir(), 'old-charts-'));
  const copy = path.join(dir, 'old-charts.ts');
  writeFileSync(copy, source);
  return import(pathToFileURL(copy).href);
}

/** <MissionKpiChart> as it worked before: table and settings built in the component. */
export function oldKpi(lib, list, props, ctx) {
  const kpiKey = lib.kpiId(props.kpi);
  const heading = String(props.title || '').trim() || lib.KPI_NAMES[kpiKey];
  const pick = (w, field) => lib.toNumber(w?.[kpiKey]?.[field]);
  const actual = list.map(w => pick(w, 'actual'));
  let table = null;
  if (!actual.every(v => v === null)) {
    const series = [{ name: 'Actual', values: actual }];
    const goals = list.map(w => pick(w, 'goal') || null);
    if (props.showGoal && goals.some(v => v !== null)) series.push({ name: 'Goal', values: goals, role: 'goal' });
    table = { labels: lib.weekLabels(list.map(w => String(w.week))), series };
  }
  const settings = { type: props.chart === 'line' ? 'line' : 'bar', title: heading, trend: props.trend, degree: props.degree, showValues: props.showValues };
  return { table, option: lib.buildOption(table, settings, ctx) };
}

/** <MissionKpiChart> now: kpiChart() in chart-core builds both. */
export function newKpi(lib, list, props, ctx) {
  const heading = String(props.title || '').trim() || lib.KPI_NAMES[lib.kpiId(props.kpi)];
  const { table, settings } = lib.kpiChart(list, props, heading);
  return { table, option: lib.buildOption(table, settings, ctx) };
}
