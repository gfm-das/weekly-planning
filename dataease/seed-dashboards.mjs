// Sets up DataEase for the portal's Dashboards and checks it. Plain Node 24, no packages; it talks to DataEase's
// own web API as the one Community Edition account ("admin"). Run it in a short-lived container on DataEase's
// private network (dataease/seed-dashboards.ps1 does this), never with the password on a command line.
//
//   node dataease/seed-dashboards.mjs            first start and updates: see below
//   node dataease/seed-dashboards.mjs --check    only read: every chart of the three dashboards must answer
//   node dataease/seed-dashboards.mjs --reset    also rebuild the three dashboards from the repository files
//                                                (changes made in DataEase to them are replaced; back up first)
//   node dataease/seed-dashboards.mjs --export   write the dashboards as they are in DataEase now to
//                                                dataease/dashboards/export/ (to keep edits made in DataEase)
//
// What a normal run does, and it is safe to run again:
//  1. Signs in. On the very first start DataEase has its public default password; it is changed at once to
//     DE_ADMIN_PASSWORD from dataease/.env, so the default never works on this server.
//  2. Removes DataEase's own Chinese sample (the tea-shop dashboard, its datasets and its "Demo" data source).
//  3. Creates or updates the data source "GFM mission data (read-only)": login gfm_dashboard_reader through the
//     relay container, at most 4 connections.
//  4. Creates or updates the six datasets of dataease/dashboards/datasets.json (the SQL in dashboards/sql/).
//  5. Creates the three dashboards that are missing (fixed ids), publishes them, and leaves existing ones alone
//     (people may have changed them in DataEase) unless --reset is given.
//  6. Checks every chart like --check.
// Prints names of dashboards, charts and datasets and counts only; never passwords, tokens or people's data.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DataEase, DataEaseError, DEFAULT_PASSWORD, changePassword, flattenTree } from './lib/dataease-client.mjs';
import { buildDashboard, datasetSql, fieldId, tableId, DASHBOARDS_DIR, loadBase } from './lib/build.mjs';
import {
  DATAEASE_VERSION, MAX_GENERATIONS, createFolder, dashboardNodes, dashboardState, deleteDashboard,
  encodeCalculatedFields, findDashboard, saveAndPublish,
} from './lib/dashboard-store.mjs';

