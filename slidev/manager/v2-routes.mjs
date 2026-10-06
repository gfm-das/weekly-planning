// GFM Presentations V2: the routes (a parallel system; Slidev's routes are not touched).
//
// What it is:
//   GET  /studio-v2/<deck>                  the V2 editor (a normal prebuilt page; no Slidev, no build)
//   GET  /p-v2/<deck>                       the V2 presentation (Reveal.js)
//   GET  /_v2/<file>                        the built application's files (code only, no data)
//   GET  /api/presentations-v2/<deck>       deck.json (who may open the deck)
//   PUT  /api/presentations-v2/<deck>       saves deck.json (who may change the deck; checked by v2-deck.mjs)
//   POST /api/presentations-v2/query        a chart's numbers: the same rules as /api/charts/data (portal-api decides
//                                           stewardship and hides small counts), pinned to the queries of the saved deck
//   PUT  /api/presentations-v2/<deck>/assets/<name>      a deck's picture (a manager or the deck's editor)
//   GET  /p-v2-assets/<deck>/<name>                      a deck's picture (who may open the deck; not under /api/ so <img> works)
// Who uses it: manager-routes.mjs.
// How it fits: access.mjs (the same who-may-do-what as Slidev), numbers.mjs (the same data path), v2-deck.mjs (what a
// deck may hold). Decks are stored in V2_DECKS_DIR/<deck>/deck.json (written atomically, the one before kept as
// deck.json.bak).
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { assertDeckEditor, assertPresentationManager, askPortalApi, checkPresentationAccess, presentationAccess } from './access.mjs';
import { CHART_BODY_LIMIT } from './chart-access.mjs';
import { chartData } from './numbers.mjs';
import { V2_APP_DIR, V2_DECKS_DIR } from './settings.mjs';
import { ASSET_NAME, DeckError, deckPinKeys, V2_SLUG, validateDeck } from './v2-deck.mjs';
import { canonicalJson, normalizeSpec } from './gfm-addon/lib/chart-spec.mjs';
import { httpError, mimeType, readBody, sendJson } from './web.mjs';

const DECK_BODY_LIMIT = 1024 * 1024;
const ASSET_LIMIT = 3 * 1024 * 1024;

const slugOf = value => {
  if (typeof value !== 'string' || !V2_SLUG.test(value) || value.length > 80) throw httpError(404, 'Presentation not found.');
  return value;
};
// V2 decks have their own sharing key, "v2-<deck>", so a V2 deck never takes over the sharing of a Slidev deck that has the
// same name (deck-files.mjs: Slidev decks can no longer be named v2-...).
export const accessKey = slug => `v2-${slugOf(slug)}`;
const deckFolder = slug => path.join(V2_DECKS_DIR, slugOf(slug));
const deckPath = slug => path.join(deckFolder(slug), 'deck.json');

