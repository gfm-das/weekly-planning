// Everything on the manager address (port 3030, inside the container 3040).
//
// What it is: the addresses the portal's Presentations frame uses:
//   /                       the library (library.html)
//   /studio/<deck>          the editor page (studio.html), for people who may change the deck
//   /p/<deck>/              the way into a published deck: gives a view pass and sends the browser to the deck address
//   /api/...                everything the pages ask for (the table API_ROUTES below)
//   /whiteboard/...         the portal Whiteboard's chart frames (managers only)
//   /_manager/..., /vendor/monaco/...   the shared scripts, the chart builder's code and the Source text editor
// Before anything else, every request from a deck page is refused (deck-origin.mjs managerRefusal): a deck is page
// code, and the manager's sign-in must never work for it.
// Who uses it: server.mjs, which sends every request on this address to handleManagerRequest.
// How it fits: each route is a short function that checks who is asking (access.mjs), then does one thing using
// the other files (deck-actions.mjs, builds.mjs, editors.mjs, numbers.mjs ...).
import crypto from 'node:crypto';
import { createReadStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { ZipArchive } from 'archiver';
import { assertDeckCreator, assertDeckEditor, assertPresentationManager, askPortalApi, checkPresentationAccess, presentationAccess } from './access.mjs';
import { CHART_BODY_LIMIT, FileCache } from './chart-access.mjs';
import { ADDON_FINGERPRINT, buildCounts, buildDeck, buildReport, ensureDeckBuildWatcher, lastBuildInfo, publishErrorMessage, refreshBuildInBackground } from './builds.mjs';
import { acceptedEncoding, COMPRESSIBLE } from './delivery.mjs';
import { createDeck, deckStatus, deleteDeck, duplicateDeck, renameDeck } from './deck-actions.mjs';
import { deckDir, deckExists, deckFile, deckTitle, listDecks, notFound, presentationSlugFromPath, safeSlug, sourceVersion, writeDeckSource } from './deck-files.mjs';
import { addressOf, doorwayFromOtherPage, managerRefusal, passCookie, passDomainFor } from './deck-origin.mjs';
import { assertEditorRequest, editorSlugFromReferer, editorStage, describeEditors, ensureEditor, prestartDeck, prestartRecentDeck, proxyToEditor, rememberClientReport, runningEditorCount, touchEditor } from './editors.mjs';
import { FAVICON_DATA_URL } from './gfm-addon/lib/favicon.mjs';
import { chartCatalog, chartData, serveBuilderFile } from './numbers.mjs';
import { confirmPage, LIBRARY_PAGE, messagePage, PORTAL_BRIDGE, studioPage } from './pages.mjs';
import { protectedReason } from './protected-decks.mjs';
import { ADDRESSES, DECK_PUBLIC_PORT, MAX_RUNNING_EDITORS, MONACO_DIR, PORTAL_ORIGINS, PORTAL_PORTS, PUBLIC_NAMES, V2_DECKS_DIR } from './settings.mjs';
import { authenticatedContext, currentSessionId, handleLogout, handleSession, passes, roleOf, studioPageId } from './sign-in.mjs';
import { httpError, isReading, mimeType, readBody, sendHtml, sendJson, sendKept, sendNotFound, wantsHtml } from './web.mjs';
import { MAX_ZIP_BYTES, readSourceZip, UploadError, writeUpload } from './source-upload.mjs';
import { chartPageCsp, frameAncestors, whiteboardFrame, whiteboardFramePage } from './whiteboard-frames.mjs';
import { libraryView, ownerChangeRefusal } from './zone-decks.mjs';
import { accessKey, listV2Decks, readV2Asset, readV2Viewers, saveV2Viewers, readV2Deck, queryV2, saveV2Asset, saveV2Deck, v2AppFile, v2PageHtml } from './v2-routes.mjs';

/** Answers one request on the manager address. */
export async function handleManagerRequest(req, res) {
  try {
    const url = new URL(req.url, 'http://localhost');
    // Round 8: nothing a deck page sends is taken (deck-origin.mjs managerRefusal).
    const refusal = managerRefusal({ method: req.method, pathname: url.pathname, headers: req.headers }, { deckPort: DECK_PUBLIC_PORT, deckName: PUBLIC_NAMES.deck });
    if (refusal) return refuse(req, res, refusal);
    // These pages may be framed only by the portal (and by each other): never by a deck page.
    res.setHeader('Content-Security-Policy', frameAncestors(req.headers.host, PORTAL_ORIGINS, PORTAL_PORTS));
    if (await routeManagerRequest(req, res, url)) return;
    return sendJson(res, 404, { error: 'Not found.' });
  } catch (error) {
    return answerError(req, res, error);
  }
}

// Sends the request to its route; false when no route takes it.
async function routeManagerRequest(req, res, url) {
  const { pathname } = url;
  if (req.method === 'GET' && pathname === '/') return serveLibrary(res);
  if (req.method === 'GET' && pathname === '/health') return serveHealth(res);
  if (req.method === 'GET' && pathname === '/_manager/portal-bridge.js') return servePortalBridge(req, res);
  if (isReading(req) && pathname.startsWith('/vendor/monaco/vs/')) return serveMonaco(req, res, pathname);
  if (isReading(req) && pathname.startsWith('/_manager/chart/')) return serveBuilderFile(req, res, pathname.slice('/_manager/chart/'.length)).then(() => true);
  if (isReading(req) && pathname.startsWith('/_v2/')) return serveV2File(req, res, pathname.slice('/_v2/'.length));
  if (pathname.startsWith('/api/')) return handleApi(req, res, url).then(() => true);
  if (req.method === 'GET' && /^\/p-v2-assets\/[a-z0-9-]+\/[a-z0-9._-]+$/.test(pathname)) return serveV2Asset(req, res, pathname, await authenticatedContext(req));
  if (isReading(req) && pathname === '/library-v2') return serveV2Library(req, res, await authenticatedContext(req));
  if (isReading(req) && /^\/(studio-v2|p-v2)\/[a-z0-9-]+\/?$/.test(pathname)) return serveV2Page(req, res, url, await authenticatedContext(req));
  // The pages below need a sign-in; it is checked first, so a signed-out person learns nothing about a deck.
  if (req.method === 'GET' && pathname.startsWith('/studio/') && await routeStudio(req, res, url, await authenticatedContext(req))) return true;
  if (req.method === 'GET' && whiteboardFrame(pathname)) return serveWhiteboardFrame(req, res, whiteboardFrame(pathname));
  if (pathname.startsWith('/p/') && await routePresentationDoorway(req, res, url, await authenticatedContext(req))) return true;
  // The chart builder of /studio reads and writes slides through the deck's editor (Slidev's own routes /__slidev/
  // and /@studio/, named by the Referer).
  if (editorSlugFromReferer(req) && await routeBuilderEditorRequest(req, res, await authenticatedContext(req))) return true;
  return false;
}

// A request the manager address refuses: a readable page for a person opening a page, JSON for everything else.
function refuse(req, res, reason) {
  if (wantsHtml(req)) return sendHtml(res, messagePage('Not available', reason), 403);
  return sendJson(res, 403, { error: reason, refused: true });
}

// An error from a route: its status (401 for "Not signed in", otherwise 500), as a readable page for a person opening
// a page (a signed-out page renews the sign-in through the portal), JSON for everything else.
function answerError(req, res, error) {
  const status = error.status || (/Not signed in/.test(error.message) ? 401 : 500);
  if (status >= 500) console.error(error);
  if (res.headersSent) {
    try { res.end(); } catch {}
    return;
  }
  if (wantsHtml(req) && !req.url.startsWith('/api/')) {
    if (status === 401) return sendHtml(res, messagePage('Signing you in…', 'Your presentation sign-in has ended. Renewing it through the mission portal…', { signIn: true }), 401);
    if (status === 403) return sendHtml(res, messagePage('Not available', error.message), 403);
    if (status === 404) return sendHtml(res, messagePage('Presentation not found', 'It may have been renamed or deleted.'), 404);
  }
  return sendJson(res, status, { error: error.message });
}

// ---- pages and files ----

function serveLibrary(res) {
  sendHtml(res, LIBRARY_PAGE);
  return true;
}

function serveHealth(res) {
  const builds = buildCounts();
  sendJson(res, 200, {
    ok: true, service: 'presentation-manager', running_slidev_instances: runningEditorCount(), chart_addon: ADDON_FINGERPRINT,
    builds_running: builds.running, builds_waiting: builds.waiting, deck_address_port: DECK_PUBLIC_PORT,
  });
  return true;
}

// portal-bridge.js: every page loads it first, so it is packed, and a browser that has it only checks it is the same.
function servePortalBridge(req, res) {
  sendKept(req, res, PORTAL_BRIDGE, 'text/javascript; charset=utf-8');
  return true;
}

// Monaco's text files, read and packed once each. No limit: Monaco is a fixed folder that nobody can change (138
// text files, about 30 MB plain and packed together), so each file is packed at most once while the manager runs.
// (Source first loads about 4.4 MB of them; a limit smaller than the folder would let anyone who loops over all of
// them force the packing again and again.)
const monacoFiles = new FileCache(Infinity);

// The Monaco text editor that Slidev already installs (a public library, so no sign-in is needed). A path is kept
// inside MONACO_DIR. A text file goes packed to a browser that asks for it (GET) and takes gzip (web.mjs sendKept);
// everything else (a HEAD, a browser without gzip, a picture or font) goes from the disk as it is, with no packing.
async function serveMonaco(req, res, pathname) {
  let relative;
  try { relative = decodeURIComponent(pathname.slice('/vendor/monaco/vs/'.length)); } catch { relative = ''; }
  const file = path.resolve(MONACO_DIR, relative);
  let stat = null;
  if (relative && !relative.includes('\0') && file.startsWith(MONACO_DIR + path.sep)) stat = await fs.stat(file).catch(() => null);
  if (!stat?.isFile()) {
    sendNotFound(res);
    return true;
  }
  const cacheControl = 'public, max-age=604800';
  const isText = COMPRESSIBLE.has(path.extname(file).toLowerCase());
  const takesGzip = acceptedEncoding(req.headers['accept-encoding'], { gzip: true }) === 'gzip';
  if (isText && takesGzip && req.method === 'GET') {
    sendKept(req, res, await monacoFiles.get(file), mimeType(file), cacheControl);
    return true;
  }
  res.writeHead(200, {
    'Content-Type': mimeType(file), 'Content-Length': stat.size, 'Cache-Control': cacheControl, 'X-Content-Type-Options': 'nosniff',
    ...(isText ? { Vary: 'Accept-Encoding' } : {}),
  });
  if (req.method === 'HEAD') {
    res.end();
    return true;
  }
  createReadStream(file).on('error', () => res.destroy()).pipe(res);
  return true;
}

// A new random number for each page's Content-Security-Policy.
const newNonce = () => crypto.randomBytes(16).toString('base64');

/** GET /studio/<deck>: the editor page around Studio, for people who may change the deck. */
async function routeStudio(req, res, url, context) {
  const slug = url.pathname.match(/^\/studio\/([a-z0-9-]+)\/?$/)?.[1] || null;
  if (!slug) return false;
  await assertDeckEditor(context, slug);
  if (!await deckExists(slug)) throw notFound();
  const title = await deckTitle(slug);
  // Round 8: opened by a deck page (its ✎ button, or its code): the person confirms first.
  if (doorwayFromOtherPage({ pathname: url.pathname, headers: req.headers })) {
    sendHtml(res, confirmPage('edit', title, url.pathname));
    return true;
  }
  // The editor itself runs in a frame on the deck address (round 8).
  const deckOrigin = addressOf('deck', req.headers.host, ADDRESSES);
  // Round 8 review: this page draws charts a Zone Leader may have written (the chart builder), so only its own
  // scripts may run here; its two inline scripts carry this nonce.
  const nonce = newNonce();
  res.setHeader('Content-Security-Policy', chartPageCsp(req.headers.host, PORTAL_ORIGINS, PORTAL_PORTS, { nonce, frames: deckOrigin ? [deckOrigin] : [] }));
  // protected_reason: the title of a protected deck is not click-to-rename (the server refuses it anyway).
  sendHtml(res, studioPage(title, { slug, title, protected_reason: protectedReason(slug), deck_origin: deckOrigin }, nonce));
  return true;
}

/** The portal Whiteboard's frames (a live chart, the chart builder): managers only, framed by the portal only. */
async function serveWhiteboardFrame(req, res, kind) {
  await assertPresentationManager(await authenticatedContext(req));
  // Round 8 review: these frames draw charts that may come from a zone's slide, so only their own scripts run.
  const nonce = newNonce();
  res.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Security-Policy': chartPageCsp(req.headers.host, PORTAL_ORIGINS, PORTAL_PORTS, { nonce }),
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
  });
  res.end(whiteboardFramePage(kind, FAVICON_DATA_URL, nonce));
  return true;
}

