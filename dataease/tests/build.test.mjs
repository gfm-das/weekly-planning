// The dashboard descriptions (dataease/dashboards/*.json) and what lib/build.mjs makes of them, without DataEase:
// ids, colours, the phone layout, the filters and the dataset SQL. Plain Node 24.
//   docker run --rm -v <repo>/dataease:/d -w /d node:24-alpine node --test tests/
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { CANVAS, DASHBOARDS_DIR, FONT_FAMILY, buildDashboard, datasetSql, fieldId, loadBase, tableId } from '../lib/build.mjs';
import { frameAncestorsProblem, shiftSpec } from '../seed-dashboards.mjs';

const read = file => JSON.parse(fs.readFileSync(path.join(DASHBOARDS_DIR, file), 'utf8'));
const config = read('datasets.json');
const specs = ['key-indicators.json', 'zones-districts.json', 'covenant-path.json'].map(read);
const base = loadBase();

// The output columns of the last SELECT of a query: each top-level item's alias, or its last name.
function outputColumns(sql) {
  const text = sql.slice(sql.lastIndexOf('\nSELECT ') + '\nSELECT '.length);
  const items = [];
  let depth = 0, current = '';
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (depth === 0 && /^\sFROM\s/i.test(text.slice(i - 1, i + 5)) && /\s/.test(text[i - 1] || ' ')) break;
    if (ch === ',' && depth === 0) { items.push(current); current = ''; continue; }
    current += ch;
  }
  items.push(current);
  return items.map(item => {
    const alias = /\bAS\s+([a-z_0-9]+)\s*$/i.exec(item.trim());
    return alias ? alias[1] : item.trim().split('.').pop();
  });
}

// Stand-in datasets: every field a dashboard asks for, as DataEase would describe it after saving.
function fakeDatasets() {
  const datasets = {};
  for (const spec of config.datasets) {
    const sql = datasetSql(path.join(DASHBOARDS_DIR, spec.sql));
    const columns = outputColumns(sql);
    const fields = columns.map((name, i) => ({
      id: fieldId(spec.index, i), originName: name, gfmKey: name, name: spec.labels?.[name] || name, extField: 0,
      groupType: /^(week|week_label|zone|district)$/.test(name) ? 'd' : 'q', deType: name === 'week' ? 1 : /^(week_label|zone|district)$/.test(name) ? 0 : 2,
    }));
    (spec.calculated || []).forEach((c, i) => fields.push({ id: fieldId(spec.index, 500 + i), originName: c.expression, gfmKey: c.name, name: c.label, extField: 2, groupType: c.deType === 0 ? 'd' : 'q', deType: c.deType, gfmAgg: true }));
    datasets[spec.key] = { id: String(1302000000000000000n + BigInt(spec.index)), name: spec.name, fields };
  }
  return datasets;
}

const datasets = fakeDatasets();
const built = specs.map(spec => buildDashboard(spec, datasets, base));

test('the dataset SQL reads only the dashboards views and leaves the week in progress out', () => {
  for (const spec of config.datasets) {
    const sql = datasetSql(path.join(DASHBOARDS_DIR, spec.sql));
    const tables = [...sql.matchAll(/\b(?:FROM|JOIN)\s+([a-z_]+\.[a-z_]+)/gi)].map(m => m[1]);
    assert.ok(tables.length > 0, spec.sql);
    for (const table of tables) assert.match(table, /^dashboards\./, `${spec.sql} reads ${table}`);
    assert.match(sql, /< cur\.sunday/, `${spec.sql}: complete weeks only`);
    assert.doesNotMatch(sql, /;\s*\S/, `${spec.sql}: one statement`);
  }
});

