// Unit tests of the manager's deck files, with Slidev's real parser:
//   manager/deck-files.mjs    names (slugs), titles (reading and changing the headmatter), and the decks folder;
//   manager/deck-actions.mjs  making, copying, renaming and deleting a deck;
//   and the small helpers of manager/builds.mjs (Slidev's messages) and manager/numbers.mjs (the weeks asked for).
// These files use Slidev's own packages (@slidev/parser, yaml), so the tests need the live layout of the test
// container: Slidev in /slidev/node_modules and this repository's manager at /slidev/manager (see
// slidev/tests/README.md). Without it they are skipped. The decks are made in a temporary folder
// (PRESENTATION_SLIDEV_HOME), never in /slidev/decks.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const LIVE = existsSync('/slidev/node_modules/@slidev/parser') && existsSync('/slidev/manager/deck-files.mjs');
const skip = LIVE ? false : 'needs the live layout (/slidev/node_modules and /slidev/manager)';

// The manager reads PRESENTATION_SLIDEV_HOME once, when it is loaded: set it first.
const home = LIVE ? await fs.mkdtemp(path.join(os.tmpdir(), 'deck-files-')) : '';
if (LIVE) process.env.PRESENTATION_SLIDEV_HOME = home;
const files = LIVE ? await import('/slidev/manager/deck-files.mjs') : {};
const actions = LIVE ? await import('/slidev/manager/deck-actions.mjs') : {};
const builds = LIVE ? await import('/slidev/manager/builds.mjs') : {};
const numbers = LIVE ? await import('/slidev/manager/numbers.mjs') : {};
const decks = path.join(home, 'decks');

after(async () => { if (home) await fs.rm(home, { recursive: true, force: true }); });

async function writeDeck(slug, markdown, extra = {}) {
  await fs.mkdir(path.join(decks, slug), { recursive: true });
  await fs.writeFile(path.join(decks, slug, 'slides.md'), markdown);
  for (const [name, text] of Object.entries(extra)) {
    await fs.mkdir(path.dirname(path.join(decks, slug, name)), { recursive: true });
    await fs.writeFile(path.join(decks, slug, name), text);
  }
}

// ---- names ----

test('slugify and safeSlug: a folder name from a title, and only clean names are accepted', { skip }, () => {
  assert.equal(files.slugify('Zone Conference!'), 'zone-conference');
  assert.equal(files.slugify('  --Äpfel b--  '), 'pfel-b');
  assert.equal(files.slugify(null), '');
  assert.equal(files.safeSlug('zone-1'), 'zone-1');
  for (const bad of ['Zone', '../decks', 'a/b', '', 'zone_1']) assert.throws(() => files.safeSlug(bad), /Invalid presentation id/);
  assert.equal(files.presentationSlugFromPath('/p/zone-1/assets/app.js'), 'zone-1');
  assert.equal(files.presentationSlugFromPath('/p/zone-1'), 'zone-1');
  assert.equal(files.presentationSlugFromPath('/p/Zone/'), null);
  assert.equal(files.presentationSlugFromPath('/studio/zone-1'), null);
  assert.equal(files.notFound().status, 404);
});

test('deckDir, deckFile and builtDir stay inside the decks folder', { skip }, () => {
  assert.equal(files.deckDir('zone-1'), path.join(decks, 'zone-1'));
  assert.equal(files.deckFile('zone-1'), path.join(decks, 'zone-1', 'slides.md'));
  assert.equal(files.builtDir('zone-1'), path.join(decks, 'zone-1', 'dist'));
  assert.throws(() => files.deckDir('../x'), /Invalid presentation id/);
});

// ---- titles ----

test('cleanTitle, safeTitle and headingText: one plain line that cannot break a slide', { skip }, () => {
  assert.equal(files.cleanTitle(' Zone\tconference\n\u0007 2026 '), 'Zone conference 2026');
  assert.equal(files.cleanTitle('x'.repeat(250)).length, 200);
  assert.equal(files.safeTitle('<b>{{ secret }}</b>'), 'b { secret } /b');
  assert.equal(files.headingText('Tom & Jerry <3'), 'Tom &amp; Jerry 3');
});

test('getTitle: the headmatter title, or the fallback', { skip }, () => {
  assert.equal(files.getTitle('---\ntitle: Zone conference\ntheme: default\n---\n\n# Hi\n', 'x'), 'Zone conference');
  assert.equal(files.getTitle('# No settings\n', 'fallback'), 'fallback');
  assert.equal(files.getTitle('---\ntitle: ""\n---\n', 'fallback'), 'fallback');
  assert.equal(files.getTitle('---\ntitle:\n---\n', 'fallback'), 'fallback');
  assert.equal(files.getTitle('---\ntitle: 2026\n---\n', 'fallback'), '2026');
});

