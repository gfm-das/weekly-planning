// The page's side of the data worker (data-worker.ts): one worker, asked one job at a time by number.
import type { ChartAnswer, DataProps, Frame } from '../shared/types';

let worker: Worker | null = null;
let next = 1;
const waiting = new Map<number, { resolve(v: any): void; reject(e: Error): void }>();

function start(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL('./data-worker.ts', import.meta.url), { type: 'module', name: 'gfm-data' });
  worker.onmessage = (event: MessageEvent<{ id: number; ok: boolean; result?: unknown; message?: string }>) => {
    const job = waiting.get(event.data.id);
    if (!job) return;
    waiting.delete(event.data.id);
    if (event.data.ok) job.resolve(event.data.result);
    else job.reject(new Error(event.data.message || 'The numbers could not be worked out.'));
  };
  worker.onerror = event => {
    const error = new Error(`The data worker failed: ${event.message || 'it could not start'}`);
    for (const job of waiting.values()) job.reject(error);
    waiting.clear();
    worker = null;
  };
  return worker;
}

function ask<T>(message: Record<string, unknown>): Promise<T> {
  const id = next++;
  return new Promise<T>((resolve, reject) => {
    waiting.set(id, { resolve, reject });
    start().postMessage({ id, ...message });
  });
}

/** The answer's numbers as a Frame (calculated fields, filter, sort and field choice applied by Arquero and math.js). */
// (props are copied as plain JSON first: the editor hands over objects that Vue or GrapesJS wrap, which cannot be posted.)
export const computeFrame = (answer: ChartAnswer, props: DataProps) => ask<Frame>({ op: 'frame', answer, props: JSON.parse(JSON.stringify(props)) });

/** Checks a formula and evaluates it over the first rows of the answer (the formula dialog's preview). */
export const checkFormula = (formula: string, known: string[], answer: ChartAnswer, keys: string[]) =>
  ask<{ label: string; value: number | null }[]>({ op: 'check', formula, known: [...known], keys: [...keys], labels: answer.table.labels, values: answer.table.series.map(s => s.values) });
