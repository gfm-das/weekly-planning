// Every setting of the presentation manager, in one place.
//
// What it is: the numbers and addresses the manager needs (ports, folders, how many editors may run, how long a
// sign-in lasts ...). Most come from the container's environment (slidev-compose.yml and slidev/.env); each one has
// a default, so the manager also starts without them.
// Who uses it: every other file of the manager's server (server.mjs and the files it loads).
// How it fits: nothing here does anything; it only reads settings once, when the manager starts.
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const env = process.env;

// ---- folders ----

/** This folder (/slidev/manager in the container): the manager's own files, the chart addon and the chart libraries. */
export const MANAGER_DIR = path.dirname(fileURLToPath(import.meta.url));

// Slidev's folder in the container. The tests point it at a temporary folder (PRESENTATION_SLIDEV_HOME), so they
// never touch real decks.
const SLIDEV_HOME = env.PRESENTATION_SLIDEV_HOME || '/slidev';

/** Where Slidev runs (the working folder of every `slidev` command). */
export const SLIDEV_DIR = SLIDEV_HOME;

/** One folder per deck: /slidev/decks/<deck>/slides.md, and its published copy in /slidev/decks/<deck>/dist. */
export const DECKS_DIR = path.join(SLIDEV_HOME, 'decks');

/** GFM Presentations V2 (v2-routes.mjs): one folder per deck with deck.json and assets/, next to the Slidev decks. */
export const V2_DECKS_DIR = path.join(SLIDEV_HOME, 'decks-v2');

/** The built V2 application (slidev/presentations-v2/dist, mounted read-only). One app serves every V2 deck. */
export const V2_APP_DIR = env.PRESENTATION_V2_APP_DIR || path.join(SLIDEV_HOME, 'presentations-v2');

/** The `slidev` program (from package.json's pinned @slidev/cli). */
export const SLIDEV_BIN = path.join(SLIDEV_HOME, 'node_modules', '.bin', 'slidev');

/**
 * Node's on-disk compile cache for the Slidev processes (editors and builds): the 1.5 to 2 s of JavaScript Slidev loads
 * at every start is compiled once and reused by the next process. SLIDEV_COMPILE_CACHE=0 turns it off (A/B measurement).
 */
export const COMPILE_CACHE_DIR = env.SLIDEV_COMPILE_CACHE === '0' ? '' : path.join(SLIDEV_HOME, '.compile-cache');

/** The text editor of the Source pane (the Monaco copy Slidev already installs). */
export const MONACO_DIR = path.join(SLIDEV_HOME, 'node_modules', 'monaco-editor', 'min', 'vs');

/** The pinned package list; part of the chart addon's fingerprint (a change rebuilds every published deck). */
export const PACKAGE_JSON = path.join(SLIDEV_HOME, 'package.json');

// ---- addresses ----

/** The network address both listeners use inside the container (the tests use 127.0.0.1). */
export const BIND_ADDRESS = env.PRESENTATION_BIND_ADDRESS || '0.0.0.0';

/** "The manager address": the library, /studio, the API and the Whiteboard frames. Browsers use port 3030. */
export const MANAGER_PORT = Number(env.PRESENTATION_MANAGER_PORT || 3040);

/**
 * "The deck address" (round 8, deck-origin.mjs): published decks and the deck editor run here, never with the
 * manager's sign-in. Inside the container 3041 (0: any free port, for tests); browsers use port 8089.
 */
export const DECK_SERVER_PORT = Number(env.PRESENTATION_DECK_SERVER_PORT ?? 3041);
export const DECK_PUBLIC_PORT = Number(env.PRESENTATIONS_DECK_PORT || 8089);
export const MANAGER_PUBLIC_PORT = Number(env.PRESENTATIONS_PUBLIC_PORT || 3030);

/**
 * Round 10: the public names on the internet (Cloudflare tunnel routes, docs/handoff/round10/public-everything.md):
 * the manager address (port 3030) and the deck address (port 8089) each have one, and a deck pass made on one is
 * used on the other as a cookie of the whole domain (deck-origin.mjs publicSide, addressOf, passDomainFor). An
 * empty setting turns a name off. The office addresses (the ports) stay as they are.
 */
