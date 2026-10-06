// Checking a pasted presentation before it touches the deck (GFM Studio, Paste Presentation).
//
// analyzeDeck(markdown, { spec, known, assets, parsed }) reads Slidev Markdown the way a careful editor would and answers:
//   { slides: [{ no, layout, heading, components, status: 'green'|'yellow'|'red', notes }],
//     issues: [{ severity: 'blocked'|'error'|'warning'|'info', slide, message, fix? }],
//     counts: { green, yellow, red }, valid, fixable, headmatter }
//
//   green   fully editable in Studio: known GFM components and layouts, standard Markdown
//   yellow  partly editable: custom HTML, custom CSS, settings Studio does not know
//   red     source-first: components Studio does not know, scripts, anything it cannot show visually
//   issues:  error = will not work as written (unknown component or layout, a tag never closed, a chart's settings wrong)
//            warning = will work but check it (a picture that is not in the deck, an unknown setting)
//            blocked = code a presentation may not carry (loading outside code, event handlers ...): never imported
// `spec` is the manifest (manager/gfm-addon/ai/gfm-spec.json); `known` more component names (Studio's own catalog);
// `assets` the files the deck already holds (null = not known, so pictures are not checked); `parsed` the answer of Slidev's
// own parser (`/@studio/check`: { ok, errors }), whose mistakes are added.
// Pure JavaScript: runs in the editor and in Node tests. Nothing here changes any text except autoFix, which only does the
// safe things listed in FIXES and says what it did.
import { joinDeck, splitDeck } from '../node/slide-source.ts';
import { normalizeSpec, pinnedKeys, SpecError } from '../../../gfm-addon/lib/chart-spec.mjs';
import { seriesProblem, readOption } from '../../../gfm-addon/lib/chart-engine.mjs';
import { parseFormula, FormulaError, FORMATS } from '../../../gfm-addon/lib/formula.mjs';
import { PRESETS } from '../../../gfm-addon/lib/chart-presets.mjs';
import { parseStory } from '../../../gfm-addon/lib/chart-story.mjs';

