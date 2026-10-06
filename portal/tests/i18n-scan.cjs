'use strict';
// Finds the user-visible English text in a page or script, so i18n-check.cjs can tell which of it is not in the
// catalog yet. Text between tags and the title, placeholder, aria-label and alt attributes of HTML (pages, and HTML
// inside JavaScript strings and Python f-strings), and JavaScript / Python strings that read like a sentence or a
// label. A "${…}" or "{…}" inside a string becomes {} ("Delete {}?"), which a catalog text with a placeholder
// ("Delete {name}?") matches. It is a heuristic: code-like strings (selectors, class names, keys, URLs, SQL) are
// skipped; what is left and still not text for people goes into IGNORE in i18n-check.cjs.
const fs = require('node:fs');

const HOLE = '\u0001';
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', rarr: '→', larr: '←', middot: '·', hellip: '…', mdash: '—', ndash: '–', times: '×', check: '✓', bull: '•', rsaquo: '›', lsaquo: '‹', raquo: '»', laquo: '«', uarr: '↑', darr: '↓', copy: '©', ne: '≠', le: '≤', ge: '≥', minus: '−' };
const decode = s => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => e[0] === '#' ? String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : (ENTITIES[e.toLowerCase()] ?? m));
const clean = s => s.replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- JavaScript
// A small tokenizer: comments, strings, template literals (with their ${…} parts scanned too) and regex literals.
function jsStrings(code, baseLine = 1) {
  const out = [];
  let i = 0, line = baseLine, prev = '';
  const regexAfter = /[(,=:[!&|?{};+\-*%<>~^]$|^(?:return|typeof|case|do|else|in|of|new|delete|void|throw|yield|await)$/;
  function template() { // at the opening backtick
    const startLine = line; let text = ''; i++;
    while (i < code.length) {
      const c = code[i];
      if (c === '\\') { text += code[i + 1] === '\n' ? '' : code[i + 1]; if (code[i + 1] === '\n') line++; i += 2; continue; }
      if (c === '`') { i++; break; }
      if (c === '$' && code[i + 1] === '{') { i += 2; text += HOLE; expression(); continue; }
      if (c === '\n') line++;
      text += c; i++;
    }
    out.push({ text, line: startLine, template: true });
  }
  function expression() { // inside ${ … } up to the matching }
    let depth = 1;
    while (i < code.length && depth) {
      const c = code[i];
      if (c === '{') { depth++; i++; } else if (c === '}') { depth--; i++; } else step();
    }
  }
  function quoted(q) {
    const startLine = line; let text = ''; i++;
    while (i < code.length && code[i] !== q) {
      if (code[i] === '\\') { const n = code[i + 1]; text += n === 'n' ? '\n' : n === 't' ? '\t' : n === 'u' ? String.fromCharCode(parseInt(code.slice(i + 2, i + 6), 16)) : n; i += n === 'u' ? 6 : 2; continue; }
      if (code[i] === '\n') { line++; break; }
      text += code[i]; i++;
    }
    i++; out.push({ text, line: startLine });
  }
  function step() {
    const c = code[i];
    if (c === '\n') { line++; i++; return; }
    if (/\s/.test(c)) { i++; return; }
    if (c === '/' && code[i + 1] === '/') { while (i < code.length && code[i] !== '\n') i++; return; }
    if (c === '/' && code[i + 1] === '*') { const end = code.indexOf('*/', i + 2); const chunk = code.slice(i, end < 0 ? code.length : end + 2); line += (chunk.match(/\n/g) || []).length; i += chunk.length; return; }
    if (c === '"' || c === "'") { quoted(c); prev = 'str'; return; }
    if (c === '`') { template(); prev = 'str'; return; }
    if (c === '/' && (prev === '' || regexAfter.test(prev))) {
      i++; let inClass = false;
      while (i < code.length && code[i] !== '\n') { if (code[i] === '\\') { i += 2; continue; } if (code[i] === '[') inClass = true; else if (code[i] === ']') inClass = false; else if (code[i] === '/' && !inClass) break; i++; }
      i++; while (/[a-z]/i.test(code[i] || '')) i++; prev = 'regex'; return;
    }
    const word = code.slice(i).match(/^[A-Za-z_$][\w$]*/);
    if (word) { prev = word[0]; i += word[0].length; return; }
    const num = code.slice(i).match(/^\d[\w.]*/);
    if (num) { prev = 'num'; i += num[0].length; return; }
    prev = c; i++;
  }
  while (i < code.length) step();
  return out;
}

// ---------------------------------------------------------------- Python
// String literals, with adjacent literals joined as Python joins them ("a" "b" is "ab").
const PY_OPEN = /^([rRbBuUfF]{0,2})("""|'''|"|')/;
function pyLiteral(code, index) {
  const m = PY_OPEN.exec(code.slice(index, index + 5));
  if (!m) return null;
  const prefix = m[1].toLowerCase(), q = m[2];
  let j = index + m[0].length, text = '', depth = 0;
  const exprs = [];
  const fString = prefix.includes('f');
  while (j < code.length) {
    // Inside an f-string's {expr} a string may use the same quotes (Python 3.12): it does not end this one.
    if (fString && depth && /['"]/.test(code[j])) {
      const start = /[rRbBuUfF]{1,2}$/.test(code.slice(Math.max(0, j - 2), j)) && !/\w/.test(code[j - 3] || '') ? j - code.slice(0, j).match(/[rRbBuUfF]{1,2}$/)[0].length : j;
      const inner = pyLiteral(code, start);
      if (inner) { text += code.slice(j, inner.end); j = inner.end; continue; }
    }
    if (code.startsWith(q, j)) break;
    if (q.length === 1 && code[j] === '\n') break;
    if (code[j] === '\\' && !prefix.includes('r')) { const n = code[j + 1]; text += n === 'n' ? '\n' : n === '\n' ? '' : n; j += 2; continue; }
    if (fString) {
      if ((code[j] === '{' || code[j] === '}') && !depth && code[j + 1] === code[j]) { text += code[j] + code[j]; j += 2; continue; }
      if (code[j] === '{') depth++; else if (code[j] === '}' && depth) depth--;
    }
    text += code[j]; j++;
  }
  if (prefix.includes('f')) {
    // {expr} is a hole, {{ and }} are braces. The strings inside an {expr} ({"<p>No questions yet.</p>" if …}) are
    // text too: pyStrings scans each expression again.
    let t = '', depth = 0, expr = '';
    for (let k = 0; k < text.length; k++) {
      const c = text[k];
      if (!depth && c === '{' && text[k + 1] === '{') { t += '{'; k++; continue; }
      if (!depth && c === '}' && text[k + 1] === '}') { t += '}'; k++; continue; }
      if (c === '{') { if (!depth) { t += HOLE; expr = ''; } else expr += c; depth++; continue; }
      if (c === '}' && depth) { depth--; if (depth) expr += c; else exprs.push(expr); continue; }
      if (!depth) t += c; else expr += c;
    }
    text = t;
  } else {
    text = text.replace(/\{[a-z_0-9]*\}|%\([a-z_]+\)s|%[sd]/g, HOLE); // str.format and % placeholders
  }
  return { text, end: j + q.length, q, exprs };
}
function pyStrings(code) {
  const out = [];
  const re = /(#[^\n]*)|([rRbBuUfF]{0,2})("""|'''|"|')/g;
  let m;
  while ((m = re.exec(code))) {
    if (m[1]) continue;
    const first = pyLiteral(code, m.index);
    const line = code.slice(0, m.index).split('\n').length;
    // A docstring (a triple-quoted string that is a statement of its own) is for programmers.
    const doc = first.q.length === 3 && /(^|\n)[ \t]*$/.test(code.slice(Math.max(0, m.index - 200), m.index)) && /^[ \t]*(#[^\n]*)?(\r?\n|$)/.test(code.slice(first.end, first.end + 200));
    let text = first.text, end = first.end;
    const exprs = [...first.exprs];
    while (!doc) {
      const gap = /^(?:[ \t\r\n]|\\\r?\n|#[^\n]*)*/.exec(code.slice(end, end + 400))[0];
      const next = PY_OPEN.test(code.slice(end + gap.length, end + gap.length + 5)) ? pyLiteral(code, end + gap.length) : null;
      if (!next) break;
      text += next.text; end = next.end; exprs.push(...next.exprs);
    }
    if (!doc) out.push({ text, line, template: text.includes(HOLE) });
    for (const expr of exprs) for (const inner of pyStrings(expr)) out.push({ ...inner, line });
    re.lastIndex = end;
  }
  return out;
}

// ---------------------------------------------------------------- HTML inside a page or a string
const ATTRS = ['title', 'placeholder', 'aria-label', 'alt', 'label', 'data-confirm'];
function htmlTexts(html, line, found) {
  const withoutBlocks = html.replace(/<!--[\s\S]*?-->/g, '').replace(/<(script|style|textarea|code|pre)\b[^>]*>[\s\S]*?<\/\1>/gi, m => /^<(textarea|code|pre)/i.test(m) ? m.replace(/>[\s\S]*</, '><') : '');
  const parts = withoutBlocks.split(/(<[^>]*>)/);
  let ignoreDepth = 0;
  const stack = [];
  for (const part of parts) {
    if (part.startsWith('<') && part.endsWith('>')) {
      const tag = part.match(/^<\/?\s*([a-zA-Z][\w-]*)/);
      if (!tag) continue;
      if (part.startsWith('</')) { const top = stack.pop(); if (top) ignoreDepth--; continue; }
      const ignored = /\sdata-i18n-ignore\b/.test(part) || /\stranslate=["']?no/.test(part);
      const voidTag = /^(input|br|hr|img|meta|link|source|wbr|col|area|base)$/i.test(tag[1]) || part.endsWith('/>');
      if (!voidTag) { stack.push(ignored); if (ignored) ignoreDepth++; }
      if (ignored || ignoreDepth) continue;
      for (const name of ATTRS) {
        const a = part.match(new RegExp('\\s' + name + '\\s*=\\s*("([^"]*)"|\'([^\']*)\')'));
        if (a) found.push({ text: clean(decode(a[2] ?? a[3])), line, attr: name });
      }
      if (/^input$/i.test(tag[1]) && /type=["']?(submit|button)/i.test(part) && !/\sname=/.test(part)) {
        const v = part.match(/\svalue\s*=\s*("([^"]*)"|'([^']*)')/); if (v) found.push({ text: clean(decode(v[2] ?? v[3])), line, attr: 'value' });
      }
      continue;
    }
    if (ignoreDepth) continue;
    const text = clean(decode(part));
    if (text) found.push({ text, line });
  }
}

// ---------------------------------------------------------------- is it text for people?
const CODE_WORDS = /^(?:GET|PUT|POST|DELETE|PATCH|HEAD|OPTIONS|true|false|null|undefined|none|auto|inherit|utf-8|UTF-8|Bearer|Content-Type|application\/json|text\/html|Europe\/Berlin|en-CA|en-GB|en-US|sv-SE)$/;
function looksLikeText(raw, { template = false } = {}) {
  const text = clean(raw.split(HOLE).join('{}'));
  if (!text || !/\p{L}{2}/u.test(text.replace(/\{\}/g, ''))) return null;
  if (CODE_WORDS.test(text)) return null;
  if (/^(https?:|mailto:|data:|\/|\.\/|#[\w-]|\.[\w-]+|\[[\w-]|@media|--)/.test(text)) return null;              // URLs, paths, selectors
  if (/^[\w-]+(\.[\w-]+)+$/.test(text) && !/ /.test(text)) return null;                                      // file.ext, a.b.c
  if (/[;{]/.test(text.replace(/\{\}/g, '')) && /:/.test(text) && !/\p{L}{2,}(\s+\S+){5,}[.!?)]$/u.test(text)) return null; // CSS, code (not prose)
  if (/^[a-z0-9_$-]+$/.test(text)) return null;                                                                // identifiers, snake_case, kebab-case
  if (/^[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$/.test(text)) return null;                                         // camelCase
  if (/^[A-Z0-9_]+$/.test(text)) return null;                                                                  // CONSTANTS, role codes
  if (/^[a-z][\w-]*(\s+[a-z][\w-]*)+$/.test(text) && /-/.test(text) && !/[A-Z]/.test(text)) return null;      // class lists
  if (/[.#[:>]/.test(text) && text.split(/[\s,>+~]+/).filter(Boolean).every(t => /^[.#]?[a-z][\w-]*(?:[.#][\w-]+)*(?:\[[^\]]*\])*(?::[\w-]+(?:\([^)]*\))?)*$/.test(t))) return null; // selectors
  // SQL: its keywords in lower or upper case. "Where the chart goes", "Delete this deck" and "Update now" are labels.
  if ((/^(select|insert|update|delete|with|set|lock|truncate|alter|create|and|or|where|order by|for update)\b/.test(text) ||
       /^(SELECT|INSERT|UPDATE|DELETE|WITH|SET|LOCK|TRUNCATE|ALTER|CREATE|AND|OR|WHERE|ORDER BY|FOR UPDATE)\b/.test(text)) && !/[.?!]$/.test(text)) return null;
  if (/\b(coalesce|concat_ws|greatest|jsonb_\w+)\(|\bis not distinct from\b|%s|\{\}\s*(=|<=|>=)|=\s*ANY\(/i.test(text)) return null;
  if (/^\{\}(\s*[^\p{L}\s]*\s*\{\})*$/u.test(text)) return null;
  if (/^[^\p{Lu}\s]+$/u.test(text) && !template) return null;                                                  // one lowercase word: a key
  return text;
}

function scanHtml(source, file, found) {
  htmlTexts(source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, m => '\n'.repeat((m.match(/\n/g) || []).length)), 1, found);
  const scripts = /<script\b[^>]*>([\s\S]*?)<\/script>/gi; let m;
  while ((m = scripts.exec(source))) scanJs(m[1], source.slice(0, m.index).split('\n').length, found);
}
function scanJs(code, baseLine, found) {
  for (const s of jsStrings(code, baseLine)) consider(s, found);
}
function consider(s, found) {
  if (/<\/?[a-zA-Z][\w-]*[\s>/]/.test(s.text) || /^\s*<[a-z]/i.test(s.text)) {
    // A page inside a string (the Presentations library): its own scripts are scanned too.
    const scripts = /<script\b[^>]*>([\s\S]*?)<\/script>/gi; let m;
    while ((m = scripts.exec(s.text))) scanJs(m[1], s.line, found);
    const before = found.length;
    htmlTexts(s.text, s.line, found);
    for (let k = before; k < found.length; k++) found[k].template = found[k].text.includes(HOLE);
    return;
  }
  found.push({ text: s.text, line: s.line, template: s.template, plain: true });
}

function scan(file, source = fs.readFileSync(file, 'utf8')) {
  const found = [];
  if (/\.html?$/.test(file)) scanHtml(source, file, found);
  else if (/\.(c|m)?js$/.test(file)) scanJs(source, 1, found);
  else if (/\.py$/.test(file)) for (const s of pyStrings(source)) consider(s, found);
  const seen = new Set(), result = [];
  for (const f of found) {
    const text = looksLikeText(f.text, f);
    if (!text) continue;
    const id = text + '\u0000' + f.line;
    if (seen.has(id)) continue;
    seen.add(id);
    result.push({ file, line: f.line, text, attr: f.attr || null });
  }
  return result;
}

// "Delete {name}?" and "Delete {}?" are the same text.
const shape = text => clean(String(text)).replace(/\{[a-zA-Z0-9_]*\}/g, '{}');

module.exports = { scan, shape, looksLikeText, jsStrings, pyStrings, htmlTexts, HOLE };

if (require.main === module) {
  const files = process.argv.slice(2);
  const all = files.flatMap(f => scan(f));
  for (const r of all) console.log(`${r.file}:${r.line}\t${r.attr ? '[' + r.attr + '] ' : ''}${r.text}`);
  console.error(all.length + ' texts, ' + new Set(all.map(r => shape(r.text))).size + ' distinct');
}
