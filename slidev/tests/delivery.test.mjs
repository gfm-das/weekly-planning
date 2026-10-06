// Unit tests of manager/delivery.mjs (compression, cache headers, addon
// fingerprint, short memory, the build queue, editor warm-up). Plain Node, no packages.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { acceptedEncoding, cacheControlFor, importsOf, JobQueue, moduleEntries, packableAnswer, precompressDir, ShortMemory, treeFingerprint, warmModuleGraph } from '../manager/delivery.mjs';

const tmp = () => fs.mkdtemp(path.join(os.tmpdir(), 'delivery-'));

test('precompressDir writes .br and .gz for text files only', async () => {
  const dir = await tmp();
  await fs.mkdir(path.join(dir, 'assets'));
  const js = 'const x = "hello world";\n'.repeat(400);
  await fs.writeFile(path.join(dir, 'assets', 'app-abc123.js'), js);
  await fs.writeFile(path.join(dir, 'index.html'), '<p>tiny</p>');
  await fs.writeFile(path.join(dir, 'assets', 'logo.png'), Buffer.alloc(5000, 7));
  const summary = await precompressDir(dir);
  assert.equal(summary.files, 1);
  const br = await fs.readFile(path.join(dir, 'assets', 'app-abc123.js.br'));
  const gz = await fs.readFile(path.join(dir, 'assets', 'app-abc123.js.gz'));
  assert.equal(zlib.brotliDecompressSync(br).toString(), js);
  assert.equal(zlib.gunzipSync(gz).toString(), js);
  assert.ok(br.length < js.length / 10);
  await assert.rejects(fs.access(path.join(dir, 'index.html.gz')), 'below 1 KB');
  await assert.rejects(fs.access(path.join(dir, 'assets', 'logo.png.gz')), 'images are left alone');
});

test('precompressDir reuses the last build\'s packed copies of files that did not change, and only of those', async () => {
  const before = await tmp(), after = await tmp();
  const same = 'export const same = "Slidev\'s own code";\n'.repeat(300);
  const changed = 'export const slides = "the deck";\n'.repeat(300);
  for (const dir of [before, after]) await fs.mkdir(path.join(dir, 'assets'));
  await fs.writeFile(path.join(before, 'assets', 'vendor-aaa.js'), same);
  await fs.writeFile(path.join(before, 'assets', 'slides-bbb.js'), changed);
  await precompressDir(before);
  // A marker in the old copy shows it was taken over, not packed again.
  await fs.writeFile(path.join(before, 'assets', 'vendor-aaa.js.gz'), zlib.gzipSync(same, { level: 1 }));
  await fs.writeFile(path.join(after, 'assets', 'vendor-aaa.js'), same);
  await fs.writeFile(path.join(after, 'assets', 'slides-bbb.js'), changed.replace('the deck', 'the new deck'));
  await fs.writeFile(path.join(after, 'index.html'), '<p>new page</p>'.repeat(100));
  const summary = await precompressDir(after, { reuseFrom: before });
  assert.deepEqual([summary.files, summary.reused], [3, 1]);
  assert.deepEqual(await fs.readFile(path.join(after, 'assets', 'vendor-aaa.js.gz')), await fs.readFile(path.join(before, 'assets', 'vendor-aaa.js.gz')));
  assert.deepEqual(await fs.readFile(path.join(after, 'assets', 'vendor-aaa.js.br')), await fs.readFile(path.join(before, 'assets', 'vendor-aaa.js.br')));
  for (const file of ['assets/slides-bbb.js', 'index.html']) {
    const plain = await fs.readFile(path.join(after, file), 'utf8');
    assert.equal(zlib.gunzipSync(await fs.readFile(path.join(after, `${file}.gz`))).toString(), plain, file);
    assert.equal(zlib.brotliDecompressSync(await fs.readFile(path.join(after, `${file}.br`))).toString(), plain, file);
  }
  // No last build (a new deck): everything is packed.
  assert.equal((await precompressDir(after, { reuseFrom: path.join(before, 'missing') })).reused, 0);
});

