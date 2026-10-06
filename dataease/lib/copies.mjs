// Makes a translated copy of one English dashboard, as DataEase stores it. No network here (translate-dashboards.mjs
// reads and saves through DataEase's API; dataease/tests/copies.test.mjs checks this file on the saved exports).
//
// Why copies at all: DataEase draws chart axes, legends and table headers on a canvas, where i18n/gfm-i18n.js cannot
// reach them. A copy has those words (the field display names) in its language, and its own title, chart titles,
// notes, filter labels and text boxes too. The copies read the same datasets as the English dashboards, so the
// numbers are always the same.
//
// What is translated (with the same dictionary as the page script, i18n/<lang>.json):
//  - the dashboard name;                         - each chart's title and note ("remark", the (?) next to the title);
//  - the filter labels (the query component);    - the display names of the fields a chart shows (legend, axis
//  - the text of the text boxes (rich text),       titles, table headers, tooltips); the datasets are not changed;
//    except the [Field] placeholders;             - axis names and assist-line names, when a chart has them.
// Text that has no translation stays English and is reported (translate-dashboards.mjs prints it).
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeId, parseId, language as languageOf } from './languages.mjs';
import { CHART_FIELD_LISTS } from './build.mjs';

const require = createRequire(import.meta.url);
const I18N_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'i18n');
const overlay = require(path.join(I18N_DIR, 'gfm-i18n.js'));

/**
 * A translate(text) function for one language: the translation, the text itself when the word is the same in that
 * language (German "Trend", "Zone"), or null when there is no translation.
 */
export function translator(code, dir = I18N_DIR) {
  const read = c => JSON.parse(fs.readFileSync(path.join(dir, c + '.json'), 'utf8'));
  const [en, tr] = [read('en'), read(code)];
  const dict = overlay.buildDictionary(en, tr);
  const same = new Set();
  for (const section of ['messages', 'gfm', 'pmg']) {
    for (const [key, value] of Object.entries(en[section] || {})) if (tr[section]?.[key] === value) same.add(value.trim());
  }
  return text => {
    if (typeof text !== 'string') return null;
    const done = overlay.translateString(dict, text);
    if (done !== null) return done;
    const t = text.trim().replace(/[:：]$/, '').replace(/^[·•]\s*/, '');
    return same.has(t) ? text : null;
  };
}

const HAS_LETTERS = /\p{L}/u;
const NAME_LIMIT = 100; // DataEase: "Name cannot exceed 100 characters"
const parse = value => (typeof value === 'string' ? JSON.parse(value) : JSON.parse(JSON.stringify(value)));

// &amp; &lt; &gt; &quot; &#39; &nbsp; and numeric entities, as TinyMCE writes them.
function decode(text) {
  return text.replace(/&(amp|lt|gt|quot|#39|nbsp|#(\d+)|#x([0-9a-f]+));/gi, (m, name, dec, hex) => {
    if (dec) return String.fromCodePoint(Number(dec));
    if (hex) return String.fromCodePoint(parseInt(hex, 16));
    return { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", nbsp: ' ' }[name.toLowerCase()];
  });
}
const encode = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/ /g, '&nbsp;');

/**
 * The text between the tags of a text box, translated; tags, attributes and [Field] placeholders stay as they are.
 * note(text) is called for text that has no translation.
 */
export function translateHtml(html, translate, note = () => {}) {
  return String(html || '').replace(/>([^<]+)</g, (whole, raw) => {
    const text = decode(raw);
    const trimmed = text.trim();
    if (!trimmed || !HAS_LETTERS.test(trimmed) || /^\[[^\]]*\]$/.test(trimmed)) return whole;
    const done = translate(text);
    if (done === null || done === undefined) { note(trimmed); return whole; }
    return '>' + encode(done) + '<';
  });
}

// Every component id (nested ones in groups and tabs too), in the order they appear.
function componentIds(components, out = []) {
  for (const c of components || []) {
    if (c && c.id !== undefined && c.id !== null) out.push(String(c.id));
    if (Array.isArray(c?.propValue)) {
      for (const inner of c.propValue) {
        if (inner && inner.component) componentIds([inner], out);          // a group
        if (Array.isArray(inner?.componentData)) componentIds(inner.componentData, out); // a tab
      }
    }
  }
  return out;
}

// Replaces old ids by new ones everywhere: values and keys, and "<id>-<n>" (the filter conditions' ids).
function remap(value, ids) {
  const one = s => {
    if (ids.has(s)) return ids.get(s);
    const m = /^(\d{1,20})-(.+)$/.exec(s);
    return m && ids.has(m[1]) ? ids.get(m[1]) + '-' + m[2] : s;
  };
  if (typeof value === 'string') return one(value);
  if (Array.isArray(value)) return value.map(v => remap(v, ids));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [one(k), remap(v, ids)]));
  return value;
}

