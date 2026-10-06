// Arquero: the answer's table -> calculated columns -> filter -> sort -> columns shown -> a Frame the charts draw.
// (Arquero is the dataframe library; nothing here is a table engine of our own.)
import * as aq from 'arquero';
import type { Calc, ChartAnswer, DataProps, Frame } from '../shared/types';
import type { Row } from '../formulas/calc';

import { fieldKey } from './field-key';
export { fieldKey };

/** The answer as an Arquero table: `label` and one column per measure (portal-api gives them in the query's order). */
export function answerTable(answer: ChartAnswer, measures: string[]): { table: aq.ColumnTable; names: Record<string, string>; roles: Record<string, string | undefined> } {
  const { labels, series } = answer.table;
  const columns: Record<string, unknown[]> = { label: labels };
  const names: Record<string, string> = {};
  const roles: Record<string, string | undefined> = {};
  const keys = series.length === measures.length ? measures.map(fieldKey) : series.map((_, i) => `series_${i + 1}`);
  series.forEach((s, i) => { columns[keys[i]] = s.values; names[keys[i]] = s.name; roles[keys[i]] = s.role; });
  return { table: aq.table(columns), names, roles };
}

type Compile = (formula: string, known: string[]) => { run(row: Row): number | null };

/** Adds the calculated columns: each formula is compiled once and evaluated over every row. */
export function withCalcs(table: aq.ColumnTable, calcs: Calc[], compile: Compile): aq.ColumnTable {
  let t = table;
  const known = t.columnNames().filter(n => n !== 'label');
  for (const calc of calcs) {
    const compiled = compile(calc.formula, [...known]);
    const values = (t.objects() as Row[]).map(r => compiled.run(r));
    t = t.assign(aq.table({ [calc.name]: values }));
    known.push(calc.name);
  }
  return t;
}

const OPS: Record<string, (a: number, b: number) => boolean> = { '>': (a, b) => a > b, '>=': (a, b) => a >= b, '<': (a, b) => a < b, '<=': (a, b) => a <= b };

/** filter + orderby + select. Rows with no number for the sort field go last. */
export function shape(table: aq.ColumnTable, props: Pick<DataProps, 'sortBy' | 'sortDir' | 'fields'> & { filter?: DataProps['filter'] }): aq.ColumnTable {
  let t = table;
  const f = props.filter;
  if (f && f.field && t.columnNames().includes(f.field) && OPS[f.op]) {
    const test = OPS[f.op];
    const column = f.field;
    t = t.params({ test, column, value: f.value }).filter(aq.escape((d: any, $: any) => d[$.column] != null && $.test(d[$.column], $.value)));
  }
  if (props.sortBy && props.sortDir !== 'none' && t.columnNames().includes(props.sortBy)) {
    const col = props.sortBy;
    // Missing numbers last, in either direction (orderby alone would put them first when descending).
    const missing = (d: any) => (d[col] == null ? 1 : 0);
    t = t.orderby(aq.escape(missing), props.sortDir === 'desc' ? aq.desc(col) : col);
  }
  const shown = props.fields.filter(n => t.columnNames().includes(n));
  return shown.length ? t.select('label', ...shown) : t;
}

/** groupby + rollup: totals of the fields for each value of `by`. */
export function groupTotals(table: aq.ColumnTable, by: string, fields: string[]): aq.ColumnTable {
  const totals: Record<string, any> = {};
  for (const f of fields) totals[f] = aq.op.sum(f);
  return table.groupby(by).rollup(totals);
}

/** A table as a Frame (labels, and a column per field with its label and format). */
export function toFrame(table: aq.ColumnTable, meta: ChartAnswer['meta'], names: Record<string, string>, calcs: Calc[], roles: Record<string, string | undefined> = {}): Frame {
  const calcByName = new Map(calcs.map(c => [c.name, c]));
  const keys = table.columnNames().filter(n => n !== 'label');
  return {
    labels: (table.array('label') as unknown[]).map(String),
    fields: keys.map((key, slot) => ({
      key, slot, label: calcByName.get(key)?.label ?? names[key] ?? key, format: calcByName.get(key)?.format ?? 'number',
      values: table.array(key) as (number | null)[], role: roles[key],
    })),
    meta,
  };
}
