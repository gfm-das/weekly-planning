// The "query" of a database chart (<MissionChart :query='{…}'>): checking it,
// its canonical form and finding the ones written in a deck.
//
// Pure JavaScript with no imports, used by the chart component (to ask for
// the numbers), the Slidev manager (chart-access.mjs: pinning, caching) and the
// chart builder in /studio. portal-api's charts.py has the same rules in
// Python (normalize_spec); both must give the same canonical JSON for the same
// spec, because the manager lets a viewer see a chart only when the canonical
// spec is written in the deck ("pinning"). The shared test vectors are in
// slidev/tests/fixtures/chart-spec-vectors.json and are checked on both sides.
//
// The canonical spec, every key present and sorted when written as JSON:
//   { v: 1, measures: ['friends_found.actual', 'friends_found.previous_goal'],
//     level: 'mission'|'zone'|'district'|'area', by: 'week'|'unit',
//     filter: { zones?: [ids], districts?: [ids], areas?: [ids] },
//     weeks: { last: 1–104 } or { from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' } (round 27), includeCurrent: true,
//     transform: 'none'|'pct_of_goal'|'cumulative'|'rolling4'|'per_area',
//     sort: 'none'|'desc'|'asc', top: 0–50,
//     audience: 'deck'|'stewardship' }
// Only portal-api knows which measure names exist; this side checks their shape.

export const LEVELS = ['mission', 'zone', 'district', 'area']
// Round 28: church units (wards and branches with missionaries), for roster counts only (charts.py ROSTER_LEVELS).
export const ROSTER_LEVELS = [...LEVELS, 'unit']
export const BYS = ['week', 'unit']
export const TRANSFORMS = ['none', 'pct_of_goal', 'cumulative', 'rolling4', 'per_area', 'per_companionship']
export const SORTS = ['none', 'desc', 'asc']
export const AUDIENCES = ['deck', 'stewardship']
const FILTER_KEYS = ['zones', 'districts', 'areas']
const LEVEL_FILTERS = { mission: [], zone: ['zones'], district: ['zones', 'districts'], area: ['zones', 'districts', 'areas'], unit: ['zones', 'districts', 'areas'] }
const SPEC_KEYS = ['v', 'measures', 'level', 'by', 'filter', 'weeks', 'includeCurrent', 'transform', 'sort', 'top', 'audience']
const MEASURE_ID = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/
export const MAX_MEASURES = 8
// Entries in the measures list before repeats are dropped (charts.py has the same).
export const MAX_MEASURE_ENTRIES = 32
export const MAX_WEEKS = 104
export const MAX_TOP = 50
const MAX_FILTER = 200
const MAX_ID = 2 ** 31 - 1

/** A mistake in a chart's settings, with a sentence for the writer. */
export class SpecError extends Error {}

function isPlain(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const proto = Object.getPrototypeOf(value)
  return proto === Object.prototype || proto === null
}

const has = (object, key) => Object.prototype.hasOwnProperty.call(object, key)
const get = (object, key, fallback) => (has(object, key) ? object[key] : fallback)

/** A whole number (12 or 12.0), else null. Booleans and text are not numbers here. */
function integer(value) {
  return typeof value === 'number' && Number.isInteger(value) ? value : null
}

function choice(spec, key, options, fallback) {
  const value = get(spec, key, fallback)
  if (!options.includes(value)) throw new SpecError(`Choose one of ${options.join(', ')} for ${key}.`)
  return value
}

/**
 * The canonical spec with every default filled in. Throws SpecError with a
 * sentence for the writer. Same rules and order of checks as charts.py
 * normalize_spec (without its measure whitelist).
 */
