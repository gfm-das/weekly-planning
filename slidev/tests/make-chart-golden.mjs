// Writes fixtures/chart-golden.json: a fingerprint of the ECharts option the
// OLD chart code drew for every case in chart-cases.mjs. Run once, in
// node:24-alpine (numbers are formatted with the container's default locale),
// from the slidev/ folder:
//   git show 0465b09:slidev/manager/gfm-addon/lib/charts.ts > /tmp/old-charts.ts
//   node tests/make-chart-golden.mjs /tmp/old-charts.ts > tests/fixtures/chart-golden.json
// Round 3 renamed the key indicator "Friends found" to "New people being
// taught" (a label people see; the id friends_found stays). The fixture is
// the old code with that one name changed, so 7 key indicator charts without
// their own title differ from round 2 in their title only:
//   sed -i "s/friends_found: 'Friends found'/friends_found: 'New people being taught'/" /tmp/old-charts.ts
// before the second line (then set "about" as in the fixture).
import { createRequire } from 'node:module';
import { cases, digest, OLD_CHART_DEFAULTS, OLD_KPI_DEFAULTS, render } from './chart-cases.mjs';
import { loadOldCharts, oldKpi } from './old-charts.mjs';

const file = process.argv[2];
if (!file) { console.error('usage: node tests/make-chart-golden.mjs <old charts.ts>'); process.exit(2); }
const ecStat = createRequire(import.meta.url)('../manager/vendor/ecStat.min.js');
const old = await loadOldCharts(file);
const out = cases().map((c) => {
  const drawn = render(old, c, c.kind === 'kpi' ? OLD_KPI_DEFAULTS : OLD_CHART_DEFAULTS, ecStat, oldKpi);
  return { name: c.name, digest: digest(drawn) };
});
console.log(JSON.stringify({ about: 'Fingerprints of the chart options drawn by lib/charts.ts at commit 0465b09 (before chart-core). See make-chart-golden.mjs.', locale: Intl.DateTimeFormat().resolvedOptions().locale, cases: out }, null, 1));
