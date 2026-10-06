// The deck editors: one Slidev development server per deck being edited.
//
// What it is: the visual editor (Studio, inside Slidev) runs in a small server of its own for each deck, started on
// demand ("slidev <deck>/slides.md --port 31xx") and reached through this manager at /edit/<deck>/ on the deck
// address. Starting one takes a while, so:
//   - the editor page shows three steps while it starts (starting, preparing, ready: editorStage);
//   - before it counts as ready, the manager loads the editor page's code once itself ("warm-up"), so the browser's
//     first visit is quick and does not reload halfway;
//   - its code goes packed (gzip) to the browser: a quarter of the size (answerFromEditor);
//   - the most recently changed deck's editor is started ahead of time (prestartRecentDeck);
//   - an editor nobody has used for 40 minutes is stopped, and what it saved is published.
// Only the /studio page starts an editor; the deck address never does (runningEditor), so a deck's code cannot wake
// up another deck's editor. When an editor stops, its edit passes end with it.
// Who uses it: the route files and deck-actions.mjs (a renamed or deleted deck's editor is stopped).
// How it fits: builds.mjs publishes; this file only runs editors. The warm-up itself is in delivery.mjs.
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import httpProxy from 'http-proxy';
import { assertDeckEditor } from './access.mjs';
import { outputLines, refreshBuildInBackground, seconds, setDraftCheck } from './builds.mjs';
import { packableAnswer, warmModuleGraph } from './delivery.mjs';
import { deckDir, deckExists, deckFile, listDecks, safeSlug } from './deck-files.mjs';
import { FIRST_EDITOR_PORT, IDLE_STOP_MS, MAX_RUNNING_EDITORS, PRESTART, PRESTART_IDLE_MS, PRESTART_MAX_RUNNING, COMPILE_CACHE_DIR, PUBLIC_HOST, SLIDEV_BIN, SLIDEV_DIR, WARMUP } from './settings.mjs';
import { OPEN_AGAIN, passes } from './sign-in.mjs';
import { httpError } from './web.mjs';
import { editorRequestAllowed, slidevEnv } from './zone-decks.mjs';

// slug -> { slug, port, process, lastUsed, spawnedAt, stage: 'starting' | 'preparing' | 'ready', readyPromise }
const editors = new Map();
setDraftCheck(slug => editors.has(slug));
let nextPort = FIRST_EDITOR_PORT;

// The name of a deck's editor in the log: "[zone-conference:edit] ...".
const label = slug => `${slug}:edit`;

/** How many editors run (for GET /health). */
export function runningEditorCount() {
  return editors.size;
}

// ---- which deck's editor a request is for, and the way in (a proxy to the editor's own port) ----

// selfHandleResponse: the editor's answers are sent on by answerFromEditor below (packed where that helps).
const proxy = httpProxy.createProxyServer({ ws: true, xfwd: true, changeOrigin: false, selfHandleResponse: true });
proxy.on('error', (error, req, res) => {
  console.error('proxy error', error);
  // For a websocket `res` is the raw socket (no writeHead): an editor that stopped while a browser still had its live
  // connection open used to crash the whole manager here (found by the Studio startup measurement).
  if (typeof res?.writeHead !== 'function') { try { res?.destroy?.(); } catch {} return; }
  if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
  try { res.end('Presentation server unavailable.'); } catch {}
});
proxy.on('proxyRes', (proxyRes, req, res) => answerFromEditor(proxyRes, req, res));

/**
 * Sends an answer of the editor on to the browser, with its status and headers. Vite sends its files as they are:
 * the editor's first visit loads about 430 of them, 21 MB (measured round 9), so text goes packed (gzip) to a browser
 * that takes it (delivery.mjs packableAnswer). Packing runs beside the server (a zlib stream); "not changed" answers
 * (304) stay as they are.
 */
