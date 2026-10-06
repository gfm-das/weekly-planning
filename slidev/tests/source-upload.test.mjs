// Upload source (manager/source-upload.mjs): a deck's .zip read back in. The ZIPs are made here with Node's zlib, the same
// way Download source's archiver makes them (entries under <slug>/, deflated). Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { cleanPath, MAX_FILES, readSourceZip, UploadError, writeUpload } from '../manager/source-upload.mjs';

const crc = (() => { const t = new Uint32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; }); return b => { let c = 0xffffffff; for (const x of b) c = t[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }; })();

/** A ZIP of { name: text|Buffer }, deflated (or stored with { store: true }). */
function makeZip(files, { store = false, flags = 0 } = {}) {
  const locals = [], centrals = [];
  let offset = 0;
  for (const [name, content] of Object.entries(files)) {
    const data = Buffer.isBuffer(content) ? content : Buffer.from(content);
    const packed = store ? data : zlib.deflateRawSync(data);
    const nameBuf = Buffer.from(name);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(flags, 6); local.writeUInt16LE(store ? 0 : 8, 8);
    local.writeUInt32LE(crc(data), 14); local.writeUInt32LE(packed.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(nameBuf.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(flags, 8); central.writeUInt16LE(store ? 0 : 8, 10);
    central.writeUInt32LE(crc(data), 16); central.writeUInt32LE(packed.length, 20); central.writeUInt32LE(data.length, 24); central.writeUInt16LE(nameBuf.length, 28); central.writeUInt32LE(offset, 42);
    locals.push(local, nameBuf, packed); centrals.push(central, nameBuf);
    offset += 30 + nameBuf.length + packed.length;
  }
  const dir = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(Object.keys(files).length, 8); end.writeUInt16LE(Object.keys(files).length, 10); end.writeUInt32LE(dir.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, dir, end]);
}

const SLIDES = '---\ntheme: default\n---\n\n# Hello\n';

test('a deck\'s source ZIP (everything under its own folder): slides.md and the pictures in public/', () => {
  const zip = makeZip({ 'my-deck/slides.md': SLIDES, 'my-deck/public/photo.jpg': Buffer.from([1, 2, 3, 4]), 'my-deck/public/sub/logo.svg': '<svg/>' });
  const r = readSourceZip(zip, 'my-deck');
  assert.equal(r.markdown, SLIDES);
  assert.deepEqual(r.files.map(f => f.path).sort(), ['public/photo.jpg', 'public/sub/logo.svg']);
  assert.deepEqual([...r.files.find(f => f.path === 'public/photo.jpg').data], [1, 2, 3, 4]);
  assert.deepEqual(r.skipped, []);
});

test('other layouts of a ZIP: slides.md at the top, or one folder around it with another name; stored or deflated', () => {
  assert.equal(readSourceZip(makeZip({ 'slides.md': SLIDES }, { store: true }), 'x').markdown, SLIDES);
  assert.equal(readSourceZip(makeZip({ 'some-folder/slides.md': SLIDES, 'some-folder/public/a.png': 'x' }), 'x').files[0].path, 'public/a.png');
});

test('code is never taken from a ZIP: components, styles, scripts and other folders are left out and listed', () => {
  const r = readSourceZip(makeZip({
    'd/slides.md': SLIDES, 'd/components/Evil.vue': '<script>fetch("x")</script>', 'd/style.css': 'h1{}', 'd/setup/main.ts': 'x', 'd/package.json': '{}',
    'd/public/ok.png': 'x', 'd/public/run.js': 'alert(1)', 'd/public/page.html': '<script>', 'd/node_modules/x/index.js': 'x', 'd/.env': 'SECRET=1',
  }), 'd');
  assert.deepEqual(r.files.map(f => f.path), ['public/ok.png']);
  assert.deepEqual(r.skipped.sort(), ['d/.env', 'd/components/Evil.vue', 'd/node_modules/x/index.js', 'd/package.json', 'd/public/page.html', 'd/public/run.js', 'd/setup/main.ts', 'd/style.css']);
});

test('paths that try to leave the deck are never used', () => {
  for (const name of ['../slides.md', 'd/../../etc/passwd', '/etc/passwd', 'C:/x/slides.md', 'd\\slides.md', 'd/public/../../x.png', './../x']) assert.equal(cleanPath(name), null, name);
  assert.equal(cleanPath('public/a/b.png'), 'public/a/b.png');
  assert.equal(cleanPath('./slides.md'), 'slides.md');
  const r = readSourceZip(makeZip({ 'd/slides.md': SLIDES, 'd/public/../../evil.png': 'x', '../outside.png': 'x' }), 'd');
  assert.deepEqual(r.files, []);
  assert.equal(r.skipped.length, 2);
});

test('mistakes: not a ZIP, no slides.md, damaged, password protected, too many files', () => {
  assert.throws(() => readSourceZip(Buffer.from('hello world, this is not a zip file at all'), 'd'), UploadError);
  assert.throws(() => readSourceZip(Buffer.alloc(10), 'd'), /not a ZIP/);
  assert.throws(() => readSourceZip(makeZip({ 'd/public/a.png': 'x' }), 'd'), /no slides\.md/);
  const bad = makeZip({ 'd/slides.md': SLIDES });
  bad.writeUInt32LE(0, 0); // the first file's signature
  assert.throws(() => readSourceZip(bad, 'd'), /damaged/);
  assert.throws(() => readSourceZip(makeZip({ 'd/slides.md': SLIDES }, { flags: 1 }), 'd'), /password protected/);
  const many = Object.fromEntries(Array.from({ length: MAX_FILES + 2 }, (_, i) => [`d/public/p${i}.png`, 'x']));
  many['d/slides.md'] = SLIDES;
  assert.throws(() => readSourceZip(makeZip(many, { store: true }), 'd'), /more than 400 pictures/);
  assert.throws(() => readSourceZip(makeZip({ 'd/slides.md': 'x'.repeat(1_600_000) }), 'd'), /slides\.md is too large/);
});

test('writing an upload: the old slides.md is kept, the pictures go into public/, nothing leaves the folder', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'upload-'));
  try {
    await fs.writeFile(path.join(dir, 'slides.md'), 'OLD');
    const r = await writeUpload(dir, { markdown: 'NEW', files: [{ path: 'public/a/b.png', data: Buffer.from([9]) }] });
    assert.equal(r.files, 1);
    assert.equal(await fs.readFile(path.join(dir, 'slides.md'), 'utf8'), 'NEW');
    assert.equal(await fs.readFile(path.join(dir, 'slides.md.before-upload'), 'utf8'), 'OLD');
    assert.deepEqual([...await fs.readFile(path.join(dir, 'public/a/b.png'))], [9]);
    await assert.rejects(writeUpload(dir, { markdown: 'X', files: [{ path: '../../escape.png', data: Buffer.from([1]) }] }), /not allowed/);
    assert.equal(await fs.readFile(path.join(dir, 'slides.md'), 'utf8'), 'NEW', 'a refused upload leaves slides.md alone');
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
