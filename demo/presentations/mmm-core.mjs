// The numbers behind the Monday Morning Meeting (MMM), zone conference (ZOKO) and Stake coordination pieces
// (<MmmCard>, <MmmGauge>, <MmmTrend>, <MmmTable>, <MmmPair>): plain functions, no Vue and no browser, so
// slidev/tests/mmm-core.test.mjs checks them with node --test.
//
// What goes in: an answer of POST /api/charts/data, { table: { labels, series: [{ name, values, role? }] }, meta },
// the same answer every <MissionChart :query> reads. A "goal" series has role 'goal' (the goal set the week before).
// What comes out: the few numbers a card, a gauge or a table shows, and the text for them. Nothing here asks for
// data and nothing here knows a person: counts only.

const isNumber = value => typeof value === 'number' && Number.isFinite(value)
const num = value => (value === null || value === undefined || value === '' ? null : (Number.isFinite(Number(value)) ? Number(value) : null))

/** The series of an answer: the ones that are actuals, the ones that are goals, and the labels. Never throws. */
export function readAnswer(answer) {
  const table = answer?.table
  const labels = Array.isArray(table?.labels) ? table.labels.map(String) : []
  const series = Array.isArray(table?.series) ? table.series.filter(s => s && Array.isArray(s.values)) : []
  const map = s => ({ name: String(s.name ?? ''), values: s.values.map(num), role: s.role === 'goal' ? 'goal' : 'actual' })
  const all = series.map(map)
  return { labels, all, actuals: all.filter(s => s.role === 'actual'), goals: all.filter(s => s.role === 'goal'), byUnit: answer?.meta?.by === 'unit' }
}

/** The index of the last week that has a number in `values` (-1 when none). */
export function lastIndex(values, before = values.length) {
  for (let i = Math.min(before, values.length) - 1; i >= 0; i--) if (isNumber(values[i])) return i
  return -1
}

/** 0.5 -> "50.0%". `digits` after the point. Empty text when there is no number. */
export function percentText(ratio, digits = 1) {
  return isNumber(ratio) ? `${(ratio * 100).toFixed(digits)}%` : ''
}

/** A whole number written for the deck's language (1,234 / 1.234). Empty text when there is no number. */
export function numberText(value, locale) {
  if (!isNumber(value)) return ''
  try { return new Intl.NumberFormat(locale || undefined, { maximumFractionDigits: 1 }).format(value) }
  catch { return String(value) }
}

/**
 * A key-number card against a goal (`mode: 'goal'`): the latest week's actual, the week before it ("Last"), the goal
 * set the week before for the latest week, and how far the actual is (0..1+) toward that goal.
 * With no goal (or 0) the ratio is null and the card shows "N/A", like the PDF's Baptisms of a zone without a goal.
 */
export function goalCard(answer) {
  const { actuals, goals } = readAnswer(answer)
  const actual = actuals[0]
  if (!actual) return { ready: false }
  const at = lastIndex(actual.values)
  if (at < 0) return { ready: false }
  const value = actual.values[at]
  const lastAt = lastIndex(actual.values, at)
  const goalRaw = goals[0]?.values[at]
  const goal = isNumber(goalRaw) && goalRaw > 0 ? goalRaw : null
  return { ready: true, value, last: lastAt >= 0 ? actual.values[lastAt] : null, goal, ratio: goal ? value / goal : null }
}

/**
 * A card that shows a share (`mode: 'share'`): the first number is the whole, the second the part of it, e.g. new
 * members and those at church. The ratio is part / whole; `last` is the whole's week before, as a badge.
 */
export function shareCard(answer) {
  const { actuals } = readAnswer(answer)
  const whole = actuals[0], part = actuals[1]
  if (!whole || !part) return { ready: false }
  const at = lastIndex(whole.values)
  if (at < 0) return { ready: false }
  const w = whole.values[at], p = part.values[at]
  const lastAt = lastIndex(whole.values, at)
  const lastPart = lastAt >= 0 ? part.values[lastAt] : null
  const lastWhole = lastAt >= 0 ? whole.values[lastAt] : null
  return {
    ready: true, value: w, part: isNumber(p) ? p : null,
    last: lastAt >= 0 ? lastWhole : null,
    ratio: isNumber(p) && w > 0 ? p / w : null,
    lastRatio: isNumber(lastPart) && isNumber(lastWhole) && lastWhole > 0 ? lastPart / lastWhole : null,
  }
}