test('setTitle: only the title changes, every other character stays', { skip }, () => {
  const before = '---\ntheme: default\ntitle: Old name\nclass: text-center\n---\n\n# Old name\n\n---\n\n# Second\n';
  assert.equal(files.setTitle(before, 'New name'), before.replace('title: Old name', 'title: New name'));
  // No title yet: one line is added; Windows line ends stay Windows line ends.
  const crlf = '---\r\ntheme: default\r\n---\r\n\r\n# A\r\n';
  const next = files.setTitle(crlf, 'Zone: North');
  assert.equal(files.getTitle(next, null), 'Zone: North');
  assert.ok(next.endsWith('---\r\n\r\n# A\r\n'));
  assert.ok(!/[^\r]\n/.test(next), 'every line ends with \\r\\n');
  // No settings at all: a settings block is added at the top.
  assert.equal(files.setTitle('# Just a slide\n', 'Plan'), '---\ntitle: Plan\ntheme: default\n---\n\n# Just a slide\n');
  // A bare --- at the top is only a slide separator: it becomes the settings block.
  const bare = files.setTitle('---\n\n# First\n', 'Plan');
  assert.equal(files.getTitle(bare, null), 'Plan');
  assert.ok(bare.endsWith('\n# First\n'));
  // A title is written safely: no HTML, no {{ }}.
  assert.equal(files.getTitle(files.setTitle(before, '<script>{{x}}</script>'), null), 'script { x } /script');
});

test('setTitle: settings with a mistake are refused (422), nothing is guessed', { skip }, () => {
  assert.throws(() => files.setTitle('---\ntitle: [unclosed\n---\n\n# A\n', 'New'), error => error.status === 422);
});

test('sourceVersion and isGeneratedEntry', { skip }, () => {
  const v = files.sourceVersion('# A\n');
  assert.match(v, /^[0-9a-f]{20}$/);
  assert.equal(files.sourceVersion('# A\n'), v);
  assert.notEqual(files.sourceVersion('# B\n'), v);
  for (const name of ['dist', 'node_modules', '.viewer.md', 'slides.md.saving', '.dist-building-1']) assert.equal(files.isGeneratedEntry(name), true, name);
  for (const name of ['slides.md', 'images', 'distance.png']) assert.equal(files.isGeneratedEntry(name), false, name);
});

// ---- the decks folder ----

test('listDecks: folders with a slides.md, sorted by title; deckTitle; writeDeckSource', { skip }, async () => {
  await writeDeck('b-deck', '---\ntitle: Alpha\n---\n\n# A\n');
  await writeDeck('a-deck', '---\ntitle: Beta\n---\n\n# B\n');
  await writeDeck('untitled', '# No settings\n');
  await fs.mkdir(path.join(decks, 'leftover'), { recursive: true });
  await fs.mkdir(path.join(decks, '.leftover-old'), { recursive: true });
  const list = await files.listDecks();
  assert.deepEqual(list.map(d => [d.slug, d.title]), [['b-deck', 'Alpha'], ['a-deck', 'Beta'], ['untitled', 'untitled']]);
  assert.ok(list.every(d => !Number.isNaN(Date.parse(d.updated_at))));
  assert.equal(await files.deckTitle('a-deck'), 'Beta');
  assert.equal(await files.deckExists('a-deck'), true);
  assert.equal(await files.deckExists('leftover'), false);
  await files.writeDeckSource('a-deck', '---\ntitle: Gamma\n---\n');
  assert.equal(await files.deckTitle('a-deck'), 'Gamma');
  assert.equal(existsSync(path.join(decks, 'a-deck', 'slides.md.saving')), false, 'the temporary copy is renamed');
});

test('latestDeckSourceMtime: the newest of the deck\'s own files (not its published copy)', { skip }, async () => {
  await writeDeck('times', '# A\n', { 'images/pic.svg': '<svg/>', 'dist/index.html': 'built' });
  const old = new Date('2026-01-01T00:00:00Z'), newer = new Date('2026-02-01T00:00:00Z'), newest = new Date('2026-03-01T00:00:00Z');
  await fs.utimes(path.join(decks, 'times', 'slides.md'), old, old);
  await fs.utimes(path.join(decks, 'times', 'images', 'pic.svg'), newer, newer);
  await fs.utimes(path.join(decks, 'times', 'dist', 'index.html'), newest, newest);
  assert.equal(await files.latestDeckSourceMtime(files.deckDir('times')), newer.getTime());
});

// ---- making, copying, renaming, deleting ----

