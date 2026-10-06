// Unit tests of gfm-i18n.js on a tiny stand-in DOM (the repository has no jsdom). Plain Node, no packages:
//   node --test "dataease/i18n/tests/*.test.mjs"
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const I18n = require(path.join(dir, 'gfm-i18n.js'));
const load = lang => JSON.parse(fs.readFileSync(path.join(dir, lang + '.json'), 'utf8'));

// ---- the stand-in DOM: only what gfm-i18n.js uses
class Text {
  constructor(v) { this.nodeType = 3; this.nodeName = '#text'; this.nodeValue = v; this.parentNode = null; }
}
class El {
  constructor(tag, attrs = {}) {
    this.nodeType = 1; this.nodeName = tag === 'svg' ? 'svg' : tag.toUpperCase();
    this.attrs = new Map(Object.entries(attrs)); this.childNodes = []; this.parentNode = null;
  }
  getAttribute(n) { return this.attrs.has(n) ? this.attrs.get(n) : null; }
  setAttribute(n, v) { this.attrs.set(n, String(v)); }
  hasAttributes() { return this.attrs.size > 0; }
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  get textContent() { return this.childNodes.map(c => (c.nodeType === 3 ? c.nodeValue : c.textContent)).join(''); }
  set textContent(v) { this.childNodes = []; this.appendChild(new Text(v)); }
}
const h = (tag, attrs, ...kids) => {
  const el = new El(tag, attrs || {});
  for (const k of kids) el.appendChild(typeof k === 'string' ? new Text(k) : k);
  return el;
};

// A small dictionary in the shape of the real files.
const EN = { messages: { a: 'No Data', b: 'Please enter', c: 'Total {total}', d: 'Name', e: 'Export As', f: 'Line one<br/>Line two', g: '{count} sample | {count} samples', h: 'Duplicate field name: %s', i: 'Can read ${\'{\'}fieldName{\'}\'} values' },
  pmg: { 'indicator.friends': 'New People Being Taught', 'indicator.friends@portal': 'New people being taught' } };
const DE = { messages: { a: 'Keine Daten', b: 'Bitte eingeben', c: 'Insgesamt {total}', d: 'Name', e: 'Exportieren als', f: 'Zeile eins<br/>Zeile zwei', g: '{count} Stichprobe | {count} Stichproben', h: 'Doppelter Feldname: %s', i: 'Liest ${\'{\'}fieldName{\'}\'}-Werte' },
  pmg: { 'indicator.friends': 'Neue Personen, die unterwiesen werden', 'indicator.friends@portal': 'Neue Personen, die unterwiesen werden' } };
const dict = I18n.buildDictionary(EN, DE);
const tr = s => I18n.translateString(dict, s);

test('exact trimmed match keeps the white space around the text', () => {
  assert.equal(tr('No Data'), 'Keine Daten');
  assert.equal(tr('  Export As \n'), '  Exportieren als \n');
  assert.equal(tr('No data at all'), null);
  assert.equal(tr('12,345'), null);
  assert.equal(tr('Name'), null, 'same text in both languages: nothing to do');
});

test('placeholders, plural forms, <br> pieces, %s, a trailing colon and vue-i18n literals', () => {
  assert.equal(tr('Total 42'), 'Insgesamt 42');
  assert.equal(tr('3 samples'), '3 Stichproben');
  assert.equal(tr('1 sample'), '1 Stichprobe');
  assert.equal(tr('Line two'), 'Zeile zwei');
  assert.equal(tr('Duplicate field name: Ward'), 'Doppelter Feldname: Ward');
  assert.equal(tr('Please enter:'), 'Bitte eingeben:');
  assert.equal(tr('Can read ${fieldName} values'), 'Liest ${fieldName}-Werte');
});

test('key indicator names: PMG wording, in any case and under their other English names', () => {
  assert.equal(tr('New People Being Taught'), 'Neue Personen, die unterwiesen werden');
  assert.equal(tr('new people being taught'), 'Neue Personen, die unterwiesen werden');
  assert.equal(tr('NEW PEOPLE BEING TAUGHT'), 'Neue Personen, die unterwiesen werden');
});

