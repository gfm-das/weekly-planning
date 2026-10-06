// GFM Presentations V2: what a deck may hold (manager/v2-deck.mjs), the pinning of its queries, and the file paths.
import assert from 'node:assert/strict';
import test from 'node:test';
import { canonicalJson, normalizeSpec } from '../manager/gfm-addon/lib/chart-spec.mjs';
import { deckPinKeys, DeckError, validateDeck } from '../manager/v2-deck.mjs';

const query = { measures: ['friends_found.actual'], level: 'zone', by: 'unit', weeks: { last: 1 } };
const deck = (components, extra = {}) => ({ version: 1, name: 'T', slides: [{ id: 's1', components, ...extra }] });
const chart = props => ({ id: 'c1', type: 'chart', x: 5, y: 5, width: 50, height: 50, props });

test('a good chart deck is kept, normalised and clamped', () => {
  const out = validateDeck(deck([{ ...chart({ query, calcs: [{ name: 'rate', formula: 'a / b', format: 'percent' }] }), x: 500 }]));
  assert.equal(out.slides[0].components[0].x, 100);
  assert.deepEqual(out.slides[0].components[0].props.query, normalizeSpec(query));
  assert.equal(out.slides[0].transition, 'slide');
});

test('unknown keys are dropped and bad things are refused with a sentence', () => {
  const out = validateDeck({ ...deck([]), evil: '<script>' });
  assert.equal(out.evil, undefined);
  for (const bad of [
    null, { version: 2, slides: [] }, deck([{ id: 'x y', type: 'text' }]), deck([{ id: 'a', type: 'iframe' }]),
    deck([chart({ query: { measures: [] } })]), deck([chart({ query, chartType: 'sankey' })]),
    deck([{ id: 'i', type: 'image', props: { asset: '../../etc/passwd.png' } }]),
    deck([{ id: 'i', type: 'image', props: { asset: 'x.svg' } }]),
    deck([chart({ query, calcs: [{ name: 'a b', formula: '1' }] })]),
  ]) assert.throws(() => validateDeck(bad), DeckError);
});

test('duplicate part ids are refused', () => {
  assert.throws(() => validateDeck(deck([{ id: 'a', type: 'text' }, { id: 'a', type: 'text' }])), DeckError);
});

test('pinning: exactly the queries of the saved deck, written in any order of keys', () => {
  const saved = validateDeck(deck([chart({ query })]));
  const keys = deckPinKeys(saved);
  assert.equal(keys.size, 1);
  assert.ok(keys.has(canonicalJson(normalizeSpec({ weeks: { last: 1 }, by: 'unit', level: 'zone', measures: ['friends_found.actual'] }))));
  assert.ok(!keys.has(canonicalJson(normalizeSpec({ ...query, measures: ['baptismal_dates.actual'] }))));
});