const args = new Set(process.argv.slice(2));
const CHECK_ONLY = args.has('--check');
// A new mission has no people loaded yet, so a chart without rows is expected then (the installer passes this).
const ALLOW_EMPTY = process.env.GFM_ALLOW_EMPTY_CHARTS === '1';
const RESET = args.has('--reset');
const EXPORT = args.has('--export');
const SAMPLE_NAME = '【官方示例】'; // "official sample": the folder of DataEase's own demo
const DASHBOARD_FOLDER_ID = '1150000000000000000'; // "Mission"; the ids of dashboards and charts are in the dashboard files
const DASHBOARD_FILES = ['key-indicators.json', 'zones-districts.json', 'covenant-path.json'];
// Calculated fields that add up rows (DataEase must then not add them up once more).
const AGGREGATE = /\b(SUM|MAX|MIN|AVG|COUNT)\s*\(/i;

const env = name => (process.env[name] || '').trim();
const base = env('DE_BASE') || 'http://dataease:8100';
const say = message => console.log(message);
let failures = 0;
const fail = message => { failures += 1; console.log('FAIL ' + message); };

function requireSecret(name) {
  const value = env(name);
  if (!value || /REPLACE|example/i.test(value)) throw new Error(`${name} is missing in dataease/.env (run dataease/init-env.ps1).`);
  return value;
}

// DataEase asks for 8-20 characters with a lower-case and an upper-case letter, a digit and a sign.
export function acceptablePassword(value) {
  return /^(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])(?=.*[~!@#$%^&*()_+\-={}|":<>?`[\];',./])[a-zA-Z0-9~!@#$%^&*()_+\-={}|":<>?`[\];',./]{8,20}$/.test(value);
}

// ---- 1. Signing in -----------------------------------------------------------------------------------------------

async function signIn() {
  const password = requireSecret('DE_ADMIN_PASSWORD');
  if (!acceptablePassword(password)) throw new Error('DE_ADMIN_PASSWORD must be 8-20 characters with a-z, A-Z, 0-9 and a sign (DataEase rule).');
  const de = new DataEase(base);
  try {
    await de.login(password);
    say('Signed in to DataEase.');
    return de;
  } catch (error) {
    if (!(error instanceof DataEaseError)) throw error;
  }
  if (CHECK_ONLY) throw new Error('DataEase refused DE_ADMIN_PASSWORD. If the Data Analyst changed it in DataEase, give the current one (seed-dashboards.ps1 asks).');
  // First start: DataEase still has its published default password. Replace it now.
  try {
    await de.login(DEFAULT_PASSWORD);
  } catch {
    throw new Error('DataEase refused DE_ADMIN_PASSWORD and the default. If the Data Analyst changed the password in DataEase, give the current one (seed-dashboards.ps1 asks).');
  }
  await changePassword(de, DEFAULT_PASSWORD, password);
  say('First start: the default DataEase password was replaced by the generated one (dataease/.env).');
  return new DataEase(base).login(password);
}

// ---- 2. DataEase's own sample ------------------------------------------------------------------------------------

async function removeSamples(de) {
  for (const folder of (await dashboardNodes(de)).filter(n => n.name === SAMPLE_NAME && !n.leaf)) {
    for (const leaf of flattenTree(folder.children).filter(n => n.leaf)) await deleteDashboard(de, leaf.id);
    await deleteDashboard(de, folder.id);
    say('Removed DataEase\'s sample dashboards.');
  }
  const datasets = flattenTree(await de.post('/datasetTree/tree', { busiFlag: 'dataset' }));
  for (const folder of datasets.filter(n => n.name === SAMPLE_NAME && !n.leaf)) {
    for (const leaf of flattenTree(folder.children).filter(n => n.leaf)) await de.post(`/datasetTree/delete/${leaf.id}`);
    await de.post(`/datasetTree/delete/${folder.id}`);
    say('Removed DataEase\'s sample datasets.');
  }
  for (const source of (await dataSources(de)).filter(n => n.name === 'Demo' && n.type === 'mysql' && n.leaf)) {
    await de.get(`/datasource/delete/${source.id}`);
    say('Removed DataEase\'s sample data source "Demo".');
  }
}

// ---- 3. The data source ------------------------------------------------------------------------------------------

async function dataSources(de) {
  return flattenTree(await de.post('/datasource/tree', { busiFlag: 'datasource' }));
}

async function ensureDatasource(de, name) {
  const configuration = {
    host: env('GFM_DATAEASE_DB_HOST') || 'dbproxy',
    port: Number(env('GFM_DATAEASE_DB_PORT') || 5432),
    dataBase: env('GFM_DATAEASE_DB_NAME') || 'postgres',
    username: 'gfm_dashboard_reader',
    password: requireSecret('GFM_DASHBOARD_READER_PASSWORD'),
    schema: 'dashboards',
    urlType: 'hostName', extraParams: '', authMethod: 'passwd', customDriver: 'default',
    initialPoolSize: 1, minPoolSize: 1, maxPoolSize: 4, queryTimeout: 30,
  };
  const body = {
    name, type: 'pg', nodeType: 'datasource', pid: '0',
    description: 'Read-only: the dashboards views (migrations 018 and 025) as gfm_dashboard_reader. No people tables.',
    configuration: Buffer.from(JSON.stringify(configuration)).toString('base64'),
  };
  const checked = await de.post('/datasource/validate', body);
  if (checked?.status !== 'Success') throw new Error('DataEase cannot reach the mission database as gfm_dashboard_reader.');
  const existing = (await dataSources(de)).find(n => n.leaf && n.name === name);
  if (existing) {
    await de.post('/datasource/update', { ...body, id: existing.id });
    say(`Data source "${name}" is up to date.`);
    return existing.id;
  }
  const saved = await de.post('/datasource/save', body);
  say(`Data source "${name}" created.`);
  return saved.id;
}

// ---- 4. The datasets ---------------------------------------------------------------------------------------------

async function ensureDatasetFolder(de, name) {
  const found = flattenTree(await de.post('/datasetTree/tree', { busiFlag: 'dataset' })).find(n => !n.leaf && n.name === name);
  if (found) return found.id;
  const saved = await de.post('/datasetTree/save', { name, pid: '0', nodeType: 'folder' });
  return saved.id;
}

// The columns DataEase finds in a dataset's SQL. Right after the data source is saved again, DataEase reopens its
// connections and briefly calls it invalid, so that answer is waited out (8 tries, 2.5 s apart).
async function readSqlColumns(de, request) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await de.post('/datasetData/tableField', request);
    } catch (error) {
      if (attempt >= 8 || !/validity of the datasource/i.test(error.message)) throw error;
      await new Promise(resolve => setTimeout(resolve, 2500));
    }
  }
}