test('text nodes and placeholder/title/aria-label; never input values, editors, code, canvas or svg', () => {
  const input = h('input', { placeholder: 'Please enter', value: 'No Data', title: 'Export As' });
  const textarea = h('textarea', { placeholder: 'Please enter' }, 'No Data');
  const body = h('body', null,
    h('div', { class: 'de-preview', 'aria-label': 'No Data' }, h('span', null, ' No Data ')),
    input, textarea,
    h('div', { contenteditable: 'true' }, 'No Data'),
    h('div', { class: 'wrap monaco-editor' }, h('span', null, 'No Data')),
    h('code', null, 'No Data'), h('pre', null, 'No Data'), h('canvas', { title: 'No Data' }),
    h('svg', null, h('text', null, 'No Data')),
    h('span', { translate: 'no' }, 'No Data'));
  new I18n.Translator(dict).tree(body);
  const [div, , , editable, monaco, code, pre, canvas, svg, notranslate] = body.childNodes;
  assert.equal(div.textContent, ' Keine Daten ');
  assert.equal(div.getAttribute('aria-label'), 'Keine Daten');
  assert.equal(input.getAttribute('placeholder'), 'Bitte eingeben');
  assert.equal(input.getAttribute('title'), 'Exportieren als');
  assert.equal(input.getAttribute('value'), 'No Data', 'an input value is the user\'s');
  assert.equal(textarea.getAttribute('placeholder'), 'Bitte eingeben');
  assert.equal(textarea.textContent, 'No Data');
  for (const el of [editable, monaco, code, pre, svg, notranslate]) assert.equal(el.textContent, 'No Data');
  assert.equal(canvas.getAttribute('title'), 'No Data');
});

test('a second pass changes nothing and does not write again', () => {
  const t = new Text('No Data');
  let writes = 0;
  const node = { nodeType: 3, parentNode: null, get nodeValue() { return t.nodeValue; }, set nodeValue(v) { writes++; t.nodeValue = v; } };
  const body = h('body');
  body.appendChild(node);
  const translator = new I18n.Translator(dict);
  translator.tree(body); translator.tree(body); translator.tree(body);
  assert.equal(t.nodeValue, 'Keine Daten');
  assert.equal(writes, 1);
  node.nodeValue = 'Export As'; // the app shows new English text in the same node
  translator.tree(body);
  assert.equal(t.nodeValue, 'Exportieren als');
});

test('language: ?gfmLang= first (address or hash route), then the remembered one; unknown codes ignored', () => {
  assert.deepEqual(I18n.pickLanguage('?gfmLang=de', '', null), { lang: 'de', remember: 'de' });
  assert.deepEqual(I18n.pickLanguage('?a=1&gfmLang=pt-BR', '', 'fr'), { lang: 'pt', remember: 'pt' });
  assert.deepEqual(I18n.pickLanguage('', '#/preview?dvId=7&gfmLang=AR', null), { lang: 'ar', remember: 'ar' });
  assert.deepEqual(I18n.pickLanguage('?gfmLang=xx', '', 'sv'), { lang: 'sv', remember: null });
  assert.deepEqual(I18n.pickLanguage('', '', null), { lang: 'en', remember: null });
  assert.deepEqual(I18n.pickLanguage('?gfmLang=en', '', 'de'), { lang: 'en', remember: 'en' });
});

// ---- a stand-in window for watch() and start()
function fakeWindow({ search = '', stored = null, files = {} } = {}) {
  const html = h('html', { lang: 'en' });
  const head = html.appendChild(h('head'));
  const body = html.appendChild(h('body'));
  const frames = [];
  const store = new Map(stored ? [[I18n.STORE_KEY, stored]] : []);
  const fetched = [];
  const win = {
    frames, fetched, observers: [],
    location: { search, hash: '' },
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
    store,
    document: { documentElement: html, head, body, createElement: tag => h(tag), addEventListener() {} },
    requestAnimationFrame: f => frames.push(f),
    fetch: url => { fetched.push(url); const code = url.match(/([a-z]+)\.json$/)[1]; return Promise.resolve({ ok: !!files[code], status: files[code] ? 200 : 404, json: () => Promise.resolve(files[code]) }); },
    console: { warn() {} },
  };
  win.MutationObserver = class {
    constructor(cb) { this.cb = cb; this.taken = 0; win.observers.push(this); }
    observe(target, options) { this.target = target; this.options = options; }
    takeRecords() { this.taken++; return []; }
  };
  return win;
}

