// The manager's database-chart helpers (manager/chart-access.mjs): who may ask
// for a chart (chartRequest), pinning a query to a deck's slides.md, shared
// answers and the builder's files.
// Plain Node, no packages.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { builderFiles, CHART_BODY_LIMIT, chartRequest, FileCache, kpiCacheKey, NOT_PINNED, PinIndex, SharedAnswers, specHash } from '../manager/chart-access.mjs';
import { normalizeSpec } from '../manager/gfm-addon/lib/chart-spec.mjs';

const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'gfm-charts-'));
const fileOf = slug => path.join(tmp, slug, 'slides.md');
async function writeDeck(slug, markdown, bumpMs = 0) {
  await fs.mkdir(path.join(tmp, slug), { recursive: true });
  await fs.writeFile(fileOf(slug), markdown);
  if (bumpMs) {
    const t = new Date(Date.now() + bumpMs);
    await fs.utimes(fileOf(slug), t, t);
  }
}
const pinnedSpec = normalizeSpec({ measures: ['friends_found.actual', 'friends_found.previous_goal'], level: 'zone', weeks: 8 });
const tag = `<MissionChart type="bar" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"zone","weeks":8}' />`;

test('pinning: only a query written in the deck is pinned, in any spelling', async () => {
  await writeDeck('council', `# Council\n\n${tag}\n`);
  const index = new PinIndex(fileOf);
  assert.equal(await index.isPinned('council', pinnedSpec), true);
  // The same chart asked for with the keys in another order and the defaults spelled out.
  const same = normalizeSpec({ weeks: { last: 8 }, level: 'zone', measures: ['friends_found.actual', 'friends_found.previous_goal'], audience: 'deck', by: 'week' });
  assert.equal(await index.isPinned('council', same), true);
  // Anything else is not: other weeks, other audience, other measures.
  assert.equal(await index.isPinned('council', normalizeSpec({ ...pinnedSpec, weeks: { last: 9 } })), false);
  assert.equal(await index.isPinned('council', normalizeSpec({ ...pinnedSpec, audience: 'stewardship' })), false);
  assert.equal(await index.isPinned('council', normalizeSpec({ measures: ['baptismal_dates.actual'] })), false);
  // A deck that does not exist (or no deck) pins nothing and never throws.
  assert.equal(await index.isPinned('missing', pinnedSpec), false);
  assert.equal(await index.isPinned('', pinnedSpec), false);
});

test('pinning: the index follows the file (removing a chart ends it at once)', async () => {
  await writeDeck('changing', `${tag}\n`);
  const index = new PinIndex(fileOf);
  assert.equal(await index.isPinned('changing', pinnedSpec), true);
  const cached = await index.hashes('changing');
  assert.equal(await index.hashes('changing'), cached, 'read once while the file is unchanged');
  await writeDeck('changing', '# No chart any more\n', 5000);
  assert.equal(await index.isPinned('changing', pinnedSpec), false);
  await writeDeck('changing', `Back again\n${tag}\n`, 10000);
  assert.equal(await index.isPinned('changing', pinnedSpec), true);
  assert.equal((await index.hashes('changing')).has(specHash(pinnedSpec)), true);
});

test('shared answers: one request in flight, failures not remembered, expiry', async () => {
  const answers = new SharedAnswers(40);
  let calls = 0;
  const load = () => { calls++; return new Promise(resolve => setTimeout(() => resolve({ n: calls }), 10)); };
  const [a, b] = await Promise.all([answers.get('k', load), answers.get('k', load)]);
  assert.equal(calls, 1);
  assert.equal(a, b);
  await new Promise(resolve => setTimeout(resolve, 60));
  await answers.get('k', load);
  assert.equal(calls, 2, 'asked again after the time ran out');
  let failures = 0;
  const failing = () => { failures++; return Promise.reject(new Error('down')); };
  await assert.rejects(answers.get('f', failing));
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(answers.get('f', failing));
  assert.equal(failures, 2, 'a failure is not remembered');
  const small = new SharedAnswers(10000, 2);
  for (const k of ['a', 'b', 'c']) await small.get(k, () => k);
  assert.equal(small.map.size, 2);
});

