// The one-off script that renames "Friends found" to "New people being taught"
// in existing decks (slidev/tools/rename-friends-found.mjs): only text people
// read changes; queries, code and ids stay, so every pinned chart keeps its hash.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { main, newNameLike, QUERY, renameText, SHOWCASE_LINES } from '../tools/rename-friends-found.mjs';
import { pinnedKeys } from '../manager/gfm-addon/lib/chart-spec.mjs';

const DECK = [
  '---',
  'title: Friends found this month',
  '---',
  '',
  '# Friends found',
  '',
  '- Friends Found',
  '- FRIENDS FOUND',
  'We rejoice in the friends found this week. The id friends_found.actual and friends-found stay.',
  '',
  '<MissionKpiChart kpi="Friends found" :weeks="12" chart="line" />',
  `<MissionChart type="bar" title="Friends found" csv="Week,Friends found; Aug 3,12" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"zone","weeks":8}' />`,
  `<MissionChart title="Friends found" trend="polynomial" :rows="[`,
  `  'Week, Friends found',`,
  `  'Aug 3, 12',`,
  `]" />`,
  `<MissionChart :query="{ measures: ['friends_found.actual'], level: 'zone' }" />`,
  `<MissionChart :query='{"measures":["friends_found.actual"],"weeks":4,"x":"Friends found"}' />`,
  `<MissionChart v-bind='{"title":"Friends found","csv":"A,B"}' />`,
  '',
  '```chart type=bar title="Friends found" query=\'{"measures":["friends_found.actual"],"note":"Friends found"}\'',
  'Week,Friends found',
  'Aug 3,12',
  '```',
  '',
  '````md',
  '```chart type=bar',
  'Week,Friends found',
  '```',
  '````',
  '',
  '```js',
  "const label = 'Friends found'",
  '```',
  '',
  '```text',
  'Finding',
  'Friends Found',
  '```',
  '',
  '<script setup>',
  "const same = 'Friends found'",
  '</script>',
  '',
  '<!--',
  '- Friends found is where every story begins.',
  '-->',
  '',
].join('\n');

test('capitalisation follows the old name', () => {
  assert.equal(newNameLike('Friends found'), 'New people being taught');
  assert.equal(newNameLike('Friends Found'), 'New People Being Taught');
  assert.equal(newNameLike('friends found'), 'new people being taught');
  assert.equal(newNameLike('FRIENDS FOUND'), 'NEW PEOPLE BEING TAUGHT');
  assert.equal(newNameLike('Friends\tfound'), 'New people being taught');
});

test('only text people read changes; queries, code and ids stay', () => {
  const { text, changes, kept } = renameText(DECK);
  const kinds = changes.map(c => c.kind);
  assert.ok(kinds.includes('headmatter title'));
  assert.ok(kinds.includes('heading'));
  assert.ok(kinds.includes('list'));
  assert.ok(kinds.includes('speaker notes'));
  assert.ok(kinds.includes('MissionKpiChart kpi'));
  assert.ok(kinds.includes('MissionChart title'));
  assert.ok(kinds.includes('MissionChart csv'));
  assert.ok(kinds.includes('MissionChart rows'));
  assert.equal(changes.length, 15, JSON.stringify(changes));
  assert.deepEqual(kept.map(k => k.kind).sort(), [':query', 'code (js)', 'query', 'script', 'v-bind']);
  assert.ok(text.includes('# New people being taught\n'));
  assert.ok(text.includes('- New People Being Taught\n- NEW PEOPLE BEING TAUGHT\n'));
  assert.ok(text.includes('in the new people being taught this week. The id friends_found.actual and friends-found stay.'));
  assert.ok(text.includes('<MissionKpiChart kpi="New people being taught" :weeks="12"'));
  assert.ok(text.includes(`title="New people being taught" csv="Week,New people being taught; Aug 3,12" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"zone","weeks":8}'`));
  assert.ok(text.includes(`  'Week, New people being taught',`));
  assert.ok(text.includes(`:query='{"measures":["friends_found.actual"],"weeks":4,"x":"Friends found"}'`), 'a query is never changed');
  assert.ok(text.includes(`v-bind='{"title":"Friends found","csv":"A,B"}'`), 'a v-bind object is left alone');
  assert.ok(text.includes('```chart type=bar title="New people being taught" query=\'{"measures":["friends_found.actual"],"note":"Friends found"}\''));
  assert.ok(text.includes("const label = 'Friends found'"), 'code blocks stay');
  assert.ok(text.includes("const same = 'Friends found'"), 'scripts stay');
  assert.ok(text.includes('Finding\nNew People Being Taught\n'), 'a text diagram is text');
  assert.ok(text.includes('- New people being taught is where every story begins.'));
  assert.equal(renameText(text).changes.length, 0, 'running it again changes nothing');
});

test('every pinned chart keeps its hash, and Windows line endings stay', () => {
  const crlf = DECK.replace(/\n/g, '\r\n');
  const { text } = renameText(crlf);
  assert.deepEqual([...pinnedKeys(text)].sort(), [...pinnedKeys(crlf)].sort());
  assert.equal(pinnedKeys(crlf).size, 2, 'the two valid queries are pinned');
  assert.equal(text.split('\r\n').length, crlf.split('\r\n').length);
  assert.ok(!/[^\r]\n/.test(text), 'no bare line feeds added');
});