test('changes are batched: many mutation records, one animation frame, one pass', () => {
  const win = fakeWindow();
  const translator = new I18n.Translator(dict);
  const observer = I18n.watch(win, translator);
  assert.deepEqual(observer.options.attributeFilter, ['placeholder', 'title', 'aria-label']);
  const records = [];
  const added = [];
  for (let i = 0; i < 500; i++) {
    const el = win.document.body.appendChild(h('div', null, h('span', null, 'No Data')));
    added.push(el);
    records.push({ type: 'childList', addedNodes: [el] });
  }
  const input = win.document.body.appendChild(h('input', { placeholder: 'Please enter' }));
  records.push({ type: 'attributes', target: input });
  observer.cb(records.slice(0, 250));
  observer.cb(records.slice(250));
  assert.equal(win.frames.length, 1, 'one frame for all records');
  assert.equal(added[0].textContent, 'No Data', 'nothing is done before the frame');
  win.frames[0]();
  assert.ok(added.every(el => el.textContent === 'Keine Daten'));
  assert.equal(input.getAttribute('placeholder'), 'Bitte eingeben');
  assert.equal(observer.taken, 1, 'our own changes are dropped from the queue');
  // A text change inside an editor is left alone.
  const editor = win.document.body.appendChild(h('div', { class: 'monaco-editor' }));
  const line = editor.appendChild(new Text('No Data'));
  observer.cb([{ type: 'characterData', target: line }]);
  win.frames[1]();
  assert.equal(line.nodeValue, 'No Data');
});

test('a large page: 30 000 text nodes in well under a second', () => {
  const body = h('body');
  for (let i = 0; i < 3000; i++) {
    body.appendChild(h('div', { class: 'de-component', title: 'Export As' },
      h('span', null, 'No Data'), h('span', null, String(i * 17)), h('span', null, 'Ward ' + i),
      h('span', null, 'Total ' + i), h('span', null, 'New People Being Taught'), h('b', null, 'x'), h('i', null, 'Name'),
      h('span', null, '  '), h('span', null, 'Please enter'), h('span', null, 'Some user label ' + (i % 50))));
  }
  const t0 = process.hrtime.bigint();
  new I18n.Translator(I18n.buildDictionary(load('en'), load('de'))).tree(body);
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  assert.ok(ms < 1000, `took ${ms.toFixed(0)} ms`);
  assert.equal(body.childNodes[0].childNodes[3].textContent, load('de').messages['el.pagination.total'].replace('{total}', '0'));
  assert.equal(body.childNodes[0].childNodes[4].textContent, load('de').pmg['indicator.friends']);
});

test('start(): ?gfmLang=de loads en.json and de.json, remembers de, sets <html lang> and translates the page', async () => {
  const win = fakeWindow({ search: '?gfmLang=de', files: { en: load('en'), de: load('de') } });
  win.document.body.appendChild(h('div', null, 'No Data'));
  const observer = await I18n.start(win);
  assert.ok(observer, 'watching');
  assert.deepEqual(win.fetched, ['/gfm-i18n/en.json', '/gfm-i18n/de.json']);
  assert.equal(win.store.get(I18n.STORE_KEY), 'de');
  assert.equal(win.document.documentElement.getAttribute('lang'), 'de');
  assert.equal(win.document.body.childNodes[0].textContent, load('de').messages['el.table.emptyText']);
  assert.equal(win.document.documentElement.getAttribute('data-gfm-rtl'), null);
});

test('start(): English, and no language at all, do nothing', async () => {
  for (const opts of [{ search: '?gfmLang=en', stored: 'de' }, {}]) {
    const win = fakeWindow(opts);
    assert.equal(await I18n.start(win), null);
    assert.deepEqual(win.fetched, []);
    assert.equal(win.observers.length, 0);
    assert.equal(win.document.documentElement.getAttribute('lang'), 'en');
  }
});

