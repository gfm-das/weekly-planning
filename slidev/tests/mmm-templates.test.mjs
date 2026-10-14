// The presentation templates: MMM MAIN, MMM Media, MMM Breakout rooms, ZOKO (zone conference) and Stake coordination,
// and the pieces they are made of (gfm-addon Mmm*.vue).
//
// 1. The words: every text in all 14 languages (templates/texts.mjs).
// 2. The slides each template writes: structure, language, direction, speaker notes, no HTML that breaks Markdown.
// 3. The live numbers: every query in a template is a valid chart query that is written in the slide as plain JSON
//    ("pinned", so the leaders who open the deck see it), asks only for numbers portal-api knows and nothing it should not.
// 4. Hand-typed places: marked `placeholder` (a Manual tag), and the template holds no real names.
// 5. The pieces: single root, a studio description, the data pieces use the shared query reader.
// 6. The showcase decks are exactly what the templates write.
// 7. The library dialog and the manager's routes; createDeck with the real manager and stand-ins.
// Plain Node: no Slidev, no browser. The look is checked by hand against the PDFs (docs/handoff/round13/presentations.md).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { normalizeSpec, pinnedKeys, querySpecs } from '../manager/gfm-addon/lib/chart-spec.mjs';
import { buildTemplate, isTemplate, LANGUAGE_INFO, LANGUAGES, pickLanguage, TEMPLATE_IDS, templateList } from '../manager/templates/index.mjs';
import { text, TEXT_KEYS, TEXT_ROWS } from '../manager/templates/texts.mjs';
import { showcaseDeck, SHOWCASE_DATE } from '../tools/make-mmm-showcase.mjs';
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(HERE, '..', '..');
const read = (...parts) => fs.readFileSync(path.join(REPO, ...parts), 'utf8').replace(/\r\n/g, '\n'); // a Windows checkout has CRLF
const TEMPLATES = TEMPLATE_IDS.filter(id => id !== 'blank');
const SLIDE_COUNT = { 'mmm-main': 7, 'mmm-media': 4, 'mmm-breakout': 6, zoko: 8, stake: 9 };
const NOW = new Date(2026, 9, 12);
const make = (id, lang = 'en') => buildTemplate(id, { title: 'My deck', lang, now: NOW });

// ---- 1. The words ----

test('the languages are the 14 of the portal, in the order of the text rows', () => {
  assert.equal(LANGUAGES.length, 14);
  const catalogs = JSON.parse(read('portal', 'i18n', 'catalogs.json')).languages;
  assert.deepEqual([...LANGUAGES].sort(), Object.keys(catalogs).sort());
  for (const code of LANGUAGES) assert.equal(LANGUAGE_INFO[code].dir, catalogs[code].dir, `${code}: the same direction as the portal`);
  for (const code of LANGUAGES) assert.equal(LANGUAGE_INFO[code].name, catalogs[code].name, `${code}: the same name as the portal`);
});

test('every template text has all 14 languages, none empty, and a language that is not English says something else', () => {
  for (const key of TEXT_KEYS) {
    const row = TEXT_ROWS[key];
    assert.equal(row.length, 14, `${key} has ${row.length} texts`);
    row.forEach((value, i) => assert.ok(typeof value === 'string' && value.trim().length > 0, `${key} in ${LANGUAGES[i]} is empty`));
  }
  // A text that is the same in all 14 languages was probably not translated (names and numbers excepted).
  const same = TEXT_KEYS.filter(key => new Set(TEXT_ROWS[key]).size === 1);
  assert.deepEqual(same, [], `not translated: ${same.join(', ')}`);
  // Few texts may stay English in a language (a word that is the same in it); a whole language in English would be a bug.
  for (const [i, code] of LANGUAGES.entries()) {
    if (code === 'en') continue;
    const english = TEXT_KEYS.filter(key => TEXT_ROWS[key][i] === TEXT_ROWS[key][0]);
    assert.ok(english.length <= 12, `${code}: ${english.length} texts are still English (${english.join(', ')})`);
  }
});

