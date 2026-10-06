// Zone presentations (round 7): Zone Leaders (ZL) and Sister Training Leaders (STL) make presentations for their
// own zone. Managers (AP, President, Data Analyst) see and change every deck; a ZL or STL sees and changes only
// their own zone's decks, and opens (never changes) a deck a manager shared with them; a DL only opens decks shared
// with them; missionaries have no Presentations. portal-api decides (app.deck_allowed, app.deck_editable; tested in
// portal-api/tests); the presentation manager must follow its answer everywhere.
//
// 1. The manager's helpers (manager/zone-decks.mjs), plain Node.
// 2. Chart scope in the manager: a zone editor may try any chart in their own deck, nowhere else; the builder's
//    list is kept per person (portal-api narrows both to the zone; see test_charts.py).
// 3. The deck-folder guard (gfm-addon/lib/deck-folder.mjs), also with Slidev 52's real parser when installed
//    (the test container with the live node_modules mounted read-only at /slidev), and the files a deck's page code
//    may load (deckFilesPlugin), also in a real `slidev build` when the container has the live layout
//    (/slidev/node_modules, /slidev/manager and a writable /slidev/decks).
// 4. The real manager/server.mjs routes (tests/helpers/manager-harness.mjs), with a portal-api stand-in that
//    answers like portal-api for five people and five decks. Needs a POSIX shell (node:24-alpine).
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chartRequest, NOT_PINNED } from '../manager/chart-access.mjs';
import { spawnSync } from 'node:child_process';
import { allowedFolders, cssLeavesDeck, deckFilesPlugin, deckFolderPreparser, deckMayLoad, fileOfModule, staysInDeck } from '../manager/gfm-addon/lib/deck-folder.mjs';
import { catalogCacheKey, editorRequestAllowed, libraryView, mayCreateDecks, mayEditDeck, mayUsePresentations, ownerChangeRefusal, slidevEnv } from '../manager/zone-decks.mjs';
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const REPO = fileURLToPath(new URL('../../', import.meta.url));

// ---- 1. Helpers ----

const AP_ACCESS = { can_manage: true, can_use: true, can_create: true, role: 'AP', allowed_slugs: ['a', 'b'], editable_slugs: ['a', 'b'], owner_zones: { a: 'Alpha Zone' } };
const ZL_ACCESS = { can_manage: false, can_use: true, can_create: true, role: 'ZL', zone_id: 5, allowed_slugs: ['a', 'shared'], editable_slugs: ['a'], owner_zones: {} };
const DL_ACCESS = { can_manage: false, can_use: false, can_create: false, role: 'DL', allowed_slugs: [], editable_slugs: [] };

test('who may use Presentations: managers, ZLs, STLs and DLs (shared decks only); never missionaries', () => {
  assert.equal(mayUsePresentations(AP_ACCESS), true);
  assert.equal(mayUsePresentations(ZL_ACCESS), true);
  // portal-api decides; a DL gets can_use (they open the decks shared with them) but never can_create.
  assert.equal(mayUsePresentations({ ...DL_ACCESS, can_use: true }), true);
  assert.equal(mayCreateDecks({ ...DL_ACCESS, can_use: true, can_create: false }), false);
  assert.equal(mayUsePresentations({ role: 'MISSIONARY', can_use: false }), false);
  // An older portal-api without can_use: the role decides (DL, ZL and STL).
  assert.equal(mayUsePresentations({ role: 'STL' }), true);
  assert.equal(mayUsePresentations({ role: 'DL' }), true);
  assert.equal(mayUsePresentations({ role: 'MISSIONARY' }), false);
  assert.equal(mayUsePresentations(null), false);
});

test('who may change a deck and make one: managers every deck; a ZL only their editable decks', () => {
  assert.equal(mayEditDeck(AP_ACCESS, 'anything'), true);
  assert.equal(mayEditDeck(ZL_ACCESS, 'a'), true);
  assert.equal(mayEditDeck(ZL_ACCESS, 'shared'), false, 'a shared deck opens but stays read-only');
  assert.equal(mayEditDeck(ZL_ACCESS, 'b'), false);
  assert.equal(mayEditDeck(DL_ACCESS, 'a'), false);
  assert.equal(mayCreateDecks(AP_ACCESS), true);
  assert.equal(mayCreateDecks(ZL_ACCESS), true);
  assert.equal(mayCreateDecks({ ...ZL_ACCESS, can_create: false }), false, 'a ZL without a zone');
  assert.equal(mayCreateDecks(DL_ACCESS), false);
});

test('the library shows a ZL only the decks they may open, and marks which they may change', () => {
  const decks = [{ slug: 'a', title: 'A' }, { slug: 'b', title: 'B' }, { slug: 'shared', title: 'S' }];
  const zl = libraryView(decks, ZL_ACCESS);
  assert.equal(zl.can_create, true);
  assert.deepEqual(zl.presentations.map(p => [p.slug, p.can_edit]), [['a', true], ['shared', false]]);
  assert.ok(zl.presentations.every(p => !('zone_name' in p)), 'no zone names for a ZL');
  const ap = libraryView(decks, AP_ACCESS);
  assert.deepEqual(ap.presentations.map(p => [p.slug, p.can_edit, p.zone_name]), [['a', true, 'Alpha Zone'], ['b', true, undefined], ['shared', true, undefined]]);
  assert.deepEqual(libraryView(decks, DL_ACCESS), { can_create: false, presentations: [] });
});