function answerFromEditor(proxyRes, req, res) {
  const headers = { ...proxyRes.headers };
  // Node sets how the connection and the body are carried itself.
  for (const name of ['connection', 'keep-alive', 'transfer-encoding']) delete headers[name];
  const packed = packableAnswer(req, proxyRes.statusCode, proxyRes.headers);
  if (packed) {
    delete headers['content-length'];
    headers['content-encoding'] = 'gzip';
    headers.vary = headers.vary ? `${headers.vary}, Accept-Encoding` : 'Accept-Encoding';
  }
  res.writeHead(proxyRes.statusCode, proxyRes.statusMessage, headers);
  const body = packed ? proxyRes.pipe(zlib.createGzip({ level: 5 })) : proxyRes;
  body.on('error', () => res.destroy());
  body.pipe(res);
}

/** The deck named by an /edit/<deck>/… address, or null. */
export function editSlugFromPath(pathname) {
  return pathname.match(/^\/edit\/([a-z0-9-]+)(?:\/|$)/)?.[1] || null;
}

/**
 * The deck whose editor page sent this request (its Referer is /edit/<deck>/…), or null. Slidev's editor also asks
 * for files outside /edit/<deck>/ (/@fs/…, /__slidev/…); the Referer says which deck's editor they are for.
 */
export function editorSlugFromReferer(req) {
  const referer = req.headers.referer || req.headers.referrer || '';
  if (!referer) return null;
  try {
    return editSlugFromPath(new URL(referer).pathname);
  } catch {
    return null;
  }
}

/**
 * Every request to a deck's editor: the person may change the deck, and reaches only that deck's own files through
 * it (zone-decks.mjs editorRequestAllowed). Since round 8 this holds for managers too: a deck's editor runs that
 * deck's code, which must not read other decks.
 */
export async function assertEditorRequest(req, context, slug) {
  const access = await assertDeckEditor(context, slug);
  if (!editorRequestAllowed(req.url, slug)) throw httpError(403, 'This file is not part of your presentation.');
  return access;
}

/** Passes a request on to the deck's editor. */
export function proxyToEditor(req, res, editor) {
  proxy.web(req, res, { target: `http://127.0.0.1:${editor.port}` });
}

/** Passes the editor's live connection (a websocket) on to the deck's editor. */
export function proxySocketToEditor(req, socket, head, editor) {
  proxy.ws(req, socket, head, { target: `http://127.0.0.1:${editor.port}` });
}

// ---- starting ----

/**
 * The deck's editor, started if it is not running. Every request that arrives while it starts waits for the same
 * start. `why` is written to the log.
 */
export async function ensureEditor(slug, why = 'opened', { prestart = false } = {}) {
  safeSlug(slug);
  if (!await deckExists(slug)) throw new Error('Presentation not found.');
  const current = editors.get(slug);
  // A process that exists is not ready yet: wait for its start like everyone else.
  if (current && current.process.exitCode === null) {
    current.lastUsed = Date.now();
    if (!prestart) current.opened = true;
    if (current.readyPromise) await current.readyPromise;
    return current;
  }
  await trimEditors();
  const editor = startEditor(slug, why);
  // opened: someone really uses it. An editor started only ahead of time stops sooner when nobody comes (PRESTART_IDLE_MS).
  editor.opened = !prestart;
  try {
    await editor.readyPromise;
  } catch (error) {
    await stopEditor(slug);
    throw error;
  }
  return editor;
}

