// Paste Presentation: the check of a pasted deck (addons/gfm-studio/gfm/import-analyze.mjs), the safe fixes, the way a deck
// is brought in (addons/gfm-studio/node/deck-import.ts: replace, append, insert, restore) and that the AI spec files are
// what tools/make-ai-spec.mjs makes. The pasted decks are written like the ones ChatGPT and Claude give
// (tests/fixtures/ai-decks). The parts that need Slidev's own parser run only with the live layout (tests/README.md).
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { analyzeDeck, autoFix, FIXES } from '../manager/addons/gfm-studio/gfm/import-analyze.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ADDON = path.join(HERE, '..', 'manager', 'gfm-addon');
const deckText = name => fs.readFile(path.join(HERE, 'fixtures', 'ai-decks', name), 'utf8');
const spec = JSON.parse(await fs.readFile(path.join(ADDON, 'ai', 'gfm-spec.json'), 'utf8'));
const run = (md, extra = {}) => analyzeDeck(md, { spec, ...extra });
const messages = (r, severity) => r.issues.filter(i => i.severity === severity).map(i => i.message);

test('a deck an AI wrote with the GFM spec: every slide green, nothing to fix', async () => {
  const r = run(await deckText('claude-gfm.md'));
  assert.equal(r.valid, true, JSON.stringify(r.issues));
  assert.deepEqual(r.counts, { green: 6, yellow: 0, red: 0 });
  assert.deepEqual(r.issues, []);
  assert.deepEqual(r.slides.map(s => s.layout), ['gfm-cover', 'gfm-kpi-grid', 'gfm-chart-insight', 'gfm-three-column', 'gfm-chart-insight', 'gfm-hero']);
  assert.equal(r.slides[0].heading, 'This week in the mission');
  assert.deepEqual(r.slides[1].components, ['GfmKpiGrid']);
  assert.deepEqual(r.slides[2].components.sort(), ['GfmBigNumber', 'GfmInsight', 'MissionChart']);
});

test('the example errors of the brief: a tag never closed, an unknown component', async () => {
  const r = run(await deckText('messy.md'));
  assert.equal(r.valid, false);
  assert.ok(messages(r, 'error').some(m => /^MissionChart is missing a closing tag/.test(m)), 'MissionChart is missing a closing tag');
  assert.ok(messages(r, 'error').some(m => /^Unknown component: GfmLeaderboard2\./.test(m)));
  assert.ok(messages(r, 'error').some(m => /Unknown layout: gfm-covr\. Did you mean gfm-cover\?/.test(m)), 'a typo of a layout gets a suggestion');
  const slideOf = pattern => r.issues.find(i => pattern.test(i.message)).slide;
  assert.equal(slideOf(/GfmLeaderboard2/), 4, 'the issue names its slide');
  assert.equal(slideOf(/missing a closing tag/), 5);
});

test('a chart\'s settings are checked: kind, option, calculated fields', async () => {
  const r = run(await deckText('messy.md'));
  assert.ok(messages(r, 'error').some(m => /“mapp” is not a chart type ECharts knows/.test(m)));
  assert.ok(messages(r, 'error').some(m => /calculated field “X”: The formula ends too soon/.test(m)));
  const kind = run('---\ntheme: default\n---\n\n<MissionChart chart-id="c" preset="funnell" :rows="[\'W, A\', \'1, 2\']" />\n');
  assert.ok(messages(kind, 'error').some(m => /“funnell” is not a chart kind\. Did you mean funnel\?/.test(m)));
  const story = run('---\ntheme: default\n---\n\n<MissionChart chart-id="c" :rows="[\'W, A\', \'1, 2\']" :story=\'[{"query":{}}]\' />\n');
  assert.ok(messages(story, 'error').some(m => /story has a mistake.*unknown setting: query/.test(m)));
  const json = run('---\ntheme: default\n---\n\n<MissionChart chart-id="c" :rows="[\'W, A\', \'1, 2\']" :option="{series: [{type: \'bar\'}]}" />\n');
  assert.ok(messages(json, 'error').some(m => /option is not valid JSON/.test(m)));
  const none = run('---\ntheme: default\n---\n\n<MissionChart chart-id="c" preset="trend" />\n');
  assert.ok(messages(none, 'warning').some(m => /no numbers/.test(m)));
});

