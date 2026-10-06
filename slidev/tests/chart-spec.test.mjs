// Chart queries (manager/gfm-addon/lib/chart-spec.mjs): the same canonical
// form and hash as portal-api's charts.py (shared vectors), and finding the
// queries written in a deck. Plain Node, no packages.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as spec from '../manager/gfm-addon/lib/chart-spec.mjs';
import { specHash } from '../manager/chart-access.mjs';

const vectors = JSON.parse(readFileSync(new URL('./fixtures/chart-spec-vectors.json', import.meta.url), 'utf8'));

test('shared vectors: the same canonical JSON and SHA-256 as charts.py', () => {
  assert.ok(vectors.valid.length >= 9);
  for (const v of vectors.valid) {
    const normal = spec.normalizeSpec(v.input);
    assert.equal(spec.canonicalJson(normal), v.canonical, v.name);
    assert.equal(specHash(normal), v.sha256, v.name);
    // Normalising twice changes nothing.
    assert.equal(spec.canonicalJson(spec.normalizeSpec(normal)), v.canonical, `${v.name} (again)`);
  }
});

test('shared vectors: the same refusals and sentences as charts.py', () => {
  assert.ok(vectors.invalid.length >= 15);
  for (const v of vectors.invalid) {
    assert.throws(() => spec.normalizeSpec(v.input), error => error instanceof spec.SpecError && error.message === v.error, v.name);
  }
});

test('defaults: audience by level, weeks, and the key order of the canonical JSON', () => {
  const zone = spec.normalizeSpec({ measures: ['friends_found.actual'], level: 'zone' });
  const district = spec.normalizeSpec({ measures: ['friends_found.actual'], level: 'district' });
  assert.equal(zone.audience, 'deck');
  assert.equal(district.audience, 'stewardship');
  assert.deepEqual(zone.weeks, { last: 12 });
  assert.equal(spec.canonicalJson({ b: 1, a: { d: [2, 1], c: true } }), '{"a":{"c":true,"d":[2,1]},"b":1}');
  assert.equal(spec.specKey('nonsense'), null);
});

test('a long list of numbers is refused at once (the manager has one thread)', () => {
  const started = performance.now();
  for (const size of [33, 60000, 400000]) {
    const measures = Array.from({ length: size }, (_, i) => `m${i}.actual`);
    assert.throws(() => spec.normalizeSpec({ measures }), error => error instanceof spec.SpecError && error.message === 'Choose at most 8 numbers for one chart.', `${size} entries`);
  }
  // The review measured 19 s for 150,000 entries with the old loop.
  assert.ok(performance.now() - started < 1000, `took ${Math.round(performance.now() - started)} ms`);
  assert.equal(spec.MAX_MEASURE_ENTRIES, 32);
  const within = spec.normalizeSpec({ measures: [...Array(31).fill('friends_found.actual'), 'friends_found.goal'] });
  assert.deepEqual(within.measures, ['friends_found.actual', 'friends_found.goal'], 'repeats dropped, first order kept');
});

test('querySpecs finds every way a deck writes a query', () => {
  const markdown = [
    `<MissionChart type="bar" :query='{"measures":["friends_found.actual"],"weeks":8}' />`,
    `<MissionChart :query="{ measures: ['sacrament_attendance.actual'], level: 'zone', }" />`,
    `<MissionChart :query="{&quot;measures&quot;:[&quot;baptismal_dates.actual&quot;]}" />`,
    '```chart type=line query=\'{"measures":["new_members.total"]}\'',
    'Week,A',
    '1,2',
    '```',
    `<p data-query='not me'>text</p>`,
    `<MissionChart :query='{"broken": ' />`,
  ].join('\n');
  const found = spec.querySpecs(markdown);
  assert.equal(found.length, 4, JSON.stringify(found));
  assert.deepEqual(found[1], { measures: ['sacrament_attendance.actual'], level: 'zone' });
  assert.deepEqual(found[2], { measures: ['baptismal_dates.actual'] });
  const keys = spec.pinnedKeys(markdown);
  assert.equal(keys.size, 4);
  assert.ok(keys.has(spec.specKey({ measures: ['new_members.total'] })));
  // The same query with other spacing and key order is the same pin.
  assert.ok(keys.has(spec.specKey({ weeks: { last: 8 }, measures: ['friends_found.actual'], level: 'mission' })));
});

test('deckOfPath reads the deck from a published or editor address', () => {
  assert.equal(spec.deckOfPath('/p/mission-charts/3'), 'mission-charts');
  assert.equal(spec.deckOfPath('/edit/weekly-report/'), 'weekly-report');
  assert.equal(spec.deckOfPath('/studio/x'), '');
  assert.equal(spec.deckOfPath('/p/../etc'), '');
});
