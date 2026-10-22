// Round 27: periods, per companionship and roster counts - the queries GFM components ask for, and their pinning.
import test from 'node:test'
import assert from 'node:assert/strict'
import { canonicalJson, componentSpecs, kpiSpec, normalizeSpec, periodOf, pinnedKeys, rosterSpec, rosterUnitSpec } from '../manager/gfm-addon/lib/chart-spec.mjs'

test('a quarter is its first and last day', () => {
  assert.deepEqual(periodOf({ quarter: '2026-Q3' }), { from: '2026-07-01', to: '2026-09-30' })
  assert.equal(periodOf({}), null)
})

test('weeks take a from and to date, checked like charts.py', () => {
  assert.deepEqual(normalizeSpec({ measures: ['friends_found.actual'], weeks: { from: '2026-07-01', to: '2026-09-30' } }).weeks, { from: '2026-07-01', to: '2026-09-30' })
  assert.throws(() => normalizeSpec({ measures: ['friends_found.actual'], weeks: { last: 4, from: '2026-07-01', to: '2026-09-30' } }), /not both/)
  assert.throws(() => normalizeSpec({ measures: ['friends_found.actual'], weeks: { from: '2026-7-1', to: '2026-09-30' } }), /like 2026-07-01/)
  assert.throws(() => normalizeSpec({ measures: ['friends_found.actual'], weeks: { from: '2026-09-30', to: '2026-07-01' } }), /must not be after/)
  assert.equal(normalizeSpec({ measures: ['friends_found.actual'] }).weeks.last, 12)
})

test('per companionship and roster measures are known', () => {
  const s = kpiSpec({ kpi: 'Baptismal dates', per: 'companionship', weeks: '8' })
  assert.equal(s.transform, 'per_companionship')
  assert.deepEqual(s.measures, ['baptismal_dates.actual', 'baptismal_dates.previous_goal'])
  assert.equal(kpiSpec({ kpi: 'friends_found' }), null) // the classic tile keeps /api/mission-kpis
  assert.deepEqual(rosterSpec({ view: 'gender' }).measures, ['roster.elders', 'roster.sisters', 'roster.missionaries'])
  assert.deepEqual(rosterSpec({ asOf: '2026-09-27' }).weeks, { from: '2026-09-21', to: '2026-09-27' })
})

test('a deck pins the queries its components ask for', () => {
  const md = '<GfmKpiGrid quarter="2026-Q3" metrics="friends_found,baptismal_dates" />\n<GfmKpi metric="Sacrament attendance" per="companionship" weeks="8" />\n<MissionRoster view="units" />\n<MissionKpiChart kpi="friends_found" />'
  const specs = componentSpecs(md)
  assert.equal(specs.length, 5) // grid 2, kpi 1, roster units 2 (counts + per unit); a plain MissionKpiChart keeps /api/mission-kpis
  const keys = pinnedKeys(md)
  for (const s of [kpiSpec({ kpi: 'friends_found', quarter: '2026-Q3' }), kpiSpec({ kpi: 'Sacrament attendance', per: 'companionship', weeks: 8 }), rosterSpec({ view: 'units' }), rosterUnitSpec({})])
    assert.ok(keys.has(canonicalJson(s)))
})

test('round 28: missionaries per church unit, and line charts', () => {
  const u = rosterUnitSpec({ asOf: '2026-09-27' })
  assert.equal(u.level, 'unit')
  assert.equal(u.by, 'unit')
  assert.deepEqual(u.measures, ['roster.missionaries'])
  assert.deepEqual(u.weeks, { from: '2026-09-21', to: '2026-09-27' })
  assert.throws(() => normalizeSpec({ measures: ['friends_found.actual'], level: 'unit' }), /only roster counts/)
  assert.equal(componentSpecs('<MissionRoster view="gender" />').length, 1)
  const line = componentSpecs('<MissionKpiChart kpi="friends_found" chart="line" quarter="2026-Q3" per="companionship" />')
  assert.equal(line.length, 1)
  assert.deepEqual(line[0].weeks, { from: '2026-07-01', to: '2026-09-30' })
  assert.equal(line[0].transform, 'per_companionship')
})