export function normalizeSpec(raw) {
  if (typeof raw === 'string') {
    try { raw = JSON.parse(raw) }
    catch { throw new SpecError('The chart settings are not valid JSON.') }
  }
  if (!isPlain(raw)) throw new SpecError('The chart settings must be a list of settings in { }.')
  const unknown = Object.keys(raw).filter(k => !SPEC_KEYS.includes(k)).sort()
  if (unknown.length) throw new SpecError(`Unknown chart setting: ${unknown[0]}.`)
  if (integer(get(raw, 'v', 1)) !== 1) throw new SpecError('This chart was made for a newer version of Presentations.')

  const measures = get(raw, 'measures', undefined)
  if (!Array.isArray(measures) || !measures.length) throw new SpecError('Choose at least one number to show.')
  // A long list is refused before it is read, so a huge request cannot keep
  // the (single-threaded) manager busy; repeats within the limit are dropped.
  if (measures.length > MAX_MEASURE_ENTRIES) throw new SpecError(`Choose at most ${MAX_MEASURES} numbers for one chart.`)
  const seen = new Set()
  for (const m of measures) {
    if (typeof m !== 'string' || !MEASURE_ID.test(m)) throw new SpecError('A number in this chart is not written like "friends_found.actual".')
    seen.add(m)
  }
  if (seen.size > MAX_MEASURES) throw new SpecError(`Choose at most ${MAX_MEASURES} numbers for one chart.`)

  const level = choice(raw, 'level', ROSTER_LEVELS, 'mission')
  if (level === 'unit' && [...seen].some(m => !m.startsWith('roster.'))) throw new SpecError('Church units can show only roster counts.')
  const by = choice(raw, 'by', BYS, 'week')

  let given = get(raw, 'filter', {})
  if (given === null) given = {}
  if (!isPlain(given)) throw new SpecError('Choose the zones, districts or areas as lists of numbers.')
  const filter = {}
  for (const key of Object.keys(given).sort()) {
    if (!FILTER_KEYS.includes(key)) throw new SpecError(`Unknown chart setting: filter.${key}.`)
    let values = given[key]
    if (values === null) values = []
    if (!Array.isArray(values)) throw new SpecError(`Choose ${key} as a list of numbers.`)
    const ids = values.map(integer)
    if (ids.some(i => i === null || i < 1 || i > MAX_ID)) throw new SpecError(`Choose ${key} as a list of numbers.`)
    const unique = [...new Set(ids)].sort((a, b) => a - b)
    if (unique.length > MAX_FILTER) throw new SpecError(`Choose at most ${MAX_FILTER} ${key}.`)
    if (!unique.length) continue
    if (!LEVEL_FILTERS[level].includes(key)) throw new SpecError(`A ${level} chart cannot be limited to ${key}.`)
    filter[key] = unique
  }

  let weeks = get(raw, 'weeks', 12)
  let span = null
  if (isPlain(weeks)) {
    const extra = Object.keys(weeks).filter(k => !['last', 'from', 'to'].includes(k)).sort()
    if (extra.length) throw new SpecError(`Unknown chart setting: weeks.${extra[0]}.`)
    if (has(weeks, 'from') || has(weeks, 'to')) {
      if (has(weeks, 'last')) throw new SpecError('Choose either the last weeks or a from and to date, not both.')
      span = [day(weeks.from), day(weeks.to)]
      if (span[0] > span[1]) throw new SpecError('The from date must not be after the to date.')
      if ((Date.parse(`${span[1]}T00:00:00Z`) - Date.parse(`${span[0]}T00:00:00Z`)) / 86400000 > MAX_WEEKS * 7)
        throw new SpecError(`Choose between 1 and ${MAX_WEEKS} weeks.`)
    }
    weeks = get(weeks, 'last', 12)
  }
  const last = integer(weeks)
  if (!span && (last === null || last < 1 || last > MAX_WEEKS)) throw new SpecError(`Choose between 1 and ${MAX_WEEKS} weeks.`)

  const includeCurrent = get(raw, 'includeCurrent', true)
  if (typeof includeCurrent !== 'boolean') throw new SpecError('includeCurrent must be true or false.')

  const transform = choice(raw, 'transform', TRANSFORMS, 'none')
  if ((transform === 'cumulative' || transform === 'rolling4') && by !== 'week')
    throw new SpecError('A running total or 4-week average needs the chart grouped by week.')

  const sort = choice(raw, 'sort', SORTS, 'none')
  const top = integer(get(raw, 'top', 0))
  if (top === null || top < 0 || top > MAX_TOP) throw new SpecError(`Choose a top number between 0 and ${MAX_TOP}.`)
  if (by === 'week' && (sort !== 'none' || top)) throw new SpecError('Sorting and "top" work when the chart is grouped by zone, district or area.')

  const audience = choice(raw, 'audience', AUDIENCES, level === 'mission' || level === 'zone' ? 'deck' : 'stewardship')

  const period = span ? { from: span[0], to: span[1] } : { last }
  return { v: 1, measures: [...seen], level, by, filter, weeks: period, includeCurrent, transform, sort, top, audience }
}

