// What DataEase can read in the mission database: through its one data source, as gfm_dashboard_reader, only the
// dashboards views (migrations 018/025). Tables with people (names, notes, sign-ins) are refused, nothing can be
// written, and DataEase cannot reach other services or the internet. Run on DataEase's private network with the
// same environment as seed-dashboards.mjs (dataease/seed-dashboards.ps1 -ReaderCheck does this):
//   node dataease/tests/reader-check.mjs
// Prints table names and PASS/FAIL only, never rows. Exit code 1 when anything is wrong.
import { DataEase, flattenTree } from '../lib/dataease-client.mjs';

const DATASOURCE = 'GFM mission data (read-only)';
const PEOPLE_TABLES = [
  'public.new_members', 'public.weekly_new_members', 'public.baptismal_date_people', 'public.weekly_baptismal_date_friends',
  'public.weekly_high_potential_friends', 'public.missionaries', 'public.user_profiles', 'public.call_in_area_updates',
  'public.import_weekly_new_members', 'public.weekly_planning_answers', 'auth.users', 'portal.attendance',
];
const VIEWS = ['dashboards.kpi_mission_week', 'dashboards.kpi_zone_week', 'dashboards.kpi_district_week',
  'dashboards.kpi_area_total_week', 'dashboards.people_mission_week', 'dashboards.people_district_week'];

let failures = 0;
const check = (name, ok, detail = '') => {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${!ok && detail ? ` -- ${detail}` : ''}`);
};

const de = await new DataEase(process.env.DE_BASE || 'http://dataease:8100').login(process.env.DE_ADMIN_PASSWORD);
const sources = flattenTree(await de.post('/datasource/tree', { busiFlag: 'datasource' })).filter(n => n.leaf);
check('DataEase has exactly one data source, the read-only mission data', sources.length === 1 && sources[0].name === DATASOURCE,
  sources.map(s => `${s.name} (${s.type})`).join(', '));
const source = sources.find(s => s.name === DATASOURCE);
if (!source) { console.log('The data source is missing: run seed-dashboards first.'); process.exit(1); }

// One SELECT through DataEase's own "SQL dataset" preview, as someone editing a dataset in DataEase would.
async function run(sql) {
  const answer = await de.raw('/datasetData/previewSql', {
    method: 'POST',
    body: { datasourceId: source.id, sql: Buffer.from(sql, 'utf8').toString('base64'), isCross: false, sqlVariableDetails: '[]', tableId: null },
  });
  const ok = answer.status === 200 && answer.json?.code === 0;
  return { ok, rows: ok ? (answer.json.data?.data?.data || []) : [], message: ok ? '' : String(answer.json?.msg || answer.text).slice(0, 300) };
}

const who = await run('SELECT current_user AS login, current_setting(\'default_transaction_read_only\') AS read_only');
const row = who.rows[0] || {};
const values = Object.values(row).map(String);
check('DataEase signs in to the database as gfm_dashboard_reader, read-only by default',
  who.ok && values.includes('gfm_dashboard_reader') && values.includes('on'), who.message || JSON.stringify(values));

for (const view of VIEWS) {
  const answer = await run(`SELECT count(*) AS n FROM ${view}`);
  check(`reads ${view}`, answer.ok, answer.message);
}
for (const table of PEOPLE_TABLES) {
  const answer = await run(`SELECT * FROM ${table} LIMIT 1`);
  check(`refused: ${table}`, !answer.ok && /permission denied|does not exist|not exist/i.test(answer.message), answer.ok ? 'it answered' : answer.message);
}
for (const [label, sql] of [
  ['write refused: a table of its own', 'SELECT 1 FROM (SELECT 1) x; CREATE TABLE dashboards.gfm_reader_probe (x int)'],
  ['write refused: changing a view', 'SELECT * FROM (SELECT 1) x WHERE 0 = (SELECT count(*) FROM pg_catalog.pg_class); UPDATE public.zones SET name = name'],
  ['refused: turning into another login', "SELECT set_config('role', 'postgres', false)"],
  ['refused: web requests from the database (pg_net)', "SELECT net.http_get('http://example.invalid/')"],
  ['refused: files of the server', "SELECT pg_read_file('/etc/hostname')"],
]) {
  const answer = await run(sql);
  check(label, !answer.ok, answer.ok ? 'it answered' : '');
}
console.log(failures ? `${failures} problem(s).` : 'The reader login refuses everything but the dashboards views.');
process.exitCode = failures ? 1 : 0;