/**
 * The fields of a dataset as DataEase saves them: one per SQL column (with the label of datasets.json), then the
 * calculated fields, whose formulas name columns as [column] and are saved as [field id], Base64-encoded.
 */
export function datasetFields(spec, columns, datasourceId, sqlTable) {
  const labels = spec.labels || {};
  const fields = columns.map((column, i) => ({
    ...column,
    id: fieldId(spec.index, i),
    datasourceId, datasetTableId: sqlTable, checked: true,
    name: labels[column.originName] || column.originName,
    description: column.originName,
  }));
  const byColumn = Object.fromEntries(fields.map(f => [f.originName, f]));
  (spec.calculated || []).forEach((calc, i) => {
    const expression = calc.expression.replace(/\[([a-z0-9_]+)\]/g, (_, column) => {
      if (!byColumn[column]) throw new Error(`Dataset ${spec.key}: calculated field ${calc.name} uses unknown column ${column}.`);
      return `[${byColumn[column].id}]`;
    });
    fields.push({
      id: fieldId(spec.index, 500 + i), datasourceId: null, datasetTableId: null, originName: Buffer.from(expression, 'utf8').toString('base64'),
      name: calc.label, description: calc.name, groupType: calc.deType === 0 ? 'd' : 'q', type: calc.deType === 0 ? 'VARCHAR' : 'DOUBLE',
      deType: calc.deType, deExtractType: calc.deType, extField: 2, checked: true, dateFormat: '', dateFormatType: '',
    });
  });
  return fields;
}

/**
 * The saved fields, each marked with the key the dashboard files use for it (gfmKey: the SQL column, or the name of
 * a calculated field), a calculated field's formula back as text, and gfmAgg on the ones that add up rows.
 */
export function withDashboardKeys(spec, savedFields) {
  const calculatedNames = new Map((spec.calculated || []).map((c, i) => [fieldId(spec.index, 500 + i), c.name]));
  const aggregate = new Set((spec.calculated || []).filter(c => AGGREGATE.test(c.expression)).map(c => c.name));
  return savedFields.map(field => {
    const calculated = field.extField === 2;
    const key = calculated ? calculatedNames.get(String(field.id)) : field.originName;
    const out = { ...field, gfmKey: key };
    if (calculated && typeof out.originName === 'string') {
      const text = Buffer.from(out.originName, 'base64').toString('utf8');
      if (text.includes('[')) out.originName = text;   // DataEase answered with the Base64 form
    }
    if (aggregate.has(key)) out.gfmAgg = true;
    return out;
  });
}

async function ensureDataset(de, spec, datasourceId, folderId, existingByName) {
  const tableName = spec.key.replace(/-/g, '_');
  const sqlTable = tableId(spec.index);
  const sql = datasetSql(path.join(DASHBOARDS_DIR, spec.sql));
  const info = JSON.stringify({ table: tableName, sql: Buffer.from(sql, 'utf8').toString('base64') });
  const columns = await readSqlColumns(de, { datasourceId, id: sqlTable, info, tableName, type: 'sql', isCross: false, sqlVariableDetails: '[]' });
  const fields = datasetFields(spec, columns, datasourceId, sqlTable);
  const body = {
    name: spec.name, pid: folderId, nodeType: 'dataset', isCross: false,
    union: [{ currentDs: { sqlVariableDetails: '[]', tableName, type: 'sql', datasourceId, id: sqlTable, info }, currentDsFields: fields.filter(f => f.extField !== 2), childrenDs: [], unionToParent: { unionType: 'left', unionFields: [] } }],
    allFields: fields,
  };
  const existing = existingByName.get(spec.name);
  if (existing) body.id = existing.id;
  const saved = await de.post('/datasetTree/save', body);
  const details = await de.post('/datasetTree/details/' + saved.id, {});
  const savedFields = withDashboardKeys(spec, details.allFields);
  say(`Dataset "${spec.name}" ${existing ? 'updated' : 'created'} (${savedFields.length} fields).`);
  return { id: String(saved.id), name: spec.name, fields: savedFields };
}

