// Mission numbers for charts.
//
// What it is: charts in slides show live mission numbers. The manager asks portal-api for them (portal-api reads the
// database) and hands them to the chart:
//   - key numbers (<MissionKpiChart>): the six key indicators, week by week (GET /api/mission-kpis);
//   - database charts (<MissionChart :query>): any numbers the chart's query names (POST /api/charts/data);
//   - the chart builder's list of numbers, zones, districts and areas (GET /api/charts/catalog).
// Answers are shared for a short time (one minute; the list five minutes), so a deck with many charts, opened by
// many people, asks portal-api only a few times. A failed answer is never remembered.
// People numbers are counts only, never names; portal-api hides small counts per area and shows every leader only
// their own stewardship.
// Who uses it: manager-routes.mjs and deck-routes.mjs.
// How it fits: who may ask for which chart ("pinning": only charts written in the deck) is decided in
// chart-access.mjs, which is tested with plain Node.
import { assertDeckCreator, assertPresentationManager, askPortalApi, presentationAccess } from './access.mjs';
import { builderFiles, chartRequest, FileCache, kpiCacheKey, PinIndex, SharedAnswers } from './chart-access.mjs';
import { deckFile } from './deck-files.mjs';
import { MANAGER_DIR } from './settings.mjs';
import { sendKept, sendNotFound } from './web.mjs';
import { catalogCacheKey } from './zone-decks.mjs';

/** The sentence a chart shows when portal-api could not give its numbers. */
export const NOT_LOADED = 'The numbers could not load. Try again in a minute.';

const kpiAnswers = new SharedAnswers(60000);
const chartAnswers = new SharedAnswers(60000);
const catalogAnswers = new SharedAnswers(5 * 60000, 50);

/** Which chart queries each deck's slides.md holds (read again only when the file changes). */
export const pinIndex = new PinIndex(slug => deckFile(slug));

/**
 * The `weeks` of a key-number request: 12 when not given, otherwise a whole number from 1 to 104; null when it is
 * not one (the route answers 400).
 */
export function weeksFrom(url) {
  const raw = url.searchParams.get('weeks');
  const weeks = raw === null || raw === '' ? 12 : Number(raw);
  return Number.isInteger(weeks) && weeks >= 1 && weeks <= 104 ? weeks : null;
}

export const BAD_WEEKS = 'Choose between 1 and 104 weeks.';

/**
 * The key numbers, oldest week first: [{ week: 'YYYY-MM-DD', friends_found: { actual, goal }, ... }] for the six
 * key indicators, where goal is the goal set the week before (as in Call-ins). `access` decides whose totals
 * (kpiCacheKey); `deck` (round 8): a zone's deck shows only that zone's numbers, whoever opens it.
 */
export function missionKpis(context, access, weeks, deck = '') {
  return kpiAnswers.get(kpiCacheKey(context, access, weeks, deck), async () => {
    const data = await askPortalApi(context, 'kpis', deck ? { weeks, deck } : { weeks });
    if (!Array.isArray(data)) throw new Error('portal-api returned no list of weeks.');
    return data;
  });
}

// Who may ask for a chart of `deck`: a manager (also without a deck, for the chart builder's preview), or a leader
// who may open that deck.
function chartViewerAccess(context, deck) {
  return deck ? presentationAccess(context, deck) : assertPresentationManager(context);
}

/**
 * A chart's numbers: [status, answer]. chart-access.mjs decides who may ask (first, so a missionary's request is
 * refused before its settings are read) and under which key the answer is shared. pinnedOnly: asked by a deck page
 * on the deck address (round 8 review), which gets only the numbers of the charts written in that deck.
 */
export async function chartData(context, body, { pinnedOnly = false, isPinned = (deck, spec) => pinIndex.isPinned(deck, spec) } = {}) {
  const request = await chartRequest(context, body, {
    access: deck => chartViewerAccess(context, deck),
    isPinned,
    pinnedOnly,
  });
  if (request.status !== 200) return [request.status, { error: request.error }];
  const { spec, deck, pinned, key } = request;
  try {
    const answer = await chartAnswers.get(key, () => askPortalApi(context, 'chart-data', { spec, deck, pinned }));
    return [200, { ...answer, meta: { ...(answer?.meta || {}), pinned } }];
  } catch (error) {
    if (error.status === 400 || error.status === 403) return [error.status, { error: error.message }];
    console.error(`[charts] ${error.status || 'error'}: ${error.message}`);
    return [503, { error: NOT_LOADED }];
  }
}

/**
 * The chart builder's list of numbers and places: [status, answer]. Managers get the whole mission; a ZL or STL only
 * their own zone (portal-api), kept for them alone.
 */
export async function chartCatalog(context) {
  const access = await assertDeckCreator(context);
  try {
    return [200, await catalogAnswers.get(catalogCacheKey(context, access), () => askPortalApi(context, 'chart-catalog', {}))];
  } catch (error) {
    console.error(`[charts] catalogue ${error.status || 'error'}: ${error.message}`);
    return [503, { error: 'The list of numbers could not load. Try again in a minute.' }];
  }
}

// ---- the chart builder's code ----

const BUILDER_FILES = builderFiles(MANAGER_DIR);
const builderFileCache = new FileCache();

/**
 * GET /_manager/chart/<file>: the chart builder, the chart engine and the chart libraries. Code only, no data, so no
 * sign-in is needed (like Monaco). Compressed once, and checked again by the browser with an ETag.
 */
export async function serveBuilderFile(req, res, name) {
  const file = Object.hasOwn(BUILDER_FILES, name) ? BUILDER_FILES[name] : null;
  const entry = file ? await builderFileCache.get(file).catch(() => null) : null;
  if (!entry) return sendNotFound(res);
  sendKept(req, res, entry, 'text/javascript; charset=utf-8');
}
