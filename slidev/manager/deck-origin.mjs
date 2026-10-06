// Round 8: presentations on their own address ("the deck address").
//
// Why. A deck is page code: its slides can run JavaScript in the browser of
// whoever opens it, and since round 7 Zone Leaders and Sister Training Leaders
// write decks too. The manager (APs, the President, Data Analysts) signs in to
// Presentations on http://<computer>:3030 ("the manager address"). If a zone's
// deck ran on that same address, its code could use the manager's sign-in.
// So published decks (/p/<deck>/) and the deck editor (/edit/<deck>/, Slidev's
// development server) are served on a second address, port 8089 of the same
// computer. The manager's sign-in cookie is never accepted there.
//
// Two browser facts shape the rest of this file:
//   1. Cookies belong to the computer's name, not to the port. The browser
//      sends the manager's cookie to 8089 too, and sends 8089's cookies to 3030.
//      So the deck address simply ignores the manager's cookie, and 3030
//      ignores the deck address's cookies.
//   2. Two ports of the same computer are "same-site". The browser therefore
//      also sends the manager's cookie when a deck page asks 3030 for
//      something. So 3030 refuses every request that comes from a deck page
//      (managerRefusal below): its data routes need the X-GFM-Request header
//      (or a Bearer token), which a page on another address can only send after
//      asking 3030 first ("CORS preflight"), and 3030 never says yes to the deck
//      address. It also looks at the Origin and Sec-Fetch-Site headers the
//      browser adds.
//
// What a deck page gets instead of the manager's sign-in: a "deck pass"
// (DeckPasses below). It is a random number in a cookie, made by 3030 when the
// person opens a deck from the library (a view pass, read-only) or from the
// editor page (an edit pass). A pass is good for one deck only, only for that
// deck's own files, its editor and the numbers of the charts written in it,
// and only for a short time (round 8 review):
//   - a view pass ends 30 minutes after it was last used; an open deck page
//     uses it every 5 minutes (a small script the server adds to the page), so
//     it lasts while the deck is open;
//   - an edit pass ends 15 minutes after it was last used; the /studio page
//     renews it while it is open, and it ends at once when /studio is left or
//     the editor stops;
//   - every pass ends with the person's Presentations sign-in (at most 12 h).
//
// Who uses it: the manager address's routes (manager-routes.mjs), the deck address's routes (deck-routes.mjs) and
// sign-in.mjs (which keeps the passes).
// How it fits: this file holds only the rules; the routes apply them. Plain Node, no packages:
// slidev/tests/deck-origin.test.mjs tests all of it.
import crypto from 'node:crypto';

/** The header every call to the manager's data routes carries (portal-bridge.js adds it). */
export const REQUEST_HEADER = 'x-gfm-request';

/** How long a pass can live at most (the person's sign-in usually ends it sooner). */
export const PASS_MAX_MS = 12 * 60 * 60 * 1000;

/** How long a pass lasts after it was last used: a view pass 30 minutes, an edit pass 15 minutes. */
export const PASS_IDLE_MS = Object.freeze({ view: 30 * 60 * 1000, edit: 15 * 60 * 1000 });

/** How often an open deck page uses its pass, so it lasts while the page is open (5 minutes). */
export const PASS_KEEPALIVE_MS = 5 * 60 * 1000;

// ---- addresses ----------------------------------------------------------------------------------------------------

/** The computer's name in a Host header ("192.168.1.20:3030" gives "192.168.1.20"), or ''. */
export function hostnameOf(host) {
  try { return new URL(`http://${host}`).hostname; } catch { return ''; }
}

/**
 * The address on this computer at `port`, for the name the browser used (so it works on localhost and on the
 * office network alike). hostname() keeps the brackets of an IPv6 name ("[::1]").
 */
export function addressFor(host, port, protocol = 'http:') {
  const name = hostnameOf(host);
  if (!name || !/^[a-z0-9.:[\]-]+$/i.test(name)) return '';
  return `${protocol}//${name}:${Number(port)}`;
}

/**
 * Is `origin` (an Origin header) a page on the deck address: the deck port on any computer name, or (round 10) the
 * deck address's public name (`deckName`, e.g. https://decks.example.org)?
 */
export function isDeckOrigin(origin, deckPort, deckName = '') {
  if (!origin || origin === 'null') return false;
  if (deckName && String(origin).toLowerCase() === String(deckName).toLowerCase()) return true;
  try { return Number(new URL(origin).port) === Number(deckPort); } catch { return false; }
}