// ---- GFM Presentations V2 (v2-routes.mjs) ----

// The V2 data worker builds small functions from text (Arquero, math.js), which the pages' policy forbids. Its own
// file gets its own policy instead: it may do that, but it has no network, no page, no cookies. Nothing else may.
const V2_WORKER_CSP = "default-src 'none'; script-src 'self' 'unsafe-eval'; connect-src 'none'; frame-ancestors 'none'";
const isV2Worker = name => /^assets\/data-worker-[\w-]+\.js$/.test(name);

/** GET /_v2/<file>: the built V2 application (code only, no data, like the chart builder's files). */
async function serveV2File(req, res, name) {
  const found = await v2AppFile(name);
  if (!found) { sendNotFound(res); return true; }
  res.writeHead(200, { 'Content-Type': found.type, 'Content-Length': found.size, 'Cache-Control': 'public, max-age=3600', 'X-Content-Type-Options': 'nosniff', ...(isV2Worker(name) ? { 'Content-Security-Policy': V2_WORKER_CSP } : {}) });
  if (req.method === 'HEAD') { res.end(); return true; }
  createReadStream(found.file).on('error', () => res.destroy()).pipe(res);
  return true;
}

/** GET /library-v2: the V2 presentations this person may open (the page asks /api/presentations-v2 for the list). */
async function serveV2Library(req, res, context) {
  await checkPresentationAccess(context, []);
  const nonce = newNonce();
  res.setHeader('Content-Security-Policy', chartPageCsp(req.headers.host, PORTAL_ORIGINS, PORTAL_PORTS, { nonce }));
  sendHtml(res, await v2PageHtml());
  return true;
}