/** The ISO Sunday key of a week (YYYY-MM-DD) as a Date at local noon, or null. */
export function weekDate(label) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(label ?? ''))
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12) : null
}

/** The start of the period (`month`, `quarter` or `year`) that `now` is in, as year and month index. */
export function periodStart(now, period) {
  const y = now.getFullYear(), m = now.getMonth()
  if (period === 'year') return { year: y, month: 0 }
  if (period === 'quarter') return { year: y, month: Math.floor(m / 3) * 3 }
  return { year: y, month: m }
}

/** The period before the one that starts at `start`. */
export function previousPeriod(start, period) {
  const step = period === 'year' ? 12 : period === 'quarter' ? 3 : 1
  const index = start.year * 12 + start.month - step
  return { year: Math.floor(index / 12), month: ((index % 12) + 12) % 12 }
}

function inPeriod(date, start, period) {
  if (!date) return false
  const step = period === 'year' ? 12 : period === 'quarter' ? 3 : 1
  const index = date.getFullYear() * 12 + date.getMonth()
  const from = start.year * 12 + start.month
  return index >= from && index < from + step
}

/**
 * A card for a period (`mode: 'period'`): the sum of the first number over the weeks that fall in this month,
 * quarter or year (`period`), the sum of the period before it ("Last"), and the ratio to `target` (a number typed in
 * the slide, because the mission's quarter goal is not stored in the portal).
 */
export function periodCard(answer, { period = 'month', target = null, now = new Date() } = {}) {
  const { labels, actuals } = readAnswer(answer)
  const actual = actuals[0]
  if (!actual) return { ready: false }
  const here = periodStart(now, period), before = previousPeriod(here, period)
  let sum = 0, previous = 0, seen = false
  labels.forEach((label, i) => {
    const v = actual.values[i], date = weekDate(label)
    if (!isNumber(v)) return
    if (inPeriod(date, here, period)) { sum += v; seen = true }
    else if (inPeriod(date, before, period)) previous += v
  })
  const goal = isNumber(Number(target)) && Number(target) > 0 ? Number(target) : null
  return { ready: true, value: seen ? sum : 0, last: previous, goal, ratio: goal ? (seen ? sum : 0) / goal : null }
}

/** How far through the year `now` is, 0..1 ("78 % of the year is done"). */
export function yearProgress(now = new Date()) {
  const start = new Date(now.getFullYear(), 0, 1), end = new Date(now.getFullYear() + 1, 0, 1)
  return Math.min(1, Math.max(0, (now - start) / (end - start)))
}

/**
 * A gauge: what the arc, the middle number and the small change under it show.
 *   mode 'value'   the latest week of the first number against `max` (First Time First Week Attendance: 38 of 100),
 *                  with the change from the week before;
 *   mode 'ratio'   the second number as a share of the first (% with Member), with the change in points from the week
 *                  before, and a tick at `target`;
 *   mode 'year'    how much of the year has passed;
 *   mode 'manual'  `value` (and `change`) typed in the slide, the way a rate with no data in the portal is shown.
 * `ratio` is what the arc fills (0..1).
 */
