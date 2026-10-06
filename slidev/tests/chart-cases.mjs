// Shared by chart-golden.test.mjs and make-chart-golden.mjs: charts as decks
// wrote them before the chart settings of September 2026 (only the settings
// that existed then), and a way to compare two ECharts options.
//
// Every case is rendered by the old chart code (to make the golden file) and
// by the new chart-core (in the test). Existing decks must look exactly the
// same, so the two must match, also when the new components' defaults for
// the new settings are added.
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';

const long = ['Week,Friends found', ...Array.from({ length: 40 }, (_, i) => `W${i + 1},${Math.round(20 + i * 0.7 + 6 * Math.sin(i))}`)].join('\n');

export const CSV = {
  one: 'Week,Friends found; Aug 3,12; Aug 10,15; Aug 17,14; Aug 24,19; Aug 31,22',
  two: 'Week\tZone North\tZone South\nJul 6\t4\t3\nJul 13\t6\t4\nJul 20\t5\t6\nJul 27\t8\t5\nAug 3\t9\t7',
  gaps: 'Week;A;B\n1;12;\n2;;9\n3;14;11\n4;19;\n5;22;14\n6;;16',
  decimals: 'Week,Rate; 1,0.5; 2,1.25; 3,2.125; 4,3.75',
  big: 'Month;People\nJan;12000\nFeb;15500\nMar;14250\nApr;19875',
  negative: 'Week,Change; 1,-3; 2,4; 3,-1; 4,6',
  long,
  scatter: 'Lessons,Baptismal dates; 20,2; 35,4; 28,3; 50,7; 44,5; 61,8',
  pie: 'Source,Friends; Members,18; Online,9; Finding,12; Service,5',
  pieZero: 'Source,Friends; Members,0; Online,9; Finding,-2; Service,5',
  gauge: 'Measure,Actual,Goal; This week,412,450',
  gaugeNoGoal: 'Measure,Actual; This week,72',
  gaugeRows: 'Week,Actual,Goal; 1,300,400; 2,350,420; 3,,',
  problem: 'Week,Friends\nAug 3,12,5\nAug 10,15',
  empty: 'Week,Friends\nAug 3,\nAug 10,',
};

/** Weeks as portal-api's /internal/presentations/kpis answers them (oldest first). */
export function kpiWeeks(count) {
  const out = [];
  const last = Date.UTC(2026, 8, 20);
  for (let i = count - 1; i >= 0; i--) {
    const n = 40 - i;
    const week = new Date(last - i * 7 * 86400000).toISOString().slice(0, 10);
    const entry = { week };
    ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament'].forEach((k, j) => {
      const actual = Math.round((j + 1) * 10 + n * 0.6 + 5 * Math.sin(n + j));
      // Goals: 0 now and then (nobody set one), null for the first week.
      const goal = i === count - 1 ? null : n % 7 === 3 ? 0 : actual + 4;
      entry[k] = { actual: n % 11 === 5 && j === 2 ? null : actual, goal };
    });
    out.push(entry);
  }
  return out;
}

/** The old components' defaults (MissionChart.vue / MissionKpiChart.vue at 0465b09). */
export const OLD_CHART_DEFAULTS = { type: 'line', title: '', rows: [], csv: '', trend: 'none', degree: 2, height: 360, showValues: false };
export const OLD_KPI_DEFAULTS = { kpi: 'friends_found', weeks: 12, chart: 'bar', showGoal: true, trend: 'linear', degree: 2, title: '', height: 360, showValues: false };

/**
 * The defaults a component's `withDefaults(defineProps<…>(), { … })` gives,
 * read from the .vue file, with factories (`() => []`) called as Vue does.
 */
export function componentDefaults(vueFile) {
  const source = readFileSync(vueFile, 'utf8');
  const at = source.indexOf('}>(), {');
  if (at < 0) throw new Error(`no withDefaults in ${vueFile}`);
  let depth = 0, end = -1;
  for (let i = at + 6; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) { end = i; break; }
  }
  const object = Function(`return (${source.slice(at + 6, end + 1)})`)();
  return Object.fromEntries(Object.entries(object).map(([k, v]) => [k, typeof v === 'function' ? v() : v]));
}

