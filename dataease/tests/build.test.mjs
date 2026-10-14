// The dashboard descriptions (dataease/dashboards/*.json) and what lib/build.mjs makes of them, without DataEase:
// ids, colours, the phone layout, the filters and the dataset SQL. Plain Node 24.
//   docker run --rm -v <repo>/dataease:/d -w /d node:24-alpine node --test tests/
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { CANVAS, DASHBOARDS_DIR, FONT_FAMILY, WEEK_DATASETS, buildDashboard, datasetSql, fieldId, loadBase, tableId } from '../lib/build.mjs';
import { config, fakeDatasets } from './fake-datasets.mjs';
import { datasetFields, emptyChartAllowed, frameAncestorsProblem, shiftSpec } from '../seed-dashboards.mjs';

const read = file => JSON.parse(fs.readFileSync(path.join(DASHBOARDS_DIR, file), 'utf8'));
const FILES = ['key-indicators.json', 'zones-districts.json', 'covenant-path.json', 'areas.json', 'trend.json', 'per-capita.json'];
const specs = FILES.map(read);
const base = loadBase();

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

const datasetKeyOf = view => Object.entries(datasets).find(([, d]) => d.id === view.tableId)?.[0];

test('filters: Zone and District everywhere, Weeks only on the charts over several weeks, Area on the area dashboards', () => {
  const expected = [
    ['Zone', 'District', 'Weeks'], ['Zone', 'District', 'Weeks'], ['Zone', 'District', 'Weeks'],
    ['Zone', 'District', 'Area'], ['Zone', 'District', 'Weeks'], ['Zone', 'District', 'Area'],
  ];
  built.forEach((dashboard, i) => {
    const query = dashboard.componentData.find(c => c.component === 'VQuery');
    assert.deepEqual(query.propValue.map(c => c.name), expected[i], dashboard.name);
    for (const condition of query.propValue) assert.ok(condition.checkedFields.length > 0, `${dashboard.name}: ${condition.name} filters something`);
    const weeks = query.propValue.find(c => c.name === 'Weeks');
    if (!weeks) return;
    const weekly = Object.values(dashboard.canvasViewInfo).filter(v => WEEK_DATASETS.includes(datasetKeyOf(v)));
    assert.deepEqual([...weeks.checkedFields].sort(), weekly.map(v => v.id).sort(), dashboard.name);
  });
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

test('counts only: no field of any dataset names a person, a note or a contact', () => {
  for (const spec of config.datasets) {
    for (const field of datasets[spec.key].fields) assert.doesNotMatch(field.gfmKey, /name|note|person|user|email|phone|birth|gender|fc_number|referral/i, `${spec.key}.${field.gfmKey}`);
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
  assert.equal(weekCharts, 6 + 2 + 4 + 7, 'six Key indicators charts, two heat maps, four Covenant path charts, seven Trend charts');
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

// ---- Round 13: the dashboards of the six key indicators of conversion (Areas, Trend, Per 10,000 residents) ---------

const SIX_TITLES = ['New People Being Taught', 'Baptisms and confirmations', 'Baptismal dates', 'Sacrament attendance', 'Members at lessons', 'New member sacrament attendance'];
const SIX_KEYS = ['npbt', 'bc', 'bd', 'sa', 'ml', 'nms'];
const [areasDash, trendDash, perCapitaDash] = built.slice(3);
// A chart field's dataset key: a calculated field and a number keep it in gfmKeyOf, a column is its originName.
const keyOf = f => f.gfmKeyOf || f.originName;

test('the set: six dashboards with fixed numbers 01 to 06 in the order the seed script makes them', () => {
  assert.deepEqual(specs.map(s => s.name), ['Key indicators', 'Zones & districts', 'Covenant path', 'Areas', 'Trend', 'Per 10,000 residents']);
  assert.deepEqual(specs.map(s => s.id), ['1150001000000000000', '1150002000000000000', '1150003000000000000', '1150004000000000000', '1150005000000000000', '1150006000000000000']);
  const seed = fs.readFileSync(path.join(DASHBOARDS_DIR, '..', 'seed-dashboards.mjs'), 'utf8');
  const listed = /const DASHBOARD_FILES = \[([^\]]*)\]/.exec(seed)[1].match(/'[^']+'/g).map(s => s.slice(1, -1));
  assert.deepEqual(listed, FILES, 'seed-dashboards.mjs makes exactly these dashboards');
});

test('Areas (the missionary level): the six key indicators per area, measured against the area\'s own goal, no names', () => {
  const tiles = areasDash.componentData.filter(c => c.innerType === 'rich-text' && c.sizeX === 12).sort((a, b) => a.x - b.x);
  assert.equal(tiles.length, 6);
  SIX_TITLES.forEach((title, i) => assert.match(tiles[i].propValue.textValue, new RegExp(title)));
  for (const tile of tiles) assert.match(tile.propValue.textValue, /% of the goal/);
  assert.match(tiles[0].propValue.textValue, /The key indicator/);
  const header = areasDash.componentData.find(c => c.y === 1).propValue.textValue;
  assert.match(header, /no names of missionaries or of the people they teach/);
  const help = Object.values(areasDash.canvasViewInfo).filter(v => v.type === 'bar-horizontal');
  assert.equal(help.length, 2);
  for (const view of help) { assert.equal(view.customAttr.label.position, 'right'); assert.equal(view.resultCount, 10); assert.equal(keyOf(view.xAxis[0]), 'area'); }
  const table = Object.values(areasDash.canvasViewInfo).find(v => v.type === 'table-normal');
  assert.deepEqual(table.xAxis.map(keyOf), ['zone', 'district', 'area']);
  assert.deepEqual(table.yAxis.map(keyOf), SIX_KEYS.map(k => k + '_pct_of_goal'), 'one % of goal column per key indicator');
});

test('Areas read area totals of the last complete weeks: the area, its goals set the week before, nothing about people', () => {
  for (const file of ['sql/area-latest.sql', 'sql/area-4weeks.sql']) {
    const sql = datasetSql(path.join(DASHBOARDS_DIR, file));
    assert.match(sql, /dashboards\.kpi_area_total_week/);
    for (const key of ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament']) {
      assert.match(sql, new RegExp(`${key}_previous_goal`), `${file}: the goal set the week before for ${key}`);
    }
  }
});

test('Trend: last 4 weeks against the 4 before, % of goal of all six, result and 4-week average per indicator', () => {
  const tiles = trendDash.componentData.filter(c => c.innerType === 'rich-text' && c.sizeX === 12).sort((a, b) => a.x - b.x);
  assert.equal(tiles.length, 6);
  SIX_TITLES.forEach((title, i) => {
    const text = tiles[i].propValue.textValue;
    assert.match(text, new RegExp(title));
    assert.match(text, /Last 4 weeks/);
    assert.match(text, /Previous 4 weeks:/);
    assert.match(text, /Change:/);
  });
  const lines = Object.values(trendDash.canvasViewInfo).filter(v => v.type === 'line');
  assert.equal(lines.length, 7);
  const all = lines.find(v => v.yAxis.length === 6);
  assert.deepEqual(all.yAxis.map(f => f.chartShowName), SIX_TITLES, 'one line per key indicator, in the order of the portal');
  assert.deepEqual(all.yAxis.map(keyOf), SIX_KEYS.map(k => k + '_pct'));
  const others = lines.filter(v => v !== all);
  assert.deepEqual(others.map(v => v.title).sort(), [...SIX_TITLES].sort());
  for (const view of others) assert.deepEqual(view.yAxis.map(f => f.chartShowName), ['Result', '4-week average']);
  const sql = datasetSql(path.join(DASHBOARDS_DIR, 'sql/trend-weeks.sql'));
  assert.match(sql, /LIMIT 29/, 'the average reads 3 weeks further back than the 26 shown');
  assert.match(sql, /ROWS BETWEEN 3 PRECEDING AND CURRENT ROW/);
});

test('Per 10,000 residents: the Geo data views of migration 046, empty until Geo data is uploaded', () => {
  for (const file of ['sql/geo-areas.sql', 'sql/geo-coverage.sql']) {
    const sql = datasetSql(path.join(DASHBOARDS_DIR, file));
    assert.match(sql, /dashboards\.(area_week_per_capita|area_geo_data)/, file);
  }
  const geoAreas = config.datasets.find(d => d.key === 'geo-areas');
  assert.equal(geoAreas.optionalRows, true, 'the per-resident charts may be empty before the first upload');
  assert.equal(config.datasets.find(d => d.key === 'geo-coverage').weekless, true);
  const bars = Object.values(perCapitaDash.canvasViewInfo).filter(v => v.type === 'bar-horizontal');
  assert.equal(bars.length, 6, 'one chart per key indicator');
  assert.deepEqual(bars.map(v => keyOf(v.yAxis[0])).sort(), SIX_KEYS.map(k => k + '_per_10k').sort());
  for (const view of bars) {
    assert.equal(view.resultCount, 10);
    assert.equal(view.yAxis[0].sort, 'desc', `${view.title}: the highest first`);
    assert.match(view.title, /per 10,000 residents$/);
    assert.equal(view.tableId, datasets['geo-areas'].id);
  }
  const tables = Object.values(perCapitaDash.canvasViewInfo).filter(v => v.type === 'table-normal');
  assert.equal(tables.length, 2);
  const geoTable = tables.find(v => v.tableId === datasets['geo-coverage'].id);
  assert.deepEqual(geoTable.yAxis.map(keyOf), ['population', 'size_km2', 'density_per_km2']);
  assert.deepEqual(geoTable.xAxis.map(keyOf), ['zone', 'district', 'area', 'source', 'data_date'], 'where the figures come from and the date they are from');
  const header = perCapitaDash.componentData.find(c => c.y === 1).propValue.textValue;
  assert.match(header, /Areas with a population/);
  assert.match(header, /uploaded in DA Management/);
});

test('seeding: a chart over a dataset marked optionalRows may be empty, every other chart must answer', () => {
  const optional = new Set([datasets['geo-areas'].id]);
  assert.equal(emptyChartAllowed({ tableId: datasets['geo-areas'].id }, optional), true);
  assert.equal(emptyChartAllowed({ tableId: datasets['kpi-weeks'].id }, optional), false);
  assert.equal(emptyChartAllowed({ tableId: Number(datasets['geo-areas'].id) }, new Set()), false, 'nothing is optional unless marked');
});

test('calculated fields use only columns their query returns, and every dataset has a unique index', () => {
  const indexes = config.datasets.map(d => d.index);
  assert.equal(new Set(indexes).size, indexes.length);
  assert.deepEqual(indexes, [...indexes].sort((a, b) => a - b));
  for (const spec of config.datasets) {
    const columns = datasets[spec.key].fields.filter(f => f.extField === 0).map(f => ({ originName: f.originName, groupType: f.groupType }));
    const fields = datasetFields(spec, columns, 'ds', 'table');   // throws on an unknown [column]
    assert.equal(fields.length, columns.length + (spec.calculated || []).length, spec.key);
  }
});

test('only managers reach these dashboards: the new datasets add no way in (reader login, dashboards views only)', () => {
  const reader = fs.readFileSync(path.join(DASHBOARDS_DIR, '..', 'tests', 'reader-check.mjs'), 'utf8');
  assert.match(reader, /'dashboards\.area_geo_data'/);
  assert.match(reader, /'dashboards\.area_week_per_capita'/);
  assert.match(reader, /'public\.area_geo_data'/, 'the Geo data table itself stays refused');
  for (const spec of config.datasets) {
    const sql = datasetSql(path.join(DASHBOARDS_DIR, spec.sql));
    assert.doesNotMatch(sql, /\b(?:public|auth|portal)\./, `${spec.sql} reads nothing outside the dashboards schema`);
  }
});
