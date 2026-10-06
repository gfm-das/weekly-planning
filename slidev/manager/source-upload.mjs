// Upload source: a deck's .zip (what "Download source" makes) read back in.
//
// What it is: reads a ZIP with Node's own zlib (no package), and picks out what a deck's source is made of:
//   slides.md   the slides (the one file the deck cannot be without)
//   public/…    the pictures and videos the slides use
// Everything else in the ZIP (components, styles, scripts, other folders) is left out and listed, so an upload can never put
// code on the deck address that the person did not write in Source. A path that tries to leave the deck's folder ("../")
// or that is not plain is refused. Limits keep a bad ZIP from filling the disk.
// Who uses it: manager-routes.mjs (POST …/upload). The ZIP side of the editor page's "Upload source".
import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';

export const MAX_ZIP_BYTES = 40 * 1024 * 1024;
export const MAX_FILES = 400;
export const MAX_UNPACKED_BYTES = 80 * 1024 * 1024;
export const MAX_MARKDOWN_BYTES = 1_500_000;
const ASSET_EXT = /\.(png|jpe?g|gif|svg|webp|avif|ico|mp4|webm|mp3|wav|ogg|woff2?|ttf|otf|json|csv)$/i;

/** A mistake in an upload, with a sentence for the person. */
export class UploadError extends Error {}

function readCentral(zip) {
  // The end of central directory record: the last 22+ bytes, signature 0x06054b50.
  let eocd = -1;
  for (let i = zip.length - 22; i >= Math.max(0, zip.length - 22 - 65535); i--) {
    if (zip.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new UploadError('This is not a ZIP file.');
  const count = zip.readUInt16LE(eocd + 10);
  let at = zip.readUInt32LE(eocd + 16);
  if (count > MAX_FILES * 4) throw new UploadError('This ZIP has too many files.');
  const entries = [];
  for (let n = 0; n < count; n++) {
    if (at + 46 > zip.length || zip.readUInt32LE(at) !== 0x02014b50) throw new UploadError('This ZIP file is damaged.');
    const flags = zip.readUInt16LE(at + 8);
    const method = zip.readUInt16LE(at + 10);
    const compressed = zip.readUInt32LE(at + 20);
    const size = zip.readUInt32LE(at + 24);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    const name = zip.toString(flags & 0x800 ? 'utf8' : 'latin1', at + 46, at + 46 + nameLength);
    entries.push({ name, method, compressed, size, local, encrypted: !!(flags & 1) });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function dataOf(zip, entry) {
  if (entry.encrypted) throw new UploadError(`${entry.name} is password protected.`);
  const at = entry.local;
  if (at + 30 > zip.length || zip.readUInt32LE(at) !== 0x04034b50) throw new UploadError('This ZIP file is damaged.');
  const start = at + 30 + zip.readUInt16LE(at + 26) + zip.readUInt16LE(at + 28);
  const raw = zip.subarray(start, start + entry.compressed);
  if (entry.method === 0) return raw;
  if (entry.method === 8) return zlib.inflateRawSync(raw, { maxOutputLength: Math.max(entry.size, 1) + 16 });
  throw new UploadError(`${entry.name} is packed in a way that is not supported.`);
}

/** A safe relative path inside the deck, or null: no "..", no drive letters, no backslashes, nothing hidden. */
export function cleanPath(name) {
  const text = String(name).replace(/^\.\//, '');
  if (!text || text.includes('\\') || text.includes('\0') || text.startsWith('/') || /^[A-Za-z]:/.test(text)) return null;
  const parts = text.split('/').filter(Boolean);
  if (!parts.length || parts.some(p => p === '..' || p === '.' || p.startsWith('.'))) return null;
  return parts.join('/');
}

/**
 * Reads a source ZIP. Returns { markdown, files: [{ path, data }], skipped: [name] }; throws UploadError.
 * `prefix`: the deck's folder name inside the ZIP (Download source puts everything in <slug>/): taken off when present.
 */
export function readSourceZip(zip, prefix = '') {
  if (!Buffer.isBuffer(zip) || zip.length < 22) throw new UploadError('This is not a ZIP file.');
  if (zip.length > MAX_ZIP_BYTES) throw new UploadError('This ZIP is too large (over 40 MB).');
  const entries = readCentral(zip).filter(e => !e.name.endsWith('/'));
  if (entries.length > MAX_FILES * 4) throw new UploadError('This ZIP has too many files.');
  const strip = name => {
    const first = name.split('/')[0];
    return prefix && first === prefix ? name.slice(prefix.length + 1) : name;
  };
  // Without the deck's own folder name, a single top folder around everything is also taken off.
  const tops = new Set(entries.map(e => e.name.split('/')[0]));
  const hasSlidesTop = entries.some(e => e.name === 'slides.md');
  const sole = !hasSlidesTop && tops.size === 1 && entries.every(e => e.name.includes('/')) ? [...tops][0] : '';
  let markdown = null;
  const files = [];
  const skipped = [];
  let unpacked = 0;
  for (const entry of entries) {
    const name = strip(sole && entry.name.startsWith(`${sole}/`) ? entry.name.slice(sole.length + 1) : entry.name);
    const clean = cleanPath(name);
    if (!clean) { skipped.push(entry.name); continue; }
    const isSlides = clean === 'slides.md';
    const isAsset = clean.startsWith('public/') && ASSET_EXT.test(clean);
    if (!isSlides && !isAsset) { skipped.push(entry.name); continue; }
    unpacked += entry.size;
    if (unpacked > MAX_UNPACKED_BYTES) throw new UploadError('This ZIP is too large once unpacked (over 80 MB).');
    if (files.length >= MAX_FILES) throw new UploadError(`This ZIP has more than ${MAX_FILES} pictures and videos.`);
    const data = dataOf(zip, entry);
    if (isSlides) {
      if (data.length > MAX_MARKDOWN_BYTES) throw new UploadError('slides.md is too large (over 1.5 MB).');
      markdown = data.toString('utf8');
    }
    else files.push({ path: clean, data });
  }
  if (markdown === null) throw new UploadError('There is no slides.md in this ZIP. A deck\'s source ZIP (Download source) has one.');
  return { markdown, files, skipped };
}

/**
 * Puts an uploaded source into a deck's folder: the old slides.md is kept as slides.md.before-upload (so nothing is lost),
 * the pictures go into public/ (a file of the same name is replaced). Returns { files }.
 */
export async function writeUpload(deckFolder, { markdown, files }) {
  const slides = path.join(deckFolder, 'slides.md');
  await fs.copyFile(slides, path.join(deckFolder, 'slides.md.before-upload')).catch(() => {});
  for (const file of files) {
    const target = path.join(deckFolder, file.path);
    if (path.relative(deckFolder, target).startsWith('..')) throw new UploadError(`${file.path} is not allowed.`);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, file.data);
  }
  await fs.writeFile(slides, markdown);
  return { files: files.length };
}
