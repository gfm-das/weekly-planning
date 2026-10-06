// Round 9 (speed): what the manager address sends packed (gzip), checked on the real manager/server.mjs
// (tests/helpers/manager-harness.mjs):
//   - its pages (the library) and portal-bridge.js, which a browser that has it only checks again ("not changed");
//   - Monaco, the text editor of Source (its main file is 3.6 MB as it is), packed only for a GET that takes gzip;
//   - files that are not text (a picture) go as they are.
// The unit parts are tested in web.test.mjs (sendHtml, sendKept) and delivery.test.mjs (packableAnswer, the build's
// packed copies). Needs a POSIX shell (node:24-alpine), like the other tests that start the manager.
import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, test } from 'node:test';
import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import { startManager, startStub, supabaseAnswer } from './helpers/manager-harness.mjs';

const posix = await fs.access('/bin/sh').then(() => true, () => false);
const skip = posix ? false : 'needs a POSIX shell (run in node:24-alpine)';

let manager, supabase, monaco;
before(async () => {
  if (skip) return;
  supabase = await startStub((req, url) => supabaseAnswer(req, url) || [404, {}]);
  manager = await startManager({ env: { SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`, PRESENTATION_ACL_API_URL: 'http://127.0.0.1:9' } });
  // A stand-in for Slidev's Monaco (MONACO_DIR is <Slidev's folder>/node_modules/monaco-editor/min/vs).
  monaco = path.join(path.dirname(manager.decks), 'node_modules', 'monaco-editor', 'min', 'vs');
  await fs.mkdir(path.join(monaco, 'editor'), { recursive: true });
  await fs.writeFile(path.join(monaco, 'editor', 'editor.main.js'), 'define("vs/editor/editor.main", [], function () {});\n'.repeat(500));
  await fs.writeFile(path.join(monaco, 'editor', 'logo.png'), Buffer.alloc(4000, 9));
});
after(async () => {
  await manager?.stop();
  supabase?.close();
});

/** A GET (or `method`) with these headers, the answer's bytes as they came (Node's fetch would unpack them). */
function get(pathname, headers = {}, method = 'GET') {
  return new Promise((resolve, reject) => {
    http.request(`${manager.url}${pathname}`, { method, headers }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    }).on('error', reject).end();
  });
}

test('the library page goes packed to a browser that takes gzip, and as it is to one that does not', { skip }, async () => {
  const packed = await get('/', { 'Accept-Encoding': 'gzip, deflate, br' });
  assert.equal(packed.status, 200);
  assert.equal(packed.headers['content-encoding'], 'gzip');
  const page = zlib.gunzipSync(packed.body).toString();
  assert.match(page, /<title>Presentations<\/title>/);
  assert.ok(packed.body.length < page.length / 3, `${packed.body.length} of ${page.length} bytes`);
  const plain = await get('/');
  assert.equal(plain.headers['content-encoding'], undefined);
  assert.equal(plain.body.toString(), page);
});

test('portal-bridge.js: packed, and "not changed" (304, nothing sent) for a browser that has it', { skip }, async () => {
  const first = await get('/_manager/portal-bridge.js', { 'Accept-Encoding': 'gzip' });
  assert.equal(first.status, 200);
  assert.equal(first.headers['content-encoding'], 'gzip');
  assert.match(zlib.gunzipSync(first.body).toString(), /PresentationSession/);
  assert.ok(first.headers.etag);
  const again = await get('/_manager/portal-bridge.js', { 'Accept-Encoding': 'gzip', 'If-None-Match': first.headers.etag });
  assert.deepEqual([again.status, again.body.length], [304, 0]);
});

test('Monaco: text packed once and checked again with its fingerprint; a picture as it is', { skip }, async () => {
  const file = '/vendor/monaco/vs/editor/editor.main.js';
  const original = await fs.readFile(path.join(monaco, 'editor', 'editor.main.js'));
  const packed = await get(file, { 'Accept-Encoding': 'gzip' });
  assert.equal(packed.status, 200);
  assert.equal(packed.headers['content-encoding'], 'gzip');
  assert.equal(packed.headers['cache-control'], 'public, max-age=604800');
  assert.deepEqual(zlib.gunzipSync(packed.body), original);
  assert.ok(packed.body.length < original.length / 10);
  assert.equal((await get(file, { 'Accept-Encoding': 'gzip', 'If-None-Match': packed.headers.etag })).status, 304);
  const plain = await get(file);
  assert.equal(plain.headers['content-encoding'], undefined);
  assert.deepEqual(plain.body, original);
  const picture = await get('/vendor/monaco/vs/editor/logo.png', { 'Accept-Encoding': 'gzip' });
  assert.deepEqual([picture.status, picture.headers['content-encoding'], picture.headers['content-type'], picture.body.length], [200, undefined, 'image/png', 4000]);
  assert.equal((await get('/vendor/monaco/vs/../../../../package.json', { 'Accept-Encoding': 'gzip' })).status, 404, 'nothing outside Monaco');
});

// Round 9 review: packing costs work, so only a GET from a browser that takes gzip causes it. A HEAD, or a browser
// without gzip, gets the file from the disk as it is (no fingerprint: it never went through the packed copy).
test('Monaco: a HEAD, or a browser without gzip, gets the plain file from the disk (nothing is packed for it)', { skip }, async () => {
  const name = path.join(monaco, 'editor', 'editor.worker.js');
  const original = Buffer.from('self.onmessage = () => {};\n'.repeat(300));
  await fs.writeFile(name, original);
  const file = '/vendor/monaco/vs/editor/editor.worker.js';
  const head = await get(file, { 'Accept-Encoding': 'gzip' }, 'HEAD');
  assert.deepEqual([head.status, head.headers['content-encoding'], head.headers.etag, head.body.length], [200, undefined, undefined, 0]);
  assert.equal(head.headers['content-length'], String(original.length));
  assert.equal(head.headers.vary, 'Accept-Encoding');
  const plain = await get(file, { 'Accept-Encoding': 'identity' });
  assert.deepEqual([plain.status, plain.headers['content-encoding'], plain.headers.etag], [200, undefined, undefined]);
  assert.deepEqual(plain.body, original);
  const packed = await get(file, { 'Accept-Encoding': 'gzip' });
  assert.equal(packed.headers['content-encoding'], 'gzip');
  assert.deepEqual(zlib.gunzipSync(packed.body), original);
});