test('a dry run writes nothing; --apply keeps a .bak copy and changes only slides.md', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'rename-ff-'));
  await mkdir(path.join(root, 'one'));
  await mkdir(path.join(root, 'two'));
  await mkdir(path.join(root, 'empty'));
  await writeFile(path.join(root, 'one', 'slides.md'), DECK);
  await writeFile(path.join(root, 'two', 'slides.md'), '# Sacrament attendance\n');
  const log = console.log;
  const lines = [];
  console.log = (...a) => lines.push(a.join(' '));
  try {
    assert.equal(await main([root, '--summary']), 0);
    assert.equal(await readFile(path.join(root, 'one', 'slides.md'), 'utf8'), DECK, 'dry run');
    assert.ok(lines.some(l => /^\[one\] 15 changes \(.*\).*\(dry run\)$/.test(l)), lines.join('\n'));
    assert.ok(lines.some(l => l === '[two] no change'));
    assert.ok(!lines.some(l => l.startsWith('  line ')), '--summary prints no slide text');
    assert.equal(await main([root, '--apply']), 0);
  }
  finally { console.log = log; }
  const files = await readdir(path.join(root, 'one'));
  const backup = files.find(f => /^slides\.md\.\d{8}-\d{6}\.bak$/.test(f));
  assert.ok(backup, files.join(', '));
  assert.equal(await readFile(path.join(root, 'one', backup), 'utf8'), DECK);
  assert.equal(await readFile(path.join(root, 'one', 'slides.md'), 'utf8'), renameText(DECK).text);
  assert.deepEqual((await readdir(path.join(root, 'two'))).sort(), ['slides.md'], 'an unchanged deck gets no copy');
  assert.ok(!files.includes('slides.md.renaming'));
});

const queriesOf = line => [...line.matchAll(QUERY)].map(m => m[0]);
const showcaseFile = deck => readFile(new URL(`../showcase/${deck}/slides.md`, import.meta.url), 'utf8');

test("a deck copied from the showcase gets the showcase's new sentences, with every query as it was", async () => {
  const special = [];
  for (const [from, to, deck, line] of SHOWCASE_LINES) {
    // Each pair is the round-2 line and the line the showcase has now.
    assert.equal((await showcaseFile(deck)).split(/\r?\n/)[line - 1], to, `${deck} line ${line}`);
    assert.notEqual(from, to);
    assert.deepEqual(queriesOf(to), queriesOf(from), `${deck} line ${line} keeps its query`);
    assert.doesNotMatch(to, /friends\s+found/i);
    assert.equal(renameText(from).text, to, `${deck} line ${line}`);
    assert.equal(renameText(to).changes.length, 0, 'the new line needs nothing more');
    if (renameText(from).changes.some(c => c.kind === 'showcase text')) special.push(`${deck} ${line}`);
  }
  // Only lines where the showcase says more than the plain rename are special; "# Friends found" is a heading.
  assert.deepEqual(special, SPECIAL_LINES);
  assert.equal(renameText('# Friends found\n').changes[0].kind, 'heading');
  // The sample funnel: "New people being taught, Came to church", not "New people being taught, Taught".
  const funnel = SHOWCASE_LINES.find(([from]) => from.includes('Friends found,120; Taught,74'))[0];
  const deck = `# Funnel and waterfall\r\n\r\n${funnel}\r\n\r\n<!--\r\n- Friends found in one week.\r\n-->\r\n`;
  const { text, changes } = renameText(deck);
  assert.ok(text.includes('csv="Step,People; New people being taught,120; Came to church,74; Lessons with a member,41;'));
  assert.deepEqual(changes.map(c => [c.line, c.kind]), [[3, 'showcase text'], [6, 'speaker notes']]);
  assert.equal(text.split('\r\n').length, deck.split('\r\n').length);
  assert.ok(!/[^\r]\n/.test(text), 'Windows line endings stay');
  // In a code block a showcase line is code: left alone.
  const inCode = `\`\`\`js\n${funnel}\n\`\`\`\n`;
  assert.equal(renameText(inCode).text, inCode);
});

// The showcase lines that are more than the plain rename (the funnel, better sentences, the old Chart button).
const SPECIAL_LINES = ['chart-gallery 154', 'mission-charts 7', 'mission-charts 140', 'mission-charts 329', 'mission-charts 342', 'mission-charts 349', 'mission-charts 400', 'mission-charts 481', 'mission-charts 508'];

test('the showcase decks as they are now have nothing left to change', async () => {
  for (const deck of ['chart-gallery', 'mission-charts']) {
    const { changes, kept } = renameText(await showcaseFile(deck));
    assert.equal(changes.length, 0, deck);
    assert.equal(kept.length, 0, deck);
  }
});

test('the dry run names the showcase line it takes the wording from', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'rename-ff-'));
  const funnel = SHOWCASE_LINES.find(([from]) => from.includes('Taught,74'))[0];
  await mkdir(path.join(root, 'gallery'));
  await writeFile(path.join(root, 'gallery', 'slides.md'), `# Funnel\n\n${funnel}\n`);
  const log = console.log;
  const lines = [];
  console.log = (...a) => lines.push(a.join(' '));
  try { assert.equal(await main([root]), 0); }
  finally { console.log = log; }
  assert.ok(lines.includes("  line 3, showcase text: the showcase's new wording (slidev/showcase/chart-gallery/slides.md line 154)"), lines.join('\n'));
  assert.equal(await readFile(path.join(root, 'gallery', 'slides.md'), 'utf8'), `# Funnel\n\n${funnel}\n`, 'dry run');
});