/** GET /p-v2-assets/<deck>/<name>: a picture of a V2 deck, for whoever may open the deck. */
async function serveV2Asset(req, res, pathname, context) {
  const [, slug, name] = pathname.match(/^\/p-v2-assets\/([a-z0-9-]+)\/([a-z0-9._-]+)$/);
  return readV2Asset({ req, res, context, slug, name });
}

/**
 * GET /studio-v2/<deck> (who may change the deck; a manager may open a deck that does not exist yet, to make it) and
 * GET /p-v2/<deck> (who may open it). The same prebuilt page for every deck: no Slidev, no build.
 */
async function serveV2Page(req, res, url, context) {
  const [, mode, slug] = url.pathname.match(/^\/(studio-v2|p-v2)\/([a-z0-9-]+)\/?$/);
  const access = mode === 'studio-v2' ? await assertDeckEditor(context, accessKey(slug)) : await presentationAccess(context, accessKey(slug));
  const exists = await fs.stat(path.join(V2_DECKS_DIR, slug, 'deck.json')).then(() => true, () => false);
  if (!exists && !(mode === 'studio-v2' && access.can_manage)) throw notFound();
  const nonce = newNonce();
  res.setHeader('Content-Security-Policy', chartPageCsp(req.headers.host, PORTAL_ORIGINS, PORTAL_PORTS, { nonce }));
  res.setHeader('Cache-Control', 'no-store');
  sendHtml(res, await v2PageHtml());
  return true;
}