// The datasets by key (datasets.json). create: make or update them (a normal run); otherwise only read them (--check).
async function loadDatasets(de, config, create) {
  const folderId = create ? await ensureDatasetFolder(de, config.folder) : null;
  const tree = flattenTree(await de.post('/datasetTree/tree', { busiFlag: 'dataset' }));
  const existingByName = new Map(tree.filter(n => n.leaf).map(n => [n.name, n]));
  const datasets = {};
  const datasourceId = create ? await ensureDatasource(de, config.datasource)
    : (await dataSources(de)).find(n => n.leaf && n.name === config.datasource)?.id;
  if (!datasourceId) throw new Error(`Data source "${config.datasource}" is missing: run without --check first.`);
  for (const spec of config.datasets) {
    if (create) {
      datasets[spec.key] = await ensureDataset(de, spec, datasourceId, folderId, existingByName);
    } else {
      const node = existingByName.get(spec.name);
      if (!node) throw new Error(`Dataset "${spec.name}" is missing: run without --check first.`);
      const details = await de.post('/datasetTree/details/' + node.id, {});
      datasets[spec.key] = { id: String(node.id), name: spec.name, fields: details.allFields };
    }
  }
  return datasets;
}

// ---- 5. The dashboards -------------------------------------------------------------------------------------------

// DataEase keeps a deleted dashboard's row (it is only marked deleted), so its id cannot be used again. A dashboard
// therefore has "generations": the ids in its file (generation 0), plus 10^10 for each later generation (the
// dashboards are 10^12 apart and their charts 10^6 apart; see fieldId in lib/build.mjs for why so far apart).
export function shiftSpec(spec, generation) {
  if (!generation) return spec;
  const shift = id => String(BigInt(id) + BigInt(generation) * 10000000000n);
  return { ...spec, id: shift(spec.id), components: spec.components.map(c => ({ ...c, id: shift(c.id) })) };
}

// The current generation of a dashboard: the live one, else the first free one. { spec, state }.
async function currentGeneration(de, spec) {
  for (let generation = 0; generation < MAX_GENERATIONS; generation += 1) {
    const shifted = shiftSpec(spec, generation);
    const state = await dashboardState(de, shifted.id);
    if (state !== 'deleted') return { spec: shifted, state };
  }
  throw new Error(`Dashboard "${spec.name}" was deleted ${MAX_GENERATIONS} times; make it in DataEase by hand instead.`);
}

// The dashboard of a file as it is in DataEase now (its current generation), or null when there is none.
async function findCurrentDashboard(de, spec) {
  const { spec: current, state } = await currentGeneration(de, spec);
  if (state !== 'live') return null;
  return findDashboard(de, current.id);
}

async function ensureDashboardFolder(de) {
  if ((await dashboardNodes(de)).some(n => String(n.id) === DASHBOARD_FOLDER_ID)) return;
  await createFolder(de, { id: DASHBOARD_FOLDER_ID, name: 'Mission', parentId: '0' });
  say('Dashboard folder "Mission" created.');
}

// Creates the dashboards that are missing; with --reset also rebuilds the ones that are there.
async function ensureDashboards(de, specs, datasets) {
  await ensureDashboardFolder(de);
  const base = loadBase();
  for (const spec of specs) {
    const { spec: current, state } = await currentGeneration(de, spec);
    const exists = state === 'live';
    if (exists && !RESET) { say(`Dashboard "${spec.name}" exists; kept as it is (use --reset to rebuild it).`); continue; }
    if (current.id !== spec.id && !exists) say(`Dashboard "${spec.name}" was deleted in DataEase; it is made again with new ids.`);
    await saveAndPublish(de, buildDashboard(current, datasets, base), { folderId: DASHBOARD_FOLDER_ID, exists });
    say(`Dashboard "${spec.name}" ${exists ? 'rebuilt' : 'created'} and published.`);
  }
}

// ---- 6. Checks ---------------------------------------------------------------------------------------------------

// Asks DataEase for the numbers of one chart, as the dashboard page does. Returns the number of rows.
async function chartRows(de, view) {
  const [encoded] = Object.values(encodeCalculatedFields({ [view.id]: view }));
  const request = { filter: [], drill: [], queryFrom: 'panel', resultCount: view.resultCount || 1000, resultMode: view.resultMode || 'all' };
  const answer = await de.post('/chartData/getData', { ...encoded, data: undefined, chartExtRequest: request });
  const rows = answer?.data?.tableRow || answer?.data?.data || [];
  return Array.isArray(rows) ? rows.length : 0;
}