test('text(): the language, English for an unknown one, an error for an unknown key', () => {
  assert.equal(text('de', 'goal'), 'Ziel');
  assert.equal(text('xx', 'goal'), 'Goal');
  assert.equal(text('ar', 'goal'), 'الهدف');
  assert.throws(() => text('en', 'nope'), /No template text/);
});

test('placeholders and sentences keep what a slide needs: no markup in a text, no straight apostrophe', () => {
  for (const key of TEXT_KEYS) for (const value of TEXT_ROWS[key]) {
    assert.doesNotMatch(value, /[<>{}]|--/, `${key}: "${value}" would break a slide`);
    assert.doesNotMatch(value, /'/, `${key}: "${value}" has a straight apostrophe (it is written inside a quoted attribute)`);
  }
});

// ---- 2. The slides ----

test('the list: the blank presentation and five templates, in this order', () => {
  assert.deepEqual(TEMPLATE_IDS, ['blank', 'mmm-main', 'mmm-media', 'mmm-breakout', 'zoko', 'stake']);
  assert.equal(isTemplate('zoko'), true);
  assert.equal(isTemplate('v2-deck'), false);
  assert.throws(() => buildTemplate('nope', { title: 'x' }), /Choose one of the presentation templates/);
});

test('blank: exactly the deck "+ New Presentation" always made', () => {
  assert.equal(buildTemplate('blank', { title: 'Zone conference', heading: 'Zone conference' }), '---\ntheme: default\n---\n\n# Zone conference\n\n---\n\n# New Slide\n\nStart building your presentation.\n');
});

for (const id of TEMPLATES) {
  test(`${id}: ${SLIDE_COUNT[id]} slides, each on the free layout, settings first, in English`, () => {
    const md = make(id);
    assert.match(md, /^---\ntheme: default\ntitle: "My deck"\ncolorSchema: light\nfonts:\n {2}provider: none\n {2}sans: Montserrat\nhtmlAttrs:\n {2}lang: en\n {2}dir: ltr\nlayout: gfm-freeform\n---\n\n</);
    // The headmatter closes the first slide's settings: count the slides by their layout lines.
    assert.equal((md.match(/^layout: gfm-freeform$/gm) || []).length, SLIDE_COUNT[id]);
    assert.equal((md.match(/^---$/gm) || []).length, SLIDE_COUNT[id] * 2, 'two --- lines for each slide');
  });

  test(`${id}: every slide is one block of components (no blank line inside, nothing indented) so Markdown leaves it alone`, () => {
    const md = make(id);
    // Cut the notes out, then split into slides; inside a slide's content there is no empty line.
    const body = md.replace(/<!--[\s\S]*?-->/g, '');
    const slides = body.split(/^layout: gfm-freeform\n---\n/m).slice(1);
    assert.equal(slides.length, SLIDE_COUNT[id]);
    for (const slide of slides) {
      const content = slide.replace(/\n---\n?$/, '').trim();
      assert.doesNotMatch(content, /\n\s*\n/, 'a blank line would end the HTML block');
      assert.doesNotMatch(content, /^ {4}/m, 'four spaces would make a code block');
      assert.match(content, /^<Mmm(Frame|Cover)\b/, 'a slide starts with its frame or cover');
    }
  });

  test(`${id}: speaker notes on the slides that need them (presenter view)`, () => {
    const notes = make(id).match(/<!--\n[\s\S]*?\n-->/g) || [];
    assert.ok(notes.length >= 1, 'at least one note');
    for (const note of notes) assert.doesNotMatch(note.slice(4, -3), /-->/);
  });
}

for (const id of TEMPLATES) for (const lang of LANGUAGES) {
  test(`${id} in ${lang}: written in that language with its direction`, () => {
    const md = make(id, lang);
    const tag = lang === 'fa' || lang === 'ar' ? `${lang}-u-nu-latn` : lang;
    assert.match(md, new RegExp(`htmlAttrs:\\n {2}lang: ${tag}\\n {2}dir: ${LANGUAGE_INFO[lang].dir}\\n`));
    if (lang !== 'en') {
      // The footer line of the reference presentations is in the language.
      if (id !== 'stake') assert.ok(md.includes(`footer-lead="${text(lang, 'footerLead')}"`), 'the footer');
      assert.ok(md.includes(text(lang, 'noteLive')) || md.includes(text(lang, 'noteMedia')) || md.includes(text(lang, 'noteBreakout')) || md.includes(text(lang, 'noteManual')), 'a speaker note');
    }
    // No English heading is left on a slide of another language.
    if (lang !== 'en' && !['ru', 'uk', 'fa', 'ar'].includes(lang) && id === 'mmm-main') assert.ok(!md.includes('heading="Key Indicators of Conversion"'));
  });
}

test('a language that is not one of the 14 gives English; a region is cut off', () => {
  assert.equal(pickLanguage('xx'), 'en');
  assert.equal(pickLanguage(''), 'en');
  assert.equal(pickLanguage('de-AT'), 'de');
  assert.equal(pickLanguage('PT_br'), 'pt');
  assert.equal(make('stake', 'xx'), make('stake', 'en'));
});

test('the title is written as a quoted line, whatever it holds', () => {
  const md = buildTemplate('mmm-main', { title: 'Zone "A": news', lang: 'en', now: NOW });
  assert.match(md, /^title: "Zone \\"A\\": news"$/m);
});

test('MMM MAIN follows the 7 pages of the reference presentation, in order', () => {
  const md = make('mmm-main');
  const order = ['<MmmCover', 'heading="Key Indicators of Conversion"', 'heading="Baptismal Goal"', 'heading="Coming This Week"', 'heading="Member Present"', 'heading="New Member Activity"', 'heading="1st Time Temple Attendance"'];
  let at = -1;
  for (const marker of order) {
    const next = md.indexOf(marker);
    assert.ok(next > at, `${marker} comes after the one before it`);
    at = next;
  }
});

test('ZOKO follows the 8 pages of the zone presentation, in order', () => {
  const md = make('zoko');
  const order = ['<MmmCover', 'heading="Key Indicators of Conversion"', 'heading="Referral Rates"', 'heading="Baptismal Goal"', 'heading="Coming This Week"', 'heading="On Date"', 'heading="Member Present"', 'heading="New Member Activity"'];
  let at = -1;
  for (const marker of order) {
    const next = md.indexOf(marker);
    assert.ok(next > at, `${marker} comes after the one before it`);
    at = next;
  }
});

test('Media has slots for videos and pictures; Breakout rooms has one section for each of four rooms', () => {
  const media = make('mmm-media');
  assert.equal((media.match(/<MmmSlot [^>]*kind="video"/g) || []).length, 3);
  assert.equal((media.match(/<MmmSlot [^>]*kind="image"/g) || []).length, 3);
  const rooms = make('mmm-breakout');
  for (const n of [1, 2, 3, 4]) assert.ok(rooms.includes(`heading="Room ${n}"`), `room ${n}`);
  // The topics are typed on the slides (nothing is fixed): each room asks for it, and the overview lists them.
  assert.equal((rooms.match(/Topic: Type the topic here/g) || []).length, 4);
  assert.match(rooms, /headers="Room\|Topic\|Leader"/);
  assert.match(rooms, /headers="Notes\|Action items\|Report back"/);
});

// ---- 3. The live numbers ----

// The measures portal-api's charts.py knows: the nine key numbers and plan counts, the people counts.
function knownMeasures() {
  const py = read('portal-api', 'charts.py');
  const known = new Set();
  const kpis = py.match(/^KPIS = \(([\s\S]*?)^\)/m)[1];
  for (const m of kpis.matchAll(/\('(\w+)', '[^']*', '\w+', \(([^)]*)\)\)/g)) for (const f of m[2].matchAll(/'(\w+)'/g)) known.add(`${m[1]}.${f[1]}`);
  const people = py.match(/^PEOPLE = \(([\s\S]*?)^\)/m)[1];
  for (const group of people.matchAll(/\('(\w+)', '[^']*', \(([\s\S]*?)\n {4}\)\)/g)) for (const f of group[2].matchAll(/\('(\w+)', '\w+',/g)) known.add(`${group[1]}.${f[1]}`);
  return known;
}

test('the measures asked for are the ones portal-api knows (charts.py), and the list is not empty', () => {
  const known = knownMeasures();
  for (const must of ['friends_found.actual', 'friends_found.previous_goal', 'new_members.total', 'new_members.at_church', 'first_time_sacrament.actual', 'follow_up_lessons.goal']) assert.ok(known.has(must), `${must} is in charts.py`);
  for (const id of TEMPLATES) for (const raw of querySpecs(make(id))) for (const m of normalizeSpec(raw).measures) assert.ok(known.has(m), `${id}: ${m} is not a measure of portal-api`);
});

for (const id of TEMPLATES) {
  test(`${id}: every query is a valid chart query written as plain JSON, so a leader who opens the deck sees it`, () => {
    for (const lang of ['en', 'de', 'ar']) {
      const md = make(id, lang);
      const specs = querySpecs(md);
      const attributes = (md.match(/:query='/g) || []).length;
      assert.equal(specs.length, attributes, 'every :query reads back as JSON');
      for (const raw of specs) assert.doesNotThrow(() => normalizeSpec(raw));
      assert.equal(pinnedKeys(md).size > 0, id !== 'mmm-media' && id !== 'mmm-breakout', 'media and breakout rooms hold no numbers; the others do');
    }
  });
}

test('the numbers are the last finished weeks (never the week still being reported), at most 104 weeks, counts by place never by name', () => {
  for (const id of TEMPLATES) for (const raw of querySpecs(make(id))) {
    const spec = normalizeSpec(raw);
    assert.equal(spec.includeCurrent, false, `${id}: a finished week`);
    assert.ok(spec.weeks.last >= 1 && spec.weeks.last <= 104);
    assert.ok(['mission', 'zone', 'area'].includes(spec.level));
  }
});

test('MMM MAIN holds the six key indicators of conversion, ZOKO the same for the zone that owns the deck', () => {
  const six = ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament'];
  for (const id of ['mmm-main', 'zoko']) {
    const used = new Set(querySpecs(make(id)).flatMap(raw => normalizeSpec(raw).measures.map(m => m.split('.')[0])));
    for (const k of six) assert.ok(used.has(k), `${id} shows ${k}`);
  }
});

test('ZOKO is zone-scoped: it never names a zone or a district, it has no zone filter, so the portal decides by the deck owner', () => {
  const md = make('zoko');
  for (const raw of querySpecs(md)) {
    const spec = normalizeSpec(raw);
    assert.deepEqual(spec.filter, {}, 'no zone or district is written into the deck');
    assert.notEqual(spec.level, 'zone', 'a zone deck never lists other zones');
  }
  // It lists the zone's own areas (companionships) and says "Zone name", not a real zone.
  assert.ok(querySpecs(md).some(raw => normalizeSpec(raw).level === 'area'));
  assert.ok(md.includes('line-1="Zone name"'));
});

test('MMM MAIN lists the zones; Stake coordination lists the areas of the whole mission until a stake filter is set', () => {
  assert.ok(querySpecs(make('mmm-main')).some(raw => normalizeSpec(raw).level === 'zone'));
  assert.ok(querySpecs(make('stake')).some(raw => normalizeSpec(raw).level === 'area'));
});

test('the year-to-date chart counts the weeks since 1 January, running total, and follows the date it is made on', () => {
  const spec = date => querySpecs(buildTemplate('mmm-main', { title: 'x', now: date })).map(normalizeSpec).find(s => s.transform === 'cumulative');
  assert.equal(spec(new Date(2026, 9, 12)).weeks.last, 42);
  assert.equal(spec(new Date(2026, 2, 2)).weeks.last, 10);
  assert.equal(spec(new Date(2026, 9, 12)).measures[0], 'baptisms_confirmations.actual');
});

// ---- 4. Hand-typed places ----

test('what the portal does not hold is typed by hand and says so: placeholders on the pieces that need them', () => {
  const main = make('mmm-main');
  for (const heading of ['Coming This Week', '1st Time Temple Attendance']) {
    const slide = main.split(/^layout: gfm-freeform$/m).find(s => s.includes(`heading="${heading}"`));
    assert.match(slide, / placeholder\b/, `${heading} is typed by hand`);
  }
  // The % Active gauge and the goals typed in the slide.
  assert.match(main, /<MmmGauge [^>]*title="% Active"[^>]*mode="manual"[^>]*placeholder/);
  assert.match(main, /<MmmCard [^>]*title="This Quarter"[^>]*placeholder/);
  // ZOKO: the referral rates and the mission's quarter.
  const zoko = make('zoko');
  assert.match(zoko, /<MmmGauge [^>]*title="Contact Rate"[^>]*placeholder/);
  assert.match(zoko, /<MmmGauge [^>]*title="Teaching Rate"[^>]*placeholder/);
  assert.match(zoko, /<MmmSlot [^>]*kind="image"[^>]*empty="Paste the referral trend picture here"/);
  // Stake: dinner appointments, youth activities, mini missions, and the new members' notes.
  const stake = make('stake');
  assert.equal((stake.match(/<MmmCard [^>]*mode="manual"[^>]*placeholder/g) || []).length, 3);
  assert.match(stake, /<MmmManual [^>]*headers="Month\|Name\|Stake\|How are they doing\?\|Discussed in Gemiko\?\|How will you support them\?"[^>]*placeholder/);
});

test('no person is in a template: manual rows hold only the words "Type here" and the like, the numbers are all queries or empty', () => {
  for (const id of TEMPLATES) for (const lang of LANGUAGES) {
    const md = make(id, lang);
    const rows = [...md.matchAll(/<MmmManual [^>]*rows="([^"]*)"/g)].map(m => m[1]);
    const hints = new Set([text(lang, 'typeHere'), `${text(lang, 'room')} 1`, `${text(lang, 'room')} 2`, `${text(lang, 'room')} 3`, `${text(lang, 'room')} 4`, text(lang, 'topicHere'), text(lang, 'stake')]);
    for (const row of rows) for (const line of row.split(';')) for (const cell of line.split('|')) {
      if (!cell) continue;
      assert.ok(hints.has(cell.replaceAll('&amp;', '&')), `${id}/${lang}: "${cell}" is not a placeholder word`);
    }
    // Typed numbers: every card, gauge and pair that is typed has an empty value.
    for (const tag of md.match(/<Mmm(?:Card|Gauge|Pair) [^>]*mode="manual"[^>]*\/>/g) || []) assert.doesNotMatch(tag, /\bvalue="[^"]/, 'a typed value starts empty');
    assert.doesNotMatch(md, /\b(?:value|actual)="\d/, 'no invented numbers');
  }
});

// ---- 5. The pieces ----

const COMPONENTS = ['MmmFrame', 'MmmCover', 'MmmCard', 'MmmGauge', 'MmmTrend', 'MmmTable', 'MmmManual', 'MmmChips', 'MmmPair', 'MmmSlot'];
const addon = (...parts) => read('slidev', 'manager', 'gfm-addon', ...parts);

function rootCount(code) {
  const template = code.match(/<template>([\s\S]*?)<\/template>\s*(?:<script|<style|<studio|$)/)?.[1] ?? '';
  let depth = 0, roots = 0;
  for (const [, closing, , attrs, selfClose] of template.replace(/<!--[\s\S]*?-->/g, '').matchAll(/<(\/?)([A-Za-z][\w.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g)) {
    if (closing) { depth--; continue; }
    if (depth === 0 && !/\sv-else/.test(attrs)) roots++;
    if (!selfClose) depth++;
  }
  return roots;
}

test('the pieces exist, and every component used in a template is one of them', () => {
  const files = fs.readdirSync(path.join(REPO, 'slidev', 'manager', 'gfm-addon', 'components')).filter(f => /^Mmm.*\.vue$/.test(f)).map(f => f.replace('.vue', ''));
  assert.deepEqual(files.sort(), [...COMPONENTS].sort());
  for (const id of TEMPLATES) for (const m of make(id).matchAll(/<(Mmm\w+)\b/g)) assert.ok(COMPONENTS.includes(m[1]), `${id}: <${m[1]}>`);
});

for (const name of COMPONENTS) {
  test(`${name}: one root, a studio description and category, a snippet that uses it`, () => {
    const code = addon('components', `${name}.vue`);
    assert.equal(rootCount(code), 1, 'one root element (Studio cannot annotate a component with several)');
    // Quoted: a colon in an unquoted description is a mistake in Studio's YAML (checked by hand against the yaml package).
    assert.match(code, /<studio>\n(?:#.*\n)*description: ".{20,}"\n/);
    assert.doesNotMatch(code.match(/<studio>\n([\s\S]*?)<\/studio>/)[1], /\n\n/, 'no blank line inside the studio block');
    assert.match(code, /category: GFM (content|data)/);
    assert.match(code, new RegExp(`snippet: [^\\n]*<${name}\\b|snippet: \\|-\\n\\s+<${name}\\b`));
  });
}

test('the data pieces read their numbers like <MissionChart :query>: through the shared reader, never their own request', () => {
  for (const name of ['MmmCard', 'MmmGauge', 'MmmTrend', 'MmmTable', 'MmmPair']) {
    const code = addon('components', `${name}.vue`);
    assert.match(code, /useMmmQuery\(\(\) => props\.query\)/, `${name} asks through useMmmQuery`);
    assert.doesNotMatch(code, /fetch\(/, `${name} makes no request of its own`);
  }
  const reader = addon('lib', 'mmm.ts');
  assert.match(reader, /fetchChartData\(deck, value, key\)/);
  assert.match(reader, /deckOfPath\(location\.pathname\)/, 'the deck of the page, so a zone deck shows only its zone');
  assert.match(reader, /canonicalJson\(value\)/);
});

test('the pieces draw on the frame\'s own scale and print as they look', () => {
  const frame = addon('components', 'MmmFrame.vue');
  assert.match(frame, /container-type: inline-size/);
  assert.match(frame, /--u: calc\(100cqw \/ 1152\)/, 'one unit is 1/1152 of the slide, like the reference pictures');
  assert.match(frame, /@media print \{ \.mmm-manual-tag \{ display: none; \} \}/, 'the Manual tag is not printed');
  // No piece draws with a canvas that the PDF exporter cannot print: gauges are SVG, charts ECharts SVG (useMissionChart).
  assert.match(addon('components', 'MmmGauge.vue'), /<svg\b/);
  assert.doesNotMatch(addon('components', 'MmmGauge.vue'), /<canvas/);
});

test('the Manual tag text and the labels are props, so the slide supplies them in its language', () => {
  for (const name of ['MmmCard', 'MmmGauge', 'MmmManual', 'MmmChips', 'MmmPair', 'MmmSlot', 'MmmCover']) assert.match(addon('components', `${name}.vue`), /tag\??: string/, `${name} has a tag prop`);
  assert.match(addon('components', 'MmmCard.vue'), /lastLabel\?: string[\s\S]*goalLabel\?: string[\s\S]*naText\?: string/);
  assert.match(addon('components', 'MmmFrame.vue'), /footerLead\?: string[\s\S]*footerFaith\?: string[\s\S]*footerHope\?: string[\s\S]*footerCharity\?: string[\s\S]*verse\?: string/);
});

test('the shared Gfm stylesheet and layouts are untouched by the pieces (they bring their own, mmm- prefixed)', () => {
  for (const name of COMPONENTS) {
    const css = (addon('components', `${name}.vue`).match(/<style>([\s\S]*?)<\/style>/) || [, ''])[1];
    for (const selector of css.match(/^[.#][\w-]+/gm) || []) assert.match(selector, /^\.(mmm-|mmm\b)/, `${name}: ${selector}`);
  }
});

// ---- 6. The showcase decks ----

for (const id of TEMPLATES) {
  test(`showcase deck ${id} is exactly what the template writes (run node slidev/tools/make-mmm-showcase.mjs after a change)`, () => {
    assert.equal(read('slidev', 'showcase', id, 'slides.md'), showcaseDeck(id));
  });
}

test('the showcase date is the one the test uses', () => {
  assert.equal(SHOWCASE_DATE.getFullYear() * 10000 + (SHOWCASE_DATE.getMonth() + 1) * 100 + SHOWCASE_DATE.getDate(), 20261012);
});

// ---- 7. The library dialog and the manager's routes ----

test('templateList: the names and descriptions in the person\'s language, the dialog\'s labels, the 14 languages under their own names', () => {
  const en = templateList('en');
  assert.deepEqual(en.templates.map(t => t.id), TEMPLATE_IDS);
  assert.deepEqual(en.templates.map(t => t.name), ['Blank presentation', 'MMM MAIN', 'MMM Media', 'MMM Breakout rooms', 'ZOKO zone conference', 'Stake coordination']);
  assert.deepEqual(en.languages.map(l => l.code), LANGUAGES);
  assert.equal(en.labels.language, 'Language of the slides');
  const de = templateList('de-DE');
  assert.equal(de.lang, 'de');
  assert.equal(de.labels.startFrom, 'Beginnen mit');
  assert.equal(de.templates[0].name, 'Leere Präsentation');
  assert.equal(templateList('ar').dir, 'rtl');
  assert.equal(templateList('klingon').lang, 'en');
  // The blank presentation has no language; the others do.
  assert.deepEqual(en.templates.map(t => t.language), [false, true, true, true, true, true]);
  for (const code of LANGUAGES) for (const t of templateList(code).templates) assert.ok(t.name && t.description, `${code}/${t.id}`);
});

test('library.html: the new presentation dialog asks for the template and the language and sends them', () => {
  const html = read('slidev', 'manager', 'library.html');
  for (const id of ['templateBox', 'templateSelect', 'templateNote', 'langRow', 'langSelect', 'templateLabel', 'langLabel', 'langNote']) assert.ok(html.includes(`id="${id}"`), id);
  assert.match(html, /\/api\/presentation-templates\?lang=/);
  assert.match(html, /JSON\.stringify\(\{ title, template, lang: byId\('langSelect'\)\.value \|\| 'en' \}\)/);
  assert.match(html, /prepareTemplates\(\)/);
  // Without the list (an older manager, a failed request) the dialog still makes a blank presentation.
  assert.match(html, /Without the list the dialog still makes a blank presentation/);
  // The dialog's words come from the manager (texts.mjs), so the page holds no English sentence of its own for them.
  assert.doesNotMatch(html, /Start from|Language of the slides/);
});

test('manager-routes.mjs: GET /api/presentation-templates (for creators), POST /api/presentations takes template and lang', () => {
  const routes = read('slidev', 'manager', 'manager-routes.mjs');
  assert.match(routes, /\['GET', \/\^\\\/api\\\/presentation-templates\$\/, listTemplates\]/);
  assert.match(routes, /async function listTemplates\(\{ res, url, context \}\) \{\n {2}await assertDeckCreator\(context\);/);
  assert.match(routes, /const \{ title, template, lang \} = await readBody\(req\);\n {2}const slug = await createDeck\(title, \{ template, lang \}\);/);
  const actions = read('slidev', 'manager', 'deck-actions.mjs');
  assert.match(actions, /export async function createDeck\(title, \{ template = 'blank', lang = 'en' \} = \{\}\)/);
  assert.match(actions, /if \(!isTemplate\(id\)\) throw notFound\(\);/);
});

// The real manager with stand-ins (tests/helpers/manager-harness.mjs). Needs a POSIX shell like the other tests that start
// the manager (the stand-in `slidev` is a shell script); started inside the test, so a failure here never hides the others.
const skip = process.platform === 'win32' ? 'needs a POSIX shell (run in node:24-alpine)' : false;

async function withManager(run) {
  const stub = await startStub((req, url, body) => {
    const supabase = supabaseAnswer(req, url);
    if (supabase) return supabase;
    if (url.pathname === '/internal/presentations/check') return [200, { role: 'AP', can_manage: true, can_use: true, can_create: true, allowed_slugs: body.deck_slugs || [], editable_slugs: body.deck_slugs || [] }];
    if (url.pathname === '/internal/presentations/access') return [200, { ok: true }];
    return [404, { error: 'stand-in: not found' }];
  });
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  const manager = await startManager({ decks: {}, env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl } });
  const api = async (pathname, { method = 'GET', body } = {}) => {
    const response = await fetch(`${manager.url}${pathname}`, {
      method,
      headers: { Authorization: `Bearer ${token('user-ap')}`, Accept: 'application/json', 'X-GFM-Request': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const raw = await response.text();
    let json = null;
    try { json = JSON.parse(raw); } catch {}
    return { status: response.status, json, raw };
  };
  try { await run(api, manager); } finally {
    await manager.stop();
    await new Promise(r => stub.close(r));
  }
}

test('the real manager: the template list in German, and a deck made from each template in a language, with its first slide as written', { skip, timeout: 60000 }, () => withManager(async (api, manager) => {
  const list = await api('/api/presentation-templates?lang=de');
  assert.equal(list.status, 200);
  assert.equal(list.json.lang, 'de');
  assert.equal(list.json.templates.length, 6);
  for (const [i, id] of TEMPLATES.entries()) {
    const lang = LANGUAGES[(i * 3) % 14];
    const made = await api('/api/presentations', { method: 'POST', body: { title: `Deck ${id}`, template: id, lang } });
    assert.equal(made.status, 201, made.raw);
    const written = fs.readFileSync(path.join(manager.decks, made.json.slug, 'slides.md'), 'utf8');
    assert.match(written, new RegExp(`^---\\ntheme: default\\ntitle: "Deck ${id}"`));
    assert.equal((written.match(/^layout: gfm-freeform$/gm) || []).length, SLIDE_COUNT[id]);
    assert.ok(written.includes(`lang: ${lang === 'fa' || lang === 'ar' ? `${lang}-u-nu-latn` : lang}`));
  }
}));

test('the real manager: no template gives the blank deck as before; an unknown template is refused and makes no folder', { skip, timeout: 60000 }, () => withManager(async (api, manager) => {
  const blank = await api('/api/presentations', { method: 'POST', body: { title: 'Plain deck' } });
  assert.equal(blank.status, 201);
  assert.match(fs.readFileSync(path.join(manager.decks, blank.json.slug, 'slides.md'), 'utf8'), /# Plain deck[\s\S]*# New Slide\n\nStart building your presentation\./);
  const folders = fs.readdirSync(manager.decks).length;
  const bad = await api('/api/presentations', { method: 'POST', body: { title: 'Odd deck', template: 'v2-deck' } });
  assert.equal(bad.status, 404);
  assert.equal(fs.readdirSync(manager.decks).length, folders);
}));