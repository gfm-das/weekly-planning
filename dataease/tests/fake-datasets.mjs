// Stand-in DataEase datasets for the tests: the columns of each dataset query (read from its SQL file) and its calculated
// fields, described as DataEase would after saving them. Used by build.test.mjs and new-dashboards.test.mjs.
import fs from 'node:fs';
import path from 'node:path';
import { DASHBOARDS_DIR, datasetSql, fieldId } from '../lib/build.mjs';

export const config = JSON.parse(fs.readFileSync(path.join(DASHBOARDS_DIR, 'datasets.json'), 'utf8'));

// The output columns of the last SELECT of a query: each top-level item's alias, or its last name.
export function outputColumns(sql) {
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

// The text columns of the datasets (everything else is a number or the week).
const TEXT_COLUMNS = /^(week_label|zone|district|area|source|data_date)$/;

// Stand-in datasets: every field a dashboard asks for, as DataEase would describe it after saving.
export function fakeDatasets() {
  const datasets = {};
  for (const spec of config.datasets) {
    const sql = datasetSql(path.join(DASHBOARDS_DIR, spec.sql));
    const columns = outputColumns(sql);
    const fields = columns.map((name, i) => ({
      id: fieldId(spec.index, i), originName: name, gfmKey: name, name: spec.labels?.[name] || name, extField: 0,
      groupType: TEXT_COLUMNS.test(name) || name === 'week' ? 'd' : 'q', deType: name === 'week' ? 1 : TEXT_COLUMNS.test(name) ? 0 : 2,
    }));
    (spec.calculated || []).forEach((c, i) => fields.push({ id: fieldId(spec.index, 500 + i), originName: c.expression, gfmKey: c.name, name: c.label, extField: 2, groupType: c.deType === 0 ? 'd' : 'q', deType: c.deType, gfmAgg: true }));
    datasets[spec.key] = { id: String(1302000000000000000n + BigInt(spec.index)), name: spec.name, fields };
  }
  return datasets;
}