test('ids: fixed, in 1.15e18..1.2e18, and far enough apart that DataEase cannot mix them up', () => {
  const dashboards = built.map(b => BigInt(b.id));
  const all = built.flatMap(b => [b.id, ...b.componentData.map(c => c.id)]).map(BigInt);
  assert.equal(new Set(all.map(String)).size, all.length, 'no id twice');
  for (const id of all) assert.ok(id >= 1150000000000000000n && id < 1200000000000000000n, String(id));
  const sorted = [...all].sort((a, b) => (a < b ? -1 : 1));
  for (let i = 1; i < sorted.length; i += 1) assert.ok(sorted[i] - sorted[i - 1] >= 10000n, `${sorted[i - 1]} and ${sorted[i]}`);
  for (let i = 1; i < dashboards.length; i += 1) assert.ok(dashboards[i] - dashboards[i - 1] >= 10n ** 12n);
  // Generations (a dashboard made again after someone deleted it in DataEase) never meet the next dashboard.
  const later = shiftSpec(specs[0], 89);
  assert.ok(BigInt(later.id) < BigInt(specs[1].id));
  assert.ok(later.components.every((c, i) => BigInt(c.id) - BigInt(specs[0].components[i].id) === 89n * 10n ** 10n));
  const fields = config.datasets.flatMap(s => [fieldId(s.index, 0), fieldId(s.index, 1), fieldId(s.index, 599), tableId(s.index)]).map(BigInt).sort((a, b) => (a < b ? -1 : 1));
  for (let i = 1; i < fields.length; i += 1) assert.ok(fields[i] - fields[i - 1] >= 10000n);
});

test('colour lists have 9 colours (DataEase fills shorter lists with its own)', () => {
  for (const dashboard of built) {
    assert.equal(dashboard.canvasStyleData.component.chartColor.basicStyle.colors.length, 9);
    for (const view of Object.values(dashboard.canvasViewInfo)) assert.equal(view.customAttr.basicStyle.colors.length, 9, view.title);
  }
  const heat = Object.values(built[1].canvasViewInfo).filter(v => v.type === 't-heatmap');
  assert.equal(heat.length, 2);
  for (const view of heat) {
    assert.equal(view.customAttr.basicStyle.colors[0], '#eef5f7', 'light: far below the goal');
    assert.equal(view.customAttr.basicStyle.colors[8], '#00667a', 'deep teal: at or above');
  }
});

test('Key indicators: New People Being Taught first, six tiles against the goal set the week before, six trend charts', () => {
  const [ki] = built;
  const tiles = ki.componentData.filter(c => c.innerType === 'rich-text' && c.sizeX === 12).sort((a, b) => a.x - b.x);
  assert.equal(tiles.length, 6);
  assert.match(tiles[0].propValue.textValue, /New People Being Taught/);
  assert.match(tiles[0].propValue.textValue, /The key indicator/);
  for (const tile of tiles) assert.match(tile.propValue.textValue, /% of the goal/);
  const lines = Object.values(ki.canvasViewInfo).filter(v => v.type === 'line');
  assert.equal(lines.length, 6);
  for (const line of lines) {
    assert.deepEqual(line.yAxis.map(f => f.chartShowName), ['Result', 'Goal set the week before', 'Trend']);
    assert.match(line.yAxis[2].gfmKeyOf || line.yAxis[2].originName, /_trend$/);
  }
});

test('filters: Zone, District and Weeks; Weeks only on the charts over several weeks', () => {
  for (const dashboard of built) {
    const query = dashboard.componentData.find(c => c.component === 'VQuery');
    assert.deepEqual(query.propValue.map(c => c.name), ['Zone', 'District', 'Weeks']);
    const weeks = query.propValue[2];
    const weekly = Object.values(dashboard.canvasViewInfo).filter(v => ['kpi-weeks', 'zone-heat', 'people-weeks'].includes(Object.entries(datasets).find(([, d]) => d.id === v.tableId)?.[0]));
    assert.deepEqual([...weeks.checkedFields].sort(), weekly.map(v => v.id).sort(), dashboard.name);
    for (const condition of query.propValue.slice(0, 2)) assert.ok(condition.checkedFields.length > 0, `${dashboard.name}: ${condition.name}`);
  }
});

test('phone layout: every part is on the phone, inside the 72 columns, nothing overlaps', () => {
  for (const dashboard of built) {
    const boxes = dashboard.componentData.map(c => {
      assert.equal(c.inMobile, true, c.id);
      assert.ok(c.mx >= 1 && c.mx + c.mSizeX - 1 <= 72 && c.my >= 1 && c.mSizeY > 0, `${dashboard.name} ${c.id}`);
      return c;
    });
    for (const a of boxes) for (const b of boxes) {
      if (a === b) continue;
      const apart = a.mx + a.mSizeX <= b.mx || b.mx + b.mSizeX <= a.mx || a.my + a.mSizeY <= b.my || b.my + b.mSizeY <= a.my;
      assert.ok(apart, `${dashboard.name}: ${a.id} and ${b.id} overlap on the phone`);
    }
  }
});

