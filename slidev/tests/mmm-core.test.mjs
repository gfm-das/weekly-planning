// The arithmetic behind the MMM / ZOKO / Stake pieces (<MmmCard>, <MmmGauge>, <MmmTrend>, <MmmTable>, <MmmPair>):
// manager/gfm-addon/lib/mmm-core.mjs, plain Node (no Slidev, no browser). Every number here is invented.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  gaugeModel, goalCard, lastIndex, numberText, pairSums, percentText, periodCard, previousPeriod, periodStart, readAnswer,
  shareCard, toneOf, unitRows, weeksSinceYearStart, yearProgress,
} from '../manager/gfm-addon/lib/mmm-core.mjs';

const weeks = ['2026-09-06', '2026-09-13', '2026-09-20', '2026-09-27', '2026-10-04'];
const answer = (...series) => ({ table: { labels: weeks, series }, meta: { by: 'week' } });

test('readAnswer: actuals and goals apart, never throws on a bad answer', () => {
  const a = readAnswer(answer({ name: 'A', values: [1, 2, 3, 4, 5] }, { name: 'G', values: [2, 2, 2, 2, 2], role: 'goal' }));
  assert.equal(a.actuals.length, 1);
  assert.equal(a.goals.length, 1);
  assert.deepEqual(a.labels, weeks);
  for (const bad of [null, undefined, {}, { table: null }, { table: { labels: 'x', series: 3 } }]) {
    const r = readAnswer(bad);
    assert.deepEqual([r.labels, r.all], [[], []]);
  }
});

test('lastIndex: the last week that has a number (a hidden or missing week is skipped)', () => {
  assert.equal(lastIndex([1, 2, null]), 1);
  assert.equal(lastIndex([null, null]), -1);
  assert.equal(lastIndex([4, 5, 6], 2), 1);
});

test('goalCard: the latest week, the week before it, the goal set the week before and the share of it', () => {
  const card = goalCard(answer({ name: 'Friends', values: [40, 41, 39, 50, 52] }, { name: 'Goal', values: [60, 60, 60, 60, 64], role: 'goal' }));
  assert.deepEqual([card.ready, card.value, card.last, card.goal], [true, 52, 50, 64]);
  assert.equal(percentText(card.ratio), '81.3%');
  assert.equal(toneOf(card.ratio), 'ok');
});

test('goalCard: no goal (or 0) says N/A (a ratio of null), a missing last week is null, nothing to show is not ready', () => {
  const noGoal = goalCard(answer({ name: 'B', values: [0, 0, 0, 1, 1] }, { name: 'G', values: [0, 0, 0, 0, 0], role: 'goal' }));
  assert.equal(noGoal.ratio, null);
  assert.equal(noGoal.goal, null);
  assert.equal(percentText(noGoal.ratio), '');
  const single = goalCard({ table: { labels: ['2026-10-04'], series: [{ name: 'A', values: [7] }] } });
  assert.deepEqual([single.value, single.last], [7, null]);
  assert.equal(goalCard(answer({ name: 'A', values: [null, null, null, null, null] })).ready, false);
  assert.equal(goalCard(null).ready, false);
});

test('shareCard: the second number as a share of the first, the whole as the big number', () => {
  const card = shareCard(answer({ name: 'Total', values: [170, 171, 172, 178, 180] }, { name: 'AtChurch', values: [70, 72, 74, 79, 76] }));
  assert.deepEqual([card.value, card.part, card.last], [180, 76, 178]);
  assert.equal(percentText(card.ratio), '42.2%');
  assert.equal(shareCard(answer({ name: 'Only', values: [1, 2, 3, 4, 5] })).ready, false);
});

test('toneOf: red under half, amber under 0.8, fine from there; no ratio, no tone', () => {
  assert.deepEqual([0.2, 0.5, 0.79, 0.8, 1.4].map(toneOf), ['low', 'mid', 'mid', 'ok', 'ok']);
  assert.equal(toneOf(null), 'none');
});

test('periods: this month, this quarter, this year, and the one before each', () => {
  const now = new Date(2026, 9, 12);
  assert.deepEqual(periodStart(now, 'month'), { year: 2026, month: 9 });
  assert.deepEqual(periodStart(now, 'quarter'), { year: 2026, month: 9 });
  assert.deepEqual(periodStart(new Date(2026, 7, 3), 'quarter'), { year: 2026, month: 6 });
  assert.deepEqual(periodStart(now, 'year'), { year: 2026, month: 0 });
  assert.deepEqual(previousPeriod({ year: 2026, month: 0 }, 'month'), { year: 2025, month: 11 });
  assert.deepEqual(previousPeriod({ year: 2026, month: 0 }, 'quarter'), { year: 2025, month: 9 });
  assert.deepEqual(previousPeriod({ year: 2026, month: 0 }, 'year'), { year: 2025, month: 0 });
});

