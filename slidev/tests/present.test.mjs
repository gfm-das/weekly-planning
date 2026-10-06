// Round 6 (Presentations): screen mirroring in the presenter view and Download PDF in published decks.
//
// 1. Download PDF: the addon's preparser turns on Slidev's browser exporter (/export) in builds only,
//    and never overrides a deck's own setting. With Slidev's real parser when it is installed (the
//    node:24-alpine test container with the live node_modules); skipped otherwise.
// 2. Screen mirroring: why it cannot start (plain http, frame without display-capture, no
//    getDisplayMedia), the failure sentences, and the Vite plugin that swaps in the addon's panel.
// 3. Every frame that shows decks allows display-capture, and nothing sends a Permissions-Policy.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { publishedDeckPreparser } from '../manager/gfm-addon/lib/published-deck.mjs';
import { isSlidevScreenMirror, localAddress, mirrorFailure, mirrorProblem } from '../manager/gfm-addon/lib/screen-mirror.mjs';

const ADDON = fileURLToPath(new URL('../manager/gfm-addon/', import.meta.url));
const REPO = fileURLToPath(new URL('../../', import.meta.url));
const read = file => readFileSync(file, 'utf8').replace(/\r\n/g, '\n');

// ---- 1. Download PDF ----

test('preparser: builds get browserExporter on the headmatter (the first slide) only', () => {
  const [ext, ...rest] = publishedDeckPreparser({ mode: 'build' });
  assert.equal(rest.length, 0);
  const head = { title: 'Deck' }, second = {}, third = { layout: 'cover' };
  for (const fm of [head, second, third]) assert.equal(ext.transformSlide('# x', fm), undefined, 'the content is unchanged');
  assert.deepEqual(head, { title: 'Deck', browserExporter: true });
  assert.deepEqual(second, {});
  assert.deepEqual(third, { layout: 'cover' });
});

test('preparser: a deck\'s own browserExporter setting is kept', () => {
  for (const own of [false, 'dev', 'build', true]) {
    const [ext] = publishedDeckPreparser({ mode: 'build' });
    const head = { browserExporter: own };
    ext.transformSlide('', head);
    assert.deepEqual(head, { browserExporter: own });
  }
});

test('preparser: the editor (dev) and the CLI export are left alone', () => {
  for (const mode of ['dev', 'export', undefined, '']) assert.deepEqual(publishedDeckPreparser({ mode }), [], String(mode));
  assert.deepEqual(publishedDeckPreparser(), []);
});

test('setup/preparser.ts is the preparser Slidev loads (Node strips its types)', async () => {
  const mod = await import(pathToFileURL(path.join(ADDON, 'setup', 'preparser.ts')));
  // Round 7: the deck-folder guard (zone-decks.test.mjs) runs in every mode, the exporter only in builds.
  assert.deepEqual(mod.default({ mode: 'dev' }).map(e => e.name), ['gfm-addon:deck-folder']);
  assert.deepEqual(mod.default({ mode: 'build' }).map(e => e.name), ['gfm-addon:deck-folder', 'gfm-addon:browser-exporter']);
});