test("the chart builder's list is shared by managers per mission, and kept per person for a ZL", () => {
  assert.equal(catalogCacheKey({ mission_id: 2, user_id: 'x' }, AP_ACCESS), '2:managers');
  assert.equal(catalogCacheKey({ mission_id: 2, user_id: 'y' }, AP_ACCESS), '2:managers');
  assert.equal(catalogCacheKey({ mission_id: 2, user_id: 'z' }, ZL_ACCESS), '2:user z');
  assert.notEqual(catalogCacheKey({ mission_id: 2, user_id: 'z' }, ZL_ACCESS), catalogCacheKey({ mission_id: 2, user_id: 'w' }, ZL_ACCESS));
});

// The protected list is empty since round 6 (the Dashboards tab is DataEase); the rule is tested with an example
// list, and the manager copy below gets a protected-decks.mjs listing 'mission-dashboard' (like protected-decks.test.mjs).
const EXAMPLE_PROTECTED = Object.freeze(['mission-dashboard']);

test('a protected deck cannot be given to a zone; other decks can', () => {
  assert.match(ownerChangeRefusal('mission-dashboard', { owner_zone_id: 5 }, EXAMPLE_PROTECTED), /stays with the mission/);
  assert.equal(ownerChangeRefusal('mission-dashboard', { owner_zone_id: null }, EXAMPLE_PROTECTED), null);
  assert.equal(ownerChangeRefusal('mission-dashboard', {}, EXAMPLE_PROTECTED), null);
  assert.equal(ownerChangeRefusal('zone-council', { owner_zone_id: 5 }, EXAMPLE_PROTECTED), null);
  assert.equal(ownerChangeRefusal('mission-dashboard', { owner_zone_id: 5 }), null, 'nothing is protected since round 6');
});

test("a zone editor's requests reach only their own deck's files", () => {
  const ok = url => editorRequestAllowed(url, 'mine');
  // Normal editor traffic.
  for (const url of ['/edit/mine/', '/edit/mine/3', '/edit/mine/@vite/client', '/edit/mine/@fs/slidev/node_modules/@slidev/client/main.ts',
    '/edit/mine/@fs/slidev/manager/gfm-addon/components/MissionChart.vue?vue&type=script', '/edit/mine/@fs/slidev/decks/mine/node_modules/.vite/deps/vue.js?v=1',
    '/__slidev/slides/2.json', '/@studio/deck', '/edit/mine/slides.md?import']) assert.equal(ok(url), true, url);
  // Other decks, backups, the top folder, and `..` in any spelling.
  for (const url of ['/edit/mine/@fs/slidev/decks/theirs/slides.md?raw', '/@fs/slidev/decks/theirs/slides.md', '/edit/mine/@fs/slidev/decks/mine-2/slides.md',
    '/edit/mine/@fs/slidev/backups/presentation-acl-20260917/x.json', '/edit/mine/@fs/slidev/vite.config.ts', '/edit/mine/@id//slidev/decks/theirs/slides.md?raw',
    '/edit/mine/%2Fslidev%2Fdecks%2Ftheirs%2Fslides.md', '/edit/mine/%252Fslidev%252Fdecks%252Ftheirs', '/edit/mine/../theirs/slides.md',
    '/edit/mine/%2e%2e/theirs/slides.md', '/edit/mine/..%5Ctheirs', '/edit/mine/%E0%A4%A', '/edit/mine/x%00y']) assert.equal(ok(url), false, url);
});

test('Slidev editors and builds get no secrets from the environment', () => {
  const env = slidevEnv({ PATH: '/bin', HOME: '/root', SUPABASE_URL: 'http://kong', SUPABASE_SERVICE_ROLE_KEY: 's', PORTAL_SERVICE_KEY: 's', ANON_KEY: 's', JWT_SECRET: 's', POSTGRES_PASSWORD: 's', DATABASE_URL: 's', SOME_TOKEN: 's', MISSION_ID: '2' }, { EXTRA: '1' });
  assert.deepEqual(Object.keys(env).sort(), ['EXTRA', 'HOME', 'MISSION_ID', 'PATH', 'SUPABASE_URL']);
});

// ---- 2. Chart scope in the manager ----

