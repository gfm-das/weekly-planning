// Small helpers that make decks load faster.
//
// What it is:
// - compressed copies of a published deck and which one to send,
// - which answers of a deck's editor are packed on the way (packableAnswer),
// - cache headers for published files,
// - the fingerprint of the chart addon a deck was built with,
// - short-lived answers (access checks),
// - one build at a time (JobQueue),
// - the editor warm-up: fetching a deck's modules once before the browser does.
// Who uses it: builds.mjs, editors.mjs, access.mjs and the route files.
// How it fits: plain Node without packages, so slidev/tests/delivery.test.mjs tests every helper directly.
import fs from 'node:fs/promises';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { promisify } from 'node:util';

const gzip = promisify(zlib.gzip);
const brotli = promisify(zlib.brotliCompress);

// Text files worth compressing. Images and woff2 fonts are compressed already.
export const COMPRESSIBLE = new Set(['.html', '.js', '.mjs', '.css', '.json', '.map', '.svg', '.txt', '.xml', '.wasm', '.ttf', '.otf', '.ico']);

async function filesUnder(dir) {
  const out = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await filesUnder(full));
    else if (entry.isFile()) out.push(full);
  }
  return out;
}

/**
 * Writes `<file>.gz` and `<file>.br` next to every compressible file of at
 * least `minBytes` in `dir` (a finished build), keeping a copy only when it is
 * really smaller. Runs on Node's worker threads, four files at a time.
 * reuseFrom: the deck's last build. A file that is byte for byte the same
 * there (most of Slidev's own code is the same in every build) takes its
 * packed copies from there instead of being packed again: brotli at its best
 * setting took about 3.5 s of every build (measured round 9).
 */
export async function precompressDir(dir, { minBytes = 1024, brotliQuality = 11, reuseFrom = null } = {}) {
  const started = Date.now();
  const files = (await filesUnder(dir)).filter(f => COMPRESSIBLE.has(path.extname(f).toLowerCase()));
  const summary = { files: 0, reused: 0, raw: 0, gz: 0, br: 0, ms: 0 };
  const queue = [...files];
  await Promise.all(Array.from({ length: 4 }, async () => {
    for (let file = queue.shift(); file; file = queue.shift()) {
      const body = await fs.readFile(file);
      if (body.length < minBytes) continue;
      const before = reuseFrom ? await packedBefore(body, path.join(reuseFrom, path.relative(dir, file))) : null;
      const [gz, br] = before || await Promise.all([
        gzip(body, { level: 9 }),
        brotli(body, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: brotliQuality, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: body.length } }),
      ]);
      summary.files++;
      if (before) summary.reused++;
      summary.raw += body.length;
      if (gz.length < body.length * 0.95) { await fs.writeFile(`${file}.gz`, gz); summary.gz += gz.length; } else summary.gz += body.length;
      if (br.length < body.length * 0.95) { await fs.writeFile(`${file}.br`, br); summary.br += br.length; } else summary.br += body.length;
    }
  }));
  summary.ms = Date.now() - started;
  return summary;
}

// The packed copies [gz, br] of the same file in the last build: only when that file is byte for byte the same and
// has both copies; otherwise null (the file is packed again).
async function packedBefore(body, before) {
  const old = await fs.readFile(before).catch(() => null);
  if (!old || !old.equals(body)) return null;
  const [gz, br] = await Promise.all([fs.readFile(`${before}.gz`).catch(() => null), fs.readFile(`${before}.br`).catch(() => null)]);
  return gz && br ? [gz, br] : null;
}

/**
 * The encoding to send for an Accept-Encoding header: 'br' before 'gzip',
 * only when that copy exists (`available`) and the browser accepts it
 * (q=0 refuses). Null means the file as it is.
 */
export function acceptedEncoding(header, available = {}) {
  const accepted = new Map();
  for (const part of String(header || '').split(',')) {
    const [name, ...params] = part.trim().toLowerCase().split(';');
    if (!name) continue;
    const q = params.map(p => p.trim()).find(p => p.startsWith('q='));
    accepted.set(name, q ? Number(q.slice(2)) : 1);
  }
  const ok = name => {
    const q = accepted.has(name) ? accepted.get(name) : accepted.get('*');
    return q !== undefined && q > 0;
  };
  if (available.br && ok('br')) return 'br';
  if (available.gzip && ok('gzip')) return 'gzip';
  return null;
}

// Answers worth packing on the way: code, styles and data (never a stream such as text/event-stream).
const PACKABLE_TYPE = /^(text\/(javascript|css|html|plain|xml)|application\/(javascript|json|xml|wasm)|image\/svg\+xml)\b/i;