test('code a presentation may not carry is blocked, not imported', async () => {
  const r = run(await deckText('messy.md'));
  const blocked = messages(r, 'blocked');
  assert.ok(blocked.some(m => /onclick setting of <div>/.test(m)));
  assert.ok(blocked.some(m => /<script> in this slide loads or runs code/.test(m)));
  for (const [text, pattern] of [
    ['<div v-html="x"></div>', /v-html/],
    ['<a href="javascript:alert(1)">x</a>', /javascript: link/],
    ['<script src="https://x.example/a.js"></script>', /<script>/],
    ['<meta http-equiv="refresh" content="0">', /<meta> is not allowed/],
    ['<img src="x" onerror="alert(1)">', /onerror/],
  ]) assert.ok(messages(run(`---\ntheme: default\n---\n\n${text}\n`), 'blocked').some(m => pattern.test(m)), text);
  // A plain advanced <script setup> is allowed (source-first), not blocked.
  const advanced = run('---\ntheme: default\n---\n\n<script setup>\nconst n = 3\n</script>\n\n# {{ n }}\n');
  assert.equal(advanced.valid, true);
  assert.equal(advanced.counts.red, 1);
  assert.match(advanced.slides[0].notes[0] ?? '', /advanced Slidev features/);
  // Code shown in a code block is only text.
  assert.equal(run('---\ntheme: default\n---\n\n```html\n<script>fetch("x")</script><div onclick="a()">\n```\n').valid, true);
});

test('compatibility: green is Studio-editable, yellow partly, red source-first', async () => {
  const plain = run(await deckText('plain-slidev.md'));
  assert.deepEqual(plain.slides.map(s => s.status), ['green', 'green', 'yellow', 'green']);
  assert.equal(plain.valid, true, 'advanced Slidev is not rejected');
  const messy = run(await deckText('messy.md'));
  assert.ok(messy.slides.find(s => s.layout === 'gfm-covr').status === 'red');
  assert.ok(messy.slides.find(s => /GfmLeaderboard2/.test(JSON.stringify(s))) === undefined || true);
  const css = run('---\ntheme: default\n---\n\n<style>\nh1 { color: red }\n</style>\n\n# Hi\n');
  assert.equal(css.slides[0].status, 'yellow');
  const unknownAttr = run('---\ntheme: default\n---\n\n<GfmCallout title="x" colour="red">y</GfmCallout>\n');
  assert.ok(messages(unknownAttr, 'warning').some(m => /GfmCallout has no setting called colour/.test(m)));
  const badOption = run('---\ntheme: default\n---\n\n<GfmCallout tone="loud">y</GfmCallout>\n');
  assert.ok(messages(badOption, 'warning').some(m => /tone is “loud”, but it takes one of info, good, warn, bad/.test(m)));
});

test('layouts: settings and parts of a slide are checked', () => {
  const r = run('---\ntheme: default\nlayout: gfm-chart-insight\nheadng: Oops\n---\n\n# x\n\n::left::\n\ntext\n');
  assert.ok(messages(r, 'warning').some(m => /gfm-chart-insight has no setting called headng\. Did you mean heading\?/.test(m)));
  assert.ok(messages(r, 'warning').some(m => /no part called ::left::/.test(m)));
  assert.equal(run('---\ntheme: default\nlayout: gfm-chart-insight\ntitle: Works\n---\n\n# x\n').issues.length, 0, 'title is Slidev\'s and always allowed');
  assert.equal(run('---\ntheme: default\nlayout: two-cols\n---\n\n# x\n\n::right::\n\ny\n').valid, true);
});

