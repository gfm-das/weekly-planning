// Everything on the deck address (port 8089, inside the container 3041), round 8.
//
// What it is: the addresses where a deck's own page code runs:
//   /p/<deck>/…        the published deck (with the ✎ button for people who may change it)
//   /edit/<deck>/…     the deck's editor (Slidev with Studio), shown in a frame of /studio
//   /api/charts/data, /api/mission-kpis   the numbers of that deck's own charts
//   /api/deck-pass     an open deck page keeps its pass alive
// Everything here needs a deck pass for that one deck (deck-origin.mjs). The manager's sign-in cookie is never read
// here and no Bearer token is taken: a deck's code must not act as the person who opened it. Changes (POST) and
// the editor's live connection are accepted only from this address's own pages.
// Who uses it: server.mjs, which sends every request on this address to handleDeckRequest.
// How it fits: publishing is builds.mjs, the editors are editors.mjs; this file checks the pass and passes on.
import { createReadStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import { presentationAccess } from './access.mjs';
import { CHART_BODY_LIMIT, NOT_PINNED } from './chart-access.mjs';
import { ensureBuild, ensureDeckBuildWatcher, refreshBuildInBackground } from './builds.mjs';
import { builtDir, deckExists, presentationSlugFromPath } from './deck-files.mjs';
import { addressOf, deckOfRequest, deckRefusal, deckSocketAllowed } from './deck-origin.mjs';
import { acceptedEncoding, cacheControlFor } from './delivery.mjs';
import { assertEditorRequest, editorSlugFromReferer, editSlugFromPath, proxySocketToEditor, proxyToEditor, runningEditor } from './editors.mjs';
import { BAD_WEEKS, chartData, missionKpis, NOT_LOADED, pinIndex, weeksFrom } from './numbers.mjs';
import { addEditorLauncher, addEditorScripts, addPassKeepAlive, deckMessagePage, portalAddressFor } from './pages.mjs';
import { ADDRESSES, PORTAL_ORIGINS, PORTAL_PORTS } from './settings.mjs';
import { localFavicon } from './gfm-addon/lib/favicon.mjs';
import { passes, passHolder } from './sign-in.mjs';
import { isReading, mimeType, readBody, sendHtml, sendJson, sendNotFound, wantsHtml } from './web.mjs';
import { frameAncestors } from './whiteboard-frames.mjs';
import { mayEditDeck } from './zone-decks.mjs';

/** Answers one request on the deck address. */
export async function handleDeckRequest(req, res) {
  const managerAddress = addressOf('manager', req.headers.host, ADDRESSES);
  try {
    const url = new URL(req.url, 'http://localhost');
    if (req.method === 'GET' && url.pathname === '/health') return sendJson(res, 200, { ok: true, service: 'deck-address', passes: passes.size });
    const refusal = deckRefusal({ method: req.method, headers: req.headers });
    if (refusal) return sendJson(res, 403, { error: refusal, refused: true });
    res.setHeader('Content-Security-Policy', deckFrameAncestors(req.headers.host));
    if (await routeDeckRequest(req, res, url, managerAddress)) return;
    return sendJson(res, 404, { error: 'Not found.' });
  } catch (error) {
    return answerError(req, res, error, managerAddress);
  }
}

// Sends the request to its route; false when no route takes it.
async function routeDeckRequest(req, res, url, managerAddress) {
  const { pathname } = url;
  if (req.method === 'POST' && pathname === '/api/charts/data') return deckChartData(req, res).then(() => true);
  if (req.method === 'GET' && pathname === '/api/mission-kpis') return deckKpis(req, res, url).then(() => true);
  if (req.method === 'GET' && pathname === '/api/deck-pass') return deckPassAlive(req, res);
  if (pathname.startsWith('/api/')) return false;
  if (pathname.startsWith('/p/') && await routeDeckPage(req, res, pathname, managerAddress)) return true;
  // The editor: /edit/<deck>/… and the requests it makes outside that folder (named by the Referer).
  const editSlug = editSlugFromPath(pathname) || editorSlugFromReferer(req);
  if (!editSlug) return false;
  const { context } = passHolder(req, editSlug, ['edit']);
  if (pathname.startsWith('/edit/')) return routeEditor(req, res, context, pathname, managerAddress);
  return routeEditorOwnRequest(req, res, context);
}

// An error from a route: a readable page for a person opening a page (with a link back to the library), JSON for
// everything else.
function answerError(req, res, error, managerAddress) {
  const status = error.status || 500;
  if (status >= 500) console.error(error);
  if (res.headersSent) {
    try { res.end(); } catch {}
    return;
  }
  if (wantsHtml(req)) {
    const page = { 401: 'open', 403: 'refused', 404: 'missing' }[status];
    if (page) return sendHtml(res, deckMessagePage(page, managerAddress, portalAddressFor(req.headers.host)), status);
  }
  return sendJson(res, status, { error: error.message });
}

/**
 * The editor's live connection (Vite's websocket): only from a page on the deck address, with an edit pass, while
 * the editor runs.
 */
export async function handleDeckSocket(req, socket, head) {
  try {
    const url = new URL(req.url, 'http://localhost');
    const slug = editSlugFromPath(url.pathname) || editorSlugFromReferer(req);
    if (!slug || !deckSocketAllowed(req.headers)) return socket.destroy();
    const { context } = passHolder(req, slug, ['edit']);
    await assertEditorRequest(req, context, slug);
    proxySocketToEditor(req, socket, head, await runningEditor(slug));
  } catch (error) {
    console.error('upgrade error', error.message);
    socket.destroy();
  }
}

// Pages here may be framed by the portal (a deck in the Presentations frame) and by the manager address (the editor
// inside /studio).
function deckFrameAncestors(host) {
  return frameAncestors(host, [...PORTAL_ORIGINS, addressOf('manager', host, ADDRESSES)].filter(Boolean), PORTAL_PORTS);
}

// ---- the numbers of a deck's own charts ----

/**
 * POST /api/charts/data { deck, spec } from a deck page (round 8 review): only for the deck of the page that asks
 * (deckOfRequest: its Referer; a request naming another deck is refused), with that deck's own pass, and only for
 * a chart written in that deck's slides (pinnedOnly), for everyone, managers too.
 */
async function deckChartData(req, res) {
  const body = await readBody(req, CHART_BODY_LIMIT);
  const { deck, refusal } = deckOfRequest(req.headers, typeof body?.deck === 'string' ? body.deck : '');
  if (refusal) return sendJson(res, 403, { error: refusal, refused: true });
  const { context } = passHolder(req, deck, ['view', 'edit']);
  const [status, value] = await chartData(context, { ...body, deck }, { pinnedOnly: true });
  return sendJson(res, status, value);
}

/**
 * GET /api/mission-kpis?weeks=N&deck=<deck> from a deck page: the key numbers, for the deck of the page that asks
 * (older builds name the deck only in the Referer), with that deck's own pass, and only if a key-number chart is
 * written in that deck (round 8 review).
 */
async function deckKpis(req, res, url) {
  const weeks = weeksFrom(url);
  if (weeks === null) return sendJson(res, 400, { error: BAD_WEEKS });
  const { deck, refusal } = deckOfRequest(req.headers, url.searchParams.get('deck') || '');
  if (refusal) return sendJson(res, 403, { error: refusal, refused: true });
  const { context } = passHolder(req, deck, ['view', 'edit']);
  const access = await presentationAccess(context, deck);
  if (!await pinIndex.hasKpiChart(deck)) return sendJson(res, 403, { error: NOT_PINNED });
  try {
    return sendJson(res, 200, { weeks: await missionKpis(context, access, weeks, deck) });
  } catch (error) {
    console.error(`[mission-kpis] ${error.status || 'error'}: ${error.message}`);
    return sendJson(res, 503, { error: NOT_LOADED });
  }
}

/**
 * GET /api/deck-pass from an open deck page (the small script addPassKeepAlive puts into it): uses the page's own
 * pass, which keeps it while the page is open. 204, or 401 when the pass has ended.
 */
function deckPassAlive(req, res) {
  const { deck, refusal } = deckOfRequest(req.headers);
  if (refusal) {
    sendJson(res, 403, { error: refusal, refused: true });
    return true;
  }
  passHolder(req, deck, ['view', 'edit']);
  res.writeHead(204, { 'Cache-Control': 'no-store' });
  res.end();
  return true;
}

// ---- published decks ----

/** GET /p/<deck>/…: the published deck, for the holder of a view pass for it. */
async function routeDeckPage(req, res, pathname, managerAddress) {
  const slug = presentationSlugFromPath(pathname);
  if (!slug || !isReading(req)) return false;
  const { context } = passHolder(req, slug, ['view']);
  const access = await presentationAccess(context, slug);
  // The ✎ edit button: for everyone who may change this deck (a zone's own ZLs and STLs too).
  await serveBuiltPresentation(req, res, slug, pathname, mayEditDeck(access, slug), managerAddress);
  return true;
}

/** A published deck's page or file. canEdit adds the ✎ button, which leads to the editor page on managerAddress. */
async function serveBuiltPresentation(req, res, slug, pathname, canEdit, managerAddress) {
  await ensureBuild(slug);
  const { file, relative } = await builtFileFor(slug, pathname);
  // The build's own notes (.gfm-build.json) are not part of the deck.
  if (relative.split('/').some(part => part.startsWith('.'))) return sendNotFound(res);
  if (path.basename(file) === 'index.html') return serveDeckPage(req, res, slug, file, canEdit, managerAddress);
  return serveDeckFile(req, res, slug, file);
}

// The file for an address under /p/<deck>/. Slidev's pages are one app: an address without a file extension that
// is not a file (a slide number, /presenter, /export) gets index.html.
async function builtFileFor(slug, pathname) {
  let relative = pathname.slice(`/p/${slug}/`.length) || 'index.html';
  try { relative = decodeURIComponent(relative); } catch {}
  if (relative.includes('..')) throw new Error('Invalid presentation path.');
  let file = path.join(builtDir(slug), relative);
  try {
    const stat = await fs.stat(file);
    if (stat.isDirectory()) file = path.join(file, 'index.html');
  } catch {
    if (!path.extname(relative)) file = path.join(builtDir(slug), 'index.html');
  }
  return { file, relative };
}

/**
 * The deck's page: with the script that keeps its pass alive and, for people who may change the deck, the ✎ button.
 * The page differs per person, so it is compressed here, not ahead of time.
 */
async function serveDeckPage(req, res, slug, file, canEdit, managerAddress) {
  let html;
  try {
    html = (await fs.readFile(file)).toString('utf8');
  } catch {
    return sendNotFound(res);
  }
  // Studio saves slides.md directly: when the page is opened and the slides are newer (or the chart addon changed),
  // a fresh copy is published in the background.
  await refreshBuildInBackground(slug);
  html = addPassKeepAlive(html);
  if (canEdit) html = addEditorLauncher(html, slug, managerAddress);
  let body = Buffer.from(html, 'utf8');
  const encoding = acceptedEncoding(req.headers['accept-encoding'], { gzip: body.length > 1024 });
  if (encoding) body = zlib.gzipSync(body);
  res.writeHead(200, {
    'Content-Type': mimeType(file),
    'Content-Length': body.length,
    'Cache-Control': 'private, no-cache',
    Vary: 'Accept-Encoding',
    ...(encoding ? { 'Content-Encoding': encoding } : {}),
  });
  return res.end(req.method === 'HEAD' ? undefined : body);
}

/** Any other file of the published deck: its compressed copy (.br or .gz, made by the build) when the browser takes it. */
async function serveDeckFile(req, res, slug, file) {
  const stat = await fs.stat(file).catch(() => null);
  if (!stat?.isFile()) return sendNotFound(res);
  const isFile = name => fs.stat(name).then(s => s.isFile(), () => false);
  const [br, gzip] = await Promise.all([isFile(`${file}.br`), isFile(`${file}.gz`)]);
  const encoding = acceptedEncoding(req.headers['accept-encoding'], { br, gzip });
  const sent = encoding === 'br' ? `${file}.br` : encoding === 'gzip' ? `${file}.gz` : file;
  const size = sent === file ? stat.size : (await fs.stat(sent)).size;
  res.writeHead(200, {
    'Content-Type': mimeType(file),
    'Content-Length': size,
    // Files in assets/ have a content hash in their names: kept for a year, never checked again.
    'Cache-Control': cacheControlFor(path.relative(builtDir(slug), file).split(path.sep).join('/')),
    Vary: 'Accept-Encoding',
    ...(encoding ? { 'Content-Encoding': encoding } : {}),
  });
  if (req.method === 'HEAD') return res.end();
  createReadStream(sent).on('error', () => res.destroy()).pipe(res);
}

// ---- the editor ----

/**
 * /edit/<deck>/… with an edit pass. Only /studio starts the editor; here it must already run (runningEditor, round 8
 * review). The editor's page itself gets two helper scripts (pages.mjs addEditorScripts); its files and code are
 * passed on as they are.
 */
async function routeEditor(req, res, context, pathname, shellOrigin) {
  const slug = editSlugFromPath(pathname);
  if (!slug) return false;
  await assertEditorRequest(req, context, slug);
  const editor = await runningEditor(slug);
  ensureDeckBuildWatcher(slug);
  const editorRoot = `/edit/${slug}/`;
  const rest = pathname.startsWith(editorRoot) ? pathname.slice(editorRoot.length) : '';
  // The page itself: /edit/<deck>/ or a slide's address such as /edit/<deck>/1.
  const isPage = pathname === editorRoot || (wantsHtml(req) && !path.extname(rest) && !/^(@|__|node_modules\/)/.test(rest));
  if (req.method === 'GET' && isPage) {
    await serveEditorPage(req, res, editor, shellOrigin);
    return true;
  }
  proxyToEditor(req, res, editor);
  return true;
}

// The editor's page, fetched from the editor with a local tab icon and the two helper scripts added.
async function serveEditorPage(req, res, editor, shellOrigin) {
  const requested = new URL(req.url, 'http://x');
  const response = await fetch(`http://127.0.0.1:${editor.port}${requested.pathname}${requested.search}`);
  if (!response.ok) throw new Error(`Editor HTML returned ${response.status}`);
  // A local tab icon instead of Slidev's default from cdn.jsdelivr.net.
  sendHtml(res, addEditorScripts(localFavicon(await response.text()), shellOrigin));
}

// A request the editor makes outside /edit/<deck>/ (/@fs/…, /__slidev/…), sent to the deck's editor named by the
// Referer, while it runs.
async function routeEditorOwnRequest(req, res, context) {
  const slug = editorSlugFromReferer(req);
  if (!slug) return false;
  await assertEditorRequest(req, context, slug);
  if (!await deckExists(slug)) return false;
  const editor = await runningEditor(slug);
  ensureDeckBuildWatcher(slug);
  editor.lastUsed = Date.now();
  console.log(`[${slug}:edit-proxy] ${req.method} ${req.url}`);
  proxyToEditor(req, res, editor);
  return true;
}