test('builder files: only the known names, compressed once per version', async () => {
  const dir = path.join(tmp, 'manager');
  await fs.mkdir(path.join(dir, 'gfm-addon', 'lib'), { recursive: true });
  const files = builderFiles(dir);
  assert.deepEqual(Object.keys(files).sort(), ['chart-builder-core.mjs', 'chart-builder.mjs', 'chart-core.mjs', 'chart-engine.mjs', 'chart-presets.mjs', 'chart-schema.mjs', 'chart-spec.mjs', 'ecStat.min.js', 'echarts.min.js', 'formula.mjs', 'gfm-ai-prompt.txt', 'gfm-ai-spec-v1.md', 'safe-chart-option.mjs', 'whiteboard-builder.mjs', 'whiteboard-chart.mjs']);
  assert.equal(Object.hasOwn(files, '../server.mjs'), false);
  const file = files['chart-core.mjs'];
  await fs.writeFile(file, 'export const x = 1;\n'.repeat(200));
  const cache = new FileCache();
  const first = await cache.get(file);
  assert.equal(zlib.gunzipSync(first.gzip).toString(), first.body.toString());
  assert.ok(first.gzip.length < first.body.length);
  assert.equal(await cache.get(file), first);
  await fs.writeFile(file, 'export const x = 2;\n');
  const t = new Date(Date.now() + 5000);
  await fs.utimes(file, t, t);
  const second = await cache.get(file);
  assert.notEqual(second.etag, first.etag);
});

test('FileCache: a limit keeps the most recently used files; no limit (Monaco) packs each file only once', async () => {
  const dir = path.join(tmp, 'many-files');
  await fs.mkdir(dir, { recursive: true });
  // More files than the old Monaco limit of 100, like Monaco's 138 text files.
  const files = [];
  for (let i = 0; i < 150; i++) {
    files.push(path.join(dir, `f${i}.js`));
    await fs.writeFile(files[i], `export const n = ${i};\n`);
  }
  const small = new FileCache(2);
  const a = await small.get(files[0]);
  await small.get(files[1]);
  assert.equal(await small.get(files[0]), a, 'used again, so kept');
  await small.get(files[2]);
  assert.equal(await small.get(files[0]), a, 'the most recently used stays');
  assert.equal(small.map.has(files[1]), false, 'the least recently used went first');

  const unlimited = new FileCache(Infinity);
  const firstRound = [];
  for (const file of files) firstRound.push(await unlimited.get(file));
  for (let i = 0; i < files.length; i++) assert.equal(await unlimited.get(files[i]), firstRound[i], `f${i}.js packed again`);
  assert.equal(unlimited.map.size, 150);
});

// ---- chartRequest: who may ask for which chart (POST /api/charts/data) ----

