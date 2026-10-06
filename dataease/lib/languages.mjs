// The mission portal's 14 languages in Dashboards (DataEase), and where each language's copy of a dashboard lives.
// Used by the gate (gate/gate.mjs: which dashboard /gfm-start opens), by translate-dashboards.mjs (makes the copies)
// and by the tests. Plain Node, no packages, no network.
//
// THE ID RULE (the "mapping" between an English dashboard and its copies)
// Every dashboard, folder and chart the scripts make has a fixed id of 19 digits:
//
//     115  LL  DD  GG  PPPP  000000
//      |   |   |   |   |     always six zeros
//      |   |   |   |   part: 0000 = the dashboard or folder itself, 0001-9999 = a chart or filter on it
//      |   |   |   generation: 00, or 01-89 when DataEase kept a deleted one (its id can never be used again)
//      |   |   dashboard: 00 = the folder, 01 Key indicators, 02 Zones & districts, 03 Covenant path
//      |   language: 00 = English (the ones people edit), 01 German ... 13 Arabic (LANGUAGES below)
//      the block of ids seed-dashboards.mjs uses (lib/build.mjs explains why it is safe)
//
// Examples: 1150001000000000000 is "Key indicators" in English (as the seeding has always made it);
// 1150101000000000000 is its German copy; 1150100000000000000 is the folder "Deutsch" inside "Mission".
// So the German copy of an English dashboard is found by changing LL from 00 to 01: no list to keep up to date.
import { flattenTree } from './dataease-client.mjs';

export const LANGUAGES = Object.freeze([
  { code: 'de', number: 1, name: 'Deutsch' },
  { code: 'es', number: 2, name: 'Español' },
  { code: 'fr', number: 3, name: 'Français' },
  { code: 'pt', number: 4, name: 'Português' },
  { code: 'uk', number: 5, name: 'Українська' },
  { code: 'ru', number: 6, name: 'Русский' },
  { code: 'it', number: 7, name: 'Italiano' },
  { code: 'tr', number: 8, name: 'Türkçe' },
  { code: 'fa', number: 9, name: 'فارسی' },
  { code: 'ro', number: 10, name: 'Română' },
  { code: 'sv', number: 11, name: 'Svenska' },
  { code: 'da', number: 12, name: 'Dansk' },
  { code: 'ar', number: 13, name: 'العربية' },
].map(Object.freeze));

/** Every language code Dashboards knows, English first (the same list as i18n/gfm-i18n.js). */
export const CODES = Object.freeze(['en', ...LANGUAGES.map(l => l.code)]);

/** 'de-DE', 'DE', ' de_at ' -> 'de'; anything else -> null. */
export function normalizeLanguage(code) {
  if (typeof code !== 'string') return null;
  const c = code.trim().toLowerCase().split(/[-_]/)[0];
  return CODES.includes(c) ? c : null;
}

/** The language entry for a code ('de'), or null (English has none: it is the original). */
export function language(code) {
  return LANGUAGES.find(l => l.code === normalizeLanguage(code)) || null;
}

const ID = /^115(\d\d)(\d\d)(\d\d)(\d{4})000000$/;

/** The parts of one of our ids, or null for an id DataEase made itself (a dashboard people built by hand). */
export function parseId(id) {
  const m = ID.exec(String(id));
  if (!m) return null;
  return { language: Number(m[1]), dashboard: Number(m[2]), generation: Number(m[3]), part: Number(m[4]) };
}

const pad = (n, width, max) => {
  if (!Number.isInteger(n) || n < 0 || n > max) throw new Error(`Id part ${n} is outside 0-${max}.`);
  return String(n).padStart(width, '0');
};

/** Builds an id from its parts (see THE ID RULE above). */
export function makeId({ language = 0, dashboard = 0, generation = 0, part = 0 }) {
  return '115' + pad(language, 2, 99) + pad(dashboard, 2, 99) + pad(generation, 2, 89) + pad(part, 4, 9999) + '000000';
}

/** Is this the id of a translated copy (a dashboard, folder or chart in another language)? */
export function isCopyId(id) {
  const p = parseId(id);
  return !!p && p.language > 0;
}

/** Is this node of DataEase's tree a copy (any generation) of dashboard number `dashboard` in language number `language`? */
export function isCopyOf(node, language, dashboard) {
  const p = node.leaf ? parseId(node.id) : null;
  return !!p && p.language === language && p.dashboard === dashboard && p.part === 0;
}

/**
 * The dashboard to open for this language: the live copy of englishId in DataEase's dashboard tree, or null
 * (English asked for, the English dashboard was made by hand in DataEase, or the copy has not been made yet).
 * Any generation of the copy counts.
 */
export function copyInTree(tree, englishId, code) {
  const lang = language(code);
  const english = parseId(englishId);
  if (!lang || !english || english.language !== 0 || english.dashboard === 0) return null;
  const found = flattenTree(tree).find(n => isCopyOf(n, lang.number, english.dashboard));
  return found ? String(found.id) : null;
}
