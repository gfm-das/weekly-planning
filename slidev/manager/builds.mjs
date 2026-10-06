// Publishing: turning a deck's slides.md into the pages viewers see.
//
// What it is: `slidev build` makes a finished website of a deck in /slidev/decks/<deck>/dist ("the published copy").
// This file runs those builds: one at a time for the whole manager (a build needs about half a gigabyte of memory),
// the ones someone is waiting for first. It also publishes on its own:
//   - when the person leaves the editor, or an idle editor is stopped (a queued publish; editing itself only saves,
//     unless SLIDEV_AUTO_PUBLISH=1 brings back a build 10 seconds after the slides stop changing);
//   - when someone opens a deck whose published copy is older than its slides;
//   - after a new version of the chart addon is deployed (every deck built with the older one, at low priority).
// A new build is made in a temporary folder and only then swapped in, so a failed build never takes a deck away:
// viewers keep seeing the last good copy.
// Who uses it: the routes (Publish now, opening a deck, leaving the editor), editors.mjs and deck-actions.mjs.
// How it fits: the queue, the compression and the fingerprint helpers are in delivery.mjs (tested there).
import { watch as watchFolder } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { JobQueue, precompressDir, treeFingerprint } from './delivery.mjs';
import { builtDir, deckDir, deckExists, deckFile, latestDeckSourceMtime, listDecks, safeSlug } from './deck-files.mjs';
import { AUTO_PUBLISH_WHILE_EDITING, BUILD_CONCURRENCY, COMPILE_CACHE_DIR, BUILD_DEBOUNCE_MS, BUILD_INFO_FILE, MANAGER_DIR, NICE_BIN, PACKAGE_JSON, SLIDEV_BIN, SLIDEV_DIR } from './settings.mjs';
import { slidevEnv } from './zone-decks.mjs';

/**
 * The chart addon's fingerprint: the addon, the chart libraries and the pinned packages. Every build notes it; a
 * published deck with another fingerprint was built with older chart code and is rebuilt.
 */
export const ADDON_FINGERPRINT = treeFingerprint([path.join(MANAGER_DIR, 'gfm-addon'), path.join(MANAGER_DIR, 'vendor'), PACKAGE_JSON]);

// Builds of one deck in progress: slug -> the promise of its build (and of the one more build queued after it).
const buildPromises = new Map();
// Decks that changed while their build ran: they are built once more afterwards.
const pendingRebuilds = new Set();
// Decks whose build someone is waiting for (they go first in the queue).
const urgentBuilds = new Set();
const buildQueue = new JobQueue(BUILD_CONCURRENCY);
// Background builds waiting for the slides to be quiet: slug -> timer.
const buildTimers = new Map();
// Folders being watched while their deck is open in the editor: slug -> watcher.
const deckWatchers = new Map();
// The last build of each deck: { building, error: { message, log, at } | null, finished_at }.
const buildState = new Map();
// How long each deck's last publish took (for the manager-only diagnostics, manager-routes.mjs diagnostics).
const lastBuilds = new Map();
export function lastBuildInfo(slug) { return lastBuilds.get(slug) ?? null; }

/** How busy the builds are, for GET /health. */
export function buildCounts() {
  return { running: buildQueue.running, waiting: buildQueue.waiting.length };
}

// ---- Slidev's messages ----