function refusal(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

// Stand-ins for the manager's checks: `decks` are the decks each person may
// open; managers may open all and ask without a deck.
const PEOPLE = {
  ap: { user_id: 'u-ap', mission_id: 1, can_manage: true },
  dl: { user_id: 'u-dl', mission_id: 1, can_manage: false, decks: ['council'] },
  dl2: { user_id: 'u-dl2', mission_id: 1, can_manage: false, decks: ['council'] },
  zl_other: { user_id: 'u-zl', mission_id: 1, can_manage: false, decks: [] },
  missionary: { user_id: 'u-m', mission_id: 1, missionary: true },
};

function checks(person, log = []) {
  return {
    access: async (deck) => {
      log.push(`access ${deck || '(none)'}`);
      if (person.missionary) throw refusal(403, 'Presentation access is available to assigned leaders.');
      if (!deck && !person.can_manage) throw refusal(403, 'You do not have permission to manage presentations.');
      if (deck && !person.can_manage && !person.decks.includes(deck)) throw refusal(403, 'This presentation is not assigned to you.');
      return { can_manage: !!person.can_manage };
    },
    isPinned: async (deck, spec) => {
      log.push(`pinned ${deck}`);
      return new PinIndex(fileOf).isPinned(deck, spec);
    },
  };
}

const ask = (who, body, log) => chartRequest(PEOPLE[who], body, checks(PEOPLE[who], log));
const pinnedQuery = { measures: ['friends_found.actual', 'friends_found.previous_goal'], level: 'zone', weeks: 8 };

test('chart requests: a missionary is refused before the settings are read', async () => {
  await writeDeck('council', `# Council\n\n${tag}\n`);
  let read = false;
  const spec = { get measures() { read = true; return ['friends_found.actual']; } };
  const log = [];
  await assert.rejects(ask('missionary', { deck: 'council', spec }, log), error => error.status === 403);
  await assert.rejects(ask('missionary', { spec }, log), error => error.status === 403);
  assert.equal(read, false, 'the settings were never looked at');
  assert.deepEqual(log, ['access council', 'access (none)']);
  // A huge list from someone who may not ask costs nothing either.
  const started = performance.now();
  await assert.rejects(ask('missionary', { deck: 'council', spec: { measures: Array.from({ length: 200000 }, (_, i) => `m${i}.x`) } }), error => error.status === 403);
  assert.ok(performance.now() - started < 500);
});

test('chart requests: a leader needs the deck, then a pinned chart', async () => {
  await writeDeck('council', `# Council\n\n${tag}\n`);
  // Without the deck (or with a deck not shared with them): refused, settings unread.
  await assert.rejects(ask('dl', { spec: pinnedQuery }), error => error.status === 403);
  await assert.rejects(ask('zl_other', { deck: 'council', spec: pinnedQuery }), error => error.status === 403);
  // A deck name that is not a slug counts as no deck.
  await assert.rejects(ask('dl', { deck: '../council', spec: pinnedQuery }), error => error.status === 403);
  // Shared, but a chart that is not written in the deck: refused.
  const unpinned = await ask('dl', { deck: 'council', spec: { ...pinnedQuery, weeks: 9 } });
  assert.deepEqual(unpinned, { status: 403, error: NOT_PINNED });
  // Shared and pinned: asked for, in any spelling of the same query.
  const ok = await ask('dl', { deck: 'council', spec: JSON.stringify({ weeks: { last: 8 }, level: 'zone', measures: pinnedQuery.measures }) });
  assert.equal(ok.status, 200);
  assert.equal(ok.pinned, true);
  assert.equal(ok.deck, 'council');
  assert.deepEqual(ok.spec, normalizeSpec(pinnedQuery));
  // A mistake in the settings from someone who may ask is a 400 with its sentence.
  assert.deepEqual(await ask('dl', { deck: 'council', spec: { measures: [] } }), { status: 400, error: 'Choose at least one number to show.' });
  assert.equal((await ask('dl', { deck: 'council', spec: { measures: Array(40).fill('friends_found.actual') } })).status, 400);
});

test('chart requests: managers ask for anything, with or without a deck', async () => {
  await writeDeck('council', `# Council\n\n${tag}\n`);
  const preview = await ask('ap', { spec: { measures: ['baptismal_dates.actual'] } });
  assert.equal(preview.status, 200);
  assert.equal(preview.pinned, false, 'the builder preview is never pinned');
  const inDeck = await ask('ap', { deck: 'council', spec: { measures: ['baptismal_dates.actual'] } });
  assert.equal(inDeck.status, 200);
  assert.equal(inDeck.pinned, false);
  assert.equal((await ask('ap', { deck: 'council', spec: pinnedQuery })).pinned, true);
  assert.equal((await ask('ap', { spec: { measures: ['x'] } })).status, 400);
  assert.equal((await ask('ap', null)).status, 400, 'no body: no settings');
});

// Round 8 review: on the deck address (a deck page asks, deck code runs there) only the charts written in that deck
// are answered, for everyone: managers, and the deck's own ZLs and STLs who may try any chart in the builder.
test('chart requests from a deck page (pinnedOnly): only charts written in the deck, managers and builders too', async () => {
  await writeDeck('council', `# Council\n\n${tag}\n`);
  const deckPage = (who, body, extra = {}) => chartRequest(PEOPLE[who], body, { ...checks(PEOPLE[who]), pinnedOnly: true, ...extra });
  const other = { measures: ['baptismal_dates.actual'] };
  assert.equal((await deckPage('ap', { deck: 'council', spec: pinnedQuery })).status, 200, 'its own chart: yes');
  const refused = await deckPage('ap', { deck: 'council', spec: other });
  assert.deepEqual([refused.status, refused.error], [403, NOT_PINNED], 'any other query: no, for a manager too');
  assert.equal((await deckPage('ap', { spec: other })).status, 403, 'no deck: nothing is pinned');
  // A ZL building their own zone's deck may try any chart in the builder (the manager address), not from a deck page.
  const building = { access: async () => ({ can_manage: false, editable_slugs: ['council'] }) };
  assert.equal((await chartRequest(PEOPLE.dl2, { deck: 'council', spec: other }, { ...checks(PEOPLE.dl2), ...building })).status, 200, 'the builder (manager address)');
  assert.equal((await deckPage('dl2', { deck: 'council', spec: other }, building)).status, 403, 'a deck page');
  assert.equal((await deckPage('dl2', { deck: 'council', spec: pinnedQuery }, building)).status, 200);
});

test('key-number charts: the index knows whether a deck holds one (the deck address asks before answering)', async () => {
  const index = new PinIndex(fileOf);
  await writeDeck('kpi-deck', '# Numbers\n\n<MissionKpiChart kpi="friends_found" :weeks="12" />\n');
  await writeDeck('kpi-kebab', '# Numbers\n\n<mission-kpi-chart kpi="baptisms" />\n');
  await writeDeck('no-kpi', `# Council\n\n${tag}\n`);
  await writeDeck('kpi-gfm', '# Numbers\n\n<GfmKpiGrid metrics="friends_found,baptismal_dates" />\n');
  await writeDeck('kpi-gfm-one', '# Numbers\n\n<GfmKpi metric="Baptismal dates" />\n');
  await writeDeck('kpi-lookalike', '# Numbers\n\n<GfmKpiBogus />\n');
  assert.equal(await index.hasKpiChart('kpi-gfm'), true, "GFM Studio's key-number grid counts");
  assert.equal(await index.hasKpiChart('kpi-gfm-one'), true, 'and its single key number');
  assert.equal(await index.hasKpiChart('kpi-lookalike'), false, 'a tag that only starts like it does not');
  assert.equal(await index.hasKpiChart('kpi-deck'), true);
  assert.equal(await index.hasKpiChart('kpi-kebab'), true);
  assert.equal(await index.hasKpiChart('no-kpi'), false);
  assert.equal(await index.hasKpiChart('gone'), false, 'a deck that is gone: no');
  assert.equal(await index.hasKpiChart(''), false);
  await writeDeck('kpi-deck', '# Numbers removed\n', 5000);
  assert.equal(await index.hasKpiChart('kpi-deck'), false, 'removing the chart ends it at once');
});

test("chart requests: managers share answers per mission; a leader's answer is theirs alone, whatever the audience", async () => {
  // Round 6: portal-api filters every chart to a leader's own stewardship ("deck" no longer means "everyone sees
  // the same numbers"), so no leader may ever get another person's (or a manager's) answer.
  const stewardship = { measures: ['friends_found.actual'], level: 'area', by: 'unit', weeks: 4 };
  const stewardshipTag = `<MissionChart :query='${JSON.stringify(stewardship)}' />`;
  await writeDeck('council', `# Council

${tag}

${stewardshipTag}
`);
  for (const spec of [pinnedQuery, stewardship]) {
    const answers = await Promise.all(['ap', 'dl', 'dl2'].map(who => ask(who, { deck: 'council', spec })));
    assert.deepEqual(answers.map(r => r.status), [200, 200, 200]);
    assert.deepEqual(answers.map(r => r.key.split(':').slice(0, 2).join(':')), ['1:managers', '1:user u-dl', '1:user u-dl2']);
    assert.equal(new Set(answers.map(r => r.key)).size, 3, "never one person's numbers for another");
  }
  assert.equal(normalizeSpec(pinnedQuery).audience, 'deck', 'the old audience is still accepted (pinned hashes stay)');
  // Every manager of the mission shares one answer (they all see the whole mission).
  const ap2 = await chartRequest({ ...PEOPLE.ap, user_id: 'u-ap2' }, { deck: 'council', spec: pinnedQuery }, checks(PEOPLE.ap));
  const ap = await ask('ap', { deck: 'council', spec: pinnedQuery });
  assert.equal(ap2.key, ap.key);
  assert.equal(ap.key, `1:managers:deck council:${specHash(normalizeSpec(pinnedQuery))}`);
  // Round 8: a zone's deck shows only that zone's numbers (portal-api), so an answer is kept per deck: a manager's
  // answer for one deck (or for the builder, without a deck) is never reused in another deck.
  const noDeck = await chartRequest(PEOPLE.ap, { spec: pinnedQuery }, checks(PEOPLE.ap));
  assert.equal(noDeck.key, `1:managers:no deck:${specHash(normalizeSpec(pinnedQuery))}`);
  // Another mission never shares an answer with this one.
  const other = await chartRequest({ ...PEOPLE.ap, mission_id: 2 }, { spec: pinnedQuery }, checks(PEOPLE.ap));
  assert.notEqual(other.key, ap.key);
});

test("mission KPI answers: shared by the mission's managers, a leader's kept for them alone", () => {
  const ap = { user_id: 'u-ap', mission_id: 1 };
  assert.equal(kpiCacheKey(ap, { can_manage: true }, 104), '1:managers:104');
  assert.equal(kpiCacheKey({ user_id: 'u-ap2', mission_id: 1 }, { can_manage: true }, 104), '1:managers:104');
  assert.equal(kpiCacheKey({ user_id: 'u-zl', mission_id: 1 }, { can_manage: false, role: 'ZL' }, 104), '1:user u-zl:104');
  assert.equal(kpiCacheKey({ user_id: 'u-dl', mission_id: 1 }, { can_manage: false, role: 'DL' }, 104), '1:user u-dl:104');
  assert.notEqual(kpiCacheKey({ user_id: 'u-zl', mission_id: 1 }, undefined, 12), kpiCacheKey(ap, { can_manage: true }, 12));
  // Round 8: per deck too (a zone's deck shows only that zone's totals).
  assert.equal(kpiCacheKey(ap, { can_manage: true }, 104, 'zone-council'), '1:managers:104:deck zone-council');
  assert.notEqual(kpiCacheKey(ap, { can_manage: true }, 104, 'zone-council'), kpiCacheKey(ap, { can_manage: true }, 104, 'mission-talk'));
});

test('chart requests: the body limit is small', () => {
  assert.equal(CHART_BODY_LIMIT, 64 * 1024);
  const builderSized = JSON.stringify({ deck: 'council', spec: normalizeSpec({ measures: Array(8).fill(0).map((_, i) => `friends_found.m${i}`), level: 'area', filter: { areas: Array.from({ length: 200 }, (_, i) => i + 1) } }) });
  assert.ok(builderSized.length < CHART_BODY_LIMIT / 20, 'the largest valid query fits many times over');
});

test.after(() => fs.rm(tmp, { recursive: true, force: true }));