async function readDeckFile(slug) {
  try {
    return JSON.parse(await fs.readFile(deckPath(slug), 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

/** Atomic write: a temporary file, then a rename; the deck it replaces is kept as deck.json.bak. */
async function writeDeckFile(slug, deck) {
  const dir = deckFolder(slug);
  await fs.mkdir(path.join(dir, 'assets'), { recursive: true });
  const file = deckPath(slug);
  const tmp = `${file}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(deck));
  await fs.copyFile(file, `${file}.bak`).catch(() => {});
  await fs.rename(tmp, file);
}

// The queries a deck holds, read again only when deck.json changes (the V2 counterpart of Slidev's PinIndex).
const pinCache = new Map();
async function pinnedKeysOf(slug) {
  const file = deckPath(slug);
  const stat = await fs.stat(file).catch(() => null);
  if (!stat) return new Set();
  const hit = pinCache.get(slug);
  if (hit && hit.mtimeMs === stat.mtimeMs && hit.size === stat.size) return hit.keys;
  const keys = deckPinKeys(await readDeckFile(slug).catch(() => null));
  pinCache.set(slug, { mtimeMs: stat.mtimeMs, size: stat.size, keys });
  return keys;
}

// ---- the application ----

/** The V2 page (the same prebuilt index.html for every deck and both modes). */
export async function v2PageHtml() {
  const html = await fs.readFile(path.join(V2_APP_DIR, 'index.html'), 'utf8');
  // The portal bridge first (like every page of the manager): it renews the sign-in and sends the X-GFM-Request header.
  return html.replace('<head>', '<head><script src="/_manager/portal-bridge.js"></script>');
}

/** The built file `name` of the V2 application, or null. Kept inside V2_APP_DIR. */
export async function v2AppFile(name) {
  let relative;
  try { relative = decodeURIComponent(name); } catch { return null; }
  const file = path.resolve(V2_APP_DIR, relative);
  if (!relative || relative.includes('\0') || !file.startsWith(V2_APP_DIR + path.sep)) return null;
  const stat = await fs.stat(file).catch(() => null);
  return stat?.isFile() ? { file, size: stat.size, type: mimeType(file) } : null;
}

// ---- the deck ----

/** GET /api/presentations-v2/<deck> */
export async function readV2Deck({ res, context, slug }) {
  slugOf(slug);
  const access = await presentationAccess(context, accessKey(slug));
  const deck = await readDeckFile(slug);
  if (!deck) throw httpError(404, 'Presentation not found.');
  return sendJson(res, 200, { deck, can_edit: await canEdit(context, slug, access), can_manage: !!access?.can_manage }, { 'Cache-Control': 'no-store' });
}

async function canEdit(context, slug, access) {
  if (access?.can_manage) return true;
  try { await assertDeckEditor(context, accessKey(slug)); return true; } catch { return false; }
}

/** PUT /api/presentations-v2/<deck> { deck }: a new deck only by a manager; an existing one by who may change it. */
export async function saveV2Deck({ req, res, context, slug }) {
  slugOf(slug);
  const access = await assertDeckEditor(context, accessKey(slug));
  const exists = !!(await fs.stat(deckPath(slug)).catch(() => null));
  if (!exists && !access.can_manage) throw httpError(403, 'Only managers make a new V2 presentation.');
  const body = await readBody(req, DECK_BODY_LIMIT);
  let deck;
  try {
    deck = validateDeck(body?.deck);
  } catch (error) {
    if (error instanceof DeckError) throw httpError(400, error.message);
    throw error;
  }
  await writeDeckFile(slug, deck);
  return sendJson(res, 200, { ok: true, saved_at: new Date().toISOString() });
}

/** POST /api/presentations-v2/query { deck, spec }: numbers for a chart of a V2 deck (the Slidev rules, V2 pinning). */
export async function queryV2({ req, res, context }) {
  const body = await readBody(req, CHART_BODY_LIMIT);
  const deck = typeof body?.deck === 'string' && V2_SLUG.test(body.deck) ? body.deck : '';
  // No deck: the preview of a manager (chartData asks assertPresentationManager). With a deck: pinned to the saved deck.
  const [status, value] = await chartData(context, { deck: deck ? accessKey(deck) : '', spec: body?.spec }, {
    isPinned: async (key, spec) => (await pinnedKeysOf(key.slice(3))).has(canonicalJson(normalizeSpec(spec))),
  });
  return sendJson(res, status, value);
}

// ---- the library and who may view ----

/**
 * GET /api/presentations-v2: the V2 decks this person may open (managers: all), each { slug, name, can_edit, updated_at }.
 * portal-api decides per deck (check with the keys v2-<deck>), as it does for Slidev decks.
 */
export async function listV2Decks({ res, context }) {
  const access = await checkPresentationAccess(context, []);
  const entries = await fs.readdir(V2_DECKS_DIR, { withFileTypes: true }).catch(() => []);
  const slugs = entries.filter(e => e.isDirectory() && V2_SLUG.test(e.name) && e.name.length <= 80).map(e => e.name);
  const checked = access.can_manage ? access : await checkPresentationAccess(context, slugs.map(accessKey));
  const decks = [];
  for (const slug of slugs) {
    const key = accessKey(slug);
    if (!checked.can_manage && !(checked.allowed_slugs || []).includes(key)) continue;
    const stat = await fs.stat(deckPath(slug)).catch(() => null);
    if (!stat) continue;
    const deck = await readDeckFile(slug).catch(() => null);
    decks.push({
      slug, name: String(deck?.name || slug), slides: deck?.slides?.length ?? 0, updated_at: stat.mtime.toISOString(),
      can_edit: !!checked.can_manage || (checked.editable_slugs || []).includes(key),
    });
  }
  decks.sort((a, b) => a.name.localeCompare(b.name));
  return sendJson(res, 200, { can_manage: !!checked.can_manage, decks });
}

/** GET /api/presentations-v2/<deck>/viewers: who may view the deck, and the choices (managers). */
export async function readV2Viewers({ res, context, slug }) {
  await assertPresentationManager(context);
  slugOf(slug);
  if (!await fs.stat(deckPath(slug)).catch(() => null)) throw httpError(404, 'Presentation not found.');
  return sendJson(res, 200, await askPortalApi(context, 'access', { operation: 'get', deck_slug: accessKey(slug) }));
}

const RULE_KEYS = ['roles', 'zone_ids', 'district_ids', 'user_ids', 'everyone'];

/**
 * PUT /api/presentations-v2/<deck>/viewers { rule }: who may view the deck (managers). Only roles, zones, districts, people
 * and "everyone" are taken; portal-api checks them. Managers always see every deck. Nobody viewing = managers only.
 */
export async function saveV2Viewers({ req, res, context, slug }) {
  await assertPresentationManager(context);
  slugOf(slug);
  if (!await fs.stat(deckPath(slug)).catch(() => null)) throw httpError(404, 'Presentation not found.');
  const body = await readBody(req, 64 * 1024);
  const rule = Object.fromEntries(RULE_KEYS.filter(k => body?.rule && k in body.rule).map(k => [k, body.rule[k]]));
  return sendJson(res, 200, await askPortalApi(context, 'access', { operation: 'save', deck_slug: accessKey(slug), rule }));
}

// ---- pictures ----

const MAGIC = [
  ['png', b => b.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))],
  ['jpg', b => b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff],
  ['jpeg', b => b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff],
  ['gif', b => b.subarray(0, 4).toString('latin1') === 'GIF8'],
  ['webp', b => b.subarray(0, 4).toString('latin1') === 'RIFF' && b.subarray(8, 12).toString('latin1') === 'WEBP'],
];

/** GET /api/presentations-v2/<deck>/assets/<name> */
export async function readV2Asset({ req, res, context, slug, name }) {
  slugOf(slug);
  await presentationAccess(context, accessKey(slug));
  if (!ASSET_NAME.test(name)) throw httpError(404, 'Not found.');
  const data = await fs.readFile(path.join(deckFolder(slug), 'assets', name)).catch(() => null);
  if (!data) throw httpError(404, 'Not found.');
  res.writeHead(200, { 'Content-Type': mimeType(name), 'Content-Length': data.length, 'Cache-Control': 'private, max-age=300', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'" });
  res.end(data);
  return true;
}

/** PUT /api/presentations-v2/<deck>/assets/<name>: a picture (png, jpg, gif, webp up to 3 MB; checked by its first bytes). */
export async function saveV2Asset({ req, res, context, slug, name }) {
  slugOf(slug);
  await assertDeckEditor(context, accessKey(slug));
  if (!ASSET_NAME.test(name)) throw httpError(400, 'Name the picture with letters, digits, - and _, ending in .png, .jpg, .gif or .webp.');
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > ASSET_LIMIT) throw httpError(413, 'The picture is larger than 3 MB.');
    chunks.push(chunk);
  }
  const data = Buffer.concat(chunks);
  const extension = name.split('.').pop();
  if (!MAGIC.find(([ext, ok]) => ext === extension && ok(data))) throw httpError(400, 'The file is not a picture of that kind.');
  const dir = path.join(deckFolder(slug), 'assets');
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, name), data);
  return sendJson(res, 200, { ok: true, name });
}