/** A real date written YYYY-MM-DD, else SpecError (the same sentence as charts.py _day). */
function day(value) {
  const bad = () => new SpecError('Write the from and to dates like 2026-07-01.')
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw bad()
  const d = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== value) throw bad()
  return value
}

// ---- the queries of GFM components that are written as plain settings (round 27) ------------------------------
// <GfmKpiGrid from=… to=… per=…>, <GfmKpi …>, <MissionKpiChart …> with a period or per="companionship", and
// <MissionRoster view=… asOf=…> ask POST /api/charts/data with a query made from their settings. The deck's
// slides.md is read with the same functions (componentSpecs), so those queries are pinned like :query ones.

export const KPI_IDS = ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament']
const KPI_LABELS = ['new people being taught', 'baptisms and confirmations', 'baptismal dates', 'sacrament attendance', 'members at lessons', 'new member sacrament attendance']

/** The id of a key indicator name or id (as chart-core kpiId), friends_found otherwise. */
export function kpiKey(value) {
  const lower = String(value ?? '').trim().toLowerCase()
  const id = lower.replace(/[\s-]+/g, '_')
  const i = KPI_IDS.findIndex((k, n) => k === id || KPI_LABELS[n] === lower)
  return KPI_IDS[i < 0 ? 0 : i]
}

/** { from, to } of quarter="2026-Q3" or from/to settings; null when none is set or it cannot be read. */
export function periodOf({ from, to, quarter } = {}) {
  const q = String(quarter ?? '').trim().match(/^(\d{4})-?Q([1-4])$/i)
  if (q) {
    const y = q[1], n = Number(q[2])
    const ends = ['03-31', '06-30', '09-30', '12-31']
    return { from: `${y}-${String(n * 3 - 2).padStart(2, '0')}-01`, to: `${y}-${ends[n - 1]}` }
  }
  if (from || to) return { from: String(from ?? '').trim(), to: String(to ?? '').trim() }
  return null
}

/** The query of one key indicator tile or chart with a period or per="companionship"; null for the classic one. */
export function kpiSpec({ kpi, from, to, quarter, per, weeks } = {}) {
  const period = periodOf({ from, to, quarter })
  const perComp = String(per ?? '').trim().toLowerCase() === 'companionship'
  if (!period && !perComp) return null
  const id = kpiKey(kpi)
  const raw = { measures: [`${id}.actual`, `${id}.previous_goal`], level: 'mission', transform: perComp ? 'per_companionship' : 'none', weeks: period ?? { last: Math.min(MAX_WEEKS, Math.max(1, Math.round(Number(weeks) || 12))) } }
  try { return normalizeSpec(raw) }
  catch { return null }
}

export const ROSTER_VIEWS = { units: ['roster.units', 'roster.missionaries', 'roster.companionships'], gender: ['roster.elders', 'roster.sisters', 'roster.missionaries'] }

/** The query of <MissionRoster view="units"|"gender" asOf="YYYY-MM-DD">: the reporting Sunday on or before asOf, else the current one. */
export function rosterSpec({ view, asOf } = {}) {
  const measures = ROSTER_VIEWS[String(view ?? '').trim().toLowerCase()] ?? ROSTER_VIEWS.units
  const until = String(asOf ?? '').trim()
  let weeks = { last: 1 }
  if (until) {
    const end = Date.parse(`${until}T00:00:00Z`)
    if (!Number.isFinite(end)) return null
    weeks = { from: new Date(end - 6 * 86400000).toISOString().slice(0, 10), to: until }
  }
  try { return normalizeSpec({ measures, level: 'mission', weeks }) }
  catch { return null }
}

/** Round 28: missionaries per church unit (one bar per unit, by name), this week or the week of asOf. */
export function rosterUnitSpec({ asOf } = {}) {
  const base = rosterSpec({ view: 'units', asOf })
  if (!base) return null
  try { return normalizeSpec({ measures: ['roster.missionaries'], level: 'unit', by: 'unit', weeks: base.weeks, sort: 'desc' }) }
  catch { return null }
}