/**
 * Is an answer of a deck's editor (editors.mjs) worth packing with gzip on the way to this browser? A whole (200)
 * answer of text, 1 KB or more (or of unknown size), not packed already, for a browser that takes gzip.
 */
export function packableAnswer(req, status, headers = {}) {
  return req.method !== 'HEAD' && status === 200 && !headers['content-encoding']
    && PACKABLE_TYPE.test(headers['content-type'] || '') && !(Number(headers['content-length']) < 1024)
    && acceptedEncoding(req.headers['accept-encoding'], { gzip: true }) === 'gzip';
}

/**
 * Cache-Control for a published file (path relative to dist/). Everything in
 * assets/ has a content hash in its name, so it never changes and can be kept
 * for a year; pages and the deck's own files are checked again each time.
 * Always private: every file needs a sign-in.
 */
export function cacheControlFor(relative) {
  return /^assets\//.test(String(relative).replace(/^\/+/, ''))
    ? 'private, max-age=31536000, immutable'
    : 'private, no-cache';
}

/**
 * A short fingerprint of files and folders (names and contents, in a fixed
 * order; dotfiles and node_modules left out). The manager stores it with each
 * build, so a deck built with an older chart addon is rebuilt.
 */
export function treeFingerprint(paths) {
  const hash = crypto.createHash('sha256');
  const add = (full, name) => {
    let stat;
    try { stat = statSync(full); } catch { hash.update(`missing:${name}\n`); return; }
    if (stat.isDirectory()) {
      for (const entry of readdirSync(full).sort()) {
        if (entry.startsWith('.') || entry === 'node_modules') continue;
        add(path.join(full, entry), `${name}/${entry}`);
      }
      return;
    }
    hash.update(`file:${name}:${stat.size}\n`);
    hash.update(readFileSync(full));
  };
  for (const p of paths) add(p, path.basename(p));
  return hash.digest('hex').slice(0, 16);
}

/** Answers kept for `ttlMs`, at most `max` of them (the oldest go first). */
export class ShortMemory {
  constructor(ttlMs, max = 2000) {
    this.ttlMs = ttlMs;
    this.max = max;
    this.map = new Map();
  }

  get(key) {
    const hit = this.map.get(key);
    if (!hit) return undefined;
    if (hit.until <= Date.now()) { this.map.delete(key); return undefined; }
    return hit.value;
  }

  set(key, value) {
    this.map.delete(key);
    this.map.set(key, { value, until: Date.now() + this.ttlMs });
    while (this.map.size > this.max) this.map.delete(this.map.keys().next().value);
  }

  delete(key) {
    this.map.delete(key);
  }
}

/**
 * Runs at most `limit` jobs at a time. Jobs someone is waiting for
 * (priority 'now') go before the others ('later'); within each, first come
 * first served. The manager runs every Slidev build through one of these:
 * a build needs about 0.5 GB, and the Docker VM is short of memory.
 */
export class JobQueue {
  constructor(limit = 1) {
    this.limit = Math.max(1, Math.floor(Number(limit)) || 1);
    this.running = 0;
    this.waiting = [];
  }

  /** Runs fn() when a place is free; settles like fn. `key` names the job for hurry()/isWaiting(). */
  run(fn, { priority = 'now', key = null } = {}) {
    return new Promise((resolve, reject) => {
      this.waiting.push({ fn, resolve, reject, key, now: priority === 'now' });
      this.next();
    });
  }

  /** A waiting job with this key moves up to the jobs someone is waiting for. */
  hurry(key) {
    for (const job of this.waiting) if (job.key === key) job.now = true;
  }

  /** Whether a job with this key has not started yet. */
  isWaiting(key) {
    return this.waiting.some(job => job.key === key);
  }

  next() {
    while (this.running < this.limit && this.waiting.length) {
      const first = this.waiting.findIndex(job => job.now);
      const [job] = this.waiting.splice(first < 0 ? 0 : first, 1);
      this.running++;
      Promise.resolve()
        .then(job.fn)
        .then(job.resolve, job.reject)
        .finally(() => { this.running--; this.next(); });
    }
  }
}

