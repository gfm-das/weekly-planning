// Zone presentations (round 7): Zone Leaders (ZL) and Sister Training Leaders
// (STL) make presentations for their own zone.
//
// What it is: who may do what is decided by portal-api (/internal/presentations/check,
// app.deck_allowed and app.deck_editable), because it knows every person's
// zone and every deck's owner (migration 035). This file only reads that
// answer:
//   - managers (AP, President, Data Analyst) open and change every deck;
//   - a ZL or STL opens and changes their own zone's decks, and opens (never
//     changes) decks a manager shared with them;
//   - a DL opens (never changes) decks a manager shared with them, as since
//     round 2; missionaries have no Presentations.
// It also holds two guards for the editor, which is Slidev's development
// server: a ZL or STL may reach only their own deck's files through it, and
// the Slidev processes never get the service keys.
// Who uses it: access.mjs (the checks), editors.mjs and builds.mjs (the guards), the route files (the library, the
// ✎ button) and numbers.mjs (the chart builder's list).
// How it fits: plain Node, no packages, so slidev/tests/zone-decks.test.mjs tests these rules directly.
import { PROTECTED_DECKS, protectedReason } from './protected-decks.mjs';

// The roles that use Presentations besides the managers (the same list as
// portal-api roles.LEADER_ROLES). Only used when an older portal-api does not
// send can_use yet.
const PRESENTATION_LEADERS = ['DL', 'ZL', 'STL'];

/** May this person use Presentations at all? `access` is portal-api's check answer. */
export function mayUsePresentations(access) {
  if (access?.can_manage) return true;
  if (typeof access?.can_use === 'boolean') return access.can_use;
  return PRESENTATION_LEADERS.includes(access?.role);
}

/** May this person change this deck (Studio, Source, publish, rename, duplicate, delete, source download)? */
export function mayEditDeck(access, slug) {
  return !!access?.can_manage || (access?.editable_slugs || []).includes(slug);
}

/** May this person make a new deck? Managers, and a ZL or STL who has a zone. */
export function mayCreateDecks(access) {
  return !!access?.can_manage || access?.can_create === true;
}

/**
 * The library's list: the decks this person may open, each with can_edit (the
 * menu offers Edit, Rename, … only then) and, for managers, the name of the
 * zone that owns it (zone_name, shown on the card).
 */
export function libraryView(decks, access) {
  const allowed = new Set(access?.allowed_slugs || []);
  const zones = access?.owner_zones || {};
  const shown = access?.can_manage ? decks : decks.filter(deck => allowed.has(deck.slug));
  return {
    can_create: mayCreateDecks(access),
    presentations: shown.map(deck => ({
      ...deck,
      can_edit: mayEditDeck(access, deck.slug),
      ...(zones[deck.slug] ? { zone_name: zones[deck.slug] } : {}),
    })),
  };
}

// A deck is page code: its slides can run JavaScript in the browser of whoever
// opens it, and a manager opens every deck. Round 7 served a zone deck opened by
// a manager sandboxed, which showed managers an empty page. Since round 8 every
// published deck and every deck editor runs on its own address, the deck
// address (deck-origin.mjs), where the manager's sign-in is never accepted, so
// managers see zone decks fully and the sandbox is gone.

/**
 * The key the chart builder's list of numbers and places is kept under:
 * managers all get the whole mission, so theirs is shared per mission; a ZL's
 * or STL's list holds only their own zone, so it is kept for them alone.
 */
export function catalogCacheKey(context, access) {
  const mission = context.mission_id ?? `user ${context.user_id}`;
  return access?.can_manage ? `${mission}:managers` : `${mission}:user ${context.user_id}`;
}

/**
 * Manage access must not give a protected deck (protected-decks.mjs: one that
 * another page opens by its folder name) to a zone: it stays a managers-only
 * mission deck. Returns the reason to refuse, or null. The list has been empty
 * since round 6 (the Dashboards tab is DataEase); `list` is for tests.
 */
export function ownerChangeRefusal(slug, rule, list = PROTECTED_DECKS) {
  if (!protectedReason(slug, list)) return null;
  const owner = rule?.owner_zone_id;
  return owner === null || owner === undefined || owner === '' ? null
    : 'Another part of the mission portal opens this deck by its name, so it stays with the mission and cannot be given to a zone.';
}

// Folders under /slidev that every editor needs: Slidev itself, the addons
// and the manager's chart code. Everything else under /slidev (other decks,
// backups) is refused to a zone editor.
const SHARED_FOLDERS = ['/slidev/node_modules/', '/slidev/manager/'];

/** The URL decoded until it stops changing (at most 3 times), or null when it cannot be decoded. */
function decodedUrl(url) {
  let text = String(url || '');
  for (let i = 0; i < 3; i++) {
    let next;
    try { next = decodeURIComponent(text); } catch { return null; }
    if (next === text) return text;
    text = next;
  }
  return text;
}

/**
 * May a zone editor's request go to their deck's Slidev development server?
 * That server can read any file under /slidev (Vite's `/@fs/` addresses), so
 * a ZL or STL could otherwise read other zones' decks through it. Allowed: the
 * deck's own folder, Slidev's packages and the manager's chart code. Refused:
 * any other folder under /slidev, and any `..` step. Since round 8 this holds for
 * managers too (editors.mjs assertEditorRequest): a deck's editor runs that deck's code.
 */
export function editorRequestAllowed(url, slug) {
  const text = decodedUrl(url);
  if (text === null || text.includes('\0') || text.includes('\\')) return false;
  const path = text.split('?')[0];
  if (path.split('/').includes('..')) return false;
  const own = `/slidev/decks/${slug}/`;
  for (let at = text.indexOf('/slidev/'); at !== -1; at = text.indexOf('/slidev/', at + 1)) {
    const rest = text.slice(at);
    if (!rest.startsWith(own) && !SHARED_FOLDERS.some(folder => rest.startsWith(folder))) return false;
  }
  return true;
}

// Environment variables that hold secrets (the service keys come from the
// container's .env). A Slidev editor or build never needs them.
const SECRET_NAME = /KEY|SECRET|TOKEN|PASSWORD|PASSWD|JWT|DATABASE_URL|DB_URL/i;

/** The environment for Slidev editors and builds: the manager's, without secrets. */
export function slidevEnv(env, extra = {}) {
  const clean = {};
  for (const [name, value] of Object.entries(env)) if (!SECRET_NAME.test(name)) clean[name] = value;
  return { ...clean, ...extra };
}