// ---- Round 10: the public names ---------------------------------------------------------------------------------
// On the internet (Cloudflare tunnel routes, docs/handoff/round10/public-everything.md) the two addresses are two
// names instead of two ports of one computer:
//   names = { manager: 'https://presentations.example.org',   (the tunnel's route to port 3030)
//             deck: 'https://decks.example.org',              (the tunnel's route to port 8089)
//             cookieDomain: 'example.org' }
// The rules stay the same: the two are different addresses ("origins"), and like two ports of one computer they are
// "same-site" to each other. One thing differs: a cookie of one name is not sent to the other name. So on the public
// names a deck pass is a cookie of the whole domain (passCookie's `domain`), which reaches the deck address. The
// manager's sign-in cookie stays on the manager's name only (the deck address never even receives it there).

const hostOf = origin => { try { return new URL(origin).host.toLowerCase(); } catch { return ''; } };

/** Which public name this Host header is: 'manager', 'deck' or '' (an office address, localhost, anything else). */
export function publicSide(host, names = {}) {
  const asked = String(host || '').toLowerCase();
  if (!asked) return '';
  if (names.manager && hostOf(names.manager) === asked) return 'manager';
  if (names.deck && hostOf(names.deck) === asked) return 'deck';
  return '';
}

/**
 * The address of one side ('manager' or 'deck') for a request that came in with this Host header: on a public name
 * the other public name (or its own), elsewhere the same computer name on that side's port (addressFor).
 * addresses: { managerPort, deckPort, names } (settings.mjs ADDRESSES).
 */
export function addressOf(side, host, { managerPort, deckPort, names = {} } = {}) {
  if (publicSide(host, names)) return names[side] || '';
  return addressFor(host, side === 'deck' ? deckPort : managerPort);
}

/** The Domain of a deck pass for a request on this Host: the public domain on a public name, else '' (the computer). */
export function passDomainFor(host, names = {}) {
  const domain = String(names.cookieDomain || '');
  return publicSide(host, names) && /^[a-z0-9.-]+$/i.test(domain) ? domain : '';
}

/** Is `origin` exactly this server's own address (the Host header the browser sent)? */
export function isOwnOrigin(origin, host) {
  try { return new URL(origin).host === String(host || ''); } catch { return false; }
}

// ---- 3030: who may call the manager's routes ------------------------------------------------------------------------

// Answers for a refused request (shown as JSON to a program, never to a person using the pages normally).
export const FROM_DECK_PAGE = 'This request came from a presentation page, so it was refused.';
export const MISSING_HEADER = 'This request did not come from the Presentations page, so it was refused. Reload the page and try again.';

// The routes that read or change something: the manager's API, and the two editor routes the chart builder of
// /studio calls on 3030 (/__slidev/ and /@studio/, passed on to the deck's editor).
const DATA_ROUTE = /^\/(api|__slidev|@studio)\//;
// The source download is a plain link (a browser navigation), which cannot carry a header.
const DOWNLOAD = /^\/api\/presentations\/[a-z0-9-]+\/download$/;
// Pages that give out a deck pass (/p/<deck>/), or lead to the editor (/studio/<deck>, /edit/<deck>/).
const DOORWAY = /^\/(p|edit|studio)\//;
// The portal's sign-in (CORS for the portal only) and sign-out have their own checks (sign-in.mjs).
const OWN_CHECKS = new Set(['/api/session', '/api/logout']);

const lower = value => String(value || '').toLowerCase();

/**
 * May this request reach the manager's route on 3030? null = yes; otherwise the sentence to refuse it with
 * (403). req: { method, pathname, headers (lower-case names, as Node gives them) }.
 * - Never from a page on the deck address (Origin on the deck port), or from a page without an address ("null").
 * - Data routes: only from this server's own pages (Sec-Fetch-Site same-origin, Origin this server), and only with
 *   the X-GFM-Request header or a Bearer token. The source download (a plain link) needs neither header.
 * - Doorways (/p/, /edit/, /studio/): see doorwayFromOtherPage.
 * Browsers too old to send Sec-Fetch-Site are still covered by the header rule.
 */
export function managerRefusal({ method = 'GET', pathname = '/', headers = {} }, { deckPort, deckName = '' }) {
  const origin = headers.origin;
  if (origin === 'null' || isDeckOrigin(origin, deckPort, deckName)) return FROM_DECK_PAGE;
  if (OWN_CHECKS.has(pathname) || !DATA_ROUTE.test(pathname)) return null;
  const site = lower(headers['sec-fetch-site']);
  const download = (method === 'GET' || method === 'HEAD') && DOWNLOAD.test(pathname);
  if (site && site !== 'same-origin' && !(download && site === 'none')) return MISSING_HEADER;
  if (origin && !isOwnOrigin(origin, headers.host)) return MISSING_HEADER;
  if (headers[REQUEST_HEADER] || /^Bearer\s/.test(String(headers.authorization || ''))) return null;
  return download ? null : MISSING_HEADER;
}