// Slidev's own parser, as `slidev build` runs it (roots with this addon, mode 'build').
const PARSER_FS = ['/slidev/node_modules/@slidev/parser/dist/fs.mjs', path.join(REPO, 'slidev/node_modules/@slidev/parser/dist/fs.mjs')].find(f => existsSync(f));
test('with Slidev 52\'s parser: headmatter gets browserExporter in build mode; slides, imports and dev do not', { skip: PARSER_FS ? false : 'Slidev\'s parser is not installed here (run in the test container)' }, async () => {
  const { load, injectPreparserExtensionLoader } = await import(pathToFileURL(PARSER_FS));
  injectPreparserExtensionLoader(async (_roots, headmatter, filepath, mode) => publishedDeckPreparser({ headmatter, filepath, mode }));
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'present-parser-'));
  try {
    await fs.writeFile(path.join(dir, 'part.md'), '---\nlayout: center\n---\n\n# Imported\n');
    const decks = {
      'with-head.md': '---\ntitle: With head\ntheme: default\n---\n\n# One\n\n---\nlayout: two-cols\n---\n\n# Two\n\n---\nsrc: ./part.md\n---\n',
      'no-head.md': '# Only a slide\n\n---\n\n# Second\n',
      'own-setting.md': '---\ntitle: Own\nbrowserExporter: false\n---\n\n# One\n',
    };
    for (const [name, text] of Object.entries(decks)) await fs.writeFile(path.join(dir, name), text);
    const opts = { userRoot: dir, roots: [dir, ADDON], allowedRoots: [dir, ADDON] };

    const built = await load(opts, path.join(dir, 'with-head.md'), undefined, 'build');
    assert.equal(built.headmatter.browserExporter, true);
    assert.equal(built.headmatter.title, 'With head');
    assert.ok(built.slides.slice(1).every(s => !('browserExporter' in (s.frontmatter || {}))), 'only the headmatter');
    assert.equal(built.slides.length, 3);

    assert.equal((await load(opts, path.join(dir, 'no-head.md'), undefined, 'build')).headmatter.browserExporter, true);
    assert.equal((await load(opts, path.join(dir, 'own-setting.md'), undefined, 'build')).headmatter.browserExporter, false);
    assert.equal('browserExporter' in (await load(opts, path.join(dir, 'with-head.md'), undefined, 'dev')).headmatter, false, 'the editor is unchanged');
  }
  finally {
    injectPreparserExtensionLoader(null);
    await fs.rm(dir, { recursive: true, force: true });
  }
});

// ---- 2. Screen mirroring ----

const lanFrame = {
  isSecureContext: false,
  location: { origin: 'http://192.168.1.20:3030', href: 'http://192.168.1.20:3030/p/weekly/presenter/3', ancestorOrigins: { length: 1, 0: 'http://192.168.1.20:8070' } },
  navigator: {},
  document: {},
};

test('mirror: plain http on the office network says why and what to do (the portal on localhost)', () => {
  const p = mirrorProblem(lanFrame);
  assert.equal(p.kind, 'insecure');
  assert.equal(p.title, 'Screen mirroring is not available at this address');
  assert.match(p.lines[0], /secure \(https\) address or on localhost\. This presentation is open at http:\/\/192\.168\.1\.20:8070\./);
  assert.match(p.lines[1], /choose Slides above/);
  assert.match(p.lines[2], /open http:\/\/localhost:8070 and present from there/);
  assert.match(p.lines[3], /ask the data office to allow this address/);
  // Opened on its own (no portal around it): the deck's own address.
  const alone = { ...lanFrame, location: { origin: 'http://192.168.1.20:3030', href: '', ancestorOrigins: { length: 0 } } };
  assert.equal(localAddress(alone), 'http://localhost:3030');
});

test('mirror: secure but the frame lacks display-capture: open the presenter view in a new tab', () => {
  const win = {
    isSecureContext: true,
    location: { origin: 'http://localhost:3030', href: 'http://localhost:3030/p/weekly/presenter/2', ancestorOrigins: { length: 1, 0: 'http://localhost:8070' } },
    navigator: { mediaDevices: { getDisplayMedia() {} } },
    document: { featurePolicy: { allowsFeature: f => f !== 'display-capture' } },
  };
  const p = mirrorProblem(win);
  assert.equal(p.kind, 'frame');
  assert.deepEqual(p.link, { href: 'http://localhost:3030/p/weekly/presenter/2', text: 'Open the presenter view in a new tab' });
  win.document = { featurePolicy: { allowsFeature: () => true } };
  assert.equal(mirrorProblem(win), null, 'allowed: Slidev\'s button is shown');
  win.document = {};
  assert.equal(mirrorProblem(win), null, 'a browser without the policy API: try');
});

test('mirror: a browser without getDisplayMedia (a phone) says so', () => {
  const p = mirrorProblem({ isSecureContext: true, location: { origin: 'https://x' }, navigator: { mediaDevices: {} }, document: {} });
  assert.equal(p.kind, 'unsupported');
  assert.match(p.lines[0], /phones and tablets cannot/);
});