// Terminal colour codes in Slidev's output.
const ANSI_PATTERN = /\u001b\[[0-9;?]*[ -\/]*[@-~]/g;

/**
 * The lines of Slidev's output worth showing a person: colours taken out, empty lines and program stack lines left
 * out. Used to explain a failed build or a failed editor start.
 */
export function outputLines(chunk) {
  return String(chunk).replace(ANSI_PATTERN, '').split(/\r?\n/).filter(line => line.trim() && !/^\s+at\s/.test(line));
}

/** The sentence shown when publishing did not work. */
export function publishErrorMessage(error) {
  return error.buildFailed
    ? 'Slidev could not build this presentation, so it was not published. The version people saw before is still live. The details below usually point to the slide with the problem.'
    : `Publishing did not work: ${error.message}`;
}

// ---- one build ----

/** Builds a deck into a temporary folder and swaps it in for the published copy. */
async function buildDeckOnce(slug) {
  safeSlug(slug);
  const dir = deckDir(slug);
  const stamp = `${process.pid}-${Date.now()}`;
  const tempOut = path.join(dir, `.dist-building-${stamp}`);
  const oldOut = path.join(dir, `.dist-old-${stamp}`);
  await fs.rm(tempOut, { recursive: true, force: true });
  await fs.rm(oldOut, { recursive: true, force: true });
  console.log(`[${slug}:build] background production build starting`);
  const started = Date.now();
  // The last lines Slidev printed, so a failed publish can explain itself. Slidev's names for single slides are
  // turned into "slide N, line L", which points at the right place.
  const output = [];
  const keep = chunk => {
    for (const line of outputLines(chunk)) {
      output.push(line
        .replaceAll(tempOut, 'dist')
        .replaceAll(`${dir}/`, '')
        .replace(/slides\.md__slidev_(\d+)\.md:(\d+):(\d+)/g, 'slides.md, slide $1, line $2 of that slide')
        .slice(0, 400));
      if (output.length > 200) output.shift();
    }
  };
  try {
    await runSlidevBuild(slug, tempOut, keep);
    await finishBuild(slug, tempOut, started);
    await swapInBuild(builtDir(slug), tempOut, oldOut);
    console.log(`[${slug}:build] published successfully`);
  } catch (error) {
    await fs.rm(tempOut, { recursive: true, force: true }).catch(() => {});
    error.log = output.slice(-20).join('\n');
    throw error;
  }
}

/** Runs `slidev build` (at a lower priority, so an open editor stays quick). Rejects when it fails. */
function runSlidevBuild(slug, out, keep) {
  return new Promise((resolve, reject) => {
    const args = ['build', deckFile(slug), '--out', out, '--base', `/p/${slug}/`];
    const child = spawn(NICE_BIN || SLIDEV_BIN, NICE_BIN ? ['-n', '10', SLIDEV_BIN, ...args] : args, {
      cwd: SLIDEV_DIR,
      // Without the service keys: Zone Leaders write decks too (zone-decks.mjs slidevEnv).
      env: slidevEnv(process.env, COMPILE_CACHE_DIR ? { NODE_COMPILE_CACHE: COMPILE_CACHE_DIR } : {}),
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    // Read as text, so a character split between two chunks survives.
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      keep(chunk);
      console.log(`[${slug}:build] ${String(chunk).trimEnd()}`);
    });
    child.stderr.on('data', chunk => {
      keep(chunk);
      console.error(`[${slug}:build] ${String(chunk).trimEnd()}`);
    });
    child.on('error', reject);
    child.on('exit', code => {
      if (code === 0) return resolve();
      reject(Object.assign(new Error(`Slidev build failed with exit code ${code}`), { buildFailed: true }));
    });
  });
}

/**
 * After a good build: compressed copies of its text files (.br, .gz) for viewers, and a note of the chart addon it
 * was built with. Files that did not change since the published copy keep its compressed copies. A failed
 * compression only costs speed: the plain files are sent instead.
 */
async function finishBuild(slug, out, started) {
  const built = Date.now();
  const packed = await precompressDir(out, { reuseFrom: builtDir(slug) }).catch(error => {
    console.error(`[${slug}:build] could not compress the build`, error.message);
    return null;
  });
  await fs.writeFile(path.join(out, BUILD_INFO_FILE), JSON.stringify({ addon: ADDON_FINGERPRINT, built_at: new Date().toISOString() }));
  const compressed = packed
    ? `; compressed ${packed.files} files (${packed.reused} unchanged) from ${Math.round(packed.raw / 1024)} KB to ${Math.round(packed.br / 1024)} KB (br) / ${Math.round(packed.gz / 1024)} KB (gzip) in ${seconds(packed.ms)} s`
    : '';
  console.log(`[${slug}:build] built in ${seconds(built - started)} s${compressed}`);
  lastBuilds.set(slug, { ms: built - started, at: new Date().toISOString(), compress_ms: packed?.ms ?? null });
}

/** Puts the new build in place of the published copy. The old copy stays until the new one is in place. */
async function swapInBuild(out, tempOut, oldOut) {
  let hadOldBuild = false;
  try {
    await fs.rename(out, oldOut);
    hadOldBuild = true;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  try {
    await fs.rename(tempOut, out);
  } catch (error) {
    // The swap failed: put the old working copy back.
    if (hadOldBuild) await fs.rename(oldOut, out).catch(() => {});
    throw error;
  }
  await fs.rm(oldOut, { recursive: true, force: true });
}

/** Seconds with one decimal, for the log. */
export function seconds(ms) {
  return (ms / 1000).toFixed(1);
}

// ---- the build queue ----

/**
 * Builds a deck through the build queue. priority 'now': someone waits for it (a change, Publish now, a first view,
 * leaving the editor); 'later': catching up with a new chart addon, after every 'now' build.
 */
export async function buildDeck(slug, { priority = 'now' } = {}) {
  safeSlug(slug);
  if (buildPromises.has(slug)) return joinRunningBuild(slug, priority);
  if (priority === 'now') urgentBuilds.add(slug);
  const job = (async () => {
    do {
      pendingRebuilds.delete(slug);
      if (buildQueue.running >= buildQueue.limit) console.log(`[${slug}:build] waiting for another presentation's build to finish`);
      await buildQueue.run(() => buildDeckOnce(slug), { key: slug, priority: urgentBuilds.has(slug) ? 'now' : 'later' });
    } while (pendingRebuilds.has(slug));
  })();
  buildPromises.set(slug, job);
  buildState.set(slug, { ...(buildState.get(slug) || {}), building: true });
  try {
    await job;
    buildState.set(slug, { building: false, error: null, finished_at: new Date().toISOString() });
  } catch (error) {
    buildState.set(slug, {
      building: false,
      finished_at: new Date().toISOString(),
      error: { message: publishErrorMessage(error), log: error.log || '', at: new Date().toISOString() },
    });
    throw error;
  } finally {
    if (buildPromises.get(slug) === job) {
      buildPromises.delete(slug);
      urgentBuilds.delete(slug);
    }
  }
}

// A build of this deck is already running or waiting: wait for it (and ask for one more when something changed).
function joinRunningBuild(slug, priority) {
  // Catching up with the chart addon: any build of this deck brings it.
  if (priority !== 'now') return buildPromises.get(slug);
  urgentBuilds.add(slug);
  buildQueue.hurry(slug);
  // Something changed while a build is already running: run one more build after it. A build still waiting for its
  // turn reads the slides when it starts, so it needs no second one.
  if (!buildQueue.isWaiting(slug)) pendingRebuilds.add(slug);
  return buildPromises.get(slug);
}

/** Builds after a rename or a copy, without letting a build problem undo the change itself. */
export async function buildReport(slug) {
  try {
    await buildDeck(slug);
    return {};
  } catch (error) {
    return { build_error: publishErrorMessage(error), build_log: error.log || '' };
  }
}

/** Publishing state for the editor page's status line (deck-actions.mjs deckStatus). */
export function buildStatus(slug) {
  const building = buildPromises.has(slug);
  const waiting = buildTimers.has(slug);
  return {
    building: building || waiting,
    // Waiting for the slides to be quiet before building (not building yet).
    build_waiting: waiting && !building,
    build_error: buildState.get(slug)?.error || null,
  };
}

/** Forgets a deck's last build result (it was renamed or deleted). */
export function forgetBuild(slug) {
  buildState.delete(slug);
}

// ---- publishing on its own ----

/** A background build after `delay` ms; a newer call for the same deck starts the wait again. */
export function scheduleBackgroundBuild(slug, delay = BUILD_DEBOUNCE_MS, priority = 'now') {
  safeSlug(slug);
  clearTimeout(buildTimers.get(slug));
  const timer = setTimeout(() => {
    buildTimers.delete(slug);
    buildDeck(slug, { priority }).catch(error => console.error(`[${slug}:build] background build failed`, error.message));
  }, delay);
  buildTimers.set(slug, timer);
}

/**
 * Publishes a deck by itself while it is being edited: Studio saves slides.md after every change, and a build starts
 * once the slides have been quiet for BUILD_DEBOUNCE_MS (not after each change). The folder is watched rather than
 * slides.md itself, because a save replaces the file, which would silently end a watch on the old file.
 */
export function ensureDeckBuildWatcher(slug) {
  safeSlug(slug);
  if (!AUTO_PUBLISH_WHILE_EDITING || deckWatchers.has(slug)) return;
  try {
    const watcher = watchFolder(deckDir(slug), { persistent: false }, (event, filename) => {
      if (filename && String(filename) !== 'slides.md') return;
      scheduleBackgroundBuild(slug, BUILD_DEBOUNCE_MS);
    });
    watcher.on('error', error => {
      console.error(`[${slug}:watch]`, error.message);
      closeDeckWatcher(slug);
    });
    deckWatchers.set(slug, watcher);
    console.log(`[${slug}:watch] automatic publishing enabled`);
  } catch (error) {
    console.error(`[${slug}:watch] could not start`, error.message);
  }
}

/** Stops watching a deck (it is being renamed or deleted) and drops its waiting background build. */
export function closeDeckWatcher(slug) {
  const watcher = deckWatchers.get(slug);
  deckWatchers.delete(slug);
  try { watcher?.close(); } catch {}
  clearTimeout(buildTimers.get(slug));
  buildTimers.delete(slug);
}

// The chart addon fingerprint a published copy was built with (null for older builds, which noted none).
async function builtAddon(slug) {
  try {
    return JSON.parse(await fs.readFile(path.join(builtDir(slug), BUILD_INFO_FILE), 'utf8')).addon || null;
  } catch {
    return null;
  }
}

// Whether a deck is being edited (editors.mjs says so): its saved slides are a draft until the person publishes.
let draftInProgress = () => false;
export function setDraftCheck(check) { draftInProgress = check; }

/**
 * Publishes in the background when the published copy is older than the slides, or was made with another chart
 * addon. Returns whether a build was scheduled. While the deck is open in an editor its newer slides are a draft:
 * a viewer opening the deck does not publish them (publishDraft: true is for the editor being left or stopped).
 */
export async function refreshBuildInBackground(slug, delay = 50, { publishDraft = false } = {}) {
  // Any build takes the slides as they are saved, so a deck with a draft is not built here, not even for a new addon.
  if (!publishDraft && !AUTO_PUBLISH_WHILE_EDITING && draftInProgress(slug)) return false;
  try {
    const index = path.join(builtDir(slug), 'index.html');
    const [sourceMtime, buildStat, addon] = await Promise.all([latestDeckSourceMtime(deckDir(slug)), fs.stat(index), builtAddon(slug)]);
    if (sourceMtime > buildStat.mtimeMs) {
      scheduleBackgroundBuild(slug, delay, 'now');
      return true;
    }
    // Only the chart addon is older (after a deploy): the queue takes it after every build someone waits for. A
    // build already running or waiting brings the new addon anyway. A deck that failed to build with this addon is
    // not tried again on every view; changing its slides (or Publish now) tries again.
    if (addon !== ADDON_FINGERPRINT && !buildState.get(slug)?.error) {
      if (!buildPromises.has(slug) && !buildTimers.has(slug)) scheduleBackgroundBuild(slug, delay, 'later');
      return true;
    }
  } catch {
    // Never published: ensureBuild builds it while the viewer waits.
  }
  return false;
}

/**
 * After a new chart addon was deployed: rebuilds every published deck built with another one, one at a time and
 * after any build someone waits for, so published charts get the new chart code without anyone publishing.
 */
export async function rebuildDecksWithOldAddon() {
  let rebuilt = 0;
  let failed = 0;
  for (const deck of await listDecks()) {
    const built = await fs.stat(path.join(builtDir(deck.slug), 'index.html')).catch(() => null);
    if (!built || await builtAddon(deck.slug) === ADDON_FINGERPRINT) continue;
    console.log(`[${deck.slug}:build] rebuilding: it was built with another chart addon`);
    try {
      await buildDeck(deck.slug, { priority: 'later' });
      rebuilt++;
    } catch (error) {
      failed++;
      console.error(`[${deck.slug}:build] rebuild failed`, error.message);
    }
  }
  if (rebuilt || failed) console.log(`[addon] chart addon ${ADDON_FINGERPRINT}: ${rebuilt} published decks rebuilt, ${failed} failed`);
}

/**
 * Makes sure a deck has a published copy. Opening a deck never waits for a build when a copy exists (a newer one is
 * made in the background); only a deck that was never published is built while the viewer waits.
 */
export async function ensureBuild(slug) {
  safeSlug(slug);
  if (!await deckExists(slug)) throw new Error('Presentation not found.');
  try {
    await fs.access(path.join(builtDir(slug), 'index.html'));
    return;
  } catch {
    // Never published: build it now.
  }
  await buildDeck(slug);
}