// Starts Slidev for the deck and returns the editor; its readyPromise settles when it is ready or failed.
function startEditor(slug, why) {
  const port = nextPort++;
  // Slidev serves the editor at /edit/<deck>/, the same address the manager passes on.
  const basePath = `/edit/${slug}/`;
  const child = spawn(SLIDEV_BIN, [deckFile(slug), '--remote', '--bind', '127.0.0.1', '--port', String(port), '--base', basePath], {
    cwd: SLIDEV_DIR,
    // Without the service keys: Zone Leaders use this editor too (zone-decks.mjs slidevEnv).
    env: slidevEnv(process.env, { __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS: PUBLIC_HOST, ...(COMPILE_CACHE_DIR ? { NODE_COMPILE_CACHE: COMPILE_CACHE_DIR } : {}) }),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  // timings (ms since the spawn) are what GET …/editor reports to the editor page's startup measurement.
  const editor = { slug, port, process: child, lastUsed: Date.now(), spawnedAt: Date.now(), stage: 'starting', readyPromise: null, timings: {} };
  editors.set(slug, editor);
  console.log(`[${label(slug)}] starting Slidev on port ${port} (${why})`);
  const recent = keepOutput(slug, child);
  const stopped = stoppedWhileStarting(child, recent);
  child.on('exit', () => {
    if (editors.get(slug)?.process === child) {
      editors.delete(slug);
      editorGone(slug);
    }
  });
  // Ready = Slidev answers and the editor page's code is prepared (warm-up).
  editor.readyPromise = Promise.race([waitUntilReady(port, basePath, () => child.exitCode !== null || child.signalCode !== null), stopped]).then(async () => {
    editor.timings.slidev_answering = Date.now() - editor.spawnedAt;
    editor.stage = 'preparing';
    const warm = WARMUP ? await Promise.race([warmEditor(editor), stopped]) : null;
    Object.assign(editor.timings, { warm_ms: warm?.ms ?? null, warm_modules: warm?.modules ?? null, warm_mb: warm ? Math.round(warm.bytes / 104857.6) / 10 : null, warm_passes: warm?.passes ?? null });
    editor.stage = 'ready';
    editor.timings.ready = Date.now() - editor.spawnedAt;
    editor.lastUsed = Date.now();
    console.log(`[${label(slug)}] ready ${seconds(Date.now() - editor.spawnedAt)} s after start`);
    console.log(`[GFM STUDIO STARTUP: ${slug}] ${JSON.stringify(editor.timings)}`);
  });
  return editor;
}

// Logs what Slidev prints, and keeps its last 40 lines so a start that fails can explain itself.
function keepOutput(slug, child) {
  const recent = [];
  const keep = chunk => {
    for (const line of outputLines(chunk)) {
      recent.push(line.replaceAll(`${deckDir(slug)}/`, '').slice(0, 400));
      if (recent.length > 40) recent.shift();
    }
  };
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    keep(chunk);
    console.log(`[${label(slug)}] ${String(chunk).trimEnd()}`);
  });
  child.stderr.on('data', chunk => {
    keep(chunk);
    console.error(`[${label(slug)}] ${String(chunk).trimEnd()}`);
  });
  return recent;
}

/**
 * A promise that fails as soon as Slidev stops (a broken add-on, theme or setting can stop it at once), so the
 * editor page is not kept waiting the whole start-up time for a process that is gone.
 */
function stoppedWhileStarting(child, recent) {
  const stopped = new Promise((resolve, reject) => {
    const fail = reason => {
      const error = new Error(`Slidev stopped while starting (${reason}).`);
      error.startFailed = true;
      error.log = recent.slice(-20).join('\n');
      reject(error);
    };
    child.once('error', error => fail(error.message));
    child.once('exit', (code, signal) => fail(signal ? `signal ${signal}` : `exit code ${code}`));
  });
  stopped.catch(() => {});
  return stopped;
}

