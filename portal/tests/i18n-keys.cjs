'use strict';
// The quick way to make a new page translatable (docs/handoff/round6/i18n.md, "A new page"). Run from the repository root.
//   node portal/tests/i18n-keys.cjs add <prefix> <file> [more files]
//       Adds every interface text of the files that portal/i18n/en.json does not have yet under "<prefix>.<name>"
//       ({} holes become {a}, {b} …) and prints the new keys. Check them: a code or an id belongs in
//       portal/tests/i18n-ignore.json instead (under the file's name), and a text built from pieces is better
//       written as one whole sentence in the page first.
//   node portal/tests/i18n-keys.cjs todo <lang> [prefix]
//       Prints, as JSON, the English texts that <lang>.json does not have yet (or has only in English): the file to
//       translate. Keep every {placeholder}; a plural ({"one": …, "other": …}) needs the forms of the language.
//   node portal/tests/i18n-keys.cjs merge <lang> <translations.json>
//       Merges {"key": "translation"} into portal/i18n/<lang>.json (in the order of en.json), after checking that
//       the placeholders and plural forms match English. Then run node portal/tests/i18n-check.cjs.
const fs = require('node:fs');
const path = require('node:path');
const { missing } = require('./i18n-missing.cjs');

const ROOT = path.join(__dirname, '..', '..');
const I18N = path.join(ROOT, 'portal', 'i18n');
const read = code => JSON.parse(fs.readFileSync(path.join(I18N, code + '.json'), 'utf8'));
const write = (code, data) => fs.writeFileSync(path.join(I18N, code + '.json'), JSON.stringify(data, null, 1) + '\n');
const placeholders = text => [...new Set([...String(text).matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map(m => m[1]))].sort().join(',');
const texts = value => (value && typeof value === 'object' ? Object.values(value) : [value]);

function keyName(text, taken) {
  const words = text.replace(/\{\}/g, ' ').replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/).filter(Boolean).slice(0, 5);
  let name = words.map((w, i) => (i ? w[0].toUpperCase() + w.slice(1) : w.toLowerCase())).join('') || 'text';
  let key = name, n = 2;
  while (taken.has(key)) key = name + n++;
  return key;
}

const [command, ...args] = process.argv.slice(2);
if (command === 'add') {
  const [prefix, ...files] = args;
  if (!prefix || !files.length) throw new Error('usage: add <prefix> <file> [more files]');
  const en = read('en'), seen = new Set(), taken = new Set(Object.keys(en).filter(k => k.startsWith(prefix + '.')).map(k => k.slice(prefix.length + 1)));
  for (const found of missing(files)) {
    if (seen.has(found.text)) continue;
    seen.add(found.text);
    let hole = 0;
    const english = found.text.replace(/\{\}/g, () => '{' + String.fromCharCode(97 + hole++) + '}');
    const name = keyName(found.text, taken);
    taken.add(name);
    en[prefix + '.' + name] = english;
    console.log(`${prefix}.${name}\t${english}\t(${found.file}:${found.line})`);
  }
  write('en', en);
} else if (command === 'todo') {
  const [code, prefix = ''] = args;
  const en = read('en'), catalog = read(code), out = {};
  for (const [key, value] of Object.entries(en)) {
    if (!key.startsWith(prefix)) continue;
    if (!(key in catalog) || (code !== 'en' && JSON.stringify(catalog[key]) === JSON.stringify(value))) out[key] = value;
  }
  console.log(JSON.stringify(out, null, 1));
} else if (command === 'merge') {
  const [code, file] = args;
  const en = read('en'), catalog = read(code), incoming = JSON.parse(fs.readFileSync(file, 'utf8'));
  const problems = [];
  for (const [key, value] of Object.entries(incoming)) {
    if (!(key in en)) { problems.push(`${key}: not in en.json`); continue; }
    if ((typeof en[key] === 'object') !== (typeof value === 'object')) { problems.push(`${key}: English is ${typeof en[key] === 'object' ? 'a plural' : 'one text'}`); continue; }
    const want = placeholders(texts(en[key]).join(' '));
    const wrong = texts(value).find(t => typeof t !== 'string' || !t.trim() || placeholders(t) !== want);
    if (wrong !== undefined) { problems.push(`${key}: needs the placeholders {${want}}: ${JSON.stringify(wrong)}`); continue; }
    catalog[key] = value;
  }
  if (problems.length) { console.error(problems.join('\n')); process.exitCode = 1; }
  const ordered = {};
  for (const key of Object.keys(en)) if (key in catalog) ordered[key] = catalog[key];
  write(code, ordered);
  console.log(`${code}: ${Object.keys(incoming).length - problems.length} merged, ${problems.length} refused`);
} else {
  console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(1, 15).join('\n'));
}