test('createDeck: a title slide and one empty slide, in the first free folder', { skip }, async () => {
  const slug = await actions.createDeck('Zone conference');
  assert.equal(slug, 'zone-conference');
  const markdown = await fs.readFile(files.deckFile(slug), 'utf8');
  assert.equal(files.getTitle(markdown, null), 'Zone conference');
  assert.match(markdown, /# Zone conference\n\n---\n\n# New Slide\n/);
  assert.equal(await actions.createDeck('Zone conference'), 'zone-conference-2');
  await assert.rejects(actions.createDeck('!!!'), /name is required/);
});

test('duplicateDeck: "<title> Copy" with the deck\'s own files, never its published copy', { skip }, async () => {
  await writeDeck('source-deck', '---\ntitle: Source\n---\n\n# S\n', { 'images/a.svg': '<svg/>', 'dist/index.html': 'built', 'node_modules/x.js': 'x', '.dist-old-1/x': 'x' });
  const copy = await actions.duplicateDeck('source-deck');
  assert.equal(copy, 'source-copy');
  assert.equal(await files.deckTitle(copy), 'Source Copy');
  assert.equal(existsSync(path.join(decks, copy, 'images', 'a.svg')), true);
  for (const left of ['dist', 'node_modules', '.dist-old-1']) assert.equal(existsSync(path.join(decks, copy, left)), false, left);
  await assert.rejects(actions.duplicateDeck('missing-deck'), error => error.status === 404);
});

test('renameDeck: the title, and the folder when the name changes; the access rule moves first', { skip }, async () => {
  await writeDeck('old-name', '---\ntitle: Old name\n---\n\n# X\n', { 'dist/index.html': 'built' });
  const moves = [];
  const renamed = await actions.renameDeck('old-name', 'New name', { move: async slug => { moves.push(slug); } });
  assert.deepEqual(renamed, { slug: 'new-name', title: 'New name' });
  assert.deepEqual(moves, ['new-name']);
  assert.equal(existsSync(path.join(decks, 'old-name')), false);
  assert.equal(await files.deckTitle('new-name'), 'New name');
  assert.equal(existsSync(path.join(decks, 'new-name', 'dist')), false, 'the old published copy is never shown under the new name');
  // Only the title changes when the folder name stays the same.
  assert.deepEqual(await actions.renameDeck('new-name', 'NEW  name', { move: async () => assert.fail('no move') }), { slug: 'new-name', title: 'NEW name' });
});

test('renameDeck: when the access rule cannot move, nothing changes', { skip }, async () => {
  await writeDeck('stays', '---\ntitle: Stays\n---\n');
  const refused = Object.assign(new Error('portal-api is away'), { status: 503 });
  await assert.rejects(actions.renameDeck('stays', 'Moved', { move: async () => { throw refused; } }), refused);
  assert.equal(await files.deckTitle('stays'), 'Stays');
  assert.equal(existsSync(path.join(decks, 'moved')), false);
});

test('deleteDeck: the folder is gone; a missing deck is 404', { skip }, async () => {
  await writeDeck('to-delete', '# Bye\n');
  await actions.deleteDeck('to-delete');
  assert.equal(existsSync(path.join(decks, 'to-delete')), false);
  await assert.rejects(actions.deleteDeck('to-delete'), error => error.status === 404);
});

// ---- builds.mjs and numbers.mjs ----

test('outputLines: Slidev\'s messages without colours, empty lines or program stack lines', { skip }, () => {
  const chunk = '\u001b[31mError\u001b[39m: broken slide\n\n    at parse (/x.js:1:2)\r\n  line 3\n';
  assert.deepEqual(builds.outputLines(chunk), ['Error: broken slide', '  line 3']);
  assert.equal(builds.seconds(1234), '1.2');
});

test('publishErrorMessage: a failed build explains that the old version stays live', { skip }, () => {
  assert.match(builds.publishErrorMessage(Object.assign(new Error('x'), { buildFailed: true })), /The version people saw before is still live/);
  assert.equal(builds.publishErrorMessage(new Error('disk full')), 'Publishing did not work: disk full');
});

test('weeksFrom: 12 weeks when not given, otherwise a whole number from 1 to 104', { skip }, () => {
  const weeks = query => numbers.weeksFrom(new URL(`http://x/api/mission-kpis${query}`));
  assert.equal(weeks(''), 12);
  assert.equal(weeks('?weeks='), 12);
  assert.equal(weeks('?weeks=1'), 1);
  assert.equal(weeks('?weeks=104'), 104);
  for (const bad of ['0', '105', '2.5', 'ten', '-3']) assert.equal(weeks(`?weeks=${bad}`), null, bad);
});