test('mirror: failures after the click are explained', () => {
  const err = (name, message = '') => Object.assign(new Error(message), { name });
  assert.match(mirrorFailure(err('NotAllowedError')), /cancelled or not allowed\. Click Start Screen Mirroring again/);
  assert.match(mirrorFailure(err('AbortError')), /cancelled or not allowed/);
  assert.match(mirrorFailure(err('NotFoundError')), /no screen or window/);
  assert.match(mirrorFailure(err('NotReadableError')), /could not be captured/);
  assert.match(mirrorFailure(new TypeError('Cannot read properties of undefined')), /not available at this address/);
  assert.equal(mirrorFailure(err('OddError', 'boom')), 'Screen mirroring did not start (OddError: boom).');
  assert.equal(mirrorFailure(undefined), 'Screen mirroring did not start.');
});

test('mirror: the Vite plugin swaps in the addon\'s panel for Slidev\'s presenter page only', async () => {
  const presenter = '/slidev/node_modules/@slidev/client/pages/presenter.vue';
  assert.equal(isSlidevScreenMirror('../internals/ScreenCaptureMirror.vue', presenter), true);
  assert.equal(isSlidevScreenMirror('../internals/ScreenCaptureMirror.vue', `${presenter}?vue&type=script&setup=true&lang.ts`), true);
  assert.equal(isSlidevScreenMirror('../internals/ScreenCaptureMirror.vue', 'C:\\x\\node_modules\\@slidev\\client\\pages\\presenter.vue'), true);
  assert.equal(isSlidevScreenMirror('../internals/ScreenCaptureMirror.vue', '/slidev/node_modules/@slidev/client/pages/play.vue'), false);
  assert.equal(isSlidevScreenMirror('../internals/NavControls.vue', presenter), false);
  assert.equal(isSlidevScreenMirror('../internals/ScreenCaptureMirror.vue', undefined), false);

  const mod = await import(pathToFileURL(path.join(ADDON, 'setup', 'vite-plugins.ts')));
  const plugin = mod.default({}).find(p => p.name === 'gfm-addon:screen-mirror');
  assert.equal(plugin.enforce, 'pre');
  const target = plugin.resolveId('../internals/ScreenCaptureMirror.vue', presenter);
  assert.equal(path.resolve(target), path.join(ADDON, 'presenter', 'ScreenMirror.vue'));
  assert.ok(existsSync(target));
  assert.equal(plugin.resolveId('vue', presenter), null);

  const panel = read(target);
  assert.match(panel, /from '\.\.\/lib\/screen-mirror\.mjs'/);
  assert.match(panel, /catch \(error\) \{\s*failure\.value = mirrorFailure\(error\)/, 'a refused capture is reported');
  assert.match(panel, /Start Screen Mirroring/);
  assert.match(panel, /track\.stop\(\)/, 'the capture stops when the panel closes');
});

// ---- 3. Frames and headers ----

const allowOf = (html, re) => (re.exec(html) || [])[1] || '';

test('frames: the portal frame and the editor frame allow display-capture (and keep fullscreen)', () => {
  const portal = allowOf(read(path.join(REPO, 'portal/index.template.html')), /<iframe\s+id="appFrame"\s+allow="([^"]*)"/);
  const studio = allowOf(read(path.join(REPO, 'slidev/manager/studio.html')), /<iframe id="studio"[^>]*allow="([^"]*)"/);
  for (const [name, allow] of [['portal', portal], ['studio', studio]]) {
    const features = allow.split(';').map(s => s.trim());
    assert.ok(features.includes('display-capture'), `${name}: ${allow}`);
    assert.ok(features.includes('fullscreen'), `${name}: ${allow}`);
  }
  assert.ok(studio.includes('clipboard-read') && studio.includes('clipboard-write'), 'the editor keeps its clipboard');
});

test('headers: no Permissions-Policy or feature policy that would block screen capture', async () => {
  // Every file of the manager's server (it was one server.mjs until round 9).
  const managerFiles = (await fs.readdir(path.join(REPO, 'slidev/manager'))).filter(name => name.endsWith('.mjs')).map(name => `slidev/manager/${name}`);
  assert.ok(managerFiles.includes('slidev/manager/manager-routes.mjs') && managerFiles.includes('slidev/manager/deck-routes.mjs'));
  for (const file of ['portal/nginx.conf', ...managerFiles]) {
    assert.doesNotMatch(read(path.join(REPO, file)), /Permissions-Policy|Feature-Policy/i, file);
  }
});