// ---- the way into a published deck ----

/**
 * GET /p/<deck>/… (round 8): whoever may open the deck gets a view pass for it (deck-origin.mjs) and is sent on to
 * the same address on the deck address. When another page (a deck page) started this, no pass is given: the person
 * confirms first.
 */
async function routePresentationDoorway(req, res, url, context) {
  const slug = presentationSlugFromPath(url.pathname);
  if (!slug || !isReading(req)) return false;
  await presentationAccess(context, slug);
  if (!await deckExists(slug)) throw notFound();
  if (doorwayFromOtherPage({ pathname: url.pathname, headers: req.headers })) {
    sendHtml(res, confirmPage('open', await deckTitle(slug), url.pathname + url.search));
    return true;
  }
  const sessionId = currentSessionId(req);
  if (!sessionId) throw httpError(401, 'Not signed in.');
  // An unusual address (no computer name the browser could use) must not send the browser round in a circle.
  const deckAddress = addressOf('deck', req.headers.host, ADDRESSES);
  if (!deckAddress) throw httpError(404, 'Presentation not found.');
  res.writeHead(302, {
    Location: `${deckAddress}${url.pathname}${url.search}`,
    'Set-Cookie': passCookie(slug, 'view', passes.issue(sessionId, slug, 'view'), passDomainFor(req.headers.host, PUBLIC_NAMES)),
    'Cache-Control': 'no-store',
  });
  res.end();
  return true;
}

// ---- the editor (it runs on the deck address; two of its routes are used from here) ----

/**
 * The chart builder of /studio reads and writes a slide through the deck's editor: only /__slidev/slides/<n>.json
 * and /@studio/deck, named by the Referer. The builder may start the editor (the deck address never does).
 */