test('start(): the remembered language is used without ?gfmLang=; Arabic gets text direction only', async () => {
  const win = fakeWindow({ stored: 'ar', files: { en: load('en'), ar: load('ar') } });
  await I18n.start(win);
  const html = win.document.documentElement;
  assert.equal(html.getAttribute('lang'), 'ar');
  assert.equal(html.getAttribute('data-gfm-rtl'), '');
  assert.equal(html.getAttribute('dir'), null, 'the layout is not mirrored');
  const style = win.document.head.childNodes[0];
  assert.match(style.textContent, /unicode-bidi:plaintext/);
  assert.doesNotMatch(style.textContent, /direction\s*:\s*rtl/);
});

test('start(): a missing language file leaves DataEase in English', async () => {
  const win = fakeWindow({ search: '?gfmLang=sv', files: { en: load('en') } });
  win.document.body.appendChild(h('div', null, 'No Data'));
  assert.equal(await I18n.start(win), null);
  assert.equal(win.document.body.childNodes[0].textContent, 'No Data');
});

test('our own words ("gfm"): they win over DataEase\'s, Preach My Gospel wins over both; "· Name:" pieces', () => {
  const en = { messages: { a: 'Filters', b: 'Result' }, gfm: { 'word.filters': 'Filters', 'cp.calling': 'Calling', 'x': 'New People Being Taught' },
    pmg: { 'indicator.friends': 'New People Being Taught' } };
  const de = { messages: { a: 'Filterungen', b: 'Resultat' }, gfm: { 'word.filters': 'Filter', 'cp.calling': 'Berufung', 'x': 'falsch' },
    pmg: { 'indicator.friends': 'Neue Personen, die unterwiesen werden' } };
  const d = I18n.buildDictionary(en, de);
  const t = s => I18n.translateString(d, s);
  assert.equal(t('Filters'), 'Filter', 'gfm over messages');
  assert.equal(t('Result'), 'Resultat', 'DataEase\'s own word where we have none');
  assert.equal(t('New People Being Taught'), 'Neue Personen, die unterwiesen werden', 'pmg over gfm');
  assert.equal(t(' · Calling: '), ' · Berufung: ', 'a line of numbers: "At church: 3 · Calling: 1" is split around the numbers');
  assert.equal(t('· Unknown:'), null);
});

test('the real German file: the dashboards bar and a Key indicators tile', () => {
  const d = I18n.buildDictionary(load('en'), load('de'));
  const t = s => I18n.translateString(d, s);
  assert.equal(t('All dashboards and Edit'), 'Alle Dashboards und Bearbeiten');
  assert.equal(t('Dashboards'), null, 'the same word in German');
  assert.equal(t('Last complete week: '), 'Letzte vollständige Woche: ');
  assert.equal(t('% of the goal ('), '% des Ziels (');
  assert.equal(t('Week before: '), 'Vorwoche: ');
  assert.equal(t(' · Temple recommend: '), ' · Tempelschein: ');
  assert.equal(t('Sacrament attendance by zone, last complete week'), 'Besuch der Abendmahlsversammlung, nach Zone, letzte vollständige Woche');
  assert.equal(t('New People Being Taught by zone, last complete week'), 'Neue Personen, die unterwiesen werden, nach Zone, letzte vollständige Woche');
  assert.equal(t('Baptisms and confirmations'), 'Getaufte und konfirmierte Personen', 'a PMG name');
});

test('DataEase\'s chart error line "[Message, <link>]": the text after the bracket is translated; <html lang> is kept', () => {
  const d = I18n.buildDictionary(load('en'), load('de'));
  assert.equal(I18n.translateString(d, '[Abnormal data acquisition, if you have any questions, please contact the administrator,'),
    '[' + load('de').messages['chart.chart_error_tips']);
  assert.equal(I18n.translateString(d, 'To'), 'bis', 'the week range of the filters');
  assert.equal(I18n.translateString(d, '[Last complete week]'), null, 'a [Field] of a text box is left alone');
});
