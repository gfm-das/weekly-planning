// TEST ONLY: serves a built deck and stand-in portal pages for tests/present/edge_present.ps1.
//   node serve-built-deck.mjs <dist folder> <slug> <repo root>
// :8461 is the "Presentations" origin: /p/<slug>/... from the dist folder (Slidev's SPA: unknown paths
// without an extension get index.html). :8462 is the "portal" origin, whose pages frame the deck with
// the allow attribute copied from the real files: /portal.html (portal/index.template.html #appFrame),
// /studio.html (slidev/manager/studio.html #studio), /old.html (the old allow="fullscreen", a control).
// The frame's src uses the host the page was opened with, so a non-localhost name tests plain http.
import { readFileSync, statSync } from 'node:fs';
import http from 'node:http';
import path from 'node:path';

const [dist, slug, repo] = process.argv.slice(2);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2' };
const read = f => readFileSync(f, 'utf8').replace(/\r\n/g, '\n');
const allowOf = (file, re) => (re.exec(read(path.join(repo, file))) || [])[1];
const ALLOW = {
  '/portal.html': allowOf('portal/index.template.html', /<iframe\s+id="appFrame"\s+allow="([^"]*)"/),
  '/studio.html': allowOf('slidev/manager/studio.html', /<iframe id="studio"[^>]*allow="([^"]*)"/),
  '/old.html': 'fullscreen',
};

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const prefix = `/p/${slug}/`;
  if (!url.pathname.startsWith(prefix)) { res.writeHead(404); return res.end('not found'); }
  let file = path.join(dist, decodeURIComponent(url.pathname.slice(prefix.length)) || 'index.html');
  try { if (statSync(file).isDirectory()) file = path.join(file, 'index.html'); }
  catch { if (!path.extname(file)) file = path.join(dist, 'index.html'); }
  try {
    const body = readFileSync(file);
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(body);
  }
  catch { res.writeHead(404); res.end('not found'); }
}).listen(8461, '0.0.0.0');

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const allow = ALLOW[url.pathname];
  if (allow === undefined) { res.writeHead(404); return res.end('not found'); }
  const deckPath = url.searchParams.get('path') || `/p/${slug}/presenter/1`;
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(`<!doctype html><title>stand-in portal</title><style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>
<iframe id="appFrame" allow="${allow}"></iframe>
<script>document.getElementById('appFrame').src = 'http://' + location.hostname + ':' + ${JSON.stringify(url.searchParams.get('deckPort') || '18461')} + ${JSON.stringify(deckPath)};</script>`);
}).listen(8462, '0.0.0.0');

console.log(`serving ${dist} at :8461${`/p/${slug}/`}, portal stand-ins at :8462`, ALLOW);