/**
 * Is this a doorway request (/p/, /edit/, /studio/) that another page started (a deck page on 8089, or anything
 * else on another address)? Then 3030 gives out no pass and opens no editor; it shows a page asking the person to
 * confirm instead (pages.mjs confirmPage), so a deck's code cannot open another deck or an editor by itself.
 * Only the manager's own pages (same-origin) and an address typed by the person (none) go straight through.
 */
export function doorwayFromOtherPage({ pathname = '/', headers = {} }) {
  if (!DOORWAY.test(pathname)) return false;
  const site = lower(headers['sec-fetch-site']);
  return site === 'same-site' || site === 'cross-site';
}

// ---- 8089: what the deck address accepts ------------------------------------------------------------------------------

/**
 * May this request reach the deck address? null = yes; otherwise the sentence to refuse it with (403).
 * Reading (GET, HEAD) is fine from anywhere: the browser never lets another address read the answer, because the
 * deck address sends no CORS headers. Anything that changes something (the editor saving slides, a chart's numbers
 * asked with POST) must come from a page on the deck address itself, so no other page on this computer can use a
 * person's pass for them.
 */
export function deckRefusal({ method = 'GET', headers = {} }) {
  if (method === 'GET' || method === 'HEAD') return null;
  const site = lower(headers['sec-fetch-site']);
  if (site && site !== 'same-origin') return FROM_OTHER_ADDRESS;
  if (headers.origin && !isOwnOrigin(headers.origin, headers.host)) return FROM_OTHER_ADDRESS;
  return null;
}

export const FROM_OTHER_ADDRESS = 'This request came from another address, so it was refused.';

/** May a websocket (the editor's live connection) be opened? Only by a page on the deck address itself. */
export function deckSocketAllowed(headers = {}) {
  return !!headers.origin && isOwnOrigin(headers.origin, headers.host);
}

// ---- deck passes ------------------------------------------------------------------------------------------------------

/** The cookie name of a pass: gfm_view_<deck> (a published deck) or gfm_edit_<deck> (its editor). */
export function passCookieName(slug, mode) {
  if (mode !== 'view' && mode !== 'edit') throw new Error('A pass is for viewing or for editing.');
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(String(slug))) throw new Error('Invalid presentation id.');
  return `gfm_${mode}_${slug}`;
}

/**
 * The Set-Cookie header for a pass. HttpOnly: the deck's own code can never read it. SameSite=Strict: only
 * pages of this computer send it. Path=/: the editor asks for files outside /edit/<deck>/ too. No Max-Age: it
 * also ends when the browser closes; the server ends it with the sign-in anyway.
 * domain (round 10, passDomainFor): on the public names the pass is made on the manager's name and used on the deck
 * address's name, so it is a cookie of the whole domain there, and only sent over https (Secure).
 */
export function passCookie(slug, mode, id, domain = '') {
  const wide = domain ? `; Domain=${domain}; Secure` : '';
  return `${passCookieName(slug, mode)}=${id}; HttpOnly; SameSite=Strict; Path=/${wide}`;
}

/** Every value of cookie `name` in a Cookie header (a page can add a second cookie of the same name). */
export function cookieValues(header, name) {
  const values = [];
  for (const part of String(header || '').split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).trim() === name) values.push(part.slice(at + 1).trim());
  }
  return values;
}

/**
 * The passes this server gave out, kept in memory (a restart ends them all, like the sign-ins).
 * A pass is { id, sessionId, slug, mode, until, limit }: whose sign-in it belongs to (never shown to the browser),
 * the one deck it is for, 'view' or 'edit', when it ends unless it is used again (until), and when it ends at the
 * latest (limit, maxMs after it was made).
 */
export class DeckPasses {
  constructor({ maxMs = PASS_MAX_MS, idleMs = PASS_IDLE_MS, max = 20000, randomId = () => crypto.randomBytes(32).toString('hex') } = {}) {
    this.maxMs = maxMs;
    this.idleMs = idleMs;
    this.max = max;
    this.byId = new Map();
    this.randomId = randomId;
  }

  /** The live pass of this sign-in for this deck and mode, or null. */
  live(sessionId, slug, mode, now = Date.now()) {
    for (const pass of this.byId.values()) {
      if (pass.sessionId === sessionId && pass.slug === slug && pass.mode === mode && pass.until > now) return pass;
    }
    return null;
  }