const COMPONENT_TAG = /<\s*(gfmkpigrid|gfm-kpi-grid|gfmkpi|gfm-kpi|missionkpichart|mission-kpi-chart|missionroster|mission-roster)\b([^>]*)>/gi
const PLAIN_ATTRIBUTE = /(?<![\w:.-])([A-Za-z][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g

/** The settings written as plain text on a tag (name="…"); bound ones (:name) are not read. Names in camelCase. */
function plainAttributes(text) {
  const out = {}
  for (const m of String(text).matchAll(PLAIN_ATTRIBUTE)) out[m[1].replace(/-(\w)/g, (_, c) => c.toUpperCase())] = m[2] ?? m[3]
  return out
}

/** The queries the GFM components in a deck ask for (see above), as normalised specs. */
export function componentSpecs(markdown) {
  const out = []
  for (const m of String(markdown ?? '').matchAll(COMPONENT_TAG)) {
    const tag = m[1].toLowerCase().replace(/-/g, '')
    const a = plainAttributes(m[2])
    if (tag === 'missionroster') {
      const s = rosterSpec(a)
      if (s) out.push(s)
      const u = String(a.view ?? '').trim().toLowerCase() === 'gender' ? null : rosterUnitSpec(a)
      if (u) out.push(u)
      continue
    }
    const kpis = tag === 'gfmkpigrid'
      ? String(a.metrics || KPI_IDS.join(',')).split(',').map(x => x.trim()).filter(Boolean).slice(0, 12)
      : [tag === 'gfmkpi' ? a.metric : a.kpi]
    for (const kpi of kpis) { const s = kpiSpec({ ...a, kpi }); if (s) out.push(s) }
  }
  return out
}

/** JSON with the keys of every object sorted and no spaces (Python: sort_keys, compact separators). */
export function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (isPlain(value)) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`
  // Every string in a valid spec is plain ASCII, so this matches Python's ensure_ascii output.
  return JSON.stringify(value)
}

/** The canonical JSON of a spec, or null when it is not a valid spec. */
export function specKey(raw) {
  try { return canonicalJson(normalizeSpec(raw)) }
  catch { return null }
}

/**
 * JSON, or a JavaScript object literal as Vue accepts it in
 * :query="{ measures: ['friends_found.actual'] }" (single quotes, bare keys,
 * trailing commas). Undefined when it is neither.
 */
export function parseLoose(text) {
  const source = String(text ?? '').trim()
  if (!source) return undefined
  try { return JSON.parse(source) }
  catch {}
  try {
    const json = source
      .replace(/'([^'\\]*)'/g, (_, s) => JSON.stringify(s))
      .replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":')
      .replace(/,\s*([}\]])/g, '$1')
    return JSON.parse(json)
  }
  catch { return undefined }
}

function decodeEntities(text) {
  return text.replace(/&(quot|#34|apos|#39|lt|gt|amp);/g, (_, e) => ({ quot: '"', '#34': '"', apos: "'", '#39': "'", lt: '<', gt: '>', amp: '&' })[e])
}

const QUERY_ATTRIBUTE = /(?<![\w:.-])(:?query)\s*=\s*(?:'([^']*)'|"([^"]*)")/g

/**
 * Every chart query written in a deck's Markdown: `:query='{…}'` and
 * `:query="{…}"` on a component, and `query='{…}'` in a ```chart block.
 * Returns the raw values (not yet checked).
 */
export function querySpecs(markdown) {
  const found = []
  for (const match of String(markdown ?? '').matchAll(QUERY_ATTRIBUTE)) {
    const text = match[2] ?? decodeEntities(match[3] ?? '')
    const value = parseLoose(text)
    if (value !== undefined) found.push(value)
  }
  return found
}

/** The canonical JSON of every valid chart query in a deck (what "pinned" means). */
export function pinnedKeys(markdown) {
  const keys = new Set()
  for (const raw of querySpecs(markdown)) {
    const key = specKey(raw)
    if (key) keys.add(key)
  }
  for (const spec of componentSpecs(markdown)) keys.add(canonicalJson(spec))
  return keys
}

/** The deck of a page: /p/<slug>/… (published) or /edit/<slug>/… (editor). */
export function deckOfPath(pathname) {
  return String(pathname ?? '').match(/^\/(?:p|edit)\/([a-z0-9-]+)(?:\/|$)/)?.[1] ?? ''
}
