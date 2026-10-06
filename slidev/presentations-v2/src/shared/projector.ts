// Projector mode: bigger text, stronger lines and colours, a black surround, nothing but the slide.
// It turns on by itself in fullscreen, with the P key or the toolbar button, or with ?projector=1 in the address.
// Text parts read --gfm-text-scale from the page; charts are redrawn through projectorOption.
const KEY = 'gfm-v2-projector';
export const SCALE = 1.3;
let on = false;
const listeners = new Set<() => void>();

export const isProjector = () => on;
export const onProjector = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };

export function setProjector(value: boolean, remember = true) {
  if (value === on) return;
  on = value;
  const root = document.documentElement;
  root.classList.toggle('gfm-projector', on);
  root.style.setProperty('--gfm-text-scale', on ? String(SCALE) : '1');
  if (remember) { try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* private window: fine */ } }
  listeners.forEach(f => f());
}

/** Switches on when the address says ?projector=1, or when this browser was left in projector mode. */
export function startProjector() {
  let saved = false;
  try { saved = localStorage.getItem(KEY) === '1'; } catch { /* ignore */ }
  const asked = new URLSearchParams(location.search).get('projector');
  setProjector(asked === '1' || (asked === null && saved), false);
}

// Light greys that vanish on a projector are made darker.
const DARKEN: Record<string, string> = { '#3d5866': '#17394b', '#556d7a': '#17394b', '#e3eaee': '#9fb0b8', '#b8c6cd': '#6f8793' };

/** A projector's version of an ECharts option: text x1.3, lines thicker, pale greys darker (a new object). */
export function projectorOption(option: any): any {
  const walk = (value: any, key = ''): any => {
    if (Array.isArray(value)) return value.map(v => walk(v, key));
    if (value && typeof value === 'object') {
      const out: any = {};
      for (const [k, v] of Object.entries(value)) out[k] = walk(v, k);
      if (out.type === 'line' && Array.isArray(out.data)) { out.lineStyle = { width: 5, ...(out.lineStyle || {}) }; out.symbolSize = 12; }
      return out;
    }
    if (key === 'fontSize' && typeof value === 'number') return Math.round(value * SCALE);
    if (typeof value === 'string' && DARKEN[value.toLowerCase()]) return DARKEN[value.toLowerCase()];
    return value;
  };
  const out = walk(option);
  out.textStyle = { fontSize: Math.round(14 * SCALE), ...(out.textStyle || {}) };
  return out;
}
