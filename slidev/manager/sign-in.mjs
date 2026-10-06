// Who is signed in: Presentations sign-ins and deck passes.
//
// What it is: a person signs in to the mission portal, not to Presentations. The portal page then asks the manager
// for a Presentations sign-in (POST /api/session with the portal's token), which the manager remembers as a
// "session" and names in a cookie, `presentation_session`. The portal renews it every few minutes.
// A deck page on the deck address (port 8089) never gets that cookie's power. It gets a "deck pass" instead: good
// for one deck, one mode (view or edit) and a short time (deck-origin.mjs explains why and how).
// Who uses it: the route files (manager-routes.mjs, deck-routes.mjs) and editors.mjs (an editor that stops ends its
// edit passes).
// How it fits: sign-ins and passes live in memory only; a restart signs everybody out (the portal signs them in
// again at once).
import crypto from 'node:crypto';
import { checkPresentationAccess, forgetManagerCheck } from './access.mjs';
import { DeckPasses, isDeckOrigin, isOwnOrigin, passFromCookies, publicSide } from './deck-origin.mjs';
import { DECK_PUBLIC_PORT, PORTAL_ORIGINS, PORTAL_PORTS, PUBLIC_NAMES, SESSION_TTL_MS, SUPABASE_SERVICE_KEY, SUPABASE_URL } from './settings.mjs';
import { httpError, parseCookies, sendJson } from './web.mjs';

// id -> { context (who, from Supabase), authenticatedUntil (when the portal's token ends), expiresAt }
const sessions = new Map();
// Sign-ins ended by /api/logout (id -> when), kept for ten minutes, so a renewal that was already on its way cannot
// sign the browser back in afterwards.
const endedSessions = new Map();

/** The deck passes this manager gave out (deck-origin.mjs). Each belongs to one sign-in and ends with it. */
export const passes = new DeckPasses();

/** Ends a sign-in and every deck pass made from it. */
function endSession(id) {
  sessions.delete(id);
  passes.endSession(id);
}

// Every ten minutes: forget ended sign-ins and passes.
setInterval(() => {
  const now = Date.now();
  for (const [id, session] of sessions) if (session.expiresAt < now) endSession(id);
  for (const [id, at] of endedSessions) if (now - at > 10 * 60 * 1000) endedSessions.delete(id);
  passes.sweep(now);
}, 10 * 60 * 1000).unref();

// ---- the sign-in cookie ----

const EXPIRED_COOKIE = 'presentation_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT';

// Round 10: on the public name (https only, through the Cloudflare tunnel) the sign-in cookie is only sent over https.
// It stays a cookie of the manager's name alone: no Domain, so it never reaches the deck address or any other name.
const secureOn = req => publicSide(req?.headers?.host, PUBLIC_NAMES) ? '; Secure' : '';

function sessionCookie(id, expiresAt, req) {
  return `presentation_session=${encodeURIComponent(id)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${Math.max(1, Math.floor((expiresAt - Date.now()) / 1000))}${secureOn(req)}`;
}

function createSession(context) {
  const id = crypto.randomBytes(32).toString('hex');
  const authenticatedUntil = Math.min(context.token_expires_at, Date.now() + SESSION_TTL_MS);
  sessions.set(id, { context, authenticatedUntil, expiresAt: authenticatedUntil });
  return id;
}

/**
 * Renews the browser's current sign-in in place when it belongs to the same person, so open pages and the editor's
 * live connection keep working. Someone else's sign-in on this browser is ended first.
 */
function upsertSession(req, context) {
  const id = parseCookies(req).presentation_session;
  const current = id ? sessions.get(id) : null;
  if (current && current.context.user_id === context.user_id) {
    const authenticatedUntil = Math.min(context.token_expires_at, Date.now() + SESSION_TTL_MS);
    Object.assign(current, { context, authenticatedUntil, expiresAt: authenticatedUntil });
    return { id, session: current, refreshed: true };
  }
  if (current) endSession(id);
  const created = createSession(context);
  return { id: created, session: sessions.get(created), refreshed: false };
}

/** This browser's live sign-in on the manager address, or null. Using it keeps it alive (up to the portal's token). */
export function getSession(req) {
  const id = parseCookies(req).presentation_session;
  if (!id) return null;
  const session = sessions.get(id);
  if (!session) return null;
  if (session.expiresAt < Date.now()) {
    endSession(id);
    return null;
  }
  session.expiresAt = Math.min(session.authenticatedUntil, Date.now() + SESSION_TTL_MS);
  return session;
}