  /**
   * A pass for this sign-in, deck and mode: the one it already has (still good, now renewed), or a new one.
   * holder: which page asked for it (the /studio page's own random id), so only that page's leaving ends it (endFor).
   */
  issue(sessionId, slug, mode, now = Date.now(), { holder = '' } = {}) {
    passCookieName(slug, mode); // checks slug and mode
    const current = this.live(sessionId, slug, mode, now);
    if (current) {
      current.holder = holder;
      return this.renew(current, now).id;
    }
    this.sweep(now);
    if (this.byId.size >= this.max) this.byId.delete(this.byId.keys().next().value);
    const id = this.randomId();
    const limit = now + this.maxMs;
    this.byId.set(id, { id, sessionId, slug, mode, holder, limit, until: Math.min(limit, now + this.idleMs[mode]) });
    return id;
  }

  /** Used again: the pass lasts idleMs from now (never past its limit). Returns the pass. */
  renew(pass, now = Date.now()) {
    pass.until = Math.max(pass.until, Math.min(pass.limit, now + this.idleMs[pass.mode]));
    return pass;
  }

  /** The pass with this id for exactly this deck and mode, still good, or null. Finding it does not renew it. */
  find(id, slug, mode, now = Date.now()) {
    const pass = typeof id === 'string' ? this.byId.get(id) : null;
    if (!pass || pass.slug !== slug || pass.mode !== mode) return null;
    if (pass.until <= now) { this.byId.delete(id); return null; }
    return pass;
  }

  /** Ends every pass of a sign-in (sign-out, or the sign-in was replaced). */
  endSession(sessionId) {
    for (const [id, pass] of this.byId) if (pass.sessionId === sessionId) this.byId.delete(id);
  }

  /**
   * Ends one sign-in's pass for this deck and mode (the person left the editor page). With holder: only if that page
   * holds it now (a second /studio tab of the same deck, or the same page reloaded, keeps it).
   */
  endFor(sessionId, slug, mode, holder = '') {
    for (const [id, pass] of this.byId) {
      if (pass.sessionId !== sessionId || pass.slug !== slug || pass.mode !== mode) continue;
      if (!holder || !pass.holder || pass.holder === holder) this.byId.delete(id);
    }
  }

  /** Ends everyone's passes for this deck and mode (its editor stopped: nobody edits it until /studio opens it again). */
  endDeck(slug, mode) {
    for (const [id, pass] of this.byId) if (pass.slug === slug && pass.mode === mode) this.byId.delete(id);
  }

  /** Forgets passes that have ended. */
  sweep(now = Date.now()) {
    for (const [id, pass] of this.byId) if (pass.until <= now) this.byId.delete(id);
  }

  get size() { return this.byId.size; }
}

/**
 * The pass a request carries for this deck and mode, or null: every cookie of that name is tried (a deck page can
 * add cookies of its own; only one made by this server is a pass).
 */
export function passFromCookies(passes, cookieHeader, slug, mode, now = Date.now()) {
  let name;
  try { name = passCookieName(slug, mode); } catch { return null; }
  for (const value of cookieValues(cookieHeader, name)) {
    const pass = passes.find(value, slug, mode, now);
    if (pass) return pass;
  }
  return null;
}

/** The deck named by a page address on the deck address (/p/<deck>/… or /edit/<deck>/…), or ''. */
export function deckOfPath(pathname) {
  const m = /^\/(?:p|edit)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\/|$)/.exec(String(pathname || ''));
  return m ? m[1] : '';
}

export const FROM_OTHER_PAGE = 'This request came from another page, so it was refused.';

/**
 * Which deck a request for numbers on the deck address is for (round 8 review): the deck of the page that sent it,
 * read from the Referer the browser adds (a page of this same address, /p/<deck>/… or /edit/<deck>/…). A request
 * that names another deck than its own page, or comes from no deck page, is refused. The request then needs that
 * deck's own pass (passFromCookies). Returns { deck } or { refusal } (403).
 * This keeps a deck's own code to its own deck's numbers in the normal case. It is not a wall: all decks share the
 * one deck address, so a deck's code could still send a request that looks as if another deck's page sent it. What
 * it could then get is limited by the passes (only decks this person has open, or had open in the last minutes) and
 * by pinning (only the numbers of the charts written in that deck).
 */
export function deckOfRequest(headers = {}, named = '') {
  let page = '';
  try {
    const referer = new URL(String(headers.referer || ''));
    if (isOwnOrigin(referer.origin, headers.host)) page = deckOfPath(referer.pathname);
  } catch {}
  if (!page || (named && named !== page)) return { refusal: FROM_OTHER_PAGE };
  return { deck: page };
}