test('packableAnswer: whole text answers of the editor, 1 KB or more, for a browser that takes gzip', () => {
  const get = { method: 'GET', headers: { 'accept-encoding': 'gzip, deflate, br' } };
  const js = { 'content-type': 'text/javascript', 'content-length': '5000' };
  assert.equal(packableAnswer(get, 200, js), true);
  assert.equal(packableAnswer(get, 200, { 'content-type': 'application/json' }), true, 'size unknown (chunked)');
  assert.equal(packableAnswer(get, 200, { 'content-type': 'text/css; charset=utf-8', 'content-length': '2048' }), true);
  assert.equal(packableAnswer(get, 304, js), false, '"not changed" has no body');
  assert.equal(packableAnswer(get, 206, js), false, 'a part of a file');
  assert.equal(packableAnswer({ ...get, method: 'HEAD' }, 200, js), false);
  assert.equal(packableAnswer(get, 200, { ...js, 'content-length': '900' }), false, 'too small to be worth it');
  assert.equal(packableAnswer(get, 200, { ...js, 'content-encoding': 'br' }), false, 'packed already');
  assert.equal(packableAnswer(get, 200, { 'content-type': 'image/png', 'content-length': '50000' }), false);
  assert.equal(packableAnswer(get, 200, { 'content-type': 'text/event-stream' }), false, 'never a stream');
  assert.equal(packableAnswer({ method: 'GET', headers: {} }, 200, js), false, 'a browser that does not take gzip');
});

test('acceptedEncoding prefers br, respects q=0 and what exists', () => {
  assert.equal(acceptedEncoding('gzip, deflate, br', { br: true, gzip: true }), 'br');
  assert.equal(acceptedEncoding('gzip, deflate, br', { br: false, gzip: true }), 'gzip');
  assert.equal(acceptedEncoding('gzip', { br: true, gzip: true }), 'gzip');
  assert.equal(acceptedEncoding('br;q=0, gzip;q=0.5', { br: true, gzip: true }), 'gzip');
  assert.equal(acceptedEncoding('*', { br: true }), 'br');
  assert.equal(acceptedEncoding('identity', { br: true, gzip: true }), null);
  assert.equal(acceptedEncoding('', { br: true, gzip: true }), null);
  assert.equal(acceptedEncoding(undefined, { gzip: true }), null);
});

test('cache headers: hashed assets for a year, pages checked every time', () => {
  assert.equal(cacheControlFor('assets/index-DWuQGe_H.js'), 'private, max-age=31536000, immutable');
  assert.equal(cacheControlFor('assets/modules/shiki-x.js'), 'private, max-age=31536000, immutable');
  assert.equal(cacheControlFor('index.html'), 'private, no-cache');
  assert.equal(cacheControlFor('cover.svg'), 'private, no-cache');
  assert.equal(cacheControlFor('my-assets/x.js'), 'private, no-cache');
});

test('treeFingerprint changes with content, not with dotfiles', async () => {
  const dir = await tmp();
  await fs.writeFile(path.join(dir, 'a.ts'), 'one');
  await fs.mkdir(path.join(dir, 'lib'));
  await fs.writeFile(path.join(dir, 'lib', 'b.mjs'), 'two');
  const first = treeFingerprint([dir]);
  assert.match(first, /^[0-9a-f]{16}$/);
  await fs.writeFile(path.join(dir, '.cache'), 'ignored');
  await fs.mkdir(path.join(dir, 'node_modules'));
  await fs.writeFile(path.join(dir, 'node_modules', 'x.js'), 'ignored');
  assert.equal(treeFingerprint([dir]), first);
  await fs.writeFile(path.join(dir, 'lib', 'b.mjs'), 'three');
  assert.notEqual(treeFingerprint([dir]), first);
  assert.notEqual(treeFingerprint([dir, path.join(dir, 'missing')]), treeFingerprint([dir]));
});

