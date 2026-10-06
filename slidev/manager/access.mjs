// Who may do what: the manager asks portal-api.
//
// What it is: portal-api knows every person's role, zone and district, and every deck's owner and sharing rule, so
// it decides who may open, change or make a deck (/internal/presentations/check). This file asks it and turns the
// answer into "yes" or an error with the right status (403 and a sentence for the person).
//   - managers (AP, President, Data Analyst) open and change every deck;
//   - a Zone Leader or Sister Training Leader opens and changes their own zone's decks, and opens decks shared
//     with them; a District Leader opens decks shared with them; missionaries have no Presentations.
// A positive answer is remembered for 15 seconds, because the editor loads hundreds of files and every one of them
// is checked. Taking access away therefore works within 15 seconds.
// Who uses it: the route files, sign-in.mjs and numbers.mjs.
// How it fits: the rules that read portal-api's answer are in zone-decks.mjs (tested there with plain Node).
import { ShortMemory } from './delivery.mjs';
import { safeSlug } from './deck-files.mjs';
import { PORTAL_API_KEY, PORTAL_API_URL } from './settings.mjs';
import { httpError } from './web.mjs';
import { mayCreateDecks, mayEditDeck, mayUsePresentations } from './zone-decks.mjs';

const CHECK_MEMORY_MS = 15000;

/**
 * Calls portal-api's /internal/presentations/<endpoint> for this person (the service key proves it is the
 * manager). 503 when portal-api cannot be reached; portal-api's own status and sentence when it refuses.
 */
export async function askPortalApi(context, endpoint, payload) {
  if (!PORTAL_API_KEY) throw httpError(503, 'Presentation access management is temporarily unavailable.');
  let response;
  try {
    response = await fetch(`${PORTAL_API_URL}/internal/presentations/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Service-Key': PORTAL_API_KEY },
      body: JSON.stringify({ ...payload, user_id: context.user_id }),
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    throw httpError(503, 'Presentation access management is temporarily unavailable. Please retry.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw httpError(response.status, data.error || data.detail || 'Presentation access denied.');
  return data;
}

/**
 * portal-api's answer about these decks for this person ({ can_manage, can_create, role, allowed_slugs,
 * editable_slugs, owner_zones }). 403 for someone who has no Presentations at all (missionaries).
 */
export async function checkPresentationAccess(context, slugs = []) {
  const access = await askPortalApi(context, 'check', { deck_slugs: slugs.map(safeSlug) });
  if (!mayUsePresentations(access)) throw httpError(403, 'Presentation access is available to assigned leaders.');
  return access;
}

// ---- opening a deck ----

// "May open this deck", per person and deck.
const presentationChecks = new ShortMemory(CHECK_MEMORY_MS);

/** May this person open this deck? Their access answer, or 403. */
export async function presentationAccess(context, slug) {
  const key = `${context.user_id}:${slug}`;
  let access = presentationChecks.get(key);
  if (!access) {
    access = await checkPresentationAccess(context, [slug]);
    if (!access.can_manage && !access.allowed_slugs?.includes(slug)) throw httpError(403, 'This presentation is not assigned to you.');
    presentationChecks.set(key, access);
  }
  return access;
}

// ---- changing and making decks ----

// "May change this deck", per person and deck.
const editorChecks = new ShortMemory(CHECK_MEMORY_MS);

/**
 * May this person change this deck (Studio, Source, Publish, rename, copy, delete, download its source)? Managers
 * every deck, a ZL or STL their own zone's decks. Their access answer, or 403.
 */
export async function assertDeckEditor(context, slug) {
  const key = `${context.user_id}:${safeSlug(slug)}`;
  const cached = editorChecks.get(key);
  if (cached) return cached;
  const access = await checkPresentationAccess(context, [slug]);
  if (!mayEditDeck(access, slug)) throw httpError(403, "You can change only your own zone's presentations.");
  editorChecks.set(key, access);
  return access;
}

/** May this person make a new deck (and use the chart builder's list of numbers)? Managers, and a ZL or STL with a zone. */
export async function assertDeckCreator(context) {
  const access = await checkPresentationAccess(context);
  if (!mayCreateDecks(access)) throw httpError(403, 'You do not have permission to manage presentations.');
  return access;
}

// ---- managers ----

// "Is a manager", per person.
const managerChecks = new ShortMemory(CHECK_MEMORY_MS);

/** Is this person a manager (AP, President, Data Analyst)? Their access answer, or 403. */
export async function assertPresentationManager(context) {
  const cached = managerChecks.get(context.user_id);
  if (cached) return cached;
  const access = await checkPresentationAccess(context);
  if (!access.can_manage) {
    managerChecks.delete(context.user_id);
    throw httpError(403, 'You do not have permission to manage presentations.');
  }
  managerChecks.set(context.user_id, access);
  return access;
}

/** Forgets the remembered manager answer (a new sign-in asks again). */
export function forgetManagerCheck(userId) {
  managerChecks.delete(userId);
}