// GFM_PUBLIC_DOMAIN (for example example.org) gives the defaults: presentations.<domain>, decks.<domain>, the domain
// itself for the cookie and https://<domain> (and www.) for the portal. Empty: no public names.
const PUBLIC_DOMAIN = String(env.GFM_PUBLIC_DOMAIN ?? '').trim().replace(/^\.+|\.+$/g, '').toLowerCase();
export const PUBLIC_NAMES = Object.freeze({
  manager: originOnly(env.PRESENTATIONS_PUBLIC_MANAGER_ORIGIN ?? (PUBLIC_DOMAIN ? `https://presentations.${PUBLIC_DOMAIN}` : '')),
  deck: originOnly(env.PRESENTATIONS_PUBLIC_DECK_ORIGIN ?? (PUBLIC_DOMAIN ? `https://decks.${PUBLIC_DOMAIN}` : '')),
  cookieDomain: String(env.PRESENTATIONS_PUBLIC_COOKIE_DOMAIN ?? PUBLIC_DOMAIN).trim(),
});

/** The portal's public addresses (its Cloudflare routes). They count as portal addresses like the office ones. */
export const PUBLIC_PORTAL_ORIGINS = (env.PRESENTATIONS_PUBLIC_PORTAL_ORIGINS ?? (PUBLIC_DOMAIN ? `https://${PUBLIC_DOMAIN},https://www.${PUBLIC_DOMAIN}` : ''))
  .split(',').map(originOnly).filter(Boolean);

/** Everything addressOf (deck-origin.mjs) needs to name the manager address or the deck address for a request. */
export const ADDRESSES = Object.freeze({ managerPort: MANAGER_PUBLIC_PORT, deckPort: DECK_PUBLIC_PORT, names: PUBLIC_NAMES });

/**
 * A host name Vite accepts for the editors (Slidev's dev servers refuse unknown host names; localhost and IP
 * addresses are always accepted). Round 10: slidev-compose.yml says "localhost", so it is the deck address's public
 * name then, which the editor is opened on from the internet.
 */
export const PUBLIC_HOST = env.PRESENTATIONS_HOST && env.PRESENTATIONS_HOST !== 'localhost'
  ? env.PRESENTATIONS_HOST
  : (PUBLIC_NAMES.deck ? new URL(PUBLIC_NAMES.deck).hostname : 'localhost');

// The portal's office addresses, as configured (slidev-compose.yml).
const OFFICE_PORTAL_ORIGINS = (env.PRESENTATIONS_PORTAL_ORIGINS || `http://localhost:8070,http://127.0.0.1:8070,http://${env.GFM_HOST_IP || '192.168.1.20'}:8070`)
  .split(',').map(origin => origin.trim()).filter(Boolean);

/** The portal's addresses: only they may sign a browser in to Presentations and frame its pages. */
export const PORTAL_ORIGINS = new Set([...OFFICE_PORTAL_ORIGINS, ...PUBLIC_PORTAL_ORIGINS]);

/**
 * The scheme and port of each office portal address ("http:8070"). The portal on this same computer (the name the
 * browser used for the manager) counts on those ports too, so a new office address or a host name needs no new
 * setting. The public addresses are not used here: they are named in full (PUBLIC_PORTAL_ORIGINS).
 */
export const PORTAL_PORTS = new Set(OFFICE_PORTAL_ORIGINS.map(schemeAndPort).filter(Boolean));

/** 'https://name' from a setting (a trailing slash or path dropped), or '' when it is empty or not an http(s) address. */
function originOnly(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  try {
    const url = new URL(text);
    return /^https?:$/.test(url.protocol) ? url.origin : '';
  } catch {
    return '';
  }
}

function schemeAndPort(origin) {
  try {
    const url = new URL(origin);
    return `${url.protocol}${url.port}`;
  } catch {
    return '';
  }
}