/** The id of this browser's live sign-in on the manager address, or null. */
export function currentSessionId(req) {
  return getSession(req) ? parseCookies(req).presentation_session : null;
}

/** The person's role in capitals ("AP", "ZL" ...). */
export function roleOf(context) {
  return String(context?.app_role || '').toUpperCase();
}

// ---- who is asking ----

/**
 * Who is asking on the manager address: the sign-in cookie, or a portal token (Authorization: Bearer). An error
 * ("Not signed in.", answered with 401) when neither is there.
 */
export async function authenticatedContext(req) {
  const session = getSession(req);
  if (session) return session.context;
  if ((req.headers.authorization || '').startsWith('Bearer ')) return getUserContextFromBearer(req);
  throw new Error('Not signed in.');
}

/**
 * Checks a portal token with Supabase and returns the person's context (their row of current_user_context) plus
 * `token_expires_at`. 401 for a token Supabase refuses, 403 for an account that is not active.
 */
async function getUserContextFromBearer(req) {
  const auth = req.headers.authorization || '';
  if (!auth.startsWith('Bearer ')) throw new Error('Not signed in.');
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) throw new Error('Supabase configuration is missing.');
  const headers = { apikey: SUPABASE_SERVICE_KEY, Authorization: auth };
  const userResponse = await fetch(`${SUPABASE_URL}/auth/v1/user`, { headers, signal: AbortSignal.timeout(10000) });
  if (!userResponse.ok) throw httpError(401, 'Not signed in. Please return to the portal.');
  const user = await userResponse.json();
  // Supabase has checked the token's signature above, so its end time can be trusted to cap the sign-in.
  const verifiedClaims = JSON.parse(Buffer.from(auth.slice(7).split('.')[1], 'base64url').toString('utf8'));
  const authenticatedUntil = Number(verifiedClaims.exp) * 1000;
  if (!Number.isFinite(authenticatedUntil) || authenticatedUntil <= Date.now()) throw httpError(401, 'Not signed in. Please return to the portal.');
  const response = await fetch(`${SUPABASE_URL}/rest/v1/current_user_context?select=*&user_id=eq.${encodeURIComponent(user.id)}`, {
    headers, signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error(`Could not verify user (${response.status}).`);
  const rows = await response.json();
  if (!rows?.[0] || rows[0].user_id !== user.id || rows[0].user_active !== true) throw httpError(403, 'Your mission account is not active.');
  return { ...rows[0], token_expires_at: authenticatedUntil };
}

// ---- deck passes ----

/** What a deck page is told when its pass is missing or has ended (with its sign-in). */
export const OPEN_AGAIN = 'Please open this presentation again from the presentation library.';

/**
 * Who is asking on the deck address: the person whose sign-in made the pass this request carries for this deck
 * (a 'view' or an 'edit' pass, in the order given). Never the manager's own cookie. 401 without a good pass.
 * Returns { context, pass }. Using a pass renews it (it lasts a while after its last use); the sign-in itself is
 * only looked at here, not extended: the portal keeps it alive.
 */
export function passHolder(req, slug, modes) {
  for (const mode of modes) {
    const pass = slug ? passFromCookies(passes, req.headers.cookie, slug, mode) : null;
    const session = pass ? sessions.get(pass.sessionId) : null;
    if (session && session.expiresAt >= Date.now()) return { context: session.context, pass: passes.renew(pass) };
  }
  throw httpError(401, OPEN_AGAIN);
}

/** The random id a /studio page gives itself ({ page } in its editor requests), or ''. */
export function studioPageId(body) {
  const page = String(body?.page || '');
  return /^[a-z0-9]{8,64}$/i.test(page) ? page : '';
}

// ---- the portal's addresses ----

/**
 * Is `origin` the mission portal? A configured portal address, or the portal on this same computer (the name the
 * browser used for this server) on a configured portal port. Never the deck address, even if it were configured by
 * mistake: its pages run deck code.
 */
export function isPortalOrigin(req, origin) {
  if (!origin) return false;
  if (isDeckOrigin(origin, DECK_PUBLIC_PORT, PUBLIC_NAMES.deck)) return false;
  if (PORTAL_ORIGINS.has(origin)) return true;
  try {
    const url = new URL(origin);
    return url.origin === origin && url.hostname === new URL(`http://${req.headers.host}`).hostname && PORTAL_PORTS.has(`${url.protocol}${url.port}`);
  } catch {
    return false;
  }
}

// Refused portal addresses are logged once each (at most 50), so a missing setting is easy to find.
const refusedOrigins = new Set();
function warnRefusedOrigin(origin) {
  if (!origin || refusedOrigins.has(origin) || refusedOrigins.size > 50) return;
  refusedOrigins.add(origin);
  console.warn(`[session] refused a sign-in from ${origin}. If that is the mission portal, add it to PRESENTATIONS_PORTAL_ORIGINS.`);
}

// Only the portal may renew the sign-in from its own address (a CORS request with the cookie).
function portalCors(req) {
  const origin = req.headers.origin;
  if (!isPortalOrigin(req, origin)) return { Vary: 'Origin' };
  return { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true', Vary: 'Origin' };
}

// ---- the two sign-in routes ----

function sessionAnswer(role, session) {
  return { ok: true, role, expires_at: new Date(session.expiresAt).toISOString() };
}

/**
 * /api/session. POST: the portal signs this browser in (or renews the sign-in) with its token; it calls from its
 * own address with the cookie (CORS); a page of this address may do the same (the headless Edge checks sign in that
 * way). GET: the sign-in's state.
 * OPTIONS: the browser's CORS question before the portal's POST.
 */
export async function handleSession(req, res) {
  const cors = portalCors(req);
  if (req.method === 'OPTIONS') return answerCorsQuestion(req, res, cors);
  if (req.method === 'GET') {
    const session = getSession(req);
    if (!session) return sendJson(res, 401, { error: 'Not signed in.' }, cors);
    return sendJson(res, 200, sessionAnswer(roleOf(session.context), session), cors);
  }
  if (req.method !== 'POST') return sendJson(res, 405, { error: 'Method not allowed.' }, cors);
  const origin = req.headers.origin;
  if (origin && !isPortalOrigin(req, origin) && !isOwnOrigin(origin, req.headers.host)) {
    warnRefusedOrigin(origin);
    return sendJson(res, 403, { error: 'This sign-in request did not come from the mission portal.' }, cors);
  }
  return signIn(req, res, cors);
}

function answerCorsQuestion(req, res, cors) {
  if (!cors['Access-Control-Allow-Origin']) {
    warnRefusedOrigin(req.headers.origin);
    res.writeHead(403, { Vary: 'Origin' });
    return res.end();
  }
  res.writeHead(204, {
    ...cors,
    'Access-Control-Allow-Methods': 'POST',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Max-Age': '600',
    ...(req.headers['access-control-request-private-network'] === 'true' ? { 'Access-Control-Allow-Private-Network': 'true' } : {}),
  });
  return res.end();
}

async function signIn(req, res, cors) {
  const carried = parseCookies(req).presentation_session;
  let context = null;
  try {
    context = await getUserContextFromBearer(req);
    const access = await checkPresentationAccess(context);
    // Signed out while this renewal was on its way: do not sign back in.
    if (carried && endedSessions.has(carried)) throw httpError(401, 'You signed out of Presentations.');
    forgetManagerCheck(context.user_id);
    const { id, session } = upsertSession(req, context);
    return sendJson(res, 200, sessionAnswer(access.role || roleOf(context), session), { ...cors, 'Set-Cookie': sessionCookie(id, session.expiresAt, req) });
  } catch (error) {
    const status = error.status || (/Not signed in/.test(error.message) ? 401 : 500);
    if (status >= 500) console.error('session error', error);
    // A failed sign-in must not leave an earlier sign-in usable in this browser (for example another missionary's
    // on a shared computer). A passing outage keeps the same person's sign-in.
    const current = carried ? sessions.get(carried) : null;
    const end = status === 401 || status === 403 || (context && current && current.context.user_id !== context.user_id);
    if (end && current) endSession(carried);
    return sendJson(res, status, { error: error.message }, { ...cors, ...(end && carried ? { 'Set-Cookie': EXPIRED_COOKIE + secureOn(req) } : {}) });
  }
}

/**
 * POST /api/logout: ends this browser's sign-in. Only from the portal, this server's own pages, or a program on
 * this computer. Safe to repeat.
 */
export function handleLogout(req, res) {
  const origin = req.headers.origin;
  // Round 10: this server's own pages by their name (on the public name the browser uses https, while the tunnel
  // brings the request here as plain http).
  const localAddress = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
  if (origin ? !isOwnOrigin(origin, req.headers.host) && !isPortalOrigin(req, origin) : !localAddress) {
    return sendJson(res, 403, { error: 'Logout origin is not allowed.' });
  }
  const id = parseCookies(req).presentation_session;
  if (id) {
    endSession(id);
    endedSessions.set(id, Date.now());
  }
  return sendJson(res, 200, { ok: true }, { 'Set-Cookie': EXPIRED_COOKIE + secureOn(req) });
}