/** Waits until Slidev answers twice in a row (at most 90 s: a deck's first start can take a while). */
async function waitUntilReady(port, basePath, stopped = () => false) {
  const url = `http://127.0.0.1:${port}${basePath}`;
  const started = Date.now();
  let successes = 0;
  while (Date.now() - started < 90000 && !stopped()) {
    try {
      const response = await fetch(url);
      successes = response.ok ? successes + 1 : 0;
      if (successes >= 2) {
        console.log(`[slidev-ready] ${basePath} answering on port ${port} after ${seconds(Date.now() - started)} s`);
        return;
      }
    } catch {
      successes = 0;
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`Slidev did not become ready at ${url}`);
}

/**
 * Loads the editor page's code once, straight from the deck's editor, so Vite has prepared everything before the
 * browser asks (delivery.mjs warmModuleGraph). Never fails the start.
 */
async function warmEditor(editor) {
  const result = await warmModuleGraph(`http://127.0.0.1:${editor.port}/edit/${editor.slug}/1`, { timeoutMs: 60000 });
  const notes = [
    result.passes > 1 ? `a second pass after Vite re-bundled: ${result.passMs.map(seconds).join(' s + ')} s` : '',
    result.failed ? `${result.failed} failed` : '',
    result.error ? `stopped: ${result.error}` : '',
  ].filter(Boolean).join(', ');
  console.log(`[${label(editor.slug)}] prepared ${result.modules} files (${(result.bytes / 1048576).toFixed(1)} MB) in ${seconds(result.ms)} s${notes ? ` (${notes})` : ''}`);
  return result;
}

// ---- using and asking about a running editor ----

/**
 * The deck's editor if it is running (round 8 review). The deck address uses this: it never starts an editor. 401
 * ("Please open this presentation again") when it is not running.
 */
export async function runningEditor(slug) {
  const openAgain = () => httpError(401, OPEN_AGAIN);
  const editor = editors.get(slug);
  if (!editor || editor.process.exitCode !== null) throw openAgain();
  if (editor.readyPromise) await editor.readyPromise.catch(() => { throw openAgain(); });
  if (editors.get(slug) !== editor) throw openAgain();
  editor.lastUsed = Date.now();
  return editor;
}

/** Marks the deck's editor as in use (the editor page asks every 5 s while it is open and on screen). */
export function touchEditor(slug) {
  const editor = editors.get(slug);
  if (editor) editor.lastUsed = Date.now();
}

/** What the editor page shows while an editor starts: { stage: 'stopped' | 'starting' | 'preparing' | 'ready', seconds }. */
export function editorStage(slug) {
  const editor = editors.get(slug);
  if (!editor || editor.process.exitCode !== null) return { stage: 'stopped', seconds: 0 };
  return { stage: editor.stage || 'ready', seconds: Math.round((Date.now() - editor.spawnedAt) / 1000), timings: editor.timings };
}

// ---- stopping ----

// An editor stopped (idle, too many, renamed, deleted or crashed): its edit passes end with it (round 8 review), so
// nothing can change the deck through the deck address until someone opens it in /studio again.
function editorGone(slug) {
  passes.endDeck(slug, 'edit');
}

/** Stops the deck's editor, if one runs (also before the deck is renamed or deleted). */
export async function stopEditor(slug) {
  const editor = editors.get(slug);
  if (!editor) return;
  editors.delete(slug);
  editorGone(slug);
  // Slidev gets a moment to stop by itself; then it is stopped for sure (each editor holds about 540 MB).
  try { editor.process.kill('SIGTERM'); } catch {}
  await new Promise(resolve => setTimeout(resolve, 150));
  if (editor.process.exitCode === null) {
    try { editor.process.kill('SIGKILL'); } catch {}
  }
}


// When as many editors run as allowed: stops the one used longest ago.
async function trimEditors() {
  if (editors.size < MAX_RUNNING_EDITORS) return;
  const oldest = [...editors.values()].sort((a, b) => a.lastUsed - b.lastUsed)[0];
  if (oldest) await stopEditor(oldest.slug);
}

// Every minute: stops editors nobody has used for IDLE_STOP_MS, and publishes what they left unpublished (the
// editor page may have been closed without saying so).
setInterval(() => {
  const now = Date.now();
  for (const editor of editors.values()) {
    if (editor.stage !== 'ready' || now - editor.lastUsed < (editor.opened === false ? PRESTART_IDLE_MS : IDLE_STOP_MS)) continue;
    console.log(`[${label(editor.slug)}] stopping: not used for ${Math.round((now - editor.lastUsed) / 60000)} min`);
    stopEditor(editor.slug).then(() => refreshBuildInBackground(editor.slug, 1000));
  }
}, 60 * 1000).unref();

// ---- starting ahead of time ----

let lastPrestart = 0;

/**
 * Starts the editor of the deck changed most recently, so the next person to edit it finds it ready. Only when few
 * editors run, and at most once a minute.
 */
export async function prestartRecentDeck(why) {
  if (!PRESTART || Date.now() - lastPrestart < 60000) return;
  if (editors.size >= Math.min(PRESTART_MAX_RUNNING, MAX_RUNNING_EDITORS - 1)) return;
  lastPrestart = Date.now();
  const decks = await listDecks();
  const recent = decks.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];
  if (!recent || editors.has(recent.slug)) return;
  ensureEditor(recent.slug, why, { prestart: true }).catch(error => console.error(`[${label(recent.slug)}] start ahead failed`, error.message));
}

