// The rules for database charts (charts whose numbers come from the mission database).
//
// What it is:
// - who may ask for a chart's numbers (chartRequest: access, settings, pinning, and the key its answer is shared
//   under);
// - pinning: which chart queries a deck's slides.md holds (by canonical hash), read again only when the file changes;
// - shared answers: one request per key at a time, kept for a short time, failures not remembered;
// - the chart builder's files (/_manager/chart/…): which file, compressed once (FileCache, also used for Monaco).
// Who uses it: numbers.mjs (the chart routes of both addresses).
// How it fits: plain Node without packages, so slidev/tests/chart-access.test.mjs tests it directly.
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import zlib from 'node:zlib';
import { canonicalJson, normalizeSpec, pinnedKeys, SpecError } from './gfm-addon/lib/chart-spec.mjs';

const gzip = promisify(zlib.gzip);

/** The largest POST /api/charts/data body read (a chart query is well under 2 KB). */
export const CHART_BODY_LIMIT = 64 * 1024;

const DECK_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const NOT_PINNED = 'This chart is not part of the presentation, so its numbers are not shown.';

// A key-number chart written in a slide: <MissionKpiChart …> or <mission-kpi-chart …>, or GFM Studio's <GfmKpi> and
// <GfmKpiGrid> (they draw MissionKpiCharts, so they ask for the same key numbers).
const KPI_CHART = /<\s*(missionkpichart|mission-kpi-chart|gfmkpi|gfm-kpi|gfmkpigrid|gfm-kpi-grid)\b/i;

/**
 * POST /api/charts/data {deck, spec}: whether to ask portal-api, and under
 * which key the answer is shared. In this order, so nothing about the
 * settings is read for someone who may not ask:
 *   1. who is asking: `access(deck)` resolves for a manager (with or without
 *      a deck; without one is the builder's preview) or a leader who may open
 *      the deck, and throws (status 401/403) for everyone else;
 *   2. the settings (normalizeSpec; a mistake is a 400 with its sentence);
 *   3. pinning: a viewer who is not a manager gets only a query written in
 *      that deck's slides.md (`isPinned(deck, spec)`), unless it is a deck
 *      they may change (round 7: a ZL or STL building their own zone's deck,
 *      `editable_slugs`), where the builder's preview asks before the chart
 *      is written.
 * The answer key: managers all see the whole mission, so their answers are
 * shared per mission; everyone else sees only their own stewardship
 * (portal-api charts.py, whatever the spec's audience says), so a leader's
 * answer is kept for that person alone and never shared (round 6).
 * pinnedOnly (round 8 review): the request came from a deck page on the deck
 * address, where deck code runs. Then only a query written in that deck's
 * slides.md is answered, for everyone, managers and the deck's own editors
 * too: deck code gets the numbers of the deck's own charts and nothing else.
 * (The chart builder's preview asks the manager address, which keeps the
 * rules above.)
 * Returns { status: 200, spec, deck, pinned, key } or { status, error }.
 */
export async function chartRequest(context, body, { access, isPinned, pinnedOnly = false }) {
  const given = body && typeof body === 'object' && !Array.isArray(body) ? body : {};
  const deck = typeof given.deck === 'string' && DECK_SLUG.test(given.deck) ? given.deck : '';
  const who = await access(deck);
  let spec;
  try {
    spec = normalizeSpec(given.spec);
  } catch (error) {
    return { status: 400, error: error instanceof SpecError ? error.message : 'The chart settings could not be read.' };
  }
  const pinned = deck ? await isPinned(deck, spec) : false;
  // A ZL or STL building their own zone's deck may try any chart, like a
  // manager; portal-api still shows them only their own zone's numbers.
  const building = !!deck && (who?.editable_slugs || []).includes(deck);
  if (!pinned && (pinnedOnly || (!who?.can_manage && !building))) return { status: 403, error: NOT_PINNED };
  const mission = context.mission_id ?? `user ${context.user_id}`;
  const scope = who?.can_manage ? 'managers' : `user ${context.user_id}`;
  // Round 8: portal-api shows a zone's deck only that zone's numbers, whoever opens it, so an answer is kept
  // per deck too (a manager's answer for a mission deck is never reused in a zone's deck).
  return { status: 200, spec, deck, pinned, key: `${mission}:${scope}:${deck ? `deck ${deck}` : 'no deck'}:${specHash(spec)}` };
}

/**
 * The key a GET /api/mission-kpis answer is shared under (numbers.mjs): per
 * mission and week count for managers (the mission totals), per person for
 * anyone else (the totals of their own stewardship, round 6). `access` is the
 * presentation check's answer ({ can_manage }). `deck` (round 8): the deck the
 * chart is in; a zone's deck shows only that zone's totals, so it is part of
 * the key.
 */
export function kpiCacheKey(context, access, weeks, deck = '') {
  const who = access?.can_manage ? 'managers' : `user ${context.user_id}`;
  return `${context.mission_id ?? `user ${context.user_id}`}:${who}:${weeks}${deck ? `:deck ${deck}` : ''}`;
}