async function routeBuilderEditorRequest(req, res, context) {
  const slug = editorSlugFromReferer(req);
  await assertEditorRequest(req, context, slug);
  if (!/^\/(__slidev|@studio)\//.test(new URL(req.url, 'http://x').pathname)) return false;
  if (!await deckExists(slug)) return false;
  const editor = await ensureEditor(slug);
  ensureDeckBuildWatcher(slug);
  editor.lastUsed = Date.now();
  console.log(`[${slug}:edit-proxy] ${req.method} ${req.url}`);
  proxyToEditor(req, res, editor);
  return true;
}

// ---- /api/ ----

// Every /api/ route after sign-in: [method, address pattern, what answers]. The pattern's (…) is the deck's slug.
const DECK = '([a-z0-9-]+)';
const API_ROUTES = [
  ['GET', /^\/api\/presentations-v2$/, listV2Decks],
  ['POST', /^\/api\/presentations-v2\/query$/, queryV2],
  ['GET', new RegExp(`^/api/presentations-v2/${DECK}/viewers$`), readV2Viewers],
  ['PUT', new RegExp(`^/api/presentations-v2/${DECK}/viewers$`), saveV2Viewers],
  ['GET', new RegExp(`^/api/presentations-v2/${DECK}$`), readV2Deck],
  ['PUT', new RegExp(`^/api/presentations-v2/${DECK}$`), saveV2Deck],
  ['PUT', new RegExp(`^/api/presentations-v2/${DECK}/assets/([a-z0-9._-]+)$`), saveV2Asset],
  ['GET', /^\/api\/presentations$/, listLibrary],
  ['POST', /^\/api\/presentations$/, createPresentation],
  ['POST', /^\/api\/charts\/data$/, answerChartData],
  ['GET', /^\/api\/charts\/catalog$/, answerChartCatalog],
  ['POST', new RegExp(`^/api/presentations/${DECK}/duplicate$`), duplicatePresentation],
  ['POST', new RegExp(`^/api/presentations/${DECK}/rename$`), renamePresentation],
  ['GET', new RegExp(`^/api/presentations/${DECK}/source$`), readSource],
  ['PUT', new RegExp(`^/api/presentations/${DECK}/source$`), saveSource],
  ['GET', new RegExp(`^/api/presentations/${DECK}/status$`), presentationStatus],
  ['POST', new RegExp(`^/api/presentations/${DECK}/publish$`), publishPresentation],
  ['GET', new RegExp(`^/api/presentations/${DECK}/editor$`), editorProgress],
  ['POST', new RegExp(`^/api/presentations/${DECK}/editor/leave$`), leaveEditor],
  ['POST', new RegExp(`^/api/presentations/${DECK}/editor$`), openEditor],
  ['POST', new RegExp(`^/api/presentations/${DECK}/preview$`), openPreview],
  ['POST', new RegExp(`^/api/presentations/${DECK}/upload$`), uploadSource],
  ['GET', /^\/api\/presentations-diagnostics$/, diagnostics],
  ['POST', new RegExp(`^/api/presentations/${DECK}/prestart$`), prestartEditor],
  ['POST', new RegExp(`^/api/presentations/${DECK}/editor/perf$`), editorPerf],
  ['GET', new RegExp(`^/api/presentations/${DECK}/download$`), downloadSource],
  ['GET', new RegExp(`^/api/presentations/${DECK}/access$`), readAccessRule],
  ['POST', new RegExp(`^/api/presentations/${DECK}/access$`), saveAccessRule],
  ['DELETE', new RegExp(`^/api/presentations/${DECK}$`), deletePresentation],
];

/**
 * Answers an /api/ request. Sign-in and sign-out come first (they have their own checks); every other route needs
 * a sign-in and gets { req, res, url, context, slug }.
 */
async function handleApi(req, res, url) {
  if (req.method === 'POST' && url.pathname === '/api/logout') return handleLogout(req, res);
  if (url.pathname === '/api/session') return handleSession(req, res);
  const context = await authenticatedContext(req);
  for (const [method, pattern, answer] of API_ROUTES) {
    const match = req.method === method ? url.pathname.match(pattern) : null;
    if (match) return answer({ req, res, url, context, slug: match[1], name: match[2] });
  }
  return sendJson(res, 404, { error: 'Not found.' });
}

// A deck that must exist: its checked slug, or 404.
async function existingDeck(slug) {
  safeSlug(slug);
  if (!await deckExists(slug)) throw notFound();
  return slug;
}

/** GET /api/presentations: the library's list (only the decks this person may open, each with can_edit). */
async function listLibrary({ res, context }) {
  const decks = await listDecks();
  const access = await checkPresentationAccess(context, decks.map(deck => deck.slug));
  // A manager in the library is likely to edit soon: have the most recently changed deck's editor ready.
  if (access.can_manage) prestartRecentDeck('a manager opened the library').catch(() => {});
  return sendJson(res, 200, { role: access.role || roleOf(context), can_manage: !!access.can_manage, ...libraryView(decks, access) });
}

/** POST /api/presentations { title }: a new deck, owned by the mission (a manager) or by the person's zone (ZL, STL). */
async function createPresentation({ req, res, context }) {
  await assertDeckCreator(context);
  const { title } = await readBody(req);
  const slug = await createDeck(title);
  // portal-api records the owner. Without that record a ZL could not open their new deck, so the folder is removed
  // again when it fails.
  try {
    await askPortalApi(context, 'access', { operation: 'create', deck_slug: slug });
  } catch (error) {
    await fs.rm(deckDir(slug), { recursive: true, force: true }).catch(() => {});
    throw error;
  }
  // The first build runs in the background while the editor opens.
  buildDeck(slug).catch(error => console.error(`[${slug}:build] first build failed`, error.message));
  return sendJson(res, 201, { ok: true, slug });
}

/** POST /api/charts/data { deck, spec }: a database chart's numbers (also the chart builder's preview). */
async function answerChartData({ req, res, context }) {
  const [status, value] = await chartData(context, await readBody(req, CHART_BODY_LIMIT));
  return sendJson(res, status, value);
}

/** GET /api/charts/catalog: the chart builder's list of numbers and places. */
async function answerChartCatalog({ res, context }) {
  const [status, value] = await chartCatalog(context);
  return sendJson(res, status, value);
}

/** POST …/duplicate: a copy of the deck; its access rule is copied too. */
async function duplicatePresentation({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  const copy = await duplicateDeck(slug);
  await askPortalApi(context, 'access', { operation: 'duplicate', deck_slug: slug, new_slug: copy });
  return sendJson(res, 201, { ok: true, slug: copy, ...await buildReport(copy) });
}

/**
 * POST …/rename { title }. The access rule moves before the folder and before any build, so neither an outage of
 * portal-api nor a build problem can separate them.
 */
async function renamePresentation({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  const { title } = await readBody(req);
  const renamed = await renameDeck(slug, title, {
    move: newSlug => askPortalApi(context, 'access', { operation: 'rename', deck_slug: slug, new_slug: newSlug }).catch(error => {
      console.error(`[${slug}:rename] access rule not moved (${error.status || 'error'}): ${error.message}`);
      throw httpError(503, 'Renaming did not work because the access settings could not be updated right now. Nothing was changed. Please try again in a moment.');
    }),
    restore: newSlug => askPortalApi(context, 'access', { operation: 'rename', deck_slug: newSlug, new_slug: slug }),
  });
  return sendJson(res, 200, { ok: true, ...renamed, ...await buildReport(renamed.slug) });
}

/** GET …/source: slides.md and its version, for the Source pane. */
async function readSource({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  const current = await fs.readFile(deckFile(slug), 'utf8');
  return sendJson(res, 200, { markdown: current, version: sourceVersion(current) });
}

/**
 * PUT …/source { markdown, version }: saves slides.md from the Source pane. The version from GET is required: without
 * it, or when the slides changed in the meantime (Studio saves too), nothing is overwritten (409). Saving never
 * publishes; that happens by itself a little later, or with Publish now.
 */
async function saveSource({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  const current = await fs.readFile(deckFile(slug), 'utf8');
  const payload = await readBody(req);
  const markdown = String(payload.markdown || '');
  if (!markdown.trim()) throw httpError(400, 'The presentation cannot be empty.');
  if (Buffer.byteLength(markdown, 'utf8') > 2 * 1024 * 1024) throw httpError(413, 'The presentation is too large.');
  if (!payload.version) {
    return sendJson(res, 409, {
      error: 'The slides were not loaded properly, so your text was not saved. Copy anything you need, choose Load latest, then make your change again.',
      version: sourceVersion(current),
    });
  }
  if (payload.version !== sourceVersion(current)) {
    return sendJson(res, 409, {
      error: 'These slides were changed somewhere else (for example in the visual editor) after you opened the source, so your version was not saved. Copy anything you need, choose Load latest, then make your change again.',
      version: sourceVersion(current),
    });
  }
  await writeDeckSource(slug, markdown);
  return sendJson(res, 200, { ok: true, version: sourceVersion(markdown) });
}

/**
 * GET …/status: the editor page's status line (it asks every 5 s while it is open and on screen, which also keeps
 * its editor from being stopped for being idle, and keeps its edit pass).
 */
async function presentationStatus({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  touchEditor(slug);
  const status = await deckStatus(slug);
  // Round 8 review: without a live edit pass (the page was hidden for a while, or the editor stopped) the editor
  // counts as stopped for this page, which then opens it again with a new pass.
  const sessionId = currentSessionId(req);
  const pass = sessionId ? passes.live(sessionId, slug, 'edit') : null;
  if (pass) passes.renew(pass);
  else if (sessionId) status.editor = 'stopped';
  return sendJson(res, 200, status);
}

/** POST …/publish: Publish now. A failed build answers 422 with Slidev's last lines; the old version stays live. */
async function publishPresentation({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  try {
    await buildDeck(slug);
  } catch (error) {
    return sendJson(res, error.buildFailed ? 422 : 500, { error: publishErrorMessage(error), log: error.log || '' });
  }
  return sendJson(res, 200, { ok: true, ...await deckStatus(slug) });
}

/** GET …/editor: the editor's start-up stage, for the editor page's loading message. */
async function editorProgress({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  return sendJson(res, 200, editorStage(slug));
}

/**
 * POST …/editor/leave { page }: the editor page was left. Its edit pass ends (the editor itself keeps running a while
 * for the next person), and what is saved is published now instead of after the quiet time.
 */
async function leaveEditor({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  safeSlug(slug);
  const sessionId = currentSessionId(req);
  if (sessionId) passes.endFor(sessionId, slug, 'edit', studioPageId(await readBody(req).catch(() => ({}))));
  if (!await deckExists(slug)) throw notFound();
  return sendJson(res, 200, { ok: true, publishing: await refreshBuildInBackground(slug, 500, { publishDraft: true }) });
}

/**
 * POST …/editor { page }: starts (or reuses) the deck's editor, and gives this /studio page the edit pass for it
 * (round 8). A start that fails answers 503 with Slidev's last lines.
 */
async function openEditor({ req, res, context, slug }) {
  const asked = Date.now();
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  const authMs = Date.now() - asked;
  try {
    const wasRunning = editorStage(slug).stage !== 'stopped';
    const editor = await ensureEditor(slug);
    editor.lastUsed = Date.now();
    console.log(`[GFM STUDIO OPEN: ${slug}] ${JSON.stringify({ auth_deck_ms: authMs, editor_wait_ms: Date.now() - asked - authMs, was_running: wasRunning })}`);
  } catch (error) {
    console.error(`[${slug}:edit] start failed`, error.message);
    if (error.startFailed) {
      return sendJson(res, 503, {
        error: 'The editor stopped while it was starting. This is usually caused by a mistake in the settings at the top of the slides, or by a missing add-on. You can still open Source to fix the slides. The details below may help.',
        log: error.log || '',
      });
    }
    return sendJson(res, 503, { error: 'The editor did not start in time. Please try again in a moment.' });
  }
  ensureDeckBuildWatcher(slug);
  // The page names itself (a random id, studio.html), so only its own leaving ends the pass (round 8 review).
  const sessionId = currentSessionId(req);
  const holder = studioPageId(await readBody(req).catch(() => ({})));
  const pass = sessionId ? { 'Set-Cookie': passCookie(slug, 'edit', passes.issue(sessionId, slug, 'edit', Date.now(), { holder }), passDomainFor(req.headers.host, PUBLIC_NAMES)) } : {};
  return sendJson(res, 200, { ok: true, editor: `${addressOf('deck', req.headers.host, ADDRESSES)}/edit/${slug}/` }, pass);
}

/**
 * POST …/preview: GFM Studio shows the published deck while the editor starts. Gives this browser a view pass for the
 * deck (the same one the library gives) and says where the published copy is; { preview: null } for a deck that was
 * never published (nothing to show yet; the person may change the deck, so no build is started for this).
 */
async function openPreview({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  const status = await deckStatus(slug);
  if (!status.published_at) return sendJson(res, 200, { ok: true, preview: null });
  const sessionId = currentSessionId(req);
  const deckAddress = addressOf('deck', req.headers.host, ADDRESSES);
  if (!sessionId || !deckAddress) return sendJson(res, 200, { ok: true, preview: null });
  const pass = { 'Set-Cookie': passCookie(slug, 'view', passes.issue(sessionId, slug, 'view'), passDomainFor(req.headers.host, PUBLIC_NAMES)) };
  return sendJson(res, 200, { ok: true, preview: `${deckAddress}/p/${slug}/`, published_at: status.published_at }, pass);
}

/**
 * POST …/prestart: the library's menu is open on this deck, so its editor is started ahead of time (editors.mjs
 * prestartDeck). Needs the right to change the deck; answers at once with what happened.
 */
async function prestartEditor({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  return sendJson(res, 200, { ok: true, prestart: prestartDeck(slug, 'the library menu was opened') });
}

/**
 * POST …/upload (the body is a source .zip, as Download source makes): puts its slides.md and its pictures in public/ into
 * the deck (source-upload.mjs; anything else in the ZIP is left out and listed). The old slides.md is kept as
 * slides.md.before-upload. The editor page reloads the editor afterwards. Needs the right to change the deck.
 */
async function uploadSource({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_ZIP_BYTES) throw httpError(413, 'This ZIP is too large (over 40 MB).');
    chunks.push(chunk);
  }
  try {
    const read = readSourceZip(Buffer.concat(chunks), slug);
    const written = await writeUpload(deckDir(slug), read);
    console.log(`[${slug}:upload] ${written.files} files and slides.md from a ZIP (${read.skipped.length} left out)`);
    return sendJson(res, 200, { ok: true, files: written.files, skipped: read.skipped.slice(0, 20) });
  } catch (error) {
    if (error instanceof UploadError) throw httpError(400, error.message);
    if (error?.code === 'ERR_BUFFER_OUT_OF_RANGE' || /inflate|zlib|invalid/i.test(String(error?.message))) throw httpError(400, 'This ZIP file is damaged.');
    throw error;
  }
}

/**
 * GET /api/presentations-diagnostics (managers only): what the editors and builds are doing, for the performance view
 * (the editor page with ?debug). Cold or warm editors, process, memory, start-up times of each step, cache state, the
 * last report of a browser (modules loaded, chart query and draw times), the last publish of each deck. Reads only.
 */
async function diagnostics({ res, context }) {
  await assertPresentationManager(context);
  const decks = await listDecks();
  const builds = {};
  for (const deck of decks) { const info = lastBuildInfo(deck.slug); if (info) builds[deck.slug] = info; }
  return sendJson(res, 200, {
    editors: await describeEditors(),
    max_editors: MAX_RUNNING_EDITORS,
    builds: { ...buildCounts(), addon: ADDON_FINGERPRINT, last: builds },
    manager: { rss_mb: Math.round(process.memoryUsage.rss() / 1048576), uptime_s: Math.round(process.uptime()) },
  });
}

/**
 * POST …/editor/perf { timeline }: what opening the editor cost in a real browser (the /studio page's window.GFM_PERF),
 * written to the log as "[GFM STUDIO CLIENT: <deck>]" so real people's numbers (their computer and line) can be
 * read next to the server's own ("[GFM STUDIO STARTUP: <deck>]"). Nothing else is done with it.
 */
async function editorPerf({ req, res, context, slug }) {
  await assertDeckEditor(context, slug);
  const body = await readBody(req).catch(() => ({}));
  rememberClientReport(slug, body?.timeline);
  const text = JSON.stringify(body?.timeline ?? null).slice(0, 6000);
  console.log(`[GFM STUDIO CLIENT: ${slug}] ${JSON.stringify({ user: context.user_id, agent: String(req.headers['user-agent'] || '').slice(0, 120) })} ${text}`);
  return sendJson(res, 200, { ok: true });
}

/** GET …/download: the deck's own files as a .zip (not its published copy or Slidev's cache). */
async function downloadSource({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  await existingDeck(slug);
  res.writeHead(200, {
    'Content-Type': 'application/zip',
    'Content-Disposition': `attachment; filename="${slug}.zip"`,
    'Cache-Control': 'no-store',
  });
  const archive = new ZipArchive({ zlib: { level: 9 } });
  archive.on('error', error => { try { res.destroy(error); } catch {} });
  archive.pipe(res);
  const generated = part => part === 'node_modules' || part === '.viewer.md' || part === 'slides.md.saving' || part.startsWith('.dist-');
  archive.directory(deckDir(slug), slug, entry => (entry.name.split('/').some(generated) ? false : entry));
  await archive.finalize();
}

/** GET …/access: the deck's sharing rule and the choices for Manage access (managers). */
async function readAccessRule({ res, context, slug }) {
  await assertPresentationManager(context);
  await existingDeck(slug);
  return sendJson(res, 200, await askPortalApi(context, 'access', { operation: 'get', deck_slug: slug }));
}

/** POST …/access { rule }: saves the deck's sharing rule (managers). A protected deck stays with the mission. */
async function saveAccessRule({ req, res, context, slug }) {
  await assertPresentationManager(context);
  await existingDeck(slug);
  const payload = await readBody(req);
  const refusal = ownerChangeRefusal(slug, payload.rule);
  if (refusal) return sendJson(res, 409, { error: refusal });
  return sendJson(res, 200, await askPortalApi(context, 'access', { operation: 'save', deck_slug: slug, rule: payload.rule }));
}

/**
 * DELETE /api/presentations/<deck>: deletes the deck, then its access rule. An older portal-api answers 4xx for
 * that; the deck is already gone, so it is only logged.
 */
async function deletePresentation({ res, context, slug }) {
  await assertDeckEditor(context, slug);
  await deleteDeck(slug);
  let accessRemoved = true;
  try {
    await askPortalApi(context, 'access', { operation: 'delete', deck_slug: slug });
  } catch (error) {
    accessRemoved = false;
    console.error(`[${slug}:delete] access rule not removed (${error.status || 'error'}): ${error.message}`);
  }
  return sendJson(res, 200, { ok: true, access_removed: accessRemoved });
}