test('ShortMemory forgets after the time and keeps at most max', async () => {
  const memory = new ShortMemory(40, 2);
  memory.set('a', 1);
  assert.equal(memory.get('a'), 1);
  memory.set('b', 2);
  memory.set('c', 3);
  assert.equal(memory.get('a'), undefined, 'oldest dropped');
  await new Promise(r => setTimeout(r, 60));
  assert.equal(memory.get('b'), undefined, 'expired');
  memory.set('d', 4);
  memory.delete('d');
  assert.equal(memory.get('d'), undefined);
});

test('module entries and imports (static, dynamic except heavy tools, ?url files)', () => {
  const page = 'http://127.0.0.1:3100/edit/deck/1';
  assert.deepEqual(moduleEntries('<script type="module" src="/edit/deck/@vite/client"></script><script type="module" src="/edit/deck/@fs/main.ts"></script>', page),
    ['http://127.0.0.1:3100/edit/deck/@vite/client', 'http://127.0.0.1:3100/edit/deck/@fs/main.ts']);
  const code = [
    'import { a } from "/edit/deck/@fs/x.js?v=1234abcd"',
    'import "./side.css"',
    'export * from "../y.ts"',
    'import vue from "vue"',
    'const s = () => import("/edit/deck/@slidev/slides/2/md")',
    'const p = () => import("/edit/deck/@fs/slidev/node_modules/@slidev/client/pages/play.vue")',
    'const m = () => import("/edit/deck/@fs/monaco.js")',
    'const e = () => import("/edit/deck/@fs/slidev/node_modules/@slidev/client/pages/export.vue")',
    'import x from "http://elsewhere.test/z.js"',
  ].join('\n');
  assert.deepEqual(importsOf(code, 'http://127.0.0.1:3100/edit/deck/@fs/main.ts'), [
    'http://127.0.0.1:3100/edit/deck/@fs/x.js?v=1234abcd',
    'http://127.0.0.1:3100/edit/deck/@fs/side.css',
    'http://127.0.0.1:3100/edit/deck/y.ts',
    'http://127.0.0.1:3100/edit/deck/@slidev/slides/2/md',
    'http://127.0.0.1:3100/edit/deck/@fs/slidev/node_modules/@slidev/client/pages/play.vue',
  ]);
  // A `?url` module answers with the file's address: that file is fetched too.
  assert.deepEqual(importsOf('export default "/edit/deck/@fs/slidev/manager/vendor/echarts.min.js"', 'http://127.0.0.1:3100/edit/deck/@fs/slidev/manager/vendor/echarts.min.js?url'),
    ['http://127.0.0.1:3100/edit/deck/@fs/slidev/manager/vendor/echarts.min.js']);
  assert.deepEqual(importsOf('export default "/elsewhere.js"', 'http://127.0.0.1:3100/edit/deck/@fs/a.js'), [], 'only for ?url modules');
});

function server(routes) {
  const hits = [];
  const srv = http.createServer((req, res) => {
    hits.push(req.url);
    const route = routes[req.url.split('?')[0]] ?? routes[req.url];
    if (!route) { res.writeHead(404); return res.end('no'); }
    const [type, body, delay = 0] = route;
    setTimeout(() => { res.writeHead(200, { 'Content-Type': type }); res.end(body); }, delay);
  });
  return new Promise(resolve => srv.listen(0, '127.0.0.1', () => resolve({ srv, hits, url: `http://127.0.0.1:${srv.address().port}` })));
}

test('warmModuleGraph walks the graph once, and twice if deps were re-bundled', async () => {
  const js = 'text/javascript';
  const { srv, hits, url } = await server({
    '/edit/d/1': ['text/html', '<script type="module" src="/edit/d/@fs/main.ts"></script>'],
    '/edit/d/@fs/main.ts': [js, 'import "/edit/d/@fs/a.js"; import "/edit/d/@slidev/slides"'],
    '/edit/d/@fs/a.js': [js, 'import "/edit/d/node_modules/.vite/deps/vue.js?v=11111111"; import "/edit/d/node_modules/.vite/deps/yaml.js?v=22222222"'],
    '/edit/d/@slidev/slides': [js, 'const l = () => import("/edit/d/@slidev/slides/1/md")'],
    '/edit/d/@slidev/slides/1/md': [js, 'export default 1'],
    '/edit/d/node_modules/.vite/deps/vue.js': [js, 'export default 2'],
    '/edit/d/node_modules/.vite/deps/yaml.js': [js, 'export default 3'],
  });
  try {
    const result = await warmModuleGraph(`${url}/edit/d/1`);
    assert.equal(result.error, '');
    assert.equal(result.passes, 2, 'two dependency versions seen');
    assert.equal(result.passMs.length, 2, 'the time of each pass');
    assert.equal(result.modules, 12, '6 modules, twice');
    assert.ok(hits.includes('/edit/d/@slidev/slides/1/md'), 'the slides are fetched');
  } finally { srv.close(); }
});

