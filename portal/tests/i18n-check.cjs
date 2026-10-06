// Checks the interface translation (portal/i18n.js and portal/i18n/*.json). Run from the repository root:
//   node portal/tests/i18n-check.cjs
//  1. The 14 catalogs have the same keys as en.json, the same {placeholders}, every plural form their language uses,
//     and the key indicator in the Church's words (Preach My Gospel 2023, chapter 8) where the Church has them.
//  2. Every page and script in PAGES (i18n-missing.cjs) has no interface text outside the catalog, except names and
//     data and what portal/tests/i18n-ignore.json lists as not for people; the portal pages load i18n.js in <head>
//     without defer; DA Management and Presentations load it from the portal, which lets them read the catalogs.
//  3. i18n.js in a small fake DOM: the 14 languages, right-to-left for Persian and Arabic, ?lang= with ISO and Church
//     codes, the gfm_lang cookie, the shell's message, texts with values and plurals, confirm(), Church links
//     (lang=deu …, eng where the Church does not offer the page), names, written content and option values left
//     alone, and the English fallback (with a notice) for a language without a catalog. Also (round 6 review): dialog
//     line breaks, the right-to-left arrows and other texts whose translation is another key's English, explicit keys
//     (data-i18n), Latin digits for fa/ar also with a named locale, dates written "04 Oct 2026", DA Management's
//     role-plan lines word for word, and no page naming English ("en") for a date.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { missing, PAGES } = require('./i18n-missing.cjs');

