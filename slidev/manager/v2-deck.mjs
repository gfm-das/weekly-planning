// GFM Presentations V2: what a saved deck (deck.json) may hold.
//
// What it is: the one check every V2 deck goes through before it is saved, and the list of chart queries a deck
// holds ("pinning": a leader who is not a manager gets numbers only for a query written in the saved deck).
// A V2 deck is data, not page code: text is shown as text, pictures are files of the deck's own, chart queries are
// checked by the same rules as every database chart (chart-spec.mjs). That is why the V2 pages may run on the manager
// address, where the Slidev decks (page code) may not.
// Who uses it: v2-routes.mjs; slidev/tests/v2-deck.test.mjs tests it with plain Node.
import { canonicalJson, normalizeSpec, SpecError } from './gfm-addon/lib/chart-spec.mjs';

export const V2_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const COMPONENT_TYPES = ['text', 'heading', 'image', 'chart', 'kpi', 'table', 'shape'];
export const TRANSITIONS = ['none', 'fade', 'slide', 'convex', 'concave', 'zoom'];
export const CHART_TYPES = ['bar', 'ranked-bar', 'line', 'area', 'pie', 'gauge', 'funnel', 'scatter'];
export const FORMATS = ['number', 'percent'];
export const ASSET_NAME = /^[a-z0-9][a-z0-9._-]{0,80}\.(png|jpe?g|gif|webp)$/;
export const MAX_SLIDES = 60;
export const MAX_COMPONENTS = 40;
const COLOUR = /^#[0-9a-fA-F]{6}$/;
const ID = /^[A-Za-z0-9_-]{1,60}$/;
const FIELD_NAME = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;

export class DeckError extends Error {}

const isPlain = v => v !== null && typeof v === 'object' && !Array.isArray(v) && [Object.prototype, null].includes(Object.getPrototypeOf(v));

function text(value, max, what) {
  if (value === undefined || value === null) return '';
  if (typeof value !== 'string' || value.length > max) throw new DeckError(`${what} must be text of at most ${max} characters.`);
  return value;
}

function percent(value, fallback, what) {
  const n = value === undefined ? fallback : value;
  if (typeof n !== 'number' || !Number.isFinite(n)) throw new DeckError(`${what} must be a number.`);
  return Math.round(Math.min(100, Math.max(0, n)) * 100) / 100;
}

function choice(value, options, fallback, what) {
  const v = value === undefined ? fallback : value;
  if (!options.includes(v)) throw new DeckError(`${what} must be one of ${options.join(', ')}.`);
  return v;
}

function calcs(list) {
  if (list === undefined) return [];
  if (!Array.isArray(list) || list.length > 8) throw new DeckError('At most 8 calculated fields per chart.');
  const seen = new Set();
  return list.map(c => {
    if (!isPlain(c)) throw new DeckError('A calculated field must be { name, formula, format }.');
    const name = text(c.name, 40, 'The calculated field name');
    if (!FIELD_NAME.test(name)) throw new DeckError('A calculated field name uses letters, digits and _ and starts with a letter.');
    if (seen.has(name)) throw new DeckError(`The calculated field ${name} is there twice.`);
    seen.add(name);
    const formula = text(c.formula, 200, 'The formula');
    if (!formula.trim()) throw new DeckError('A calculated field needs a formula.');
    return { name, label: text(c.label, 60, 'The label') || name, formula, format: choice(c.format, FORMATS, 'number', 'The format') };
  });
}

function scenes(list) {
  if (list === undefined) return [];
  if (!Array.isArray(list) || list.length > 10) throw new DeckError('At most 10 scenes per chart.');
  return list.map(s => {
    if (!isPlain(s) || !Array.isArray(s.fields) || s.fields.length > 12) throw new DeckError('A scene must be { name, fields: [...] }.');
    return { name: text(s.name, 60, 'The scene name'), fields: s.fields.map(f => text(f, 60, 'A scene field')) };
  });
}

function valueFilter(f) {
  if (f === undefined || f === null) return null;
  if (!isPlain(f) || !['>', '>=', '<', '<='].includes(f.op) || typeof f.value !== 'number' || !Number.isFinite(f.value)) throw new DeckError('The value filter must be { field, op, value }.');
  return { field: text(f.field, 60, 'The filter field'), op: f.op, value: f.value };
}

function query(raw) {
  try {
    return normalizeSpec(raw);
  } catch (error) {
    throw new DeckError(error instanceof SpecError ? error.message : 'The chart settings could not be read.');
  }
}