// A person showed they are about to edit this deck (the library's menu is open on it): start its editor now. Never
// more than INTENT_MAX_UNOPENED editors started ahead of time wait at once (about 540 MB each), never the last free
// place, and one start per deck every 30 s. An editor nobody comes to stops after PRESTART_IDLE_MS.
const lastIntent = new Map();
const INTENT_MAX_UNOPENED = 3;

/** Starts the deck's editor ahead of time. Returns what happened: 'running', 'starting', 'recent', 'busy' or 'off'. */
export function prestartDeck(slug, why) {
  safeSlug(slug);
  if (!PRESTART) return 'off';
  const current = editors.get(slug);
  if (current && current.process.exitCode === null) {
    current.lastUsed = Date.now();
    return 'running';
  }
  if (Date.now() - (lastIntent.get(slug) || 0) < 30000) return 'recent';
  const waiting = [...editors.values()].filter(editor => editor.opened === false).length;
  if (editors.size >= MAX_RUNNING_EDITORS - 1 || waiting >= INTENT_MAX_UNOPENED) return 'busy';
  lastIntent.set(slug, Date.now());
  ensureEditor(slug, why, { prestart: true }).catch(error => console.error(`[${label(slug)}] start ahead failed`, error.message));
  return 'starting';
}

// ---- manager-only diagnostics ----

// The last report of the /studio page for each deck (POST …/editor/perf), kept in short form.
const clientReports = new Map();

/** Remembers what a person's browser saw when it opened the editor (the page's window.GFM_PERF), in short form. */
export function rememberClientReport(slug, timeline) {
  if (!timeline || typeof timeline !== 'object') return;
  const frame = timeline.frame || {};
  const groups = frame.resources?.groups || {};
  clientReports.set(slug, {
    at: new Date().toISOString(),
    marks: timeline.marks || null,
    editor_marks: frame.marks || null,
    resources: frame.resources ? { count: frame.resources.count, wire_kb: frame.resources.wire_kb, decoded_kb: frame.resources.decoded_kb } : null,
    // The Studio parts the editor loaded: the lazy ones (panels, formula editor, import dialog) appear only once opened.
    studio_modules: Object.fromEntries(Object.entries(groups).filter(([name]) => /^studio|^gfm/.test(name))),
    charts: frame.charts || null,
    long_tasks: frame.long_tasks ? { count: frame.long_tasks.count, total_ms: frame.long_tasks.total_ms } : null,
    env: timeline.env || null,
  });
}

// Resident memory of a process in MB (Linux /proc), or null.
function residentMb(pid) {
  try {
    const m = /VmRSS:\s+(\d+) kB/.exec(readFileSync(`/proc/${pid}/status`, 'utf8'));
    return m ? Math.round(Number(m[1]) / 1024) : null;
  } catch {
    return null;
  }
}

/** Every running editor, for the manager-only diagnostics: cold or warm, process, memory, start-up times, last report. */
export async function describeEditors() {
  const now = Date.now();
  const out = [];
  for (const editor of editors.values()) {
    const vite = await fs.stat(path.join(deckDir(editor.slug), 'node_modules', '.vite')).catch(() => null);
    out.push({
      slug: editor.slug,
      pid: editor.process.pid,
      port: editor.port,
      stage: editor.stage,
      state: editor.stage === 'ready' ? (editor.opened === false ? 'warm, started ahead of time' : 'warm, in use') : editor.stage,
      uptime_s: Math.round((now - editor.spawnedAt) / 1000),
      idle_s: Math.round((now - editor.lastUsed) / 1000),
      rss_mb: residentMb(editor.process.pid),
      startup_ms: editor.timings,
      cache: { vite_cache: !!vite, vite_cache_updated: vite ? vite.mtime.toISOString() : null, compile_cache: !!COMPILE_CACHE_DIR, warmup: WARMUP },
      last_client_report: clientReports.get(editor.slug) ?? null,
    });
  }
  return out;
}