const ROOT = path.join(__dirname, '..', '..');
const I18N = path.join(ROOT, 'portal', 'i18n');
const source = fs.readFileSync(path.join(ROOT, 'portal', 'i18n.js'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.join(I18N, 'catalogs.json'), 'utf8'));
const CODES = ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar'];
const catalogs = Object.fromEntries(CODES.map(code => [code, JSON.parse(fs.readFileSync(path.join(I18N, code + '.json'), 'utf8'))]));
const en = catalogs.en;
const keys = Object.keys(en).sort();
const placeholders = text => [...new Set([...String(text).matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map(m => m[1]))].sort().join(',');
const texts = value => (value && typeof value === 'object' ? Object.values(value) : [value]);

// ------------------------------------------------------------------ 1. catalogs
assert.deepEqual(Object.keys(manifest.languages), CODES, 'catalogs.json lists the 14 languages');
for (const code of CODES) {
  const messages = catalogs[code];
  assert.deepEqual(Object.keys(messages).sort(), keys, code + '.json has exactly the keys of en.json');
  const categories = new Intl.PluralRules(code).resolvedOptions().pluralCategories;
  for (const key of keys) {
    const english = en[key], value = messages[key];
    assert.equal(typeof value, typeof english, `${code} ${key}: plural in English and ${code} alike`);
    assert.ok(texts(value).every(t => typeof t === 'string' && t.trim()), `${code} ${key}: not empty`);
    const want = placeholders(texts(english).join(' '));
    for (const t of texts(value)) assert.equal(placeholders(t), want, `${code} ${key}: the placeholders of "${t}" are {${want}}`);
    if (typeof value === 'object') for (const category of categories) assert.ok(value[category] || value.other, `${code} ${key}: plural form "${category}"`);
  }
  if (code !== 'en') assert.equal(manifest.languages[code].review, 'needs review by a native speaker', code + ' is marked for review');
}
const churchTerm = {
  de: 'Neue Personen, die unterwiesen werden', es: 'Personas nuevas a las que se está enseñando', fr: 'Nouvelles personnes instruites actuellement',
  pt: 'Novas pessoas sendo ensinadas', uk: 'Нові люди, яких навчають', ru: 'Новые люди, проходящие обучение', it: 'Nuove persone a cui si sta insegnando',
  tr: 'Yeni insanlar öğretiliyor', ro: 'Oameni noi cărora li se propovăduiește', sv: 'Nya personer som undervisas', da: 'Nye personer, der undervises',
  ar: 'أشخاص جدد يتم تعليمهم',
};
for (const [code, term] of Object.entries(churchTerm)) assert.equal(catalogs[code]['indicator.friends'].toLocaleLowerCase(code), term.toLocaleLowerCase(code), code + ': the key indicator in the Church\'s words');

// ------------------------------------------------------------------ 2. pages
assert.deepEqual(missing(PAGES).map(r => `${r.file}:${r.line} ${r.text}`), [], 'every interface text is in the catalog');
for (const page of PAGES.filter(p => /^portal\/[^/]+\.html$/.test(p))) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');
  assert.match(html.slice(0, html.search(/<\/head>/i)), /<script src="i18n\.js(\?v=\d+)?"><\/script>/, page + ' loads i18n.js in <head>, without defer');
}
assert.match(fs.readFileSync(path.join(ROOT, 'roster-importer', 'page.py'), 'utf8'), /:8070\/i18n\.js/, 'DA Management loads i18n.js from the portal');
assert.match(fs.readFileSync(path.join(ROOT, 'slidev', 'manager', 'portal-bridge.js'), 'utf8'), /portal \+ '\/i18n\.js'/, 'Presentations load i18n.js from the portal');
assert.match(fs.readFileSync(path.join(ROOT, 'portal', 'nginx.conf'), 'utf8'), /location \^~ \/i18n\/ \{[^}]*Access-Control-Allow-Origin "\*"/, 'the catalogs may be read from :8090 and :3030');
// A date formatted for "en" ignores the chosen language (the calendar's date badge did): leave the locale out.
for (const page of PAGES.filter(p => /\.(html|m?js)$/.test(p) && fs.existsSync(path.join(ROOT, p)))) {
  const code = fs.readFileSync(path.join(ROOT, page), 'utf8');
  assert.doesNotMatch(code, /toLocale(Date|Time)String\(\s*["'`]en["'`]|DateTimeFormat\(\s*["'`]en["'`]/, page + ' formats a date in English whatever the language');
}
// The Overview's scripture excerpts (portal-api inspiration()) are catalog texts, so they show in the language.
const app = fs.readFileSync(path.join(ROOT, 'portal-api', 'app.py'), 'utf8');
for (const key of ['overview.almaText', 'overview.dcText']) assert.ok(app.includes(`'text':'${en[key]}'`), key + ' is the excerpt portal-api sends');

// ------------------------------------------------------------------ 3. i18n.js in a fake DOM
const nodes = [], notices = new Map();
function element(tagName, { protectedContent = false, attrs = {} } = {}) {
  const map = new Map(Object.entries(attrs));
  return {
    tagName, nodeType: 1, children: [], childNodes: [], dataset: {}, style: {}, isConnected: true, textContent: '',
    closest: () => (protectedContent ? {} : null), matches: () => false, querySelectorAll: () => [],
    hasAttribute: key => map.has(key), getAttribute: key => map.get(key) ?? null, setAttribute: (key, value) => map.set(key, String(value)),
    setAttributeNS() {}, set value(value) { map.set('value', String(value)); }, get value() { return map.get('value') ?? ''; },
    get type() { return map.get('type') || ''; }, get name() { return map.get('name') || ''; },
    remove() { notices.delete(this.id); }, append() {}, prepend() {},
  };
}
function text(value, tagName = 'SPAN', protectedContent = false) {
  const node = { nodeType: 3, nodeValue: value, english: value, parentElement: element(tagName, { protectedContent }), isConnected: true };
  nodes.push(node); return node;
}
const church = path => element('A', { attrs: { href: 'https://www.churchofjesuschrist.org' + path } });
const alma = church('/study/scriptures/bofm/alma/37?lang=eng&id=p6');
const pmg = church('/study/manual/preach-my-gospel-2023/16-chapter-8?lang=eng');
const dc = church('/study/scriptures/dc-testament/dc/64?lang=eng&id=p33');
const button = element('BUTTON', { attrs: { title: 'Previous week', 'aria-label': 'Previous week' } });
const label = text('New event');
const planStatus = text('Week ending Sunday, September 27 · Locked');
const several = text('3 questions to answer');
const one = text('1 question to answer');
const written = text('New event', 'P', true);
const role = text('OFFICE', 'OPTION');
const welcome = text('Welcome, Sample Missionary');
const person = text('Lena');
// Presentations library texts with values, and a DA Management piece added after another sentence.
const updated = text('Updated 5 min ago');
const deleteQuestion = text('Delete “Zone conference”?');
const deckCount = text('3 presentations');
const afterSentence = text('Section saved. Area: moves to Frankfurt 1 on 2026-10-05');
const plainEnglish = text('Tom and Jerry are teaching on Saturday');  // not interface text: "{a} and {b}" must not fit
const joinedLabels = text('Baptized 30 Aug 2026 · Confirmed 6 Sep 2026 · Found through Member/Member');
// A translation that is another key's English: Italian "Zone" (Zones) is English "Zone"; Persian and Arabic "←" (→) is
// English "←". Each page text is still read as the English it is.
const zones = text('Zones'), zone = text('Zone'), forward = text('→'), back = text('←');
// An element with its own key (data-i18n) takes its text from the key.
const keyed = text('←');
Object.assign(keyed.parentElement, { matches: selector => selector === '[data-i18n]', dataset: { i18n: 'common.arrowBack' } });
keyed.parentElement.setAttribute('data-i18n', 'common.arrowBack');
// DA Management's role plan ("What saving will change", and the save confirmation built from it), as management.py
// writes it: leader phrases per scope, capitals at the start, dates as "04 Oct 2026" (tests/test_management.py).
const ROLE_PLAN = [
  'The current AP assignment for the whole mission already ends on 04 Oct 2026.',
  'The current ZL assignment for North zone stays as it is.',
  'The current AP assignment for the whole mission stays as it is and ends on 04 Oct 2026.',
  'The AP assignment for the whole mission (starts 01 Jan 2099) stays as it is.',
  'Changing the role ends the current ZL assignment for North zone on 04 Oct 2026.',
  'Moving to Riverside North ends the current DL assignment for Riverside district on 04 Oct 2026.',
  'A new DL assignment for Riverside district starts on 05 Oct 2026.',
  'The effective date must be after 01 Jan 2000, when the current ZL assignment for North zone started.',
  'The effective date must be after 01 Jan 2099, when the AP assignment for the whole mission starts.',
  'Removes the ZL assignment for North zone that starts on 05 Oct 2026.',
  'The ZL assignment for North zone no longer ends on 04 Oct 2026.',
  // DA Management access (round 8: whole sentences, the English "lose"/"get" no longer goes into a placeholder).
  'They lose DA Management access now.',
  'They get DA Management access from 04 Oct 2026.',
  // The "Current role" line of the account page.
  'ZL, from the ZL assignment for North zone since 01 Jan 2000, ending 04 Oct 2026. Starting later: AP assignment for the whole mission from 01 Jan 2099. Recorded account role: ZL',
];
const ENGLISH_LEFT = /\b(assignment|current|stays|already|ends?|starts?|since|ending|whole|effective|changing|moving|removes|longer|later|recorded|lose|get)\b|\d\d (Jan|Oct) \d{4}/i;

// A fresh page (document and window) for each load, with the page's English text again, as after a reload.
function load({ search = '', stored = null, cookie = '' } = {}) {
  for (const node of nodes) node.nodeValue = node.english;
  const env = { stored, cookie, dialogs: [], listeners: new Map() };
  const html = { lang: 'en', dir: 'ltr', dataset: {} };
  const body = {
    nodeType: 1, isConnected: true, matches: () => false, prepend: el => notices.set(el.id, el),
    querySelectorAll: selector => (/churchofjesuschrist/.test(selector) ? [alma, pmg, dc] : /placeholder/.test(selector) ? [button] : []),
  };
  const document = {
    body, head: { append() {} }, documentElement: html, readyState: 'complete', currentScript: { src: 'http://localhost:8070/i18n.js' },
    get cookie() { return env.cookie; }, set cookie(value) { env.cookie = value.split(';')[0]; },
    querySelector: () => null, getElementById: id => notices.get(id) || null, createElement: tag => element(tag.toUpperCase()), addEventListener() {},
    createTreeWalker: (_root, _type, filter) => {
      let index = -1;
      return { currentNode: null, nextNode() {
        while (++index < nodes.length) if (filter.acceptNode(nodes[index]) === 1) { this.currentNode = nodes[index]; return true; }
        return false;
      } };
    },
  };
  const parent = {};
  const window = {
    parent, addEventListener: (name, handler) => env.listeners.set(name, handler), dispatchEvent() {},
    alert: m => env.dialogs.push(m), confirm: m => { env.dialogs.push(m); return true; }, prompt: m => { env.dialogs.push(m); return ''; },
  };
  const context = vm.createContext({
    window, document, console, URL, URLSearchParams,
    location: { href: 'http://localhost:8090/accounts' + search, origin: 'http://localhost:8090', hostname: 'localhost', search },
    sessionStorage: { getItem: () => env.stored, setItem: (k, v) => { env.stored = v; } },
    Node: { TEXT_NODE: 3, ELEMENT_NODE: 1 }, NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    MutationObserver: class { observe() {} }, requestAnimationFrame: action => action(),
    fetch: async url => {
      const code = String(url).match(/i18n\/([a-z]+)\.json$/)?.[1];
      return catalogs[code] ? { ok: true, json: async () => catalogs[code] } : { ok: false, json: async () => ({}) };
    },
  });
  vm.runInContext(source, context);
  env.api = window.MissionI18n; env.html = html; env.window = window; env.parent = parent; env.context = context;
  return env.api.ready.then(() => env);
}
const expected = (code, key) => catalogs[code][key];

(async () => {
  // The portal's choice for this tab: German.
  let page = await load({ stored: 'de' });
  let api = page.api;
  assert.equal(api.state.locale, 'de');
  assert.equal(label.nodeValue, expected('de', 'calendar.new'));
  assert.equal(button.getAttribute('title'), expected('de', 'callins.previousWeek'));
  assert.equal(page.cookie, 'gfm_lang=de', 'shared with DA Management and Presentations (cookie)');
  assert.match(alma.getAttribute('href'), /lang=deu/);
  // Every language.
  for (const code of CODES) {
    await api.setLanguage(code, { wait: true });
    assert.equal(label.nodeValue, expected(code, 'calendar.new'), code + ': a label');
    assert.equal(page.html.dir, code === 'fa' || code === 'ar' ? 'rtl' : 'ltr', code + ': direction');
    assert.equal(page.html.lang, code, code + ': lang');
    assert.equal(planStatus.nodeValue, expected(code, 'planning.weekEnding').replace('{date}', 'Sunday, September 27').replace('{status}', expected(code, 'common.locked')), code + ': values in a text, the status translated too');
    const rules = new Intl.PluralRules(code), forms = expected(code, 'planning.questionsToAnswer');
    for (const [node, n] of [[several, 3], [one, 1]]) assert.equal(node.nodeValue, (forms[rules.select(n)] || forms.other).replace('{count}', n), code + ': plural for ' + n);
    assert.equal(written.nodeValue, 'New event', code + ': written content stays');
    assert.equal(role.parentElement.value, 'OFFICE', code + ': an option keeps its value');
    assert.ok(welcome.nodeValue.includes('Sample Missionary'), code + ': a name stays');
    assert.equal(person.nodeValue, 'Lena');
    const code3 = manifest.languages[code].church;
    assert.match(alma.getAttribute('href'), new RegExp('[?&]lang=' + code3 + '(&|$)'), code + ': Book of Mormon link lang=' + code3);
    assert.match(pmg.getAttribute('href'), new RegExp('[?&]lang=' + (code3 === 'pes' ? 'eng' : code3) + '(&|$)'), code + ': Preach My Gospel link');
    assert.match(dc.getAttribute('href'), new RegExp('[?&]lang=' + (code3 === 'ara' ? 'eng' : code3) + '(&|$)'), code + ': Doctrine and Covenants link');
    page.dialogs.length = 0; page.window.confirm('Discard this text? It cannot be brought back.');
    assert.equal(page.dialogs[0], expected(code, 'callins.discardConfirm'), code + ': confirm() in the language');
    // One change per line, as DA Management's account page asks before saving: the lines stay lines.
    page.dialogs.length = 0; page.window.confirm('Discard this text? It cannot be brought back.\nNew event\n\nSave these changes?');
    assert.equal(page.dialogs[0], [expected(code, 'callins.discardConfirm'), expected(code, 'calendar.new'), '', expected(code, 'dam.saveTheseChanges')].join('\n'), code + ': confirm() keeps its lines');
    assert.equal(zones.nodeValue, expected(code, 'common.zones'), code + ': Zones');
    assert.equal(zone.nodeValue, expected(code, 'overview.zone'), code + ': Zone, also where the translation of Zones is "Zone"');
    assert.equal(forward.nodeValue, expected(code, 'common.arrowForward'), code + ': →');
    assert.equal(back.nodeValue, expected(code, 'common.arrowBack'), code + ': ←, also after → became ← (right to left)');
    assert.equal(keyed.parentElement.textContent, expected(code, 'common.arrowBack'), code + ': data-i18n');
    // Latin digits and the Gregorian calendar in Persian and Arabic, also where a chart names the locale itself.
    const digits = vm.runInContext("[(21).toLocaleString('fa'), new Intl.NumberFormat('ar-EG').format(1234), new Date(Date.UTC(2026, 9, 4, 12)).toLocaleDateString('fa', { year: 'numeric', timeZone: 'UTC' })].join('|')", page.context);
    assert.match(digits, /^21\|1.?234\|2026/, code + ': Latin digits and the Gregorian year with a named fa/ar locale: ' + digits);
    // DA Management's role plan, word for word in the language, dates too.
    for (const line of ROLE_PLAN) {
      const done = api.translate(line);
      if (code === 'en') { assert.equal(done, line); continue; }
      assert.doesNotMatch(done, ENGLISH_LEFT, `${code}: "${line}" → "${done}"`);
      assert.ok(!/North|Riverside/.test(line) || /North|Riverside/.test(done), code + ': names stay: ' + done);
      assert.ok(!/^\p{Ll}/u.test(done), code + ': a sentence starts with a capital: ' + done);
    }
  }
  // German, word for word (the capital comes back where the English phrase opened the sentence).
  await api.setLanguage('de', { wait: true });
  const de = (y, m, d) => new Intl.DateTimeFormat('de', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m, d, 12));
  assert.equal(api.translate(ROLE_PLAN[0]), `Die aktuelle AP-Zuteilung für die ganze Mission endet bereits am ${de(2026, 9, 4)}.`);
  assert.equal(api.translate(ROLE_PLAN[4]), `Durch die Änderung der Rolle endet die aktuelle ZL-Zuteilung für die Zone North am ${de(2026, 9, 4)}.`);
  assert.equal(api.translate('They lose DA Management access now.'), 'Die Person verliert ab sofort den Zugriff auf die DA-Verwaltung.');
  assert.equal(api.translate('They get DA Management access from 04 Oct 2026.'), `Die Person bekommt ab ${de(2026, 9, 4)} Zugriff auf die DA-Verwaltung.`);
  assert.equal(api.translate('20 Sep 2026 14:15'), new Intl.DateTimeFormat('de', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC' }).format(Date.UTC(2026, 8, 20, 14, 15)), 'a date and time on its own (Import history)');
  await api.setLanguage('de-CH', { wait: true }); assert.equal(api.state.locale, 'de');
  assert.equal(updated.nodeValue, expected('de', 'pres.updatedMinAgo').replace('{n}', '5'));
  assert.equal(deleteQuestion.nodeValue, expected('de', 'pres.deleteNamed').replace('{name}', 'Zone conference'), 'the deck name stays');
  assert.equal(deckCount.nodeValue, expected('de', 'pres.countPresentations').other.replace('{count}', '3'));
  assert.equal(afterSentence.nodeValue, expected('de', 'dam.sectionSaved') + ' ' + expected('de', 'dam.areaMovesToOn').replace(/^\. /, '').replace('{a}', 'Frankfurt 1').replace('{b}', '2026-10-05'),
    'a catalog piece that starts with ". " also matches as a sentence of its own');
  assert.equal(plainEnglish.nodeValue, 'Tom and Jerry are teaching on Saturday', 'a template without a fixed start or end needs catalog parts');
  const deDate = (m, d) => new Intl.DateTimeFormat('de', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(2026, m, d, 12));
  assert.equal(joinedLabels.nodeValue, [expected('de', 'planning.baptizedOn').replace('{date}', deDate(7, 30)),
    expected('de', 'planning.confirmedOn').replace('{date}', deDate(8, 6)),
    expected('de', 'planning.foundThrough').replace('{source}', expected('de', 'api.srcMember'))].join(' · '),
    'labels joined with " · " are translated one by one (a value never runs over " · ")');
  // A date the page wrote in the language may hold ". " itself, which is not the end of a sentence (Weekly Planning's
  // "Week ending Sonntag, 27. September"); "… 2026. Starting later: …" in the role plan above still is one.
  const weekEnding = (code, date) => expected(code, 'planning.weekEnding').replace('{date}', date).replace('{status}', expected(code, 'overview.needsSubmission'));
  assert.equal(api.translate('Week ending Sonntag, 27. September · Not submitted yet'), weekEnding('de', 'Sonntag, 27. September'), 'a German date with "27. "');
  await api.setLanguage('da', { wait: true });
  assert.equal(api.translate('Week ending søndag den 27. september · Not submitted yet'), weekEnding('da', 'søndag den 27. september'), 'a Danish date with "27. "');
  await api.setLanguage('ja', { wait: true }); assert.equal(api.state.fallback, true); assert.equal(page.html.lang, 'en');
  assert.ok(notices.get('mission-i18n-fallback').textContent.includes('Japanese'), 'the English fallback says so');
  await api.setLanguage('en', { wait: true }); assert.equal(notices.size, 0); assert.equal(label.nodeValue, 'New event');

  // ?lang= wins, also with the Church's code (pes = Persian); it is remembered for the tab and the host.
  page = await load({ search: '?lang=pes', stored: 'de' });
  assert.equal(page.api.state.locale, 'fa'); assert.equal(page.api.addressLanguage, 'fa'); assert.equal(page.html.dir, 'rtl');
  assert.equal(page.stored, 'fa'); assert.equal(page.cookie, 'gfm_lang=fa');
  assert.equal(label.nodeValue, expected('fa', 'calendar.new'));
  // DA Management or Presentations on another port: the cookie, then the shell's message.
  page = await load({ cookie: 'gfm_lang=ar' });
  assert.equal(page.api.state.locale, 'ar'); assert.equal(page.html.dir, 'rtl');
  page.listeners.get('message')({ source: page.parent, origin: 'http://localhost:8070', data: { type: 'mission-language', language: 'sv' } });
  await page.api.setLanguage('sv', { wait: true });
  assert.equal(page.api.state.locale, 'sv'); assert.equal(label.nodeValue, expected('sv', 'calendar.new'));
  page.listeners.get('message')({ source: page.parent, origin: 'http://evil.example', data: { type: 'mission-language', language: 'de' } });
  assert.equal(page.api.state.locale, 'sv', 'another host cannot change the language');

  // Text a page shows while a new language's catalog is still on its way (the shell's reminder notice: signing in
  // switches the portal to the person's language) is shown in that language once the catalog arrives, not left in
  // English (round 9).
  page = await load({ stored: 'en' });
  const switching = page.api.setLanguage('it', { wait: true });
  const lateNotice = text(en['reminders.off']);
  page.api.apply(lateNotice);
  await switching;
  assert.equal(lateNotice.nodeValue, expected('it', 'reminders.off'), 'text shown while the catalog was loading is translated when it arrives');

  console.log(JSON.stringify({ languages: CODES.length, keys: keys.length, pages: PAGES.filter(p => fs.existsSync(path.join(ROOT, p))).length, textOutsideCatalog: 0, switching: 'passed',
    rtl: 'passed', plurals: 'passed', churchLinks: 'passed', address: 'passed', cookie: 'passed', writtenContent: 'preserved', fallback: 'passed',
    dialogLines: 'kept', otherKeysEnglish: 'passed', latinDigits: 'passed', dates: 'passed', rolePlanLines: ROLE_PLAN.length }));
})().catch(error => { console.error(error); process.exitCode = 1; });