function props(type, raw) {
  const p = raw === undefined ? {} : raw;
  if (!isPlain(p)) throw new DeckError('Component props must be { }.');
  switch (type) {
    case 'text':
      return { text: text(p.text, 5000, 'The text'), size: percent(p.size, 28, 'The size'), color: COLOUR.test(p.color || '') ? p.color : '#193746' };
    case 'heading':
      return { text: text(p.text, 300, 'The heading'), size: percent(p.size, 48, 'The size'), color: COLOUR.test(p.color || '') ? p.color : '#17394b' };
    case 'image': {
      const asset = text(p.asset, 90, 'The picture');
      if (asset && !ASSET_NAME.test(asset)) throw new DeckError('A picture must be one of the deck\'s own uploaded files.');
      return { asset, alt: text(p.alt, 200, 'The picture description') };
    }
    case 'shape':
      return { color: COLOUR.test(p.color || '') ? p.color : '#087f8c', round: p.round === true };
    case 'chart':
    case 'table':
    case 'kpi':
      return {
        title: text(p.title, 200, 'The title'),
        query: query(p.query),
        chartType: choice(p.chartType, CHART_TYPES, 'bar', 'The chart type'),
        transitionId: text(p.transitionId, 60, 'The transition id'),
        calcs: calcs(p.calcs),
        fields: Array.isArray(p.fields) ? p.fields.slice(0, 16).map(f => text(f, 60, 'A field')) : [],
        sortBy: text(p.sortBy, 60, 'The sort field'),
        sortDir: choice(p.sortDir, ['none', 'desc', 'asc'], 'none', 'The sort'),
        filter: valueFilter(p.filter),
        scenes: scenes(p.scenes),
        advanced: p.advanced === undefined || p.advanced === null ? null : (isPlain(p.advanced) ? p.advanced : (() => { throw new DeckError('Advanced chart settings must be { }.'); })()),
      };
    default:
      return {};
  }
}

/** The deck as it may be stored (a new object with every unknown key dropped), or a DeckError with a sentence. */
export function validateDeck(raw) {
  if (!isPlain(raw)) throw new DeckError('The deck must be { }.');
  if (raw.version !== 1) throw new DeckError('This deck has an unknown version.');
  if (!Array.isArray(raw.slides) || raw.slides.length > MAX_SLIDES) throw new DeckError(`A deck has at most ${MAX_SLIDES} slides.`);
  const slideIds = new Set();
  const slides = raw.slides.map(s => {
    if (!isPlain(s)) throw new DeckError('A slide must be { }.');
    const id = text(s.id, 60, 'A slide id');
    if (!ID.test(id) || slideIds.has(id)) throw new DeckError('Every slide needs its own id.');
    slideIds.add(id);
    if (s.components !== undefined && (!Array.isArray(s.components) || s.components.length > MAX_COMPONENTS)) throw new DeckError(`A slide has at most ${MAX_COMPONENTS} parts.`);
    const ids = new Set();
    const components = (s.components || []).map(c => {
      if (!isPlain(c)) throw new DeckError('A part of a slide must be { }.');
      const cid = text(c.id, 60, 'A part id');
      if (!ID.test(cid) || ids.has(cid)) throw new DeckError('Every part of a slide needs its own id.');
      ids.add(cid);
      const type = choice(c.type === 'gfm-chart' ? 'chart' : c.type, COMPONENT_TYPES, undefined, 'A part type');
      return {
        id: cid, type, x: percent(c.x, 10, 'x'), y: percent(c.y, 10, 'y'), width: percent(c.width, 30, 'width'), height: percent(c.height, 20, 'height'),
        props: props(type, c.props),
      };
    });
    return { id, transition: choice(s.transition, TRANSITIONS, 'slide', 'The transition'), autoAnimate: s.autoAnimate === true, notes: text(s.notes, 2000, 'The notes'), components };
  });
  return { version: 1, name: text(raw.name, 120, 'The name') || 'Untitled', theme: 'gfm', slides };
}

/** The canonical chart queries of a deck (what "pinned" means for a viewer). */
export function deckPinKeys(deck) {
  const keys = new Set();
  for (const slide of deck?.slides || []) {
    for (const c of slide.components || []) {
      if (!['chart', 'table', 'kpi'].includes(c.type)) continue;
      try { keys.add(canonicalJson(normalizeSpec(c.props?.query))); } catch { /* an invalid query is never pinned */ }
    }
  }
  return keys;
}