test("a zone editor may try any chart in their own deck; elsewhere only what the deck holds (and never someone else's answer)", async () => {
  const spec = { measures: ['friends_found.actual'], level: 'mission' };
  const zl = { mission_id: 2, user_id: 'zl' };
  const ask = (deck, pinned = false) => chartRequest(zl, { deck, spec }, { access: async () => ZL_ACCESS, isPinned: async () => pinned });
  const own = await ask('a');
  assert.equal(own.status, 200, 'the builder preview in their own deck');
  assert.equal(own.pinned, false);
  assert.match(own.key, /^2:user zl:/, 'kept for this person alone');
  assert.deepEqual(await ask('shared'), { status: 403, error: NOT_PINNED }, 'a shared deck: only the charts written in it');
  assert.equal((await ask('shared', true)).status, 200);
  assert.deepEqual(await ask(''), { status: 403, error: NOT_PINNED }, 'no deck: managers only');
  const ap = await chartRequest({ mission_id: 2, user_id: 'ap' }, { deck: 'a', spec }, { access: async () => AP_ACCESS, isPinned: async () => false });
  assert.match(ap.key, /^2:managers:/);
});

// ---- 3. The deck-folder guard ----

test('a deck includes files only from its own folder', () => {
  for (const p of ['part.md', './part.md', 'pages/part.md', '/part.md']) assert.equal(staysInDeck(p), true, p);
  for (const p of ['../other/slides.md', './../x.md', 'pages/../../x.md', '//etc/x', '', '~/x.md', 'C:/x.md', '..\\x.md']) assert.equal(staysInDeck(p), false, p);
  for (const p of ['@/snippets/a.ts', 'snippets/a.ts', './a.ts']) assert.equal(staysInDeck(p, { snippet: true }), true, p);
  for (const p of ['/proc/1/environ', '@/../other/slides.md', '../other/slides.md']) assert.equal(staysInDeck(p, { snippet: true }), false, p);

  const [guard] = deckFolderPreparser();
  const lines = ['# One', '<<< @/snippets/a.ts', '<<< ../other/slides.md#region', '  <<< /proc/1/environ {2-3}', 'text'];
  guard.transformRawLines(lines);
  assert.deepEqual(lines, ['# One', '<<< @/snippets/a.ts', '', '', 'text']);
  const escaping = { src: '../other/slides.md#2', layout: 'center' };
  assert.equal(guard.transformSlide('', escaping), '');
  assert.deepEqual(escaping, { layout: 'center' });
  const own = { src: './part.md' };
  assert.equal(guard.transformSlide('', own), undefined);
  assert.deepEqual(own, { src: './part.md' });
  assert.equal(guard.transformSlide('# x', { title: 'x' }), undefined);
});