test('warmModuleGraph never throws and stops at its time limit', async () => {
  const { srv, url } = await server({
    '/p': ['text/html', '<script type="module" src="/slow.js"></script>'],
    '/slow.js': ['text/javascript', 'export {}', 500],
  });
  try {
    const slow = await warmModuleGraph(`${url}/p`, { timeoutMs: 100 });
    assert.equal(slow.timedOut, true);
    const missing = await warmModuleGraph(`${url}/nothing`);
    assert.match(missing.error, /404/);
    const down = await warmModuleGraph('http://127.0.0.1:9/nothing', { timeoutMs: 2000 });
    assert.ok(down.error);
  } finally { srv.close(); }
});

// A job that finishes when told to; `log` records starts and ends in order.
function gate(log, name) {
  let open;
  const done = new Promise(resolve => { open = resolve; });
  return { fn: async () => { log.push(`start ${name}`); await done; log.push(`end ${name}`); return name; }, open };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('JobQueue: one job at a time, waiting jobs someone waits for go first', async () => {
  const queue = new JobQueue(1);
  const log = [];
  const a = gate(log, 'a'), b = gate(log, 'b'), c = gate(log, 'c'), d = gate(log, 'd');
  const pa = queue.run(a.fn, { key: 'a', priority: 'later' });
  const pb = queue.run(b.fn, { key: 'b', priority: 'later' });
  const pc = queue.run(c.fn, { key: 'c', priority: 'later' });
  const pd = queue.run(d.fn, { key: 'd', priority: 'now' });
  await tick();
  assert.deepEqual(log, ['start a'], 'only one runs');
  assert.equal(queue.running, 1);
  assert.deepEqual(queue.waiting.map(job => job.key), ['b', 'c', 'd']);
  assert.ok(queue.isWaiting('c') && !queue.isWaiting('a'), 'a started, c waits');
  queue.hurry('c');
  a.open(); await pa; await tick();
  assert.deepEqual(log.slice(-1), ['start c'], 'hurried c goes first (it came before d)');
  c.open(); await pc; await tick();
  assert.deepEqual(log.slice(-1), ['start d'], 'then d, which someone waits for, before b');
  d.open(); b.open();
  assert.deepEqual(await Promise.all([pb, pd]), ['b', 'd']);
  assert.deepEqual(log, ['start a', 'end a', 'start c', 'end c', 'start d', 'end d', 'start b', 'end b']);
  await tick();
  assert.equal(queue.running, 0);
  assert.equal(queue.waiting.length, 0);
});

test('JobQueue: a failed job is reported and the next one still runs; limit 2', async () => {
  const one = new JobQueue(1);
  const failed = one.run(async () => { throw new Error('build failed'); });
  const next = one.run(async () => 'next');
  await assert.rejects(failed, /build failed/);
  assert.equal(await next, 'next');
  await tick();
  assert.equal(one.running, 0);

  const two = new JobQueue(2);
  const log = [];
  const gates = ['a', 'b', 'c'].map(name => gate(log, name));
  const runs = gates.map(g => two.run(g.fn));
  await tick();
  assert.deepEqual(log, ['start a', 'start b'], 'two at a time');
  gates[1].open(); await runs[1]; await tick();
  assert.deepEqual(log.slice(-1), ['start c']);
  gates[0].open(); gates[2].open();
  await Promise.all(runs);
  assert.equal(new JobQueue(0).limit, 1, 'at least one');
  assert.equal(new JobQueue('x').limit, 1);
});