export function gaugeModel(answer, { mode = 'value', max = 100, target = null, value = null, change = null, now = new Date() } = {}) {
  if (mode === 'year') {
    const ratio = yearProgress(now)
    return { ready: true, ratio, display: percentText(ratio, 0), change: null, tick: null, min: 0, max: 1 }
  }
  if (mode === 'manual') {
    const v = num(value)
    if (v === null) return { ready: false }
    const top = num(max) || 100
    const ratio = Math.max(0, Math.min(1, v / top))
    const isPercent = top <= 1
    return { ready: true, ratio, display: isPercent ? percentText(v, 0) : String(v), change: num(change), tick: num(target), min: 0, max: top, percent: isPercent }
  }
  if (mode === 'ratio') {
    const { actuals } = readAnswer(answer)
    const whole = actuals[0], part = actuals[1]
    if (!whole || !part) return { ready: false }
    const at = lastIndex(whole.values)
    if (at < 0 || !isNumber(part.values[at]) || !(whole.values[at] > 0)) return { ready: false }
    const ratio = part.values[at] / whole.values[at]
    const before = lastIndex(whole.values, at)
    const lastRatio = before >= 0 && isNumber(part.values[before]) && whole.values[before] > 0 ? part.values[before] / whole.values[before] : null
    return { ready: true, ratio: Math.max(0, Math.min(1, ratio)), display: percentText(ratio, 0), change: lastRatio === null ? null : (ratio - lastRatio) * 100, changeIsPoints: true, tick: num(target), min: 0, max: 1, percent: true }
  }
  const { actuals } = readAnswer(answer)
  const actual = actuals[0]
  if (!actual) return { ready: false }
  const at = lastIndex(actual.values)
  if (at < 0) return { ready: false }
  const v = actual.values[at]
  const before = lastIndex(actual.values, at)
  const top = num(max) || 100
  return { ready: true, ratio: Math.max(0, Math.min(1, v / top)), display: String(v), change: before >= 0 ? v - actual.values[before] : null, tick: num(target), min: 0, max: top }
}

/**
 * Rows of a table by zone, area or other unit: [{ name, cells: [number|null...], ratio }]. `columns` says which series
 * (by position) each column shows; `ratio` is series[b] / series[a] when `ratioOf` is [a, b] (the share at church).
 * Sorted by the first column, largest first, and cut to `top` rows.
 */
export function unitRows(answer, { columns = null, ratioOf = [0, 1], top = 6 } = {}) {
  const { labels, actuals } = readAnswer(answer)
  if (!columns) columns = actuals.map((_, i) => i)
  const rows = labels.map((name, i) => {
    const cells = columns.map(c => actuals[c]?.values[i] ?? null)
    const whole = actuals[ratioOf[0]]?.values[i], part = actuals[ratioOf[1]]?.values[i]
    return { name, cells, ratio: isNumber(whole) && isNumber(part) && whole > 0 ? part / whole : null }
  }).filter(row => row.cells.some(isNumber))
  rows.sort((a, b) => (b.cells[0] ?? -Infinity) - (a.cells[0] ?? -Infinity) || a.name.localeCompare(b.name))
  return top > 0 ? rows.slice(0, top) : rows
}

/**
 * Two boxes beside a chart ("Actual" and "Goal"): the sum of the last `weeks` weeks of the first number and of the
 * goal series (or `goalFrom` series). With no goal series the goal is null.
 */
export function pairSums(answer, { weeks = 4 } = {}) {
  const { actuals, goals } = readAnswer(answer)
  const actual = actuals[0]
  if (!actual) return { ready: false }
  const sum = (values) => {
    const tail = values.slice(-Math.max(1, weeks)).filter(isNumber)
    return tail.length ? tail.reduce((a, b) => a + b, 0) : null
  }
  const a = sum(actual.values)
  const g = goals[0] ? sum(goals[0].values) : null
  return { ready: a !== null, actual: a, goal: g }
}

/** The ratio-to-goal tone of a bar: red under half, amber under 0.8 of the goal, otherwise as the card's own colour. */
export function toneOf(ratio) {
  if (!isNumber(ratio)) return 'none'
  if (ratio < 0.5) return 'low'
  if (ratio < 0.8) return 'mid'
  return 'ok'
}

/** How many weeks of the year have started by `now`, counting the week of 1 January: the `weeks` of a year-to-date chart. */
export function weeksSinceYearStart(now = new Date()) {
  const start = new Date(now.getFullYear(), 0, 1)
  return Math.min(104, Math.max(1, Math.ceil((now - start) / 86400000 / 7) + 1))
}