const PARSER_FS = ['/slidev/node_modules/@slidev/parser/dist/fs.mjs', path.join(REPO, 'slidev/node_modules/@slidev/parser/dist/fs.mjs')].find(f => existsSync(f));
test("with Slidev 52's parser: another deck's slides stay out, the deck's own imports stay in", { skip: PARSER_FS ? false : "Slidev's parser is not installed here (run in the test container)" }, async () => {
  const { load, injectPreparserExtensionLoader } = await import(pathToFileURL(PARSER_FS));
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zone-parser-'));
  try {
    const mine = path.join(root, 'mine'), theirs = path.join(root, 'theirs');
    await fs.mkdir(mine); await fs.mkdir(theirs);
    await fs.writeFile(path.join(theirs, 'slides.md'), '---\ntitle: Theirs\n---\n\n# OTHER ZONE SECRET\n');
    await fs.writeFile(path.join(mine, 'part.md'), '# Own part\n');
    await fs.writeFile(path.join(mine, 'slides.md'), '---\ntitle: Mine\n---\n\n# One\n\n---\nsrc: ../theirs/slides.md\n---\n\n---\nsrc: ./part.md\n---\n\n---\n\n# Code\n\n<<< ../theirs/slides.md\n\n<<< @/part.md\n');
    // Like the live editor: Slidev allows everything under /slidev (the folder above every deck).
    const opts = { userRoot: mine, roots: [mine], allowedRoots: [root, mine] };
    const text = loaded => loaded.slides.map(s => s.content).join('\n');

    injectPreparserExtensionLoader(async () => []);
    assert.match(text(await load(opts, path.join(mine, 'slides.md'), undefined, 'dev')), /OTHER ZONE SECRET/, 'control: without the guard the other deck comes in');

    injectPreparserExtensionLoader(async () => deckFolderPreparser());
    for (const mode of ['dev', 'build']) {
      const loaded = await load(opts, path.join(mine, 'slides.md'), undefined, mode);
      const all = text(loaded);
      assert.doesNotMatch(all, /OTHER ZONE SECRET/, mode);
      assert.doesNotMatch(all, /theirs/, `${mode}: the snippet line is gone`);
      assert.match(all, /# Own part/, `${mode}: the deck's own import`);
      assert.match(all, /<<< @\/part\.md/, `${mode}: the deck's own snippet`);
      assert.ok(Object.keys(loaded.markdownFiles).every(f => !f.includes('theirs')), `${mode}: the other file was never read`);
    }
  }
  finally {
    injectPreparserExtensionLoader(null);
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("a deck's page code loads files only from its own folder, node_modules and the manager's code", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zone-files-'));
  try {
    const decks = path.join(root, 'decks'), mine = path.join(decks, 'mine'), theirs = path.join(decks, 'theirs');
    const packages = path.join(root, 'node_modules'), cli = path.join(packages, '@slidev', 'cli');
    for (const dir of [mine, theirs, cli, path.join(root, 'backups')]) await fs.mkdir(dir, { recursive: true });
    for (const file of [path.join(mine, 'part.md'), path.join(theirs, 'slides.md'), path.join(theirs, 'style.css'), path.join(cli, 'x.mjs'), path.join(root, 'backups', 'acl.json')]) await fs.writeFile(file, 'x');
    const folders = allowedFolders({ userRoot: mine, cliRoot: cli });
    assert.deepEqual(folders.slice(0, 2), [mine, packages], "the deck and node_modules (found from Slidev's cliRoot)");
    assert.equal(folders[2], path.resolve(fileURLToPath(new URL('../manager/', import.meta.url))), "and the manager's own code");
    assert.equal(deckMayLoad(path.join(mine, 'part.md'), folders), true);
    assert.equal(deckMayLoad(path.join(cli, 'x.mjs'), folders), true);
    assert.equal(deckMayLoad(path.join(theirs, 'slides.md'), folders), false);
    assert.equal(deckMayLoad(path.join(root, 'backups', 'acl.json'), folders), false);
    assert.equal(deckMayLoad(path.join(decks, 'mine-2', 'slides.md'), folders), false, 'a folder whose name starts the same');

    // Modules that are not files pass; a file id may carry a query.
    for (const id of ['\0virtual:x', '/@slidev/configs', 'virtual:uno.css', '', path.join(mine, 'missing.md')]) assert.equal(fileOfModule(id), null, id);
    assert.equal(fileOfModule(path.join(theirs, 'slides.md') + '?import&raw'), path.join(theirs, 'slides.md'));

    const plugin = deckFilesPlugin({ userRoot: mine, cliRoot: cli });
    assert.equal(plugin.enforce, 'pre', 'before Vite reads the file itself');
    assert.equal(plugin.load(path.join(mine, 'part.md') + '?raw'), null);
    assert.equal(plugin.load('/@slidev/configs'), null);
    assert.throws(() => plugin.load(path.join(theirs, 'slides.md') + '?raw'), /only the files in its own folder/);
    assert.throws(() => plugin.load(path.join(root, 'backups', 'acl.json')), /only the files in its own folder/);

    // A slide's <style>: @import and url() to another deck are refused; data:, https: and own names pass.
    const style = path.join(mine, 'slides.md__slidev_1.md') + '?vue&type=style&index=0&lang.css';
    assert.throws(() => plugin.transform('@import "../theirs/style.css";', style), /only the files in its own folder/);
    assert.throws(() => plugin.transform("h1 { background: url('../theirs/slides.md') }", style), /only the files in its own folder/);
    // image-set() and the like name files as bare quoted strings, which url()/@import miss (finding, round 7 review).
    assert.throws(() => plugin.transform('h1 { background-image: image-set("../theirs/style.css" 1x); }', style), /only the files in its own folder/);
    assert.throws(() => plugin.transform('h1 { background-image: -webkit-image-set("../theirs/slides.md" 2x); }', style), /only the files in its own folder/);
    assert.equal(plugin.transform('h1 { color: red; background: url(data:image/png;base64,AAAA) } @import url(https://example.invalid/x.css);', style), null);
    assert.equal(plugin.transform('h1 { font-family: "Comic Sans"; content: "hello"; }', style), null, 'quoted names that are no file pass');
    assert.equal(plugin.transform('@import "../theirs/style.css";', path.join(cli, 'theme.css')), null, "a theme's own CSS is not checked");
    assert.equal(cssLeavesDeck('@import "/does-not-exist.css";', mine, mine, folders), false, 'a name that is no file is left to Vite');
    assert.equal(cssLeavesDeck('h1 { background-image: image-set("../theirs/style.css" 1x); }', mine, mine, folders), true, 'image-set to another deck');

    // A slide's code may not read files through `new URL(x, import.meta.url)`: refused in the deck's own code,
    // however the path or the base URL is built up (finding, round 7 review). Installed code is not checked.
    const script = path.join(mine, 'slides.md__slidev_1.md') + '?vue&type=script&setup=true&lang.ts';
    assert.throws(() => plugin.transform('const u = new URL("../theirs/slides.md", import.meta.url)', script), /only the files in its own folder/);
    assert.throws(() => plugin.transform('const u = new URL("/proc/1/environ", import.meta.url)', script), /only the files in its own folder/);
    assert.throws(() => plugin.transform('const b = import.meta.url; const u = new URL("../theirs/x", b)', script), /only the files in its own folder/);
    assert.equal(plugin.transform('const u = new URL("./pic.png", location.href)', script), null, 'a deck may still build its own runtime URLs without import.meta.url');
    assert.equal(plugin.transform('const u = new URL("../theirs/slides.md", import.meta.url)', path.join(cli, 'x.mjs')), null, "installed code is not checked");
  }
  finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

// The live layout in the test container: Slidev in /slidev/node_modules, this worktree's manager at /slidev/manager.
const LIVE_LAYOUT = existsSync('/slidev/node_modules/.bin/slidev') && existsSync('/slidev/manager/gfm-addon/lib/deck-folder.mjs');
test('in a real slidev build: a deck cannot copy another deck or its style into its published pages', { skip: LIVE_LAYOUT ? false : 'needs the live layout (/slidev/node_modules and /slidev/manager)', timeout: 180000 }, async () => {
  const mine = '/slidev/decks/zdtest-mine', theirs = '/slidev/decks/zdtest-theirs';
  await fs.mkdir(mine, { recursive: true });
  await fs.mkdir(theirs, { recursive: true });
  await fs.writeFile(path.join(theirs, 'slides.md'), '---\ntitle: Theirs\n---\n\n# OTHER-ZONE-MARKER\n');
  await fs.writeFile(path.join(theirs, 'style.css'), '.other-zone-marker{color:red}\n');
  await fs.writeFile(path.join(mine, 'part.md'), '# OWN-PART-MARKER\n');
  // Builds the deck with this body; returns whether it built, and the built pages plus the build's messages.
  const build = async body => {
    await fs.writeFile(path.join(mine, 'slides.md'), '---\ntitle: Mine\n---\n\n' + body + '\n');
    const out = await fs.mkdtemp(path.join(os.tmpdir(), 'zone-build-'));
    const run = spawnSync('/slidev/node_modules/.bin/slidev', ['build', path.join(mine, 'slides.md'), '--out', out], { cwd: '/slidev', encoding: 'utf8' });
    const files = (await fs.readdir(out, { recursive: true })).filter(f => /\.(js|css|html)$/.test(f));
    const text = (await Promise.all(files.map(f => fs.readFile(path.join(out, f), 'utf8')))).join('\n') + run.stdout + run.stderr;
    await fs.rm(out, { recursive: true, force: true });
    return { ok: run.status === 0, text };
  };
  try {
    const own = await build('<script setup>\nimport part from "./part.md?raw"\n</script>\n\n# {{ part }}');
    assert.ok(own.ok && own.text.includes('OWN-PART-MARKER'), "the deck's own file is used");
    for (const body of [
      '<script setup>\nimport theirs from "../zdtest-theirs/slides.md?raw"\n</script>\n\n# {{ theirs }}',
      '# One\n\n<img src="../zdtest-theirs/style.css">',
      '# One\n\n<style>\n@import "../zdtest-theirs/style.css";\n</style>',
      '# One\n\n<style>\nh1 { background: url(../zdtest-theirs/style.css); }\n</style>',
      // Vite reads `new URL(x, import.meta.url)` itself (not through `load`): another deck and the manager's own
      // environment (the service keys) through /proc (finding, round 7 review). The guard refuses import.meta.url.
      '<script setup>\nconst u = new URL("../zdtest-theirs/slides.md", import.meta.url).href\n</script>\n\n# {{ u }}',
      '<script setup>\nconst u = new URL("/proc/1/environ", import.meta.url).href\n</script>\n\n# {{ u }}',
      // image-set() names files as bare quoted strings, which url()/@import miss (finding, round 7 review).
      '# One\n\n<style>\nh1 { background-image: image-set("../zdtest-theirs/style.css" 1x); }\n</style>',
    ]) {
      const other = await build(body);
      assert.equal(other.ok, false, body);
      assert.match(other.text, /only the files in its own folder/, body);
      assert.doesNotMatch(other.text, /OTHER-ZONE-MARKER|other-zone-marker/, body);
    }
  }
  finally {
    await fs.rm(mine, { recursive: true, force: true });
    await fs.rm(theirs, { recursive: true, force: true });
  }
});

// ---- 4. The manager's routes ----

const posix = process.platform !== 'win32';
const skip = posix ? false : 'needs a POSIX shell (run in node:24-alpine)';

// Five people and five decks, answered the way portal-api answers (app.deck_allowed / deck_editable).
const PEOPLE = {
  'user-ap': { role: 'AP', manager: true },
  'user-zl5': { role: 'ZL', zone: 5 },
  'user-stl5': { role: 'STL', zone: 5 },
  'user-zl6': { role: 'ZL', zone: 6 },
  'user-dl': { role: 'DL' },
};
const AS = Object.fromEntries(Object.keys(PEOPLE).map(id => [id.slice(5), token(id)]));
const owners = new Map([['zone5-council', 5], ['zone6-council', 6]]);
const SHARED_WITH_ZLS = new Set(['shared-talk']);
const calls = [];
let failNextCreate = false;

function portalApi(url, body) {
  const person = PEOPLE[body.user_id];
  const zone = person.manager ? null : person.zone ?? null;
  const editable = slug => !!person.manager || (zone !== null && owners.get(slug) === zone);
  const allowed = slug => editable(slug) || (person.role === 'ZL' && SHARED_WITH_ZLS.has(slug));
  if (url.pathname === '/internal/presentations/check') {
    const slugs = body.deck_slugs || [];
    const use = !!person.manager || ['DL', 'ZL', 'STL'].includes(person.role);  // a DL opens only decks shared with them
    return [200, {
      role: person.role, can_manage: !!person.manager, can_use: use, can_create: !!person.manager || zone !== null, zone_id: zone,
      allowed_slugs: use ? slugs.filter(allowed) : [], editable_slugs: use ? slugs.filter(editable) : [],
      owner_zones: person.manager ? Object.fromEntries(slugs.filter(s => owners.has(s)).map(s => [s, `Zone ${owners.get(s)}`])) : {},
    }];
  }
  if (url.pathname === '/internal/presentations/access') {
    calls.push(`${body.operation}:${body.deck_slug}${body.new_slug ? `>${body.new_slug}` : ''}:${body.user_id.slice(5)}`);
    const slug = body.deck_slug;
    if (body.operation === 'create') {
      if (failNextCreate) { failNextCreate = false; return [503, { error: 'stand-in: down' }]; }
      if (zone !== null) owners.set(slug, zone);
      return [200, { ok: true }];
    }
    if (!editable(slug)) return [403, { error: "You can change only your own zone's presentations." }];
    if (body.operation === 'rename' || body.operation === 'duplicate') { if (owners.has(slug)) owners.set(body.new_slug, owners.get(slug)); if (body.operation === 'rename') owners.delete(slug); }
    if (body.operation === 'delete') owners.delete(slug);
    return [200, { ok: true, access: { roles: [], owner_zone_id: owners.get(slug) ?? null }, options: { zones: [] } }];
  }
  if (url.pathname === '/internal/presentations/chart-catalog') return [200, { who: body.user_id }];
  if (url.pathname === '/internal/presentations/chart-data') return [200, { table: { labels: [], series: [] }, meta: { who: body.user_id } }];
  return [404, { error: 'stand-in: not found' }];
}

let stub, manager;
before(async () => {
  if (!posix) return;
  stub = await startStub((req, url, body) => supabaseAnswer(req, url) || portalApi(url, body));
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  manager = await startManager({
    decks: { 'zone5-council': 'Zone 5 council', 'zone6-council': 'Zone 6 council', 'mission-training': 'Mission training', 'mission-dashboard': 'Mission Dashboard', 'shared-talk': 'Shared talk' },
    env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl },
    protectedDecks: EXAMPLE_PROTECTED,
  });
});

after(async () => {
  if (manager) await manager.stop();
  if (stub) await new Promise(r => stub.close(r));
});

async function api(pathname, { method = 'GET', body, as, headers = {} } = {}) {
  const response = await fetch(`${manager.url}${pathname}`, {
    method, redirect: 'manual',
    headers: { Authorization: `Bearer ${as}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let json = null;
  try { json = JSON.parse(text); } catch {}
  return { status: response.status, json, text };
}

const library = async as => (await api('/api/presentations', { as })).json;
const folders = async () => (await fs.readdir(manager.decks)).filter(name => !name.startsWith('.')).sort();

test("library: a ZL sees only their zone's deck (and one shared with them); an STL only the zone's deck", { skip }, async () => {
  const zl = await library(AS.zl5);
  assert.deepEqual(zl.presentations.map(p => [p.slug, p.can_edit]), [['shared-talk', false], ['zone5-council', true]]);
  assert.equal(zl.can_create, true);
  assert.equal(zl.can_manage, false);
  const stl = await library(AS.stl5);
  assert.deepEqual(stl.presentations.map(p => p.slug), ['zone5-council']);
  const zl6 = await library(AS.zl6);
  assert.deepEqual(zl6.presentations.map(p => [p.slug, p.can_edit]), [['shared-talk', false], ['zone6-council', true]]);
  const ap = await library(AS.ap);
  assert.equal(ap.presentations.length, 5);
  assert.ok(ap.presentations.every(p => p.can_edit));
  assert.equal(ap.presentations.find(p => p.slug === 'zone5-council').zone_name, 'Zone 5');
  assert.deepEqual((await library(AS.dl)).presentations, [], 'a DL sees only decks shared with them (none here)');
});

test("changing: a ZL or STL edits their zone's deck, never another zone's, a mission deck or a protected deck", { skip }, async () => {
  for (const as of [AS.zl5, AS.stl5]) {
    const own = await api('/api/presentations/zone5-council/source', { as });
    assert.equal(own.status, 200);
    const saved = await api('/api/presentations/zone5-council/source', { method: 'PUT', as, body: { markdown: `${own.json.markdown}\n---\n\n# More\n`, version: own.json.version } });
    assert.equal(saved.status, 200, saved.text);
    for (const slug of ['zone6-council', 'mission-training', 'mission-dashboard', 'shared-talk']) {
      for (const [pathname, method] of [[`/api/presentations/${slug}/source`, 'GET'], [`/api/presentations/${slug}/publish`, 'POST'], [`/api/presentations/${slug}/status`, 'GET'], [`/api/presentations/${slug}/download`, 'GET'], [`/studio/${slug}`, 'GET']]) {
        const r = await api(pathname, { method, as });
        assert.equal(r.status, 403, `${method} ${pathname}`);
      }
    }
    assert.equal((await api('/studio/zone5-council', { as })).status, 200);
  }
  assert.equal((await api('/api/presentations/zone5-council/publish', { method: 'POST', as: AS.zl5 })).status, 200, 'publish own');
  assert.equal((await api('/api/presentations/zone5-council/download', { as: AS.stl5 })).status, 200, 'download own source');
  assert.equal((await api('/api/presentations/zone5-council/source', { as: AS.dl })).status, 403);
  assert.equal((await api('/api/presentations/zone6-council/source', { as: AS.zl6 })).status, 200);
  assert.equal((await api('/api/presentations/mission-training/source', { as: AS.ap })).status, 200);
});

test('Manage access stays with managers, and a protected deck cannot be given to a zone', { skip }, async () => {
  assert.equal((await api('/api/presentations/zone5-council/access', { as: AS.zl5 })).status, 403);
  const refused = await api('/api/presentations/mission-dashboard/access', { method: 'POST', as: AS.ap, body: { rule: { owner_zone_id: 5, roles: [] } } });
  assert.equal(refused.status, 409);
  assert.match(refused.json.error, /stays with the mission/);
  assert.ok(!calls.some(c => c.startsWith('save:mission-dashboard')), 'nothing was saved');
  assert.equal((await api('/api/presentations/mission-dashboard/access', { method: 'POST', as: AS.ap, body: { rule: { owner_zone_id: null, roles: [] } } })).status, 200);
});

test("creating: a ZL's new deck belongs to their zone; a DL cannot create; a failed record leaves no folder", { skip }, async () => {
  const made = await api('/api/presentations', { method: 'POST', as: AS.zl5, body: { title: 'Zone five talk' } });
  assert.equal(made.status, 201, made.text);
  assert.equal(made.json.slug, 'zone-five-talk');
  assert.ok(calls.includes('create:zone-five-talk:zl5'));
  assert.ok((await library(AS.stl5)).presentations.some(p => p.slug === 'zone-five-talk' && p.can_edit), 'the STL of the zone edits it too');
  assert.ok(!(await library(AS.zl6)).presentations.some(p => p.slug === 'zone-five-talk'), 'another zone never sees it');

  assert.equal((await api('/api/presentations', { method: 'POST', as: AS.dl, body: { title: 'District talk' } })).status, 403);
  failNextCreate = true;
  const failed = await api('/api/presentations', { method: 'POST', as: AS.zl6, body: { title: 'Lost talk' } });
  assert.equal(failed.status, 503);
  assert.ok(!(await folders()).includes('lost-talk'), 'the folder was removed again');
  assert.ok(!(await folders()).includes('district-talk'));
});

test("rename, duplicate and delete: own zone's decks only; protected decks stay protected", { skip }, async () => {
  const copy = await api('/api/presentations/zone-five-talk/duplicate', { method: 'POST', as: AS.zl5 });
  assert.equal(copy.status, 201, copy.text);
  assert.ok((await library(AS.stl5)).presentations.some(p => p.slug === 'zone-five-talk-copy' && p.can_edit), 'the copy stays with zone 5');
  const renamed = await api('/api/presentations/zone-five-talk-copy/rename', { method: 'POST', as: AS.stl5, body: { title: 'Zone five review' } });
  assert.equal(renamed.status, 200, renamed.text);
  assert.equal((await api('/api/presentations/zone-five-review', { method: 'DELETE', as: AS.zl5 })).status, 200);
  for (const [pathname, method, body] of [['/api/presentations/zone6-council/duplicate', 'POST'], ['/api/presentations/zone6-council/rename', 'POST', { title: 'Mine now' }], ['/api/presentations/zone6-council', 'DELETE'], ['/api/presentations/mission-dashboard', 'DELETE'], ['/api/presentations/mission-dashboard/rename', 'POST', { title: 'X' }], ['/api/presentations/shared-talk', 'DELETE']]) {
    assert.equal((await api(pathname, { method, body, as: AS.zl5 })).status, 403, `${method} ${pathname}`);
  }
  assert.equal((await api('/api/presentations/mission-dashboard', { method: 'DELETE', as: AS.ap })).status, 409, 'protected for managers too');
  assert.deepEqual(await folders(), ['mission-dashboard', 'mission-training', 'shared-talk', 'zone-five-talk', 'zone5-council', 'zone6-council']);
});

test("the editor: a ZL reaches only their own deck's editor and files", { skip }, async () => {
  // Round 8: the editor itself is on the deck address, only with an edit pass (the manager's sign-in never counts there).
  for (const pathname of ['/edit/zone5-council/', '/edit/zone5-council/1', '/__slidev/slides/1.json']) {
    const r = await fetch(`${manager.deckUrl}${pathname}`, { headers: { Authorization: `Bearer ${AS.zl5}`, Referer: `${manager.deckUrl}/edit/zone5-council/1` } });
    assert.equal(r.status, 401, pathname);
  }
  const other = '/@fs/slidev/decks/zone6-council/slides.md?raw';
  // The manager address has no editor pages (round 9: its old /edit/ addresses are gone): nothing there for anyone.
  for (const pathname of ['/edit/zone6-council/', '/edit/mission-dashboard/', `/edit/zone5-council${other}`, '/edit/zone5-council/..%2Fzone6-council/slides.md'])
    assert.equal((await api(pathname, { as: AS.zl5 })).status, 404, pathname);
  // The chart builder's requests through the manager address (named by the Referer) reach only the ZL's own deck.
  for (const [pathname, headers] of [[other, { Referer: `${manager.url}/edit/zone5-council/1` }], ['/__slidev/slides/1.json', { Referer: `${manager.url}/edit/zone6-council/1` }]]) {
    const r = await api(pathname, { as: AS.zl5, headers });
    assert.equal(r.status, 403, pathname);
  }
  assert.ok(!/starting Slidev/.test(manager.log()), 'no editor was started for a refused request');
});

// Round 8: a published deck opens on the deck address (deck-origin.mjs): the manager address checks access, gives a
// view pass for that one deck and sends the browser on (deck-origin.test.mjs tests the passes themselves).
async function openDeck(pathname, as) {
  const signIn = await fetch(`${manager.url}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${as}` } });
  const session = (signIn.headers.get('set-cookie') || '').split(';')[0];
  const door = await fetch(`${manager.url}${pathname}`, { redirect: 'manual', headers: { Cookie: session, Accept: 'text/html' } });
  if (door.status !== 302) return { status: door.status, text: await door.text() };
  const pass = (door.headers.get('set-cookie') || '').split(';')[0];
  const page = await fetch(door.headers.get('location'), { headers: { Cookie: pass, Accept: 'text/html' } });
  return { status: page.status, text: await page.text(), location: door.headers.get('location'), csp: page.headers.get('content-security-policy') || '' };
}

test("published decks: a ZL opens their zone's deck (with the edit button) and a shared one (without); never another zone's", { skip }, async () => {
  const own = await openDeck('/p/zone5-council/', AS.zl5);
  assert.equal(own.status, 200, own.text);
  assert.equal(own.location, `${manager.deckUrl}/p/zone5-council/`, 'on the deck address');
  assert.match(own.text, /portal-edit-presentation/);
  assert.ok(own.text.includes(`${manager.url}/studio/zone5-council`), 'the edit button leads to the editor page on the manager address');
  const shared = await openDeck('/p/shared-talk/', AS.zl5);
  assert.equal(shared.status, 200);
  assert.doesNotMatch(shared.text, /portal-edit-presentation/);
  assert.equal((await openDeck('/p/zone6-council/', AS.zl5)).status, 403);
  assert.equal((await openDeck('/p/mission-dashboard/', AS.stl5)).status, 403);
  assert.equal((await openDeck('/p/shared-talk/', AS.dl)).status, 403);
  // Managers see zone decks fully (round 8; round 7 served them sandboxed, an empty page): no sandbox header.
  const ap = await openDeck('/p/zone5-council/', AS.ap);
  assert.equal(ap.status, 200);
  assert.match(ap.text, /<title>built<\/title>/);
  assert.doesNotMatch(ap.csp, /sandbox/);
  assert.match(ap.csp, /^frame-ancestors /, 'only the portal and the manager address may frame it');
});

test("charts: a ZL's builder list and previews are their own; DLs get none", { skip }, async () => {
  const spec = { measures: ['friends_found.actual'], level: 'mission' };
  assert.equal((await api('/api/charts/catalog', { as: AS.ap })).json.who, 'user-ap');
  assert.equal((await api('/api/charts/catalog', { as: AS.zl5 })).json.who, 'user-zl5', "never the managers' list");
  assert.equal((await api('/api/charts/catalog', { as: AS.stl5 })).json.who, 'user-stl5');
  assert.equal((await api('/api/charts/catalog', { as: AS.dl })).status, 403);
  const preview = await api('/api/charts/data', { method: 'POST', as: AS.zl5, body: { deck: 'zone5-council', spec } });
  assert.equal(preview.status, 200, preview.text);
  assert.equal(preview.json.meta.who, 'user-zl5');
  assert.equal((await api('/api/charts/data', { method: 'POST', as: AS.zl5, body: { deck: 'shared-talk', spec } })).status, 403, 'not written in the shared deck');
  assert.equal((await api('/api/charts/data', { method: 'POST', as: AS.zl5, body: { deck: 'zone6-council', spec } })).status, 403);
  assert.equal((await api('/api/charts/data', { method: 'POST', as: AS.dl, body: { deck: 'zone5-council', spec } })).status, 403);
});