// The two ways a word is translated in a copy, both noting what has no translation yet:
//   text(t): any text; name(t): a name, which DataEase refuses above 100 characters (then it stays English).
function wordTranslators(translate, missing) {
  const text = t => {
    if (typeof t !== 'string' || !t.trim() || !HAS_LETTERS.test(t)) return t;
    const done = translate(t);
    if (done === null || done === undefined) { missing.add(t.trim()); return t; }
    return done;
  };
  const name = t => {
    const done = text(t);
    if (typeof done === 'string' && done.length > NAME_LIMIT) { missing.add(`${t.trim()} (translation longer than ${NAME_LIMIT} characters)`); return t; }
    return done;
  };
  return { text, name };
}

// New ids for the copy: the dashboard, then each component and chart in order (part 1, 2, 3...).
function copyIds(dv, components, views, place) {
  const ids = new Map([[String(dv.id), makeId(place)]]);
  for (const old of [...componentIds(components), ...Object.keys(views)]) {
    if (!ids.has(old)) ids.set(old, makeId({ ...place, part: ids.size }));
  }
  return ids;
}

// The words on the canvas: component names and labels, filter labels and hints, text boxes, tab titles (also in
// groups and tabs). A name that is an id stays as it is.
function translateComponents(list, words, ids, translate, missing) {
  for (const c of list || []) {
    if (typeof c.name === 'string' && !ids.has(c.name)) c.name = words.name(c.name);
    if (typeof c.label === 'string' && !ids.has(c.label)) c.label = words.name(c.label);
    if (c.component === 'VQuery' && Array.isArray(c.propValue)) {
      for (const condition of c.propValue) {
        condition.name = words.name(condition.name);
        if (condition.field && typeof condition.field.name === 'string') condition.field.name = words.text(condition.field.name);
        if (condition.placeholder) condition.placeholder = words.text(condition.placeholder);
      }
    } else if (c.innerType === 'rich-text' && c.propValue && typeof c.propValue.textValue === 'string') {
      c.propValue.textValue = translateHtml(c.propValue.textValue, translate, text => missing.add(text));
    }
    if (!Array.isArray(c.propValue)) continue;
    for (const inner of c.propValue) {
      if (inner && inner.component) translateComponents([inner], words, ids, translate, missing);   // a group
      if (Array.isArray(inner?.componentData)) {                                                    // a tab
        if (inner.title) inner.title = words.text(inner.title);
        translateComponents(inner.componentData, words, ids, translate, missing);
      }
    }
  }
}

// The words of each chart: title, note, axis names, assist lines, and the names its fields show (legend, axes,
// table headers, tooltips). The numbers are cleared (DataEase fetches them again).
function translateViews(views, words, translate) {
  for (const view of Object.values(views)) {
    view.data = null;
    if (view.title) view.title = words.name(view.title);
    const text = view.customStyle?.text;
    if (text?.remark) text.remark = words.text(text.remark);
    for (const axis of ['xAxis', 'yAxis', 'yAxisExt']) {
      const style = view.customStyle?.[axis];
      if (style && typeof style.name === 'string' && style.name.trim()) style.name = words.text(style.name);
    }
    for (const line of view.senior?.assistLineCfg?.assistLine || []) if (line.name) line.name = words.text(line.name);
    // A text box refers to its fields by [name]: its fields keep their names.
    if (view.type === 'rich-text') continue;
    for (const list of CHART_FIELD_LISTS) {
      for (const field of view[list] || []) {
        if (field.chartShowName) field.chartShowName = words.text(field.chartShowName);
        else if (typeof field.name === 'string') {
          const shown = translate(field.name);
          if (shown) field.chartShowName = shown;
        }
      }
    }
  }
}

/**
 * The copy of one English dashboard in one language.
 *   dv:         the English dashboard as DataEase's findById answers it (or an export file of dashboards/export/)
 *   code:       'de', 'ar'...
 *   translate:  translator(code)
 *   generation: 0, or more when DataEase kept a deleted copy (translate-dashboards.mjs finds the free one)
 * Returns { id, name, canvasStyleData, componentData, canvasViewInfo, mobileLayout, missing } with the objects
 * parsed (not JSON text), or throws when the English dashboard is not one of ours (lib/languages.mjs).
 */
export function copyDashboard(dv, code, translate, generation = 0) {
  const lang = languageOf(code);
  if (!lang) throw new Error(`"${code}" is not one of the 13 languages that get copies.`);
  const english = parseId(dv.id);
  if (!english || english.language !== 0 || english.dashboard === 0 || english.part !== 0) {
    throw new Error(`Dashboard "${dv.name}" (${dv.id}) was not made by seed-dashboards.mjs, so it has no place for copies.`);
  }
  const missing = new Set();
  const words = wordTranslators(translate, missing);
  const components = parse(dv.componentData);
  const views = parse(dv.canvasViewInfo || {});
  const ids = copyIds(dv, components, views, { language: lang.number, dashboard: english.dashboard, generation });
  translateComponents(components, words, ids, translate, missing);
  translateViews(views, words, translate);
  return {
    id: ids.get(String(dv.id)),
    name: words.name(dv.name),
    canvasStyleData: parse(dv.canvasStyleData),
    componentData: remap(components, ids),
    canvasViewInfo: remap(views, ids),
    mobileLayout: dv.mobileLayout !== false,
    missing: [...missing].sort(),
  };
}