async function checkDashboard(de, spec) {
  const name = spec.name;
  const dv = await findCurrentDashboard(de, spec);
  if (!dv) { fail(`dashboard "${name}" is missing`); return; }
  if (dv.status !== 1) fail(`dashboard "${name}" is not published (status ${dv.status})`);
  let charts = 0, withNumbers = 0;
  for (const view of Object.values(dv.canvasViewInfo || {})) {
    const hasData = (view.xAxis?.length || view.yAxis?.length || view.extColor?.length);
    if (!hasData) continue;
    charts += 1;
    const started = Date.now();
    const title = view.title || view.type;
    try {
      const count = await chartRows(de, view);
      if (count > 0) withNumbers += 1;
      else if (!ALLOW_EMPTY) fail(`"${name}" › "${title}" answered without rows`);
      say(`  ok  ${name} › ${title} (${view.type}): ${count} row(s), ${Date.now() - started} ms`);
    } catch (error) {
      fail(`"${name}" › "${title}": ${error.message}`);
    }
  }
  if (!charts) fail(`dashboard "${name}" has no charts`);
  say(`Dashboard "${name}": ${withNumbers} of ${charts} charts answered with numbers.`);
}

/**
 * The portal shows Dashboards in its frame, so DataEase must name the portal addresses in its frame-ancestors
 * (GFM_PORTAL_FRAME_ORIGINS). A value without double quotes in dataease/.env leaves only 'self', and the Dashboards
 * tab stays blank; this says so. Returns the problem, or null.
 */
export function frameAncestorsProblem(csp) {
  const rule = /frame-ancestors([^;]*)/i.exec(String(csp || ''));
  if (!rule) return 'DataEase sends no frame-ancestors rule, so the portal cannot show Dashboards.';
  if (!/https?:\/\/\S+/i.test(rule[1])) {
    return `DataEase lets only itself show Dashboards in a frame (frame-ancestors${rule[1]}): put double quotes around the whole GFM_PORTAL_FRAME_ORIGINS value in dataease/.env, then start DataEase again (docker compose ... up -d).`;
  }
  return null;
}

async function checkFrameAncestors() {
  try {
    const answer = await fetch(base + '/', { redirect: 'manual' });
    const problem = frameAncestorsProblem(answer.headers.get('content-security-policy'));
    if (problem) fail(problem); else say('The portal may show Dashboards in its frame (frame-ancestors).');
  } catch (error) {
    fail('frame-ancestors could not be read: ' + error.message);
  }
}

// ---- --export ----------------------------------------------------------------------------------------------------

async function exportDashboards(de, specs) {
  const dir = path.join(DASHBOARDS_DIR, 'export');
  fs.mkdirSync(dir, { recursive: true });
  for (const spec of specs) {
    const dv = await findCurrentDashboard(de, spec);
    if (!dv) { fail(`dashboard "${spec.name}" is missing`); continue; }
    const views = Object.fromEntries(Object.entries(dv.canvasViewInfo || {}).map(([k, v]) => [k, { ...v, data: null }]));
    const out = { id: dv.id, name: dv.name, exportedAt: new Date().toISOString(), dataeaseVersion: DATAEASE_VERSION,
      canvasStyleData: JSON.parse(dv.canvasStyleData), componentData: JSON.parse(dv.componentData), canvasViewInfo: views };
    const file = path.join(dir, spec.file.replace(/\.json$/, '.dataease.json'));
    fs.writeFileSync(file, JSON.stringify(out, null, 1) + '\n');
    say(`Exported "${dv.name}" to dataease/dashboards/export/${path.basename(file)}.`);
  }
}

// ---- main --------------------------------------------------------------------------------------------------------

function readDashboardFiles() {
  return DASHBOARD_FILES.filter(f => fs.existsSync(path.join(DASHBOARDS_DIR, f)))
    .map(f => ({ ...JSON.parse(fs.readFileSync(path.join(DASHBOARDS_DIR, f), 'utf8')), file: f }));
}

async function main() {
  const config = JSON.parse(fs.readFileSync(path.join(DASHBOARDS_DIR, 'datasets.json'), 'utf8'));
  const specs = readDashboardFiles();
  const de = await signIn();
  if (EXPORT) { await exportDashboards(de, specs); return; }
  if (!CHECK_ONLY) {
    await removeSamples(de);
    const datasets = await loadDatasets(de, config, true);
    await ensureDashboards(de, specs, datasets);
  }
  for (const spec of specs) await checkDashboard(de, spec);
  await checkFrameAncestors();
  if (failures) { console.log(`${failures} problem(s).`); process.exitCode = 1; } else say('All dashboards answer.');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.log('ERROR ' + error.message); process.exitCode = 1; });
}