test('periodCard: the sum of the weeks in this month against the month before, and the typed target', () => {
  const labels = ['2026-08-30', '2026-09-06', '2026-09-13', '2026-09-20', '2026-09-27', '2026-10-04', '2026-10-11'];
  const values = [1, 2, 3, 4, 5, 6, 7];
  const data = { table: { labels, series: [{ name: 'Baptisms', values }] } };
  const month = periodCard(data, { period: 'month', target: '67', now: new Date(2026, 9, 12) });
  assert.deepEqual([month.value, month.last, month.goal], [13, 14, 67]);
  assert.equal(percentText(month.ratio, 0), '19%');
  // The target is typed in the slide: empty means "no goal yet" (N/A), never 0.
  assert.equal(periodCard(data, { period: 'month', target: '', now: new Date(2026, 9, 12) }).ratio, null);
  const quarter = periodCard(data, { period: 'quarter', target: 67, now: new Date(2026, 9, 12) });
  assert.deepEqual([quarter.value, quarter.last], [13, 15], 'the quarter before holds the end of August and all of September');
  // No week in the period yet: 0, not a missing number.
  assert.equal(periodCard(data, { period: 'month', now: new Date(2026, 10, 3) }).value, 0);
});

test('yearProgress and weeksSinceYearStart: the year-to-date chart and gauge', () => {
  const p = yearProgress(new Date(2026, 9, 12));
  assert.ok(p > 0.77 && p < 0.79, `78 percent of the year, got ${p}`);
  assert.equal(percentText(p, 0), '78%');
  assert.equal(yearProgress(new Date(2026, 0, 1)), 0);
  assert.equal(weeksSinceYearStart(new Date(2026, 9, 12)), 42);
  assert.equal(weeksSinceYearStart(new Date(2026, 0, 1, 12)), 2);
  assert.ok(weeksSinceYearStart(new Date(2026, 11, 31)) <= 104);
});

test('gaugeModel: value against max with the change, ratio with points and a tick, year, manual', () => {
  const first = gaugeModel(answer({ name: 'First time', values: [30, 31, 35, 35, 38] }), { mode: 'value', max: 100 });
  assert.deepEqual([first.display, first.change, first.ratio], ['38', 3, 0.38]);
  const ratio = gaugeModel(answer({ name: 'Follow-up', values: [500, 520, 530, 540, 542] }, { name: 'With member', values: [250, 260, 280, 290, 289] }), { mode: 'ratio', target: 0.55 });
  assert.equal(ratio.display, '53%');
  assert.equal(ratio.tick, 0.55);
  assert.equal(ratio.changeIsPoints, true);
  assert.ok(Math.abs(ratio.change - ((289 / 542 - 290 / 540) * 100)) < 1e-9);
  assert.equal(gaugeModel(null, { mode: 'year', now: new Date(2026, 9, 12) }).display, '78%');
  // A rate with no source in the portal: typed in the slide, or empty (a dash) until it is.
  assert.equal(gaugeModel(null, { mode: 'manual', max: 1 }).ready, false);
  const typed = gaugeModel(null, { mode: 'manual', max: 1, value: 0.33, change: 0.0123 });
  assert.deepEqual([typed.display, typed.percent], ['33%', true]);
  assert.equal(gaugeModel(answer({ name: 'A', values: [null, null, null, null, null] }), { mode: 'value' }).ready, false);
});

test('gaugeModel: the arc never leaves 0..1, a missing whole is not a division by zero', () => {
  assert.equal(gaugeModel(answer({ name: 'A', values: [1, 1, 1, 1, 500] }), { mode: 'value', max: 100 }).ratio, 1);
  assert.equal(gaugeModel(answer({ name: 'W', values: [0, 0, 0, 0, 0] }, { name: 'P', values: [0, 0, 0, 0, 0] }), { mode: 'ratio' }).ready, false);
});

test('unitRows: one row for each zone, largest first, cut to the top, the share of the second in the first', () => {
  const data = { table: { labels: ['Zone A', 'Zone B', 'Zone C', 'Zone D'], series: [{ name: 'Total', values: [30, 41, 36, null] }, { name: 'At church', values: [11, 18, 14, null] }] }, meta: { by: 'unit' } };
  const rows = unitRows(data, { top: 3 });
  assert.deepEqual(rows.map(r => r.name), ['Zone B', 'Zone C', 'Zone A']);
  assert.deepEqual(rows[0].cells, [41, 18]);
  assert.equal(percentText(rows[0].ratio, 0), '44%');
  assert.equal(unitRows(data, { top: 0 }).length, 3, 'a row with no numbers at all is left out');
  assert.equal(unitRows(null).length, 0);
});

test('pairSums: the last weeks added up, with the goal beside them', () => {
  const data = answer({ name: 'A', values: [1, 2, 3, 4, 5] }, { name: 'G', values: [2, 2, 2, 2, 2], role: 'goal' });
  assert.deepEqual([pairSums(data, { weeks: 4 }).actual, pairSums(data, { weeks: 4 }).goal], [14, 8]);
  assert.equal(pairSums(answer({ name: 'A', values: [1, 2, 3, 4, 5] }), { weeks: 2 }).goal, null);
  assert.equal(pairSums(null).ready, false);
});

test('numberText: the deck language, and nothing for a number that is not there', () => {
  assert.equal(numberText(1234, 'en'), '1,234');
  assert.equal(numberText(1234, 'de'), '1.234');
  assert.equal(numberText(null, 'en'), '');
  assert.equal(numberText(undefined), '');
});
