// Small helpers for answering web requests.
//
// What it is: sending JSON, a page or a file kept in memory (packed with gzip when the browser takes it), reading a
// request's JSON body and cookies, the file types of published files, and an error that carries its HTTP status.
// Who uses it: the manager's route files (manager-routes.mjs, deck-routes.mjs) and the files they call.
// How it fits: plain Node, no packages. slidev/tests/web.test.mjs tests it.
import crypto from 'node:crypto';
import path from 'node:path';
import zlib from 'node:zlib';
import { acceptedEncoding } from './delivery.mjs';

/** An Error with an HTTP status (the routes answer with that status and the message). */
export function httpError(status, message) {
  return Object.assign(new Error(message), { status });
}

/** Text safe to put between HTML tags or inside a quoted attribute. */
export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

/** Every cookie of a request as { name: value }. */
export function parseCookies(req) {
  const out = {};
  const raw = req.headers.cookie || '';
  for (const part of raw.split(';')) {
    const at = part.indexOf('=');
    if (at < 0) continue;
    out[part.slice(0, at).trim()] = decodeURIComponent(part.slice(at + 1).trim());
  }
  return out;
}

/** Answers with JSON (never kept in a cache). */
export function sendJson(res, status, value, extraHeaders = {}) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  res.end(JSON.stringify(value));
}

/**
 * Answers with a web page (never kept in a cache). A page of more than 1 KB goes packed (gzip) to a browser that
 * takes it; res.req is the request Node keeps with every answer. The library, for example: 24 KB, 6 KB packed.
 */
export function sendHtml(res, html, status = 200) {
  let body = Buffer.from(String(html), 'utf8');
  const packed = body.length > 1024 && acceptedEncoding(res.req?.headers?.['accept-encoding'], { gzip: true }) === 'gzip';
  if (packed) body = zlib.gzipSync(body);
  res.writeHead(status, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': body.length,
    Vary: 'Accept-Encoding',
    ...(packed ? { 'Content-Encoding': 'gzip' } : {}),
  });
  res.end(body);
}

/** A text kept in memory for sendKept: { body, gzip (packed once), etag (its fingerprint) }. */
export function keptText(text) {
  const body = Buffer.from(String(text), 'utf8');
  return { body, gzip: zlib.gzipSync(body, { level: 9 }), etag: `"${crypto.createHash('sha256').update(body).digest('hex').slice(0, 20)}"` };
}

/**
 * Sends a file kept in memory ({ body, gzip, etag }: keptText, or chart-access.mjs FileCache). Packed to a browser
 * that takes gzip; "not changed" (304, nothing sent) when the browser already has this version.
 */
export function sendKept(req, res, kept, type, cacheControl = 'no-cache') {
  const common = { 'Cache-Control': cacheControl, ETag: kept.etag, Vary: 'Accept-Encoding', 'X-Content-Type-Options': 'nosniff' };
  if (req.headers['if-none-match'] === kept.etag) {
    res.writeHead(304, common);
    return res.end();
  }
  const packed = acceptedEncoding(req.headers['accept-encoding'], { gzip: true }) === 'gzip';
  const body = packed ? kept.gzip : kept.body;
  res.writeHead(200, { ...common, 'Content-Type': type, 'Content-Length': body.length, ...(packed ? { 'Content-Encoding': 'gzip' } : {}) });
  res.end(req.method === 'HEAD' ? undefined : body);
}

/** A plain "Not found." answer. */
export function sendNotFound(res) {
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Not found.');
}

/** A request's JSON body ({} when empty). 413 when it is larger than `limit` bytes, 400 when it is not JSON. */
export async function readBody(req, limit = 4 * 1024 * 1024) {
  // Decoded once at the end: a chunk boundary can fall inside a character of several bytes.
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw httpError(413, 'The request is too large.');
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  try {
    return raw ? JSON.parse(raw) : {};
  } catch {
    throw httpError(400, 'The request could not be read.');
  }
}

/** Is this a browser opening a page (not a script asking for data)? Then a refusal is shown as a readable page. */
export function wantsHtml(req) {
  return req.method === 'GET' && /text\/html/.test(req.headers.accept || '');
}

/** GET or HEAD: a request that only reads. */
export function isReading(req) {
  return req.method === 'GET' || req.method === 'HEAD';
}

const FILE_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.avif': 'image/avif',
  '.gif': 'image/gif',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.wasm': 'application/wasm',
  '.ico': 'image/x-icon',
  '.pdf': 'application/pdf',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
};

/** The Content-Type of a file, by its extension. */
export function mimeType(file) {
  return FILE_TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream';
}