const RE_STATIC = /(?:^|[;\n}\s])(?:import|export)\s*(?:[\w*${}\s,]*?\sfrom\s*)?["']([^"'\n]+)["']/g;
const RE_DYNAMIC = /import\(\s*["']([^"'\n]+)["']\s*\)/g;
// The editor page loads most of Slidev and Studio through import(): the play
// page, the slides, layouts, global layers, Studio's panels. Those are
// followed. These are not: code editors, highlighters and diagram tools,
// and the pages the editor does not open (presenter, overview, export …).
// Measured on the showcase deck: this covers all but 8 of the ~470 modules
// the browser loads when the editor opens.
const RE_SKIP_DYNAMIC = /monaco|shiki|twoslash|mermaid|plantuml|katex|prettier|typescript|pages\/(?:presenter|overview|notes|export|print|entry)|RecordingDialog|mcp/i;
// `?url` modules (the chart libraries) answer with the file's address.
const RE_URL_EXPORT = /export default\s+["']([^"'\n]+)["']/;

/** Module URLs a page's HTML loads (<script type="module" src>). */
export function moduleEntries(html, pageUrl) {
  return [...String(html).matchAll(/<script[^>]*type="module"[^>]*src="([^"]+)"/g)].map(m => new URL(m[1], pageUrl).href);
}

/** Imports in one module's code, absolute, same origin only. */
export function importsOf(code, url) {
  const origin = new URL(url).origin;
  const specs = [...String(code).matchAll(RE_STATIC)].map(m => m[1]);
  specs.push(...[...String(code).matchAll(RE_DYNAMIC)].map(m => m[1]).filter(s => !RE_SKIP_DYNAMIC.test(s)));
  if (/[?&]url\b/.test(url)) {
    const address = String(code).match(RE_URL_EXPORT);
    if (address) specs.push(address[1]);
  }
  const out = [];
  for (const spec of specs) {
    if (!/^(\/|\.\.?\/)/.test(spec)) continue;
    let next;
    try { next = new URL(spec, url).href; } catch { continue; }
    if (next.startsWith(`${origin}/`)) out.push(next);
  }
  return out;
}

/**
 * Loads a Slidev dev page's module graph the way a browser would (6 requests
 * at a time): static imports and the import() calls the editor runs (see
 * RE_SKIP_DYNAMIC). Vite compiles each module once and keeps it, finds and
 * pre-bundles every dependency, and UnoCSS sees every class, all before the
 * editor says it is ready. So the browser's first load no longer reloads
 * itself halfway. If Vite re-bundled dependencies during the first pass (two
 * ?v= versions seen), a second pass fetches the new versions. Never throws;
 * stops at `timeoutMs` or `maxModules`.
 */
export async function warmModuleGraph(pageUrl, { concurrency = 6, timeoutMs = 60000, maxModules = 4000, fetchImpl = globalThis.fetch } = {}) {
  const started = Date.now();
  const result = { modules: 0, bytes: 0, failed: 0, passes: 0, passMs: [], versions: [], timedOut: false, ms: 0, error: '' };
  const signal = AbortSignal.timeout(timeoutMs);
  try {
    const page = await fetchImpl(pageUrl, { headers: { Accept: 'text/html' }, signal });
    const html = await page.text();
    if (!page.ok) throw new Error(`the page answered ${page.status}`);
    const entries = moduleEntries(html, pageUrl);
    for (let pass = 1; pass <= 2; pass++) {
      result.passes = pass;
      const passStarted = Date.now();
      const versions = new Set();
      const seen = new Set(entries);
      const queue = [...entries];
      let inflight = 0;
      await new Promise((resolve) => {
        const pump = () => {
          if (signal.aborted) { result.timedOut = true; if (!inflight) resolve(); return; }
          if (!queue.length && !inflight) return resolve();
          while (inflight < concurrency && queue.length) {
            const url = queue.shift();
            const v = url.match(/\/deps\/[^?]*\?v=([0-9a-f]{6,})/);
            if (v) versions.add(v[1]);
            inflight++;
            fetchImpl(url, { headers: { Accept: '*/*' }, signal })
              .then(async (response) => {
                const code = await response.text();
                result.modules++;
                result.bytes += code.length;
                if (!response.ok) { result.failed++; return; }
                if (!/javascript|typescript/.test(response.headers.get('content-type') || '')) return;
                for (const next of importsOf(code, url)) {
                  if (seen.has(next) || seen.size >= maxModules) continue;
                  seen.add(next);
                  queue.push(next);
                }
              })
              .catch(() => { result.failed++; })
              .finally(() => { inflight--; pump(); });
          }
        };
        pump();
      });
      result.passMs.push(Date.now() - passStarted);
      result.versions = [...versions];
      if (versions.size <= 1 || signal.aborted) break;
    }
  } catch (error) {
    result.error = signal.aborted ? 'timed out' : String(error?.message || error);
    result.timedOut = signal.aborted;
  }
  result.ms = Date.now() - started;
  return result;
}