function sha256(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

/** SHA-256 of a normalised spec's canonical JSON (the same as charts.py spec_hash). */
export function specHash(spec) {
  return sha256(canonicalJson(spec));
}

/**
 * The canonical hashes of the chart queries written in each deck's slides.md.
 * A viewer (ZL, STL) gets a chart's numbers only when its query is one of
 * them: the query is one the deck's editors chose (managers, or since round 7
 * the ZLs and STLs of the zone that owns the deck), and portal-api shows every
 * viewer who is not a manager only their own zone's numbers anyway.
 * Removing the chart from the slides ends it at once, even while an older
 * build is still published. Only slides.md itself is read (not files a deck
 * pulls in with `src:`).
 */
export class PinIndex {
  constructor(fileOf) {
    this.fileOf = fileOf;
    this.entries = new Map();
  }

  // What slides.md holds: { hashes, kpis } (kpis: a key-number chart is written in it), read again only when the
  // file changes.
  async read(slug) {
    const file = this.fileOf(slug);
    const stat = await fs.stat(file);
    const cached = this.entries.get(slug);
    if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) return cached;
    const markdown = await fs.readFile(file, 'utf8');
    const entry = { mtimeMs: stat.mtimeMs, size: stat.size, hashes: new Set([...pinnedKeys(markdown)].map(sha256)), kpis: KPI_CHART.test(markdown) };
    this.entries.set(slug, entry);
    return entry;
  }

  async hashes(slug) {
    return (await this.read(slug)).hashes;
  }

  /** False (never an error) when the deck or its file is gone. */
  async isPinned(slug, spec) {
    if (!slug) return false;
    try {
      return (await this.hashes(slug)).has(specHash(spec));
    } catch {
      return false;
    }
  }

  /**
   * Round 8 review: whether the deck's slides.md holds a key-number chart (<MissionKpiChart>), so a page of that
   * deck on the deck address may ask for the key numbers. False (never an error) when the deck is gone.
   */
  async hasKpiChart(slug) {
    if (!slug) return false;
    try {
      return (await this.read(slug)).kpis;
    } catch {
      return false;
    }
  }
}

/**
 * Answers shared for `ttlMs`: everyone asking for the same key while a request
 * runs, or shortly after, gets the same promise. A failure is not remembered,
 * so the next chart asks again.
 */
export class SharedAnswers {
  constructor(ttlMs, max = 500) {
    this.ttlMs = ttlMs;
    this.max = max;
    this.map = new Map();
  }

  get(key, load) {
    const now = Date.now();
    let entry = this.map.get(key);
    if (!entry || entry.until <= now) {
      entry = { until: now + this.ttlMs, promise: Promise.resolve().then(load) };
      this.map.delete(key);
      this.map.set(key, entry);
      entry.promise.catch(() => { if (this.map.get(key) === entry) this.map.delete(key); });
      for (const [k, v] of this.map) if (v.until <= now) this.map.delete(k);
      while (this.map.size > this.max) this.map.delete(this.map.keys().next().value);
    }
    return entry.promise;
  }
}

/**
 * The files of the chart builder in /studio, by the name they are asked for at
 * /_manager/chart/<name>. Only these; they hold code, never data.
 */
export function builderFiles(managerDir) {
  return {
    'chart-builder.mjs': path.join(managerDir, 'chart-builder.mjs'),
    'chart-builder-core.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'chart-builder-core.mjs'),
    'chart-core.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'chart-core.mjs'),
    'chart-engine.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'chart-engine.mjs'),
    // chart-engine.mjs imports these two (calculated fields and chart kinds), so every page that loads the engine needs them.
    'formula.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'formula.mjs'),
    'chart-presets.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'chart-presets.mjs'),
    'chart-schema.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'chart-schema.mjs'),
    'chart-spec.mjs': path.join(managerDir, 'gfm-addon', 'lib', 'chart-spec.mjs'),
    // Round 8 review: what the manager address may draw of a chart's settings (never HTML).
    'safe-chart-option.mjs': path.join(managerDir, 'safe-chart-option.mjs'),
    // GFM Studio: the instructions an AI needs to write a deck (the editor page copies them; ai/ is made by tools/make-ai-spec.mjs).
    'gfm-ai-prompt.txt': path.join(managerDir, 'gfm-addon', 'ai', 'gfm-ai-prompt.txt'),
    'gfm-ai-spec-v1.md': path.join(managerDir, 'gfm-addon', 'ai', 'gfm-ai-spec-v1.md'),
    'echarts.min.js': path.join(managerDir, 'vendor', 'echarts.min.js'),
    'ecStat.min.js': path.join(managerDir, 'vendor', 'ecStat.min.js'),
    // The portal's Whiteboard frames (whiteboard-frames.mjs): a live chart, and the builder placing charts on a board.
    'whiteboard-chart.mjs': path.join(managerDir, 'whiteboard-chart.mjs'),
    'whiteboard-builder.mjs': path.join(managerDir, 'whiteboard-builder.mjs'),
  };
}

/**
 * A file as { version, body, gzip, etag }, read and packed once per version of the file (ECharts is 1.1 MB, about
 * 360 KB packed; Monaco's main file 3.6 MB, about 0.9 MB). Packing runs beside the server (Node's worker threads),
 * so nobody else waits for it; people asking for the same file at once share one packing. At most `max` files are
 * kept, the least recently used go first (Infinity: no limit, for a fixed folder such as Monaco's, so that asking for
 * every file in turn can never force the same packing twice).
 */
export class FileCache {
  constructor(max = 200) {
    this.map = new Map();
    this.max = max;
  }

  async get(file) {
    const stat = await fs.stat(file);
    const version = `${stat.size}-${Math.round(stat.mtimeMs)}`;
    const hit = this.map.get(file);
    this.map.delete(file);
    if (hit && hit.version === version) {
      this.map.set(file, hit);
      return hit.entry;
    }
    const entry = fs.readFile(file).then(async body => ({ version, body, gzip: await gzip(body, { level: 9 }), etag: `"${sha256(`${file}:${version}`).slice(0, 20)}"` }));
    const kept = { version, entry };
    this.map.set(file, kept);
    while (this.map.size > this.max) this.map.delete(this.map.keys().next().value);
    // A file that could not be read is asked for again next time.
    entry.catch(() => { if (this.map.get(file) === kept) this.map.delete(file); });
    return entry;
  }
}
