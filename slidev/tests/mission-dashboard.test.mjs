// The Mission Dashboard deck (showcase/mission-dashboard, opened by the portal's Dashboards button):
// its charts are valid database charts the manager pins, use finished weeks only, keep each leader to their
// own stewardship where it matters, and can be opened and saved again with Edit chart in /studio without
// losing anything. The numbers themselves are checked against a copy of the database by
// portal-api/tests/dashboard_deck_db.py and tests/dashboard-deck/chain-check.mjs.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { canonicalJson, normalizeSpec, pinnedKeys, querySpecs } from '../manager/gfm-addon/lib/chart-spec.mjs'
import { chartTag, findChartTags, PROPS, tagToModel } from '../manager/gfm-addon/lib/chart-builder-core.mjs'

const deck = readFileSync(new URL('../showcase/mission-dashboard/slides.md', import.meta.url), 'utf8')
const slides = deck.split(/\r?\n---\r?\n/)
const KPIS = ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament']

test('every chart is a database chart with a valid query, all pinned', () => {
  const tags = findChartTags(deck)
  const queries = querySpecs(deck)
  assert.ok(tags.length >= 20)
  assert.equal(queries.length, tags.length, 'one query per chart')
  assert.ok(tags.every(t => t.tag === 'MissionChart'))
  const specs = queries.map(q => normalizeSpec(q))
  assert.equal(pinnedKeys(deck).size, new Set(specs.map(canonicalJson)).size, 'every query is written as plain JSON, so it is pinned')
})

test('finished weeks only, no area numbers, district charts per stewardship', () => {
  for (const spec of querySpecs(deck).map(q => normalizeSpec(q))) {
    assert.equal(spec.includeCurrent, false, 'the week still being reported would pull every trend down on a Monday')
    assert.notEqual(spec.level, 'area')
    if (spec.level === 'district') assert.equal(spec.audience, 'stewardship')
  }
})

test('the opening slide: six key indicator tiles, New people being taught first, against the goal set the week before', () => {
  const first = findChartTags(slides[0] + '\n---\n' + slides[1])
  const tiles = first.map(t => tagToModel(t).model).filter(m => m.props.type === 'tile')
  assert.equal(tiles.length, 6)
  assert.deepEqual(tiles.map(m => m.spec.measures[0].split('.')[0]), KPIS)
  for (const m of tiles) assert.deepEqual(m.spec.measures.slice(1), [m.spec.measures[0].replace('.actual', '.previous_goal')])
})

test('one slide per key indicator: 26 weeks, the goal line and a linear or polynomial trend', () => {
  const kpiCharts = findChartTags(deck).map(t => tagToModel(t).model)
    .filter(m => m.props.type !== 'tile' && m.spec.level === 'mission' && m.spec.weeks.last === 26)
  assert.deepEqual(kpiCharts.map(m => m.spec.measures[0].split('.')[0]), KPIS)
  for (const m of kpiCharts) {
    assert.deepEqual(m.spec.measures, [m.spec.measures[0], m.spec.measures[0].replace('.actual', '.previous_goal')])
    assert.ok(['linear', 'polynomial'].includes(m.props.trend))
  }
  assert.ok(kpiCharts.some(m => m.props.trend === 'polynomial') && kpiCharts.some(m => m.props.trend === 'linear'))
})

test('zones against their goals, a heat map of zones by week, districts lowest first, people counts', () => {
  const specs = querySpecs(deck).map(q => normalizeSpec(q))
  assert.ok(specs.some(s => s.level === 'zone' && s.by === 'unit' && s.transform === 'pct_of_goal' && s.weeks.last === 1))
  assert.ok(findChartTags(deck).some(t => { const m = tagToModel(t).model; return m.props.type === 'heatmap' && m.spec.level === 'zone' && m.spec.by === 'week' }))
  assert.ok(specs.some(s => s.level === 'district' && s.sort === 'asc' && s.top > 0 && s.transform === 'pct_of_goal'))
  const people = new Set(specs.flatMap(s => s.measures).filter(m => !m.includes('.actual') && !m.includes('goal')))
  for (const m of ['new_members.at_church', 'new_members.temple_recommend', 'new_members.calling', 'new_members.aaronic_priesthood',
    'new_members.melchizedek_priesthood', 'baptismal_date_friends.next_4_weeks', 'baptismal_date_friends.at_church', 'high_potentials.total'])
    assert.ok(people.has(m), m)
})

test('Edit chart opens every chart with nothing lost, and Update chart writes the same chart back', () => {
  for (const found of findChartTags(deck)) {
    const { model, notes } = tagToModel(found)
    assert.deepEqual(notes, [], found.text)
    assert.deepEqual(model.keep, [], `no attribute the builder does not know: ${found.text}`)
    const again = tagToModel(findChartTags(chartTag(model))[0]).model
    assert.equal(canonicalJson(again.spec), canonicalJson(model.spec))
    assert.equal(again.option, model.option)
    // Settings written at their default (for example :degree="2") are left out when the builder writes the tag.
    const set = props => Object.fromEntries(Object.entries(props).filter(([k, v]) => !(Object.hasOwn(PROPS, k) && Number.isFinite(Number(v)) && Number(v) === PROPS[k][1])))
    assert.deepEqual(set(again.props), set(model.props))
  }
})

test('the opening slide links go to slides that exist', () => {
  for (const alias of ['kpis', 'zones', 'people', 'districts']) {
    assert.ok(deck.includes(`<Link to="${alias}">`), alias)
    // \r?: a Windows checkout (core.autocrlf) has CRLF line ends.
    assert.match(deck, new RegExp(`routeAlias: ${alias}\\r?\\n`), alias)
  }
})

test('every week axis keeps the latest finished week labelled (ECharts may drop the last label otherwise)', () => {
  const weekCharts = findChartTags(deck).map(t => tagToModel(t).model)
    .filter(m => m.props.type !== 'tile' && (m.spec.level === 'mission' || m.props.type === 'heatmap'))
  assert.equal(weekCharts.length, 7, 'six key indicator slides and the heat map')
  for (const m of weekCharts) assert.equal(JSON.parse(m.option).xAxis.axisLabel.showMaxLabel, true, m.spec.measures[0])
  // Edit chart keeps it.
  for (const m of weekCharts) assert.equal(JSON.parse(tagToModel(findChartTags(chartTag(m))[0]).model.option).xAxis.axisLabel.showMaxLabel, true)
})

test('the last slide asks to keep the name and not to delete or share the deck (the Dashboards button opens it by name)', () => {
  const last = slides[slides.length - 1]
  assert.match(last, /keep the name <b>Mission Dashboard<\/b>/)
  assert.match(last, /do not delete it or use Manage access/)
})
