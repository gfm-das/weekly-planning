// The data worker: Arquero and math.js run here, not in the page.
// Why: both build small functions from text at run time (Arquero compiles its table expressions, math.js its
// formulas), which the page's Content-Security-Policy forbids on purpose (no 'unsafe-eval' next to the manager's sign-in).
// The manager serves this one file with its own policy: it may build functions, but it has no network, no page, no
// cookies and no storage. It only turns numbers it is given into numbers it gives back.
import { compileFormula, FormulaError } from '../formulas/calc';
import { answerTable, shape, toFrame, withCalcs } from './pipeline';
import type { Calc, ChartAnswer, DataProps } from '../shared/types';

type Request =
  | { id: number; op: 'frame'; answer: ChartAnswer; props: DataProps }
  | { id: number; op: 'check'; formula: string; known: string[]; keys: string[]; labels: string[]; values: (number | null)[][] };

function frame(answer: ChartAnswer, props: DataProps) {
  const { table, names, roles } = answerTable(answer, props.query.measures || []);
  const measureKeys = table.columnNames().filter(n => n !== 'label');
  const t = withCalcs(table, props.calcs || [], compileFormula);
  const fields = props.fields?.length ? props.fields : measureKeys;
  return toFrame(shape(t, { sortBy: props.sortBy, sortDir: props.sortDir, filter: props.filter, fields }), answer.meta, names, (props.calcs || []) as Calc[], roles);
}

function check(r: Extract<Request, { op: 'check' }>) {
  const compiled = compileFormula(r.formula, r.known);
  return r.labels.slice(0, 4).map((label, i) => {
    const row: Record<string, number | null> = {};
    r.keys.forEach((k, s) => { row[k] = r.values[s]?.[i] ?? null; });
    return { label, value: compiled.run(row) };
  });
}

self.onmessage = (event: MessageEvent<Request>) => {
  const r = event.data;
  try {
    const result = r.op === 'frame' ? frame(r.answer, r.props) : check(r);
    (self as any).postMessage({ id: r.id, ok: true, result });
  } catch (error) {
    (self as any).postMessage({ id: r.id, ok: false, message: (error as Error).message, formula: error instanceof FormulaError });
  }
};