export function cases() {
  const out = [];
  let i = 0;
  const add = (kind, props, ctx = {}) => {
    i++;
    out.push({ name: `${String(i).padStart(3, '0')} ${kind} ${JSON.stringify(props)}`.slice(0, 160), kind, props, ctx: { dark: i % 3 === 0, animate: i % 5 !== 0, ...ctx } });
  };
  for (const table of ['one', 'two', 'gaps', 'decimals', 'big', 'negative', 'long']) {
    for (const type of ['line', 'bar', 'area', 'scatter']) {
      for (const trend of ['none', 'linear', 'polynomial']) {
        for (const showValues of [false, true]) {
          add('chart', { csv: CSV[table], type, trend, showValues, ...(i % 2 ? { title: 'Friends found' } : {}), ...(trend === 'polynomial' && i % 4 === 1 ? { degree: 3 } : {}) });
        }
      }
    }
  }
  for (const trend of ['none', 'linear', 'polynomial']) for (const degree of [2, 3]) add('chart', { csv: CSV.scatter, type: 'scatter', trend, degree, title: 'Lessons' });
  for (const table of ['pie', 'pieZero', 'two']) for (const type of ['pie', 'donut']) for (const showValues of [false, true]) add('chart', { csv: CSV[table], type, showValues, ...(showValues ? { title: 'Where friends were found' } : {}) });
  for (const table of ['gauge', 'gaugeNoGoal', 'gaugeRows']) for (const max of [undefined, 500]) add('chart', { csv: CSV[table], type: 'gauge', ...(max ? { max } : {}), ...(table === 'gauge' ? { title: 'This week' } : {}) });
  add('chart', { csv: CSV.gauge, type: 'gauge', seriesLabel: 'Sacrament' });
  for (const degree of [1, 4, 6, 7, '3', undefined]) add('chart', { csv: CSV.long, type: 'line', trend: 'polynomial', degree });
  for (const trend of ['Linear', ' polynomial ', '', 'exponential-ish', undefined]) add('chart', { csv: CSV.two, type: 'bar', trend });
  for (const type of ['Bar', ' area ', 'unknown', '', undefined]) add('chart', { csv: CSV.one, type, trend: 'linear' });
  for (const colors of [['#111111', '#222222'], '#aa0000, #00aa00', [], ['teal']]) add('chart', { csv: CSV.two, type: 'line', trend: 'linear', colors });
  add('chart', { rows: ['Week, Friends found', 'Aug 3, 12', 'Aug 10, 15', 'Aug 17, 14'], type: 'bar', trend: 'linear' });
  add('chart', { rows: ['Week\tNorth\tSouth', '1\t4\t5', '2, 6, 7'], csv: CSV.one, type: 'line' });
  add('chart', { data: { labels: ['Q1', 'Q2', 'Q3'], series: { North: [4, 6, 9], South: [3, 5, 4] } }, type: 'bar', trend: 'polynomial' });
  add('chart', { data: [{ Week: 'A', X: '1,5', Y: 2 }, { Week: 'B', X: '2,5', Y: 3 }], type: 'line' });
  add('chart', { csv: CSV.problem, type: 'line' });
  add('chart', { csv: CSV.empty, type: 'bar' });
  add('chart', { csv: CSV.one, type: 'line', trend: 'linear' }, { dark: true, animate: false });
  for (const chart of ['bar', 'line']) {
    for (const trend of ['linear', 'polynomial', 'none']) {
      for (const showGoal of [true, false]) {
        add('kpi', { kpi: chart === 'bar' ? 'Friends found' : 'sacrament_attendance', chart, trend, showGoal, weeks: trend === 'none' ? 26 : 16, ...(showGoal ? {} : { showValues: true }), ...(trend === 'polynomial' ? { degree: 3 } : {}) });
      }
    }
  }
  add('kpi', { kpi: 'baptismal_dates', chart: 'line', trend: 'none', showGoal: true, weeks: 12, title: 'Mission total per week' });
  add('kpi', { kpi: 'constructor', weeks: 1 });
  add('kpi', { kpi: 'Members at lessons', chart: 'bar', trend: 'none', showGoal: false, showValues: true, weeks: 12 });
  return out;
}

const PROBES = [0, 7.456, 1234.5, 98765.4, -3, { value: 12.5, name: 'A', percent: 40, dataIndex: 1 }, { value: [3, 1234.5], name: 'B', percent: 5, dataIndex: 0 }];

/**
 * An option as plain data in a fixed key order: undefined keys dropped (as
 * ECharts treats them), functions replaced by what they answer for a few
 * sample inputs.
 */
export function canonical(value) {
  if (typeof value === 'function') {
    return { fn: PROBES.map((probe) => { try { return String(value(probe)); } catch { return 'ERR'; } }) };
  }
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) if (value[key] !== undefined) out[key] = canonical(value[key]);
    return out;
  }
  return value;
}

export function digest(value) {
  return crypto.createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex').slice(0, 24);
}

/** The first difference between two canonical values, as "path: a != b". */
export function firstDifference(a, b, where = '') {
  if (JSON.stringify(a) === JSON.stringify(b)) return '';
  if (a && b && typeof a === 'object' && typeof b === 'object' && Array.isArray(a) === Array.isArray(b)) {
    for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
      const d = firstDifference(a[key], b[key], `${where}.${key}`);
      if (d) return d;
    }
  }
  return `${where || '(root)'}: ${JSON.stringify(a)?.slice(0, 200)} != ${JSON.stringify(b)?.slice(0, 200)}`;
}

/** The option a component would draw for a case, with chart code `lib` (old or new). */
export function render(lib, testCase, defaults, ecStat, kpi) {
  const ctx = { font: 'Inter, sans-serif', ecStat, ...testCase.ctx };
  if (testCase.kind === 'chart') {
    const props = { ...defaults, ...testCase.props };
    const table = lib.parseRows(props.rows) ?? lib.parseCsv(props.csv) ?? lib.parseData(props.data);
    return { table, option: lib.buildOption(table, props, ctx) };
  }
  const props = { ...defaults, ...testCase.props };
  const list = kpiWeeks(104).slice(-Math.min(104, Math.max(1, Math.round(Number(props.weeks) || 12))));
  return kpi(lib, list, props, ctx);
}
