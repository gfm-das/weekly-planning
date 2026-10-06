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
//     weeks: { last: 1–104 }, includeCurrent: true,
//     transform: 'none'|'pct_of_goal'|'cumulative'|'rolling4'|'per_area',
//     sort: 'none'|'desc'|'asc', top: 0–50,
//     audience: 'deck'|'stewardship' }
// Only portal-api knows which measure names exist; this side checks their shape.

export const LEVELS = ['mission', 'zone', 'district', 'area']
export const BYS = ['week', 'unit']
export const TRANSFORMS = ['none', 'pct_of_goal', 'cumulative', 'rolling4', 'per_area']
export const SORTS = ['none', 'desc', 'asc']
export const AUDIENCES = ['deck', 'stewardship']
const FILTER_KEYS = ['zones', 'districts', 'areas']
const LEVEL_FILTERS = { mission: [], zone: ['zones'], district: ['zones', 'districts'], area: ['zones', 'districts', 'areas'] }
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

  const level = choice(raw, 'level', LEVELS, 'mission')
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
  if (isPlain(weeks)) {
    const extra = Object.keys(weeks).filter(k => k !== 'last').sort()
    if (extra.length) throw new SpecError(`Unknown chart setting: weeks.${extra[0]}.`)
    weeks = get(weeks, 'last', 12)
  }
  const last = integer(weeks)
  if (last === null || last < 1 || last > MAX_WEEKS) throw new SpecError(`Choose between 1 and ${MAX_WEEKS} weeks.`)

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

  return { v: 1, measures: [...seen], level, by, filter, weeks: { last }, includeCurrent, transform, sort, top, audience }
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
  return keys
}

/** The deck of a page: /p/<slug>/… (published) or /edit/<slug>/… (editor). */
export function deckOfPath(pathname) {
  return String(pathname ?? '').match(/^\/(?:p|edit)\/([a-z0-9-]+)(?:\/|$)/)?.[1] ?? ''
}