// ---- other services ----

/** Supabase checks a sign-in token and says who the person is. */
export const SUPABASE_URL = env.SUPABASE_URL;
export const SUPABASE_SERVICE_KEY = env.SUPABASE_SERVICE_ROLE_KEY;

/** portal-api answers who may do what (/internal/presentations/check) and gives the mission numbers. */
export const PORTAL_API_URL = (env.PRESENTATION_ACL_API_URL || 'http://portal-api:8091').replace(/\/$/, '');
export const PORTAL_API_KEY = env.PORTAL_SERVICE_KEY;

// ---- sign-in ----

/** A Presentations sign-in lasts at most this long (and never longer than the portal's own token). */
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

// ---- editors (one Slidev development server per deck being edited) ----

/** The first internal port an editor gets (each new editor takes the next one). */
export const FIRST_EDITOR_PORT = Number(env.SLIDEV_INTERNAL_PORT_START || 3100);

/** At most this many editors run; starting one more stops the one used longest ago. */
export const MAX_RUNNING_EDITORS = Number(env.SLIDEV_MAX_RUNNING || 10);

/** An editor nobody has used for this long is stopped (each uses about 540 MB). */
export const IDLE_STOP_MS = Math.max(5, Number(env.SLIDEV_IDLE_MINUTES) || 40) * 60 * 1000;

/** Start the most recently changed deck's editor ahead of time. SLIDEV_PRESTART=0 turns this off. */
export const PRESTART = env.SLIDEV_PRESTART !== '0';

/**
 * The manager's own warm-up of a starting editor (editors.mjs warmEditor: it loads the editor page's ~450 files once
 * before the editor counts as ready). SLIDEV_WARMUP=0 turns it off; only for the A/B measurement of click-to-editable
 * (slidev/tests/studio-perf), it stays on in the live system until that measurement says otherwise.
 */
export const WARMUP = env.SLIDEV_WARMUP !== '0';

/** ... but not when this many editors already run. */
export const PRESTART_MAX_RUNNING = 2;

/** An editor started ahead of time that nobody opened stops after this long (10 minutes). */
export const PRESTART_IDLE_MS = 10 * 60 * 1000;

// ---- publishing (slidev build) ----

/** Background builds wait until the slides have not changed for this long (10 s). */
export const BUILD_DEBOUNCE_MS = Math.max(1000, Number(env.SLIDEV_BUILD_DEBOUNCE_MS) || 10000);

/**
 * GFM Studio saves only while a deck is edited: nothing is built until Publish now, until the person leaves the editor
 * (its queued publish) or until an idle editor is stopped. SLIDEV_AUTO_PUBLISH=1 brings back the old behaviour (a build
 * BUILD_DEBOUNCE_MS after the slides stop changing).
 */
export const AUTO_PUBLISH_WHILE_EDITING = env.SLIDEV_AUTO_PUBLISH === '1';

/** Builds run at a lower priority (BusyBox nice) so editing stays quick; null when nice is missing. */
export const NICE_BIN = ['/bin/nice', '/usr/bin/nice'].find(file => existsSync(file)) || null;

/**
 * How many builds may run at once: one (a build needs about 0.5 GB), or two with SLIDEV_BUILD_CONCURRENCY=2.
 * Builds someone waits for (a change, Publish now, a first view) go before catching up with a new chart addon.
 */
export const BUILD_CONCURRENCY = Math.min(2, Math.max(1, Math.round(Number(env.SLIDEV_BUILD_CONCURRENCY) || 1)));

/** A published deck's note of which chart addon it was built with (a dotfile, never served). */
export const BUILD_INFO_FILE = '.gfm-build.json';

/** A minute after the manager starts, decks built with another chart addon are rebuilt. SLIDEV_ADDON_REBUILD=0: never. */
export const ADDON_REBUILD = env.SLIDEV_ADDON_REBUILD !== '0';
export const ADDON_REBUILD_DELAY_MS = 60000;
