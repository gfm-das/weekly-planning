// Timings of the V2 pages: window.__gfmPerf always; printed to the console in development or with ?perf=1.
const t0 = performance.timeOrigin;
const marks: Record<string, number> = {};
const show = () => import.meta.env.DEV || /[?&]perf=1/.test(location.search);

/** Time since the page started, in ms, noted under `name` (the first call of a name wins). */
export function mark(name: string): number {
  const at = Math.round(performance.now());
  if (!(name in marks)) {
    marks[name] = at;
    (window as any).__gfmPerf = { ...marks };
    if (show()) console.info(`[gfm-v2 perf] ${name}: ${at} ms`);
  }
  return marks[name];
}

/** Measures an async job and notes how long it took (every call is noted, with a number). */
export async function timed<T>(name: string, job: () => Promise<T>): Promise<T> {
  const start = performance.now();
  try {
    return await job();
  } finally {
    const ms = Math.round(performance.now() - start);
    const key = name in marks ? `${name}#${Object.keys(marks).filter(k => k.startsWith(name)).length}` : name;
    marks[key] = ms;
    (window as any).__gfmPerf = { ...marks };
    if (show()) console.info(`[gfm-v2 perf] ${key}: ${ms} ms`);
  }
}
void t0;