test('covenant path: counts only (no field of the datasets names a person)', () => {
  for (const spec of config.datasets.filter(s => s.key.startsWith('people-'))) {
    for (const field of datasets[spec.key].fields) assert.doesNotMatch(field.gfmKey, /name|note|person|user|email|phone/i);
  }
});

test('readable in the portal: a 1280 x 800 canvas, a sans-serif font, and parts that fit their rows', () => {
  for (const dashboard of built) {
    assert.equal(dashboard.canvasStyleData.width, CANVAS.width);
    assert.equal(dashboard.canvasStyleData.height, CANVAS.height);
    assert.deepEqual([CANVAS.width, CANVAS.height], [1280, 800], 'about a laptop screen, not DataEase\'s 1920 x 1080');
    assert.equal(dashboard.canvasStyleData.fontFamily, FONT_FAMILY);
    const header = dashboard.componentData.find(c => c.y === 1);
    assert.equal(header.sizeY, 4, `${dashboard.name}: the header has room for its note`);
    const query = dashboard.componentData.find(c => c.component === 'VQuery');
    assert.equal(query.sizeY, 6, `${dashboard.name}: the filters and Query fit`);
    for (const c of query.propValue) assert.ok(c.queryConditionWidth > 0 && c.queryConditionWidth <= 190, `${dashboard.name}: ${c.name} is narrower than DataEase's 227 px`);
    for (const c of dashboard.componentData.filter(c => c.innerType === 'rich-text')) {
      assert.match(c.propValue.textValue, /font-family:'Segoe UI'/, `${dashboard.name}: ${c.id} in the sans-serif font`);
      for (const size of c.propValue.textValue.match(/font-size:(\d+)px/g) || []) assert.ok(Number(size.slice(10, -2)) >= 13, `${dashboard.name}: ${c.id} has text under 13 px (11 px on screen in the portal)`);
    }
  }
  const tiles = built[0].componentData.filter(c => c.innerType === 'rich-text' && c.sizeX === 12);
  for (const tile of tiles) assert.ok(tile.sizeY >= 10, 'a Key indicators tile has room for two-line titles');
});

test('the latest complete week keeps its label: week axes upright (slanted in heat maps), 11 px', () => {
  let weekCharts = 0;
  for (const dashboard of built) {
    for (const view of Object.values(dashboard.canvasViewInfo)) {
      const x = view.xAxis?.[0];
      if (!x || x.gfmKey !== 'week' && x.originName !== 'week') continue;
      weekCharts += 1;
      const label = view.customStyle.xAxis.axisLabel;
      if (view.type === 't-heatmap') assert.equal(label.rotate, -45, `${dashboard.name}: ${view.title}`);
      else { assert.equal(label.rotate, -90, `${dashboard.name}: ${view.title}`); assert.equal(label.fontSize, 11); }
    }
  }
  assert.equal(weekCharts, 6 + 2 + 4, 'six Key indicators charts, two heat maps, four Covenant path charts');
  const conf = fs.readFileSync(path.join(DASHBOARDS_DIR, '..', 'web', 'default.conf'), 'utf8');
  assert.match(conf, /sub_filter 'xAxis:\{nice:!0,label:\{autoRotate:!1,autoHide:\{type:"equidistance",cfg:\{minGap:6\}\}\}\}' 'xAxis:\{nice:!0,label:\{autoRotate:!1,autoHide:\{type:"equidistanceWithReverseBoth",cfg:\{minGap:6\}\}\}\}';/,
    'nginx keeps the first and last x-axis label of every chart (G2Plot default changed)');
});

test('districts that may need help: the numbers stand beside the bars', () => {
  const help = Object.values(built[1].canvasViewInfo).filter(v => v.type === 'bar-horizontal');
  assert.equal(help.length, 2);
  for (const view of help) assert.equal(view.customAttr.label.position, 'right');
});

test('frame-ancestors: the portal must be named, else the Dashboards tab stays blank', () => {
  assert.equal(frameAncestorsProblem("default-src *; frame-ancestors 'self' http://localhost:8070 http://192.168.1.20:8070"), null);
  assert.match(frameAncestorsProblem("default-src *; frame-ancestors 'self'"), /double quotes/);
  assert.match(frameAncestorsProblem("default-src *; frame-ancestors self"), /double quotes/);
  assert.match(frameAncestorsProblem(null), /no frame-ancestors/);
});