/** Slidev's reserved frontmatter words (a layout never receives them) and the usual per-slide settings. */
const SLIDE_KEYS = new Set(['layout', 'title', 'level', 'src', 'lang', 'hide', 'hideInToc', 'transition', 'clicks', 'clicksStart', 'disabled', 'preload', 'routeAlias', 'zoom', 'dragPos', 'class', 'background', 'image', 'backgroundSize', 'color', 'style', 'mdc', 'clickAnimation', 'defaults', 'name']);
/** Words that belong to the deck as a whole (the first block). */
const DECK_KEYS = new Set(['theme', 'titleTemplate', 'info', 'author', 'keywords', 'fonts', 'themeConfig', 'drawings', 'colorSchema', 'aspectRatio', 'canvasWidth', 'highlighter', 'lineNumbers', 'monaco', 'download', 'exportFilename', 'export', 'presenter', 'browserExporter', 'remoteAssets', 'selectable', 'record', 'contextMenu', 'wakeLock', 'seoMeta', 'htmlAttrs', 'favicon', 'addons', 'css', 'twoslash', 'duration', 'timer', 'routerMode', 'studio']);
const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
const HTML_OK = new Set(['a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'center', 'cite', 'code', 'dd', 'del', 'details', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'kbd', 'li', 'mark', 'ol', 'p', 'pre', 'q', 's', 'section', 'small', 'span', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul', 'video', 'audio', 'source', 'svg', 'path', 'circle', 'rect', 'g', 'line', 'polyline', 'polygon', 'text', 'tspan', 'defs', 'linearGradient', 'stop', 'style', 'template', 'br', 'label', 'button', 'input', 'form', 'select', 'option', 'textarea', 'nav', 'header', 'footer', 'main', 'article', 'aside', 'picture', 'iframe', 'object', 'embed', 'script', 'link', 'meta', 'base', 'canvas']);
const GLOBAL_ATTRS = /^(class|style|id|key|ref|is|slot|title|role|lang|dir|hidden|tabindex|draggable|v-[\w:.-]+|@[\w:.-]+|#[\w-]+|data-[\w-]+|aria-[\w-]+|width|height)$/;
const BLOCKED_ATTR = /^(on[a-z]+)$/i;
const RISKY_CODE = /\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|eval|importScripts)\s*\(|new\s+Function|document\s*\.\s*(cookie|write)|\b(localStorage|sessionStorage|indexedDB)\b|window\s*\.\s*(parent|top|opener)|postMessage|import\s*\(|import\s+[^;\n]*\s+from\s+['"](?!vue['"]|@slidev\/)/;

// ---- reading the text ----------------------------------------------------------------------------------------------

const blank = s => s.replace(/[^\n]/g, ' ');

/** The slide with code, inline code and comments blanked out (same length), so tags are only looked for in real markup. */
function mask(body) {
  return body
    .replace(/(^|\n)([ \t]*)(`{3,}|~{3,})[^\n]*\n[\s\S]*?(\n[ \t]*\3[^\n]*|$)/g, m => blank(m))
    .replace(/<!--[\s\S]*?-->/g, blank)
    .replace(/`[^`\n]*`/g, blank);
}

function lineOf(text, index) { return text.slice(0, index).split('\n').length; }

/** The attributes of an opening tag: [{ name (as written), key (without : or v-bind:), bound, value (text or null) }]. */
function parseAttrs(text) {
  const attrs = [];
  const re = /([:@#]?[\w.:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  for (let m; (m = re.exec(text));) {
    const name = m[1];
    const value = m[2] ?? m[3] ?? m[4] ?? null;
    attrs.push({ name, key: name.replace(/^(:|v-bind:)/, ''), bound: name.startsWith(':') || name.startsWith('v-bind:'), value: value === null ? null : decodeEntities(value) });
  }
  return attrs;
}

const decodeEntities = s => s.replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const kebab = s => s.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();

/** Every tag of a slide, with its position and attributes. */
function scanTags(masked) {
  const tags = [];
  const re = /<(\/?)([A-Za-z][\w.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  for (let m; (m = re.exec(masked));) tags.push({ closing: !!m[1], name: m[2], attrsText: m[3], selfClose: !!m[4], index: m.index, attrs: m[1] ? [] : parseAttrs(m[3]) });
  return tags;
}

// A suggestion for a name that is nearly one that exists.
function distance(a, b) {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0]; row[0] = i;
    for (let j = 1; j <= b.length; j++) { const keep = row[j]; row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1)); prev = keep; }
  }
  return row[b.length];
}
function didYouMean(name, options) {
  const lower = name.toLowerCase();
  let best = null;
  for (const o of options) { const d = distance(lower, o.toLowerCase()); if (d <= Math.max(2, Math.floor(o.length / 4)) && (!best || d < best.d)) best = { o, d }; }
  return best ? ` Did you mean ${best.o}?` : '';
}

/** The top-level `key: value` lines of a frontmatter block (nested lines are skipped). */
function frontmatterOf(raw) {
  const lines = raw.split('\n');
  if (lines[0]?.trimEnd() !== '---') return { yaml: '', body: raw, closed: true, keys: {}, lines: [] };
  const end = lines.findIndex((l, i) => i > 0 && l.trimEnd() === '---');
  if (end < 0) return { yaml: lines.slice(1).join('\n'), body: '', closed: false, keys: {}, lines: lines.slice(1) };
  const yamlLines = lines.slice(1, end);
  const keys = {};
  const bad = [];
  yamlLines.forEach((line, i) => {
    if (!line.trim() || /^\s*#/.test(line) || /^\s/.test(line) || /^-\s/.test(line)) return;
    const m = /^([A-Za-z_][\w-]*)\s*:\s*(.*)$/.exec(line);
    if (m) keys[m[1]] = m[2].replace(/^["']|["']$/g, '').trim();
    else bad.push({ line: i + 2, text: line });
  });
  return { yaml: yamlLines.join('\n'), body: lines.slice(end + 1).join('\n'), closed: true, keys, bad, lines: yamlLines };
}

// ---- the checks ----------------------------------------------------------------------------------------------------

function attrIssue(component, attr, spec, issues, no) {
  // Vue and Slidev attributes (v-click, :style, @click ...) and the usual global ones are always fine.
  if (GLOBAL_ATTRS.test(attr.key) || attr.key === 'chart-id') return;
  const props = new Map(component.props.map(p => [p.name, p]));
  const name = camel(attr.key);
  const prop = props.get(name);
  if (!prop) {
    issues.push({ severity: 'warning', slide: no, message: `${component.name} has no setting called ${attr.key}.${didYouMean(name, [...props.keys()])}`, unknownSetting: true });
    return;
  }
  if (prop.options && !attr.bound && attr.value !== null && !prop.options.includes(attr.value))
    issues.push({ severity: 'warning', slide: no, message: `${component.name}: ${attr.key} is “${attr.value}”, but it takes one of ${prop.options.join(', ')}.` });
}

function jsonAttr(attr) {
  if (attr.value === null) return { problem: `${attr.key} has no value.` };
  try { return { value: JSON.parse(attr.value) }; }
  catch {
    // :rows="['a', 'b']" is a JavaScript list, not JSON: single quotes are fine for rows only.
    if (attr.key === 'rows') {
      try { return { value: JSON.parse(attr.value.replace(/'/g, '"')) }; } catch { /* below */ }
    }
    return { problem: `${attr.key} is not valid JSON (use double quotes inside, and put the whole value in single quotes: :${attr.key}='…').` };
  }
}

function checkChart(tag, no, issues, rowsHint) {
  const byKey = Object.fromEntries(tag.attrs.map(a => [camel(a.key), a]));
  const say = (severity, message) => issues.push({ severity, slide: no, message: `MissionChart: ${message}` });
  if (byKey.preset?.value && !Object.hasOwn(PRESETS, byKey.preset.value)) say('error', `“${byKey.preset.value}” is not a chart kind.${didYouMean(byKey.preset.value, Object.keys(PRESETS))}`);
  for (const key of ['option', 'query', 'calc', 'story', 'shape']) {
    const a = byKey[key];
    if (!a) continue;
    const { value, problem } = jsonAttr(a);
    if (problem) { say('error', problem); continue; }
    if (key === 'option') {
      const read = readOption(value);
      const p = read.problem || seriesProblem(value);
      if (p) say('error', `the chart option has a mistake: ${p}`);
    }
    else if (key === 'query') {
      try { normalizeSpec(value); } catch (error) { if (error instanceof SpecError) say('error', `the mission numbers query has a mistake: ${error.message}`); else throw error; }
    }
    else if (key === 'calc') {
      if (!Array.isArray(value)) say('error', 'calc must be a list of calculated fields.');
      else value.forEach((c, i) => {
        try {
          parseFormula(String(c?.formula ?? ''));
          if (!String(c?.name ?? '').trim()) say('error', `calculated field ${i + 1} has no name.`);
          if (c?.format !== undefined && !FORMATS.includes(c.format)) say('error', `calculated field “${c?.name ?? i + 1}”: format must be one of ${FORMATS.join(', ')}.`);
        }
        catch (error) { if (error instanceof FormulaError) say('error', `calculated field “${c?.name ?? i + 1}”: ${error.message}`); else throw error; }
      });
    }
    else if (key === 'story') {
      const { problem: sp } = parseStory(value);
      if (sp) say('error', `the story has a mistake: ${sp}`);
    }
  }
  if (!byKey.rows && !byKey.query && !byKey.csv && !byKey.data) say('warning', 'it has no numbers (rows) yet, so it will show nothing.');
  if (byKey.query) rowsHint.query = true;
}

/**
 * Reads a whole presentation. See the top of the file for what comes back.
 */
export function analyzeDeck(markdown, { spec, known = [], assets = null, parsed = null } = {}) {
  const text = String(markdown ?? '').replace(/\r\n?/g, '\n').replace(/^﻿/, '');
  const issues = [];
  const slidesOut = [];
  const fixable = new Set();
  const layoutByName = new Map([...spec.layouts.map(l => [l.name, l]), ...spec.slidevLayouts.map(n => [n, { name: n, props: null, slots: ['default'] }])]);
  const componentByName = new Map(spec.components.map(c => [c.name, c]));
  const slidevKnown = new Set([...spec.slidevComponents, ...spec.slidevComponents.map(kebab), ...known, ...known.map(kebab)]);
  const allComponentNames = [...componentByName.keys(), ...spec.slidevComponents, ...known];
  const wanted = new Set(['v-click', 'v-clicks', 'v-after', 'v-drag', 'v-switch', 'v-drag-arrow', 'v-click-gap', 'VClickGap', 'Transform', 'transform']);

  if (!text.trim()) return { slides: [], issues: [{ severity: 'error', slide: 0, message: 'There is nothing to import: paste the presentation first.' }], counts: { green: 0, yellow: 0, red: 0 }, valid: false, fixable: [], headmatter: {} };

  // Whole-text mistakes that an AI makes often.
  if (/^\s*```[a-z]*\n[\s\S]*\n```\s*$/i.test(text)) {
    issues.push({ severity: 'warning', slide: 0, message: 'The whole presentation is inside a code box (``` … ```). That is how chat programs show code; it is not part of the presentation.', fix: 'unwrap-fence' });
    fixable.add('unwrap-fence');
  }
  const deck = splitDeck(/^\s*```[a-z]*\n([\s\S]*)\n```\s*$/i.exec(text)?.[1] ?? text);
  if (!deck.slides.length) return { slides: [], issues: [{ severity: 'error', slide: 0, message: 'No slides were found.' }], counts: { green: 0, yellow: 0, red: 0 }, valid: false, fixable: [], headmatter: {} };

  const first = frontmatterOf(deck.slides[0].raw);
  // Chat programs often start with a sentence of their own ("Here is your presentation:").
  const firstLine = (deck.lines.find(l => l.trim()) ?? '').trim();
  if (firstLine && !firstLine.startsWith('---') && /^(here|sure|certainly|okay|of course|below|this is|i['’]ve|i have)\b/i.test(firstLine))
    issues.push({ severity: 'warning', slide: 0, message: `The text starts with “${firstLine.slice(0, 60)}”, which looks like the AI talking to you, not a slide. Delete it before importing.` });
  const headmatter = first.keys;

  // The deck's own settings.
  if (headmatter.theme && !['default', 'none', '@slidev/theme-default'].includes(headmatter.theme)) {
    issues.push({ severity: 'error', slide: 1, message: `The theme “${headmatter.theme}” is not installed (only “default” is).`, fix: 'theme-default' });
    fixable.add('theme-default');
  }
  if (/[“”‘’]/.test(deck.slides.map(s => frontmatterOf(s.raw).yaml).join('\n'))) {
    issues.push({ severity: 'warning', slide: 0, message: 'The settings at the top of a slide use curly quotes (“ ” ‘ ’). Slidev needs straight quotes (" \').', fix: 'smart-quotes' });
    fixable.add('smart-quotes');
  }

  if (parsed && Array.isArray(parsed.errors)) for (const e of parsed.errors) issues.push({ severity: 'error', slide: e.slide, message: `Slidev cannot read this: ${e.message}` });

  const refs = { query: false };
  deck.slides.forEach((slide, index) => {
    const no = index + 1;
    const fm = frontmatterOf(slide.raw);
    const notes = [];
    const here = { red: false, yellow: false };
    const body = fm.body;
    const masked = mask(body);

    if (!fm.closed) issues.push({ severity: 'error', slide: no, message: 'The settings at the top of this slide are not closed with a line of three dashes (---).' }), here.red = true;
    for (const b of fm.bad ?? []) issues.push({ severity: 'error', slide: no, message: `The settings at the top of this slide have a line that is not “name: value”: ${b.text.trim().slice(0, 60)}` }), here.red = true;

    // Layout.
    const layoutName = fm.keys.layout ?? (index === 0 ? 'cover' : 'default');
    const layout = layoutByName.get(layoutName);
    if (!layout) {
      issues.push({ severity: 'error', slide: no, message: `Unknown layout: ${layoutName}.${didYouMean(layoutName, [...layoutByName.keys()])}` });
      here.red = true;
    }
    else if (layout.props) {
      // A GFM layout takes only its own settings, plus Slidev's own words.
      const allowed = new Set([...layout.props.map(p => p.name), ...SLIDE_KEYS, ...(index === 0 ? DECK_KEYS : [])]);
      for (const key of Object.keys(fm.keys)) if (!allowed.has(key)) { issues.push({ severity: 'warning', slide: no, message: `The layout ${layoutName} has no setting called ${key}.${didYouMean(key, layout.props.map(p => p.name))}` }); here.yellow = true; }
      for (const p of layout.props) if (p.options && fm.keys[p.name] && !p.options.includes(fm.keys[p.name])) issues.push({ severity: 'warning', slide: no, message: `${layoutName}: ${p.name} is “${fm.keys[p.name]}”, but it takes one of ${p.options.join(', ')}.` });
      // The parts of a slide (::right::) the layout does not have are shown as text.
      for (const part of body.matchAll(/^::([A-Za-z]\w*)::\s*$/gm)) if (!layout.slots.includes(part[1])) { issues.push({ severity: 'warning', slide: no, message: `The layout ${layoutName} has no part called ::${part[1]}::.${didYouMean(part[1], layout.slots)}` }); here.yellow = true; }
    }
    else if (index > 0) {
      // A Slidev layout: only Slidev's own words are expected; others are the layout's own settings (image, class ...).
    }

    // Tags.
    const tags = scanTags(masked);
    // A tag that was started but never finished (no > or />): the whole rest of the slide would be read as its settings.
    const starts = new Set(tags.map(t => t.index));
    for (const m of masked.matchAll(/<([A-Za-z][\w.-]*)(?=[\s/]|$)/g)) {
      if (starts.has(m.index) || !(/^[A-Z]/.test(m[1]) || HTML_OK.has(m[1].toLowerCase()))) continue;
      issues.push({ severity: 'error', slide: no, message: `${m[1]} is missing a closing tag: it starts on line ${lineOf(masked, m.index)} of the slide but never ends with > or />.` });
      here.red = true;
      break;
    }
    const stack = [];
    const used = new Set();
    for (const tag of tags) {
      const name = tag.name;
      const isComponent = /^[A-Z]/.test(name) || (name.includes('-') && !HTML_OK.has(name.toLowerCase()) && !name.startsWith('svg'));
      if (tag.closing) {
        const at = stack.map(t => t.name).lastIndexOf(name);
        if (at < 0) { issues.push({ severity: 'error', slide: no, message: `A closing </${name}> has no matching opening tag (line ${lineOf(masked, tag.index)} of the slide).` }); here.red = true; }
        else {
          for (const open of stack.splice(at + 1)) if (!VOID.has(open.name.toLowerCase())) { issues.push({ severity: 'error', slide: no, message: `${open.name} is missing a closing tag (line ${lineOf(masked, open.index)} of the slide).` }); here.red = true; }
          stack.pop();
        }
        continue;
      }
      if (!tag.selfClose && !VOID.has(name.toLowerCase())) stack.push({ name, index: tag.index });

      // What the tag is.
      const lowerName = name.toLowerCase();
      if (['script'].includes(lowerName)) {
        const closing = masked.indexOf('</script>', tag.index);
        const code = closing > 0 ? body.slice(tag.index + tag.attrsText.length + 8, closing) : '';
        const external = tag.attrs.some(a => a.key === 'src');
        if (external || RISKY_CODE.test(code)) issues.push({ severity: 'blocked', slide: no, message: 'A <script> in this slide loads or runs code that a presentation may not use (outside code, network calls, storage, cookies). It was not imported.' });
        else { issues.push({ severity: 'info', slide: no, message: 'This slide has a <script> block: advanced Vue. It can only be edited as source.' }); here.red = true; }
        continue;
      }
      if (['base', 'meta', 'link', 'object', 'embed'].includes(lowerName)) { issues.push({ severity: 'blocked', slide: no, message: `<${name}> is not allowed in a slide.` }); continue; }
      if (lowerName === 'iframe') { issues.push({ severity: 'warning', slide: no, message: 'An <iframe> shows another web page inside the slide. It may not load on the mission network, and cannot be edited visually.' }); here.red = true; }
      for (const a of tag.attrs) {
        if (BLOCKED_ATTR.test(a.key)) issues.push({ severity: 'blocked', slide: no, message: `The ${a.key} setting of <${name}> runs code when clicked or loaded, which a presentation may not use.` });
        if (a.key === 'v-html') issues.push({ severity: 'blocked', slide: no, message: 'v-html puts HTML text into the slide as code, which a presentation may not use.' });
        if (a.value && /^\s*javascript:/i.test(a.value)) issues.push({ severity: 'blocked', slide: no, message: 'A javascript: link is not allowed.' });
      }

      if (isComponent) {
        used.add(name);
        const spec = componentByName.get(name);
        if (spec) {
          for (const a of tag.attrs) attrIssue(spec, a, spec, issues, no);
          if (name === 'MissionChart') checkChart(tag, no, issues, refs);
          if (name === 'MissionKpiChart') refs.query = refs.query || false;
        }
        else if (!slidevKnown.has(name) && !wanted.has(name)) {
          issues.push({ severity: 'error', slide: no, message: `Unknown component: ${name}.${didYouMean(name, allComponentNames)}` });
          here.red = true;
        }
        else if (/^(Gfm|Mission)/.test(name) && !spec) { /* unreachable: unknown ones are errors above */ }
      }
      else if (!HTML_OK.has(lowerName) && !lowerName.startsWith('svg')) {
        issues.push({ severity: 'warning', slide: no, message: `<${name}> is not a tag Studio knows.` });
        here.yellow = true;
      }
      else if (!['br', 'hr', 'p', 'strong', 'em', 'b', 'i', 'u', 'li', 'ul', 'ol', 'code', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'img', 'kbd', 'blockquote', 'sup', 'sub', 'small', 'mark', 'del', 's'].includes(lowerName)) here.yellow = true; // custom layout built from HTML
      if (lowerName === 'style') { notes.push('custom CSS'); here.yellow = true; }
    }
    for (const open of stack) if (!VOID.has(open.name.toLowerCase())) { issues.push({ severity: 'error', slide: no, message: `${open.name} is missing a closing tag (line ${lineOf(masked, open.index)} of the slide).` }); here.red = true; }

    // Pictures.
    for (const ref of pictureRefs(fm, body, masked)) {
      if (/^data:/.test(ref)) continue;
      if (/^https?:\/\//i.test(ref)) { issues.push({ severity: 'warning', slide: no, message: `The picture ${shorten(ref)} comes from another website. It may not load for everyone, and is not kept with the deck. Download it and add it in Assets.` }); here.yellow = true; }
      else if (assets) {
        const clean = ref.split(/[?#]/)[0].replace(/^\.?\//, '');
        if (!assets.has(clean) && !assets.has('/' + clean)) { issues.push({ severity: 'warning', slide: no, message: `The picture ${shorten(ref)} is not in this deck's Assets. Add the file, or the slide shows a broken picture.` }); here.yellow = true; }
      }
    }

    // Styled by class attributes beyond Slidev's own utility classes is fine; a <style> is flagged above.
    const status = here.red ? 'red' : here.yellow ? 'yellow' : 'green';
    if (status === 'red' && !issues.some(i => i.slide === no && (i.severity === 'error' || i.severity === 'blocked'))) notes.push('This slide uses advanced Slidev features. Some parts can be edited visually; use Source for full control.');
    if (status === 'red' && notes.length === 0) notes.push('Parts of this slide cannot be edited visually; use Source for full control.');
    const heading = (/^\s*#\s+(.+)$/m.exec(body)?.[1] ?? fm.keys.heading ?? fm.keys.title ?? '').trim();
    slidesOut.push({ no, layout: layoutName, heading, components: [...used], status, notes });
  });

  // Pinned numbers: a chart's query must be plain JSON in the slide for leaders to see it.
  const queryAttrs = (text.match(/:query\s*=/g) ?? []).length;
  if (queryAttrs) {
    const pinned = pinnedKeys(text).size;
    if (pinned < queryAttrs) issues.push({ severity: 'warning', slide: 0, message: 'Some mission-number charts are not written as plain JSON, so leaders who view the deck may not see their numbers. Use Add chart or Edit chart to write them.' });
  }

  const counts = { green: 0, yellow: 0, red: 0 };
  for (const s of slidesOut) counts[s.status]++;
  const valid = !issues.some(i => i.severity === 'error' || i.severity === 'blocked');
  return { slides: slidesOut, issues, counts, valid, fixable: [...fixable], headmatter };
}

const shorten = s => (s.length > 50 ? s.slice(0, 47) + '…' : s);

function pictureRefs(fm, body, masked) {
  const out = new Set();
  for (const m of masked.matchAll(/!\[[^\]]*\]\(\s*<?([^)\s>]+)/g)) out.add(m[1]);
  for (const m of masked.matchAll(/<(?:img|source|video|audio)\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/gi)) out.add(m[1]);
  for (const m of masked.matchAll(/url\(\s*["']?([^"')]+)/gi)) out.add(m[1]);
  for (const key of ['image', 'background', 'src']) if (fm.keys[key] && /[./]/.test(fm.keys[key]) && !/^(#|rgb|hsl|linear|radial)/i.test(fm.keys[key]) && !/^[\w-]+$/.test(fm.keys[key]) && /\.(png|jpe?g|gif|svg|webp|avif|mp4|webm)(\?|$)|^https?:/i.test(fm.keys[key])) out.add(fm.keys[key]);
  return [...out];
}

// ---- the safe fixes ------------------------------------------------------------------------------------------------

export const FIXES = {
  'unwrap-fence': 'Take the presentation out of the code box (``` … ```).',
  'theme-default': 'Use the installed theme (default).',
  'smart-quotes': 'Change curly quotes in slide settings to straight quotes.',
};

/** Applies the named safe fixes and says what it did: { markdown, applied: [text] }. Nothing else is ever changed. */
export function autoFix(markdown, ids) {
  let text = String(markdown ?? '').replace(/\r\n?/g, '\n').replace(/^﻿/, '');
  const applied = [];
  if (ids.includes('unwrap-fence')) {
    const m = /^\s*```[a-z]*\n([\s\S]*)\n```\s*$/i.exec(text);
    if (m) { text = m[1]; applied.push(FIXES['unwrap-fence']); }
  }
  const deck = splitDeck(text);
  const fixed = deck.slides.map((slide, index) => {
    let raw = slide.raw;
    const fm = frontmatterOf(raw);
    if (!fm.closed || raw.split('\n')[0]?.trimEnd() !== '---') return raw;
    let lines = fm.lines.slice();
    if (ids.includes('smart-quotes')) {
      const next = lines.map(l => l.replace(/[“”]/g, '"').replace(/[‘’]/g, "'"));
      if (next.join('\n') !== lines.join('\n')) { lines = next; if (!applied.includes(FIXES['smart-quotes'])) applied.push(FIXES['smart-quotes']); }
    }
    if (ids.includes('theme-default') && index === 0) {
      const next = lines.map(l => (/^theme\s*:/.test(l) && !/^theme\s*:\s*(["']?)(default|none|@slidev\/theme-default)\1\s*$/.test(l) ? 'theme: default' : l));
      if (next.join('\n') !== lines.join('\n')) { lines = next; applied.push(FIXES['theme-default']); }
    }
    return ['---', ...lines, '---', ...fm.body.split('\n')].join('\n');
  });
  return { markdown: joinDeck(fixed), applied };
}

export { DECK_KEYS, SLIDE_KEYS };