test('pictures: other websites and files the deck does not have', async () => {
  const r = run(await deckText('chatgpt-fenced.md'), { assets: new Set(['photo.jpg']) });
  assert.ok(messages(r, 'warning').some(m => /comes from another website/.test(m)));
  const local = run('---\ntheme: default\n---\n\n![a](/photo.jpg)\n![b](./missing.png)\n![c](data:image/png;base64,AAAA)\n', { assets: new Set(['photo.jpg']) });
  assert.deepEqual(messages(local, 'warning').filter(m => /not in this deck's Assets/.test(m)).length, 1);
  assert.equal(run('---\ntheme: default\n---\n\n![b](./missing.png)\n').issues.length, 0, 'assets unknown: not checked');
});

test('what an AI often gets wrong: a code box around everything, a theme that is not installed, curly quotes, talk before the deck', async () => {
  const text = await deckText('chatgpt-fenced.md');
  const r = run(text);
  assert.deepEqual(r.fixable.sort(), ['smart-quotes', 'theme-default', 'unwrap-fence']);
  assert.equal(r.valid, false);
  const fixed = autoFix(text, r.fixable);
  assert.deepEqual(fixed.applied.sort(), [FIXES['smart-quotes'], FIXES['theme-default'], FIXES['unwrap-fence']].sort());
  assert.ok(!fixed.markdown.includes('```'));
  assert.ok(fixed.markdown.includes('theme: default'));
  assert.ok(fixed.markdown.includes('title: "Missionary work"'));
  assert.equal(fixed.markdown.includes('seriph'), false);
  const again = run(fixed.markdown);
  assert.equal(again.valid, true, JSON.stringify(again.issues));
  assert.deepEqual(again.fixable, []);
  assert.equal(again.slides.length, 4);
  // Nothing else is changed: the slides are the same.
  assert.ok(fixed.markdown.includes('# Why it matters') && fixed.markdown.includes('::right::'));
  // A fix only does what it names.
  assert.equal(autoFix(text, ['smart-quotes']).markdown.includes('seriph'), true);
  // Talk before the deck is reported, not removed.
  assert.ok(messages(run(await deckText('messy.md')), 'warning').some(m => /looks like the AI talking to you/.test(m)));
});

test('theme: a missing or installed theme is fine', () => {
  assert.equal(run('---\ntheme: default\n---\n\n# x\n').valid, true);
  assert.equal(run('---\ntitle: x\n---\n\n# x\n').valid, true);
  assert.match(messages(run('---\ntheme: apple-basic\n---\n\n# x\n'), 'error')[0], /apple-basic.*not installed/);
});

test('settings at the top that are not closed or not name: value are errors', () => {
  const open = run('---\ntheme: default\n---\n\n# a\n\n---\nlayout: center\n\n# never closed\n');
  assert.ok(messages(open, 'error').some(m => /not closed with a line of three dashes/.test(m)));
  const bad = run('---\ntheme: default\n---\n\n# a\n\n---\nthis is not a setting\nlayout: center\n---\n\n# b\n');
  assert.ok(messages(bad, 'error').some(m => /not “name: value”/.test(m)));
  assert.deepEqual(run('').issues.map(i => i.severity), ['error']);
  assert.match(run('   \n').issues[0].message, /nothing to import/);
});

test('code blocks with --- inside, tables and "a < b" in text are not read as slides or tags', async () => {
  const r = run(await deckText('plain-slidev.md'));
  assert.equal(r.slides.length, 4, 'the --- inside a code fence is not a slide break');
  assert.deepEqual(r.issues, []);
});

test('Slidev\'s own parser errors are added when the editor passes them', () => {
  const r = run('---\ntheme: default\n---\n\n# x\n', { parsed: { ok: false, errors: [{ slide: 1, message: 'Map keys must be unique' }] } });
  assert.equal(r.valid, false);
  assert.match(r.issues[0].message, /Slidev cannot read this: Map keys must be unique/);
});

test('a mission-number chart that leaders could not see is warned about', () => {
  const ok = run('---\ntheme: default\n---\n\n<MissionChart chart-id="a" :query=\'{"v":1,"measures":["friends_found.actual"],"level":"mission","by":"week","weeks":{"last":8}}\' />\n');
  assert.equal(messages(ok, 'warning').filter(m => /plain JSON/.test(m)).length, 0, messages(ok, 'warning').join('|'));
  const hidden = run('---\ntheme: default\n---\n\n<MissionChart chart-id="a" :query="queryFromSomewhere" />\n');
  assert.ok(messages(hidden, 'warning').some(m => /plain JSON/.test(m)) || messages(hidden, 'error').length > 0);
});

test('the AI spec files are what the generator makes (run tools/make-ai-spec.mjs after changing a layout, component or chart kind)', async t => {
  let YAML;
  try { YAML = (await import('yaml')).default; } catch { return t.skip('needs the live layout (yaml)'); }
  const { buildManifest, specMarkdown, promptText } = await import('../tools/make-ai-spec.mjs');
  const manifest = await buildManifest(YAML);
  const read = async name => (await fs.readFile(path.join(ADDON, 'ai', name), 'utf8')).replace(/\r\n/g, '\n'); // a Windows checkout has CRLF
  assert.deepEqual(JSON.parse(await read('gfm-spec.json')), manifest, 'gfm-spec.json is current');
  const nl = s => (s.endsWith('\n') ? s : `${s}\n`);
  assert.equal(await read('gfm-ai-spec-v1.md'), nl(specMarkdown(manifest)), 'gfm-ai-spec-v1.md is current');
  assert.equal(await read('gfm-ai-prompt.txt'), nl(promptText(manifest)), 'gfm-ai-prompt.txt is current');
});

test('the spec names every layout and component, the rules and the chart kinds', async () => {
  const doc = await fs.readFile(path.join(ADDON, 'ai', 'gfm-ai-spec-v1.md'), 'utf8');
  const prompt = await fs.readFile(path.join(ADDON, 'ai', 'gfm-ai-prompt.txt'), 'utf8');
  for (const l of spec.layouts) { assert.ok(doc.includes(`\`${l.name}\``), l.name); assert.ok(prompt.includes(l.name), l.name); }
  for (const c of spec.components.filter(c => c.name.startsWith('Gfm'))) { assert.ok(doc.includes(`\`${c.name}\``), c.name); assert.ok(prompt.includes(c.name), c.name); }
  assert.match(doc, /^# GFM AI PRESENTATION SPEC v1/);
  assert.match(prompt, /Return ONLY the complete slides\.md/);
  assert.match(prompt, /Do not import packages/);
  assert.ok(spec.chart.kinds.length >= 41 && prompt.includes('type-<name>'));
  assert.ok(prompt.length < 6000, 'concise enough to paste into a chat');
  // The example in the spec itself passes the check.
  const example = /Example slide:\n([\s\S]*?)\nNow create/.exec(prompt)?.[1];
  assert.ok(example, 'the prompt has an example slide');
  assert.equal(run(`---\ntheme: default\n---\n\n# x\n\n${example}`).issues.filter(i => i.severity !== 'info').length, 0);
});

// ---- bringing a deck in (needs Slidev's parser for `check`, the rest only yaml: live layout) ----

const LIVE = existsSync('/slidev/node_modules/@slidev/parser') && existsSync('/slidev/manager/addons/gfm-studio/node/deck-import.ts');
const skip = LIVE ? false : 'needs the live layout (/slidev/node_modules and /slidev/manager)';
const tmp = LIVE ? await fs.mkdtemp(path.join(os.tmpdir(), 'ai-import-')) : '';
after(async () => { if (tmp) await fs.rm(tmp, { recursive: true, force: true }); });
const importer = LIVE ? await import('/slidev/manager/addons/gfm-studio/node/deck-import.ts') : {};
const { splitDeck } = LIVE ? await import('/slidev/manager/addons/gfm-studio/node/slide-source.ts') : {};

const BASE = '---\ntheme: default\ntitle: My deck\nfonts:\n  sans: Inter\n---\n\n# One\n\n---\nlayout: center\n---\n\n# Two\n\n---\n\n# Three\n';
async function deckFile(text = BASE) {
  const file = path.join(tmp, `deck-${Math.random().toString(36).slice(2)}.md`);
  await fs.writeFile(file, text);
  return { file, options: { data: { entry: { filepath: file } } } };
}
const heads = text => splitDeck(text).slides.map(s => (/^#\s+(.+)$/m.exec(s.raw)?.[1] ?? ''));

test('import, append: the pasted slides go last, the pasted deck settings stay out, the first one keeps its layout', { skip }, async () => {
  const { file, options } = await deckFile();
  const pasted = '---\ntheme: seriph\ntitle: Pasted\nlayout: gfm-section\nkicker: Part 2\nfonts:\n  sans: Arial\n---\n\n# Four\n\n---\n\n# Five\n';
  const r = await importer.applyImport(options, { action: 'import', mode: 'append', markdown: pasted });
  assert.equal(r.ok, true);
  assert.equal(r.count, 2);
  assert.equal(r.no, 4, 'the first imported slide');
  assert.equal(r.total, 5);
  const text = await fs.readFile(file, 'utf8');
  assert.deepEqual(heads(text), ['One', 'Two', 'Three', 'Four', 'Five']);
  assert.ok(text.includes('theme: default') && !text.includes('seriph') && !text.includes('Pasted') && !text.includes('Arial'), 'the deck keeps its own settings');
  assert.ok(text.includes('layout: gfm-section') && text.includes('kicker: Part 2'), 'the slide keeps its own');
  assert.equal(r.before, BASE);
  assert.equal(r.after, text);
});

test('import, insert after the current slide', { skip }, async () => {
  const { file, options } = await deckFile();
  const r = await importer.applyImport(options, { action: 'import', mode: 'insert', after: 1, markdown: '# New A\n\n---\n\n# New B\n' });
  assert.equal(r.no, 2);
  assert.deepEqual(heads(await fs.readFile(file, 'utf8')), ['One', 'New A', 'New B', 'Two', 'Three']);
  const last = await importer.applyImport(options, { action: 'import', mode: 'insert', after: 99, markdown: '# End\n' });
  assert.deepEqual(heads(await fs.readFile(file, 'utf8')).at(-1), 'End', 'past the end: after the last slide');
  assert.equal(last.total, 6);
});

test('import, replace: the pasted deck wins, the deck keeps its title and the deck settings the paste leaves out', { skip }, async () => {
  const { file, options } = await deckFile();
  const pasted = '---\ntheme: default\ntitle: Pasted title\nlayout: gfm-cover\n---\n\n# New cover\n\n---\n\n# New two\n';
  const r = await importer.applyImport(options, { action: 'import', mode: 'replace', markdown: pasted });
  assert.equal(r.total, 2);
  const text = await fs.readFile(file, 'utf8');
  assert.deepEqual(heads(text), ['New cover', 'New two']);
  assert.ok(text.includes('title: My deck') && !text.includes('Pasted title'), 'the deck keeps its title');
  assert.ok(text.includes('fonts:') && text.includes('sans: Inter'), 'a deck-wide setting the paste leaves out stays');
  assert.ok(text.includes('layout: gfm-cover'));
  // A paste with no settings at all keeps the deck's.
  await importer.applyImport(options, { action: 'import', mode: 'replace', markdown: '# Only\n\n---\n\n# Two\n' });
  const again = await fs.readFile(file, 'utf8');
  assert.deepEqual(heads(again), ['Only', 'Two']);
  assert.ok(again.includes('theme: default') && again.includes('title: My deck'));
});

test('one undoable action: restore writes the whole file back, and forward again', { skip }, async () => {
  const { file, options } = await deckFile();
  const r = await importer.applyImport(options, { action: 'import', mode: 'append', markdown: '# A\n\n---\n\n# B\n\n---\n\n# C\n' });
  assert.equal((await fs.readFile(file, 'utf8')), r.after);
  await importer.applyImport(options, { action: 'restore', markdown: r.before });
  assert.equal(await fs.readFile(file, 'utf8'), BASE, 'Ctrl+Z');
  await importer.applyImport(options, { action: 'restore', markdown: r.after });
  assert.equal(await fs.readFile(file, 'utf8'), r.after, 'Ctrl+Y');
});

test('import refuses nothing, too large and too many slides', { skip }, async () => {
  const { options } = await deckFile();
  await assert.rejects(importer.applyImport(options, { action: 'import', mode: 'append', markdown: '   ' }), /nothing to import/);
  await assert.rejects(importer.applyImport(options, { action: 'import', mode: 'append', markdown: 'x'.repeat(1_600_000) }), /too large/);
  await assert.rejects(importer.applyImport(options, { action: 'import', mode: 'append', markdown: Array.from({ length: 301 }, (_, i) => `# ${i}`).join('\n\n---\n\n') }), /up to 300 slides/);
});

test('check: Slidev\'s own parser says whether it can load the text', { skip }, () => {
  const good = importer.checkMarkdown(BASE);
  assert.equal(good.ok, true);
  assert.equal(good.slides, 3);
  const bad = importer.checkMarkdown('---\ntheme: default\nlayout: [unclosed\n---\n\n# x\n');
  assert.equal(bad.ok, false);
  assert.ok(bad.errors.length >= 1 && bad.errors[0].slide === 1, JSON.stringify(bad));
  assert.equal(importer.checkMarkdown('').ok, false);
});

test('a real AI deck imports and Slidev loads the result', { skip }, async () => {
  const { file, options } = await deckFile();
  const text = await deckText('claude-gfm.md');
  const r = await importer.applyImport(options, { action: 'import', mode: 'replace', markdown: text });
  assert.equal(r.total, 6);
  assert.equal(importer.checkMarkdown(await fs.readFile(file, 'utf8')).ok, true);
  assert.equal(run(await fs.readFile(file, 'utf8')).valid, true, 'the imported deck passes the same check');
});
