// "+ New Presentation" (round 22): the product ships no templates (its one deck, the showcase, is checked by shipped-decks.test.mjs). A new deck is one title
// slide with its name, in the default theme; the library's dialog asks only for the name.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(HERE, '..', '..');
const read = (...parts) => fs.readFileSync(path.join(REPO, ...parts), 'utf8').replace(/\r\n/g, '\n');

test('no templates and no example decks ship', () => {
  for (const gone of ['slidev/showcase', 'slidev/decks', 'slidev/manager/templates', 'slidev/tools/make-mmm-showcase.mjs', 'slidev/manager/gfm-addon/layouts/gfm-freeform.vue', 'slidev/manager/gfm-addon/lib/mmm-core.mjs', 'slidev/manager/gfm-addon/lib/mmm.ts']) assert.equal(fs.existsSync(path.join(REPO, gone)), false, gone);
  assert.deepEqual(fs.readdirSync(path.join(REPO, 'slidev', 'manager', 'gfm-addon', 'components')).filter(f => f.startsWith('Mmm')), [], 'the template building blocks are gone');
  const routes = read('slidev', 'manager', 'manager-routes.mjs');
  assert.doesNotMatch(routes, /presentation-templates|templateList/);
  assert.match(routes, /const \{ title \} = await readBody\(req\);\n  const slug = await createDeck\(title\);/);
});

test('library.html: the dialog asks only for a name, and the empty library says how to start', () => {
  const lib = read('slidev', 'manager', 'library.html');
  assert.doesNotMatch(lib, /templateSelect|langSelect|presentation-templates/);
  assert.match(lib, /body: JSON\.stringify\(\{ title \}\)/);
  assert.match(lib, /'No presentations yet\. Click \+ New Presentation to start one\.'/);
  const catalogs = path.join(REPO, 'portal', 'i18n');
  for (const file of fs.readdirSync(catalogs).filter(f => /^[a-z]{2}\.json$/.test(f))) {
    const c = JSON.parse(fs.readFileSync(path.join(catalogs, file), 'utf8'));
    assert.ok(c['pres.noPresentationsYet'], file);
    if (file !== 'en.json') assert.notEqual(c['pres.noPresentationsYet'], 'No presentations yet. Click + New Presentation to start one.', file);
  }
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

test('the real manager: a new deck is one title slide with its name; a name that makes no address is refused', { skip, timeout: 60000 }, () => withManager(async (api, manager) => {
  const made = await api('/api/presentations', { method: 'POST', body: { title: 'Zone council: <May>' } });
  assert.equal(made.status, 201, made.raw);
  const written = fs.readFileSync(path.join(manager.decks, made.json.slug, 'slides.md'), 'utf8');
  assert.equal(written, '---\ntitle: "Zone council: May"\ntheme: default\n---\n\n# Zone council: May\n', 'one title slide, the default theme');
  assert.doesNotMatch(written, /<May>|Mmm|layout:/);
  // An old page that still sends a template gets the same blank deck.
  const old = await api('/api/presentations', { method: 'POST', body: { title: 'Old page', template: 'mmm-main', lang: 'de' } });
  assert.equal(old.status, 201);
  assert.doesNotMatch(fs.readFileSync(path.join(manager.decks, old.json.slug, 'slides.md'), 'utf8'), /Mmm/);
  const folders = fs.readdirSync(manager.decks).length;
  const bad = await api('/api/presentations', { method: 'POST', body: { title: '!!!' } });
  assert.notEqual(bad.status, 201, bad.raw);
  assert.match(bad.raw, /Presentation name is required/);
  assert.equal(fs.readdirSync(manager.decks).length, folders);
  const list = await api('/api/presentation-templates');
  assert.equal(list.status, 404);
}));
