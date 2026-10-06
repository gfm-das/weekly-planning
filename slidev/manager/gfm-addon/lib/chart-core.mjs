// The chart engine behind <MissionChart> and <MissionKpiChart>: reading tables,
// trend lines and the ECharts option for every chart type.
//
// Pure JavaScript with no Vue, Slidev or DOM imports, so the same file runs in
// a slide (through charts.ts), in plain Node for the unit tests
// (slidev/tests/chart-core.test.mjs), in the manager's chart builder and in the
// Whiteboard's chart frame (served at /_manager/chart/chart-core.mjs). The only
// outside things it touches are `ctx.ecStat` (the vendored echarts-stat, passed
// in) and the page's language (document.documentElement.lang, read only when a
// document exists). Charts written with a table plus an ECharts option are
// drawn by chart-engine.mjs, which uses the helpers here.
//
// Every new setting is off by default: a chart written before these settings
// existed gets exactly the option it got before (see the golden test).

/** @typedef {'line'|'bar'|'area'|'scatter'|'pie'|'donut'|'gauge'|'heatmap'|'radar'|'funnel'|'treemap'|'sunburst'|'boxplot'|'waterfall'|'tile'} ChartType */
/** @typedef {{ name: string, values: (number|null)[], role?: 'goal' }} ChartSeries */
/** @typedef {{ labels: string[], series: ChartSeries[], problem?: string }} ChartTable */
/** @typedef {{ dark: boolean, font: string, animate: boolean, ecStat: any, width?: number, height?: number }} ChartContext */

// Categorical order teal, orange, violet, gold, plum, green, blue, red. Checked
// with the data-viz palette validator against the slide surfaces (white and
// Slidev's dark #121212): lightness band, chroma, adjacent colour-blind and
// normal-vision separation and 3:1 contrast all pass in both modes, and the
// first three stay apart as all pairs (scatter, pie).
export const PALETTE = {
  light: ['#00869e', '#d96b2b', '#6656c9', '#b88400', '#a64f8e', '#3f8a3a', '#2a5f99', '#cf4545'],
  dark: ['#1aa3b0', '#d9722c', '#8f84e8', '#b0850f', '#c46aa9', '#52a042', '#5b8fd0', '#dd5e5e'],
}

// Text and axes: mission navy on light slides, pale ink on dark ones.
export const CHROME = {
  light: { ink: '#17394b', soft: '#3d5866', muted: '#556d7a', grid: '#e3eaee', axis: '#b8c6cd', surface: '#ffffff', track: '#e3eaee', tip: '#ffffff', tipLine: '#d5e0e5', shade: 'rgba(23,57,75,0.06)' },
  dark: { ink: '#e8f1f3', soft: '#c3d3d8', muted: '#9fb3bb', grid: '#263238', axis: '#4a5b63', surface: '#121212', track: '#263238', tip: '#1b2830', tipLine: '#34464f', shade: 'rgba(255,255,255,0.06)' },
}

// ---- numbers and tables --------------------------------------------------

function cleanNumber(value) {
  return String(value ?? '').trim().replace(/[\s'’%]/g, '').replace(/^[−–]/, '-')
}

/** 1,234 or 1.234: one mark, three digits after it, 1–3 digits before. */
function groupable(parts) {
  return parts.length === 2 && parts[1].length === 3 && /^[-+]?[1-9]\d{0,2}$/.test(parts[0])
}

const localeMarks = new Map()

/** The decimal mark of the deck's language: '.' in English, ',' in German. */
function localeDecimal() {
  const lang = locale() || 'en'
  let mark = localeMarks.get(lang)
  if (!mark) {
    let found
    try { found = new Intl.NumberFormat(lang).formatToParts(1.5).find(p => p.type === 'decimal')?.value }
    catch {}
    mark = found === ',' ? ',' : '.'
    localeMarks.set(lang, mark)
  }
  return mark
}

/**
 * The decimal mark a column uses, from the numbers that show it (12.5, 12,5,
 * 1.234,5, 1.234.567). Null when every number is whole or ambiguous (1.234).
 * @returns {'.'|','|null}
 */
export function decimalMarkOf(cells) {
  for (const cell of cells) {
    if (typeof cell === 'number') continue
    const s = cleanNumber(cell)
    const dot = s.lastIndexOf('.'), comma = s.lastIndexOf(',')
    if (dot >= 0 && comma >= 0) return dot > comma ? '.' : ','
    const mark = dot >= 0 ? '.' : comma >= 0 ? ',' : null
    if (!mark || !/\d/.test(s)) continue
    const parts = s.split(mark)
    if (parts.length > 2) return mark === '.' ? ',' : '.'
    if (!groupable(parts)) return mark
  }
  return null
}

/**
 * 12 · 12.5 · 12,5 · 1.234,5 · 1,234.5 · 1.234.567 · 45% · empty → null.
 * 1,234 and 1.234 are read with `decimal` (the column's decimal mark) or else
 * the deck's language: in English 1,234 is 1234 and 1.234 is 1.234; in German
 * it is the other way round.
 * @returns {number|null}
 */
export function toNumber(value, decimal = null) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  let s = cleanNumber(value)
  if (!s || !/\d/.test(s)) return null
  const dot = s.lastIndexOf('.'), comma = s.lastIndexOf(',')
  if (dot >= 0 && comma >= 0) {
    // Both used: the last one is the decimal mark.
    s = dot > comma ? s.replace(/,/g, '') : s.replace(/\./g, '').replace(',', '.')
  }
  else if (comma >= 0 || dot >= 0) {
    const mark = comma >= 0 ? ',' : '.'
    const parts = s.split(mark)
    const thousands = parts.length > 2 || (groupable(parts) && mark !== (decimal ?? localeDecimal()))
    s = thousands ? parts.join('') : `${parts[0]}.${parts[1]}`
  }
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

// null: columns are runs of two or more spaces (a table typed in the editor,
// whose Tab key writes spaces).
function delimiterOf(line) {
  if (line.includes('\t')) return '\t'
  const semicolons = line.split(';').length, commas = line.split(',').length
  if (semicolons > commas) return ';'
  if (commas === 1 && /\S {2,}\S/.test(line)) return null
  return ','
}

function splitRow(line, delimiter) {
  if (delimiter === null) return line.split(/ {2,}/).map(cell => cell.trim())
  const cells = []
  let cell = '', quoted = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cell += '"'; i++ }
      else if (c === '"') quoted = false
      else cell += c
    }
    else if (c === '"' && !cell.trim()) { quoted = true; cell = '' }
    else if (c === delimiter) { cells.push(cell.trim()); cell = '' }
    else cell += c
  }
  cells.push(cell.trim())
  return cells
}

function problemTable(problem) {
  return { labels: [], series: [], problem }
}

function short(text) {
  return text.length > 30 ? `${text.slice(0, 29)}…` : text
}

/** Breaks `text` into lines of about `width` characters, between words. */
export function wrapWords(text, width) {
  const lines = []
  for (const word of String(text ?? '').split(/\s+/).filter(Boolean)) {
    const last = lines.length - 1
    if (last >= 0 && lines[last].length + 1 + word.length <= width) lines[last] += ` ${word}`
    else lines.push(word)
  }
  return lines.join('\n')
}

/**
 * The cells of each line and the separator each line used, or null for no
 * lines. `perRow`: each row may use its own column separator (one row per
 * box in Studio, where a row pasted from a spreadsheet has tabs and a typed
 * one commas).
 */
function splitLines(source, perRow) {
  const lines = source.map(line => line.replace(/^ +| +$/g, '')).filter(line => line.trim())
  if (!lines.length) return null
  const head = delimiterOf(lines[0])
  const delimiters = lines.map(line => (!perRow ? head : line.includes('\t') ? '\t' : head !== '\t' ? head : delimiterOf(line)))
  const rows = lines.map((line, i) => {
    const cells = splitRow(line, delimiters[i])
    // Empty cells at the end of a row (an extra column in a paste) mean nothing.
    while (cells.length > 1 && !cells[cells.length - 1]) cells.pop()
    return cells
  })
  return { rows, delimiters }
}

/**
 * The cells of a table as text, headings first, split exactly as parseRows
 * and parseCsv split them (for charts that need words in a column, such as
 * the "to" column of a sankey or network chart). Null when there is no table.
 * @returns {string[][]|null}
 */
export function tableCells({ rows, csv } = {}) {
  let lines = null
  if (Array.isArray(rows)) lines = splitLines(rows.flatMap(row => String(row ?? '').replace(/\r\n?/g, '\n').split('\n')), true)
  const text = typeof rows === 'string' ? rows : csv
  if ((!lines || lines.rows.length < 2) && typeof text === 'string') {
    const source = text.replace(/\r\n?/g, '\n').replace(/^\s*\n|\n\s*$/g, '')
    if (source.trim()) lines = splitLines(source.includes('\n') ? source.split('\n') : source.split(';'), false)
  }
  return lines && lines.rows.length >= 2 ? lines.rows : null
}

/**
 * Rows of cells into a table: the first row holds the headings, the first
 * column the labels (x axis or slices) and every other column one series.
 * @returns {ChartTable|null}
 */
function tableFrom(source, perRow) {
  const split = splitLines(source, perRow)
  if (!split) return null
  const { rows, delimiters } = split
  const [header, ...body] = rows
  if (!body.length) return null
  // A row longer than the headings would invent a series. Usually a decimal
  // or thousands comma split a number (12,5 in a table with commas).
  const long = header.length >= 2 ? body.findIndex(r => r.length > header.length) : -1
  if (long >= 0) {
    const which = `Row “${short(body[long][0] || String(long + 1))}” has more values than there are headings.`
    if (delimiters[long + 1] === ',') return problemTable(`${which} In a table with commas, write decimals with a dot (12.5) and thousands without a separator (1234).`)
    return problemTable(perRow ? `${which} Put one table row in each box.` : which)
  }
  const width = Math.max(...rows.map(r => r.length))
  if (width < 2) return null
  const series = []
  for (let c = 1; c < width; c++) {
    const cells = body.map(r => r[c])
    const mark = decimalMarkOf(cells)
    series.push({
      name: header[c] || (width === 2 ? 'Value' : `Series ${c}`),
      values: cells.map(cell => toNumber(cell, mark)),
    })
  }
  return { labels: body.map((r, i) => r[0] || String(i + 1)), series }
}

/**
 * A pasted table (`csv`). Columns are separated by tabs (a spreadsheet paste),
 * semicolons, commas or runs of spaces; rows by line breaks. Written on one
 * line, `;` separates the rows.
 * @returns {ChartTable|null}
 */
export function parseCsv(text) {
  const source = String(text ?? '').replace(/\r\n?/g, '\n').replace(/^\s*\n|\n\s*$/g, '')
  if (!source.trim()) return null
  if (source.includes('\n')) return tableFrom(source.split('\n'), false)
  // Tabs but no line breaks: a pasted table whose rows ran together (a
  // one-line box keeps the tabs and drops the line breaks).
  if (source.includes('\t') && !source.includes(';') && source.split('\t').length > 2)
    return problemTable('The rows of this table ran together. Put each row on its own line, or ; between rows.')
  return tableFrom(source.split(';'), false)
}

/** `rows`: one table row per entry, as Studio's list editor keeps them. */
export function parseRows(rows) {
  if (typeof rows === 'string') return parseCsv(rows)
  if (!Array.isArray(rows)) return null
  return tableFrom(rows.flatMap(row => String(row ?? '').replace(/\r\n?/g, '\n').split('\n')), true)
}

/** `{ labels: [...], series: { Name: [...] } }` or rows `[{ Week: 'Aug 3', Name: 12 }]`. */
export function parseData(data) {
  const numbers = (values) => {
    const mark = decimalMarkOf(values)
    return values.map(v => toNumber(v, mark))
  }
  if (Array.isArray(data)) {
    const rows = data.filter(r => r && typeof r === 'object')
    if (!rows.length) return null
    const [labelKey, ...keys] = Object.keys(rows[0])
    if (!keys.length) return null
    return { labels: rows.map(r => String(r[labelKey] ?? '')), series: keys.map(k => ({ name: k, values: numbers(rows.map(r => r[k])) })) }
  }
  if (data && typeof data === 'object' && data.series && typeof data.series === 'object') {
    const list = (Array.isArray(data.series)
      ? data.series.map((s, i) => ({ name: String(s?.name ?? `Series ${i + 1}`), values: s?.values ?? s?.data }))
      : Object.entries(data.series).map(([name, values]) => ({ name, values })))
      .map(s => ({ name: s.name, values: Array.isArray(s.values) ? s.values : [] }))
    const length = Math.max(0, ...list.map(s => s.values.length))
    const labels = Array.isArray(data.labels) ? data.labels.map(String) : Array.from({ length }, (_, i) => String(i + 1))
    if (!labels.length || !list.length) return null
    return { labels, series: list.map(s => ({ name: s.name, values: numbers(labels.map((_, i) => s.values[i])) })) }
  }
  return null
}

/** Every chart type, the everyday ones first. */
export const CHART_TYPES = ['line', 'bar', 'area', 'scatter', 'pie', 'donut', 'gauge', 'tile', 'heatmap', 'radar', 'funnel', 'treemap', 'sunburst', 'boxplot', 'waterfall']
const CARTESIAN = ['line', 'bar', 'area', 'scatter']

/**
 * "Bar" and " bar " mean bar; anything unknown is a line chart.
 * @returns {ChartType}
 */
export function chartType(value) {
  const type = String(value || '').trim().toLowerCase()
  return CHART_TYPES.includes(type) ? type : 'line'
}

/**
 * What the chart area says instead of a chart, or '' when there is something
 * to draw.
 */
export function chartProblem(table, type) {
  if (!table) return 'Add data to show this chart.'
  if (table.problem) return table.problem
  if (!table.labels.length || !table.series.length) return 'Add data to show this chart.'
  const kind = chartType(type)
  if (['pie', 'donut', 'funnel', 'treemap', 'sunburst'].includes(kind))
    return table.series[0].values.some(v => v !== null && v > 0) ? '' : 'Add numbers above 0 to show this chart.'
  const values = ['gauge', 'waterfall', 'tile'].includes(kind) ? table.series[0].values : table.series.flatMap(s => s.values)
  return values.some(v => v !== null) ? '' : 'Add numbers to show this chart.'
}

// Numbers and dates follow the deck's language (Slidev's `htmlAttrs.lang`,
// English unless the deck sets another), so they match the words around them.
function locale() {
  return (typeof document !== 'undefined' && document.documentElement.lang) || undefined
}

export function formatNumber(value) {
  const n = typeof value === 'number' ? value : toNumber(value)
  if (n === null) return '–'
  return n.toLocaleString(locale(), { maximumFractionDigits: Math.abs(n) < 10 ? 2 : 1 })
}

function axisNumber(value) {
  return Math.abs(value) >= 10000
    ? value.toLocaleString(locale(), { notation: 'compact', maximumFractionDigits: 1 })
    : value.toLocaleString(locale())
}

export const NUMBER_FORMATS = ['auto', 'plain', 'percent', 'compact', 'decimals']

/**
 * How values (tooltips, labels) and axis numbers are written.
 * - auto: as before (up to 2 decimals below 10, 1 above; axes compact from 10,000);
 * - plain: the whole number with the language's grouping (1,234,567);
 * - percent: a % sign after the number (the table holds 45 for 45 %);
 * - compact: 1.2K, 3.4M;
 * - decimals: always `decimals` places (1 unless set).
 * `prefix` and `suffix` go around every number, e.g. "€" or " people".
 */
export function numberFormat(settings = {}) {
  const format = oneOf(settings.format, NUMBER_FORMATS, 'auto')
  const prefix = text(settings.prefix), suffix = text(settings.suffix)
  const raw = settings.decimals
  const d = raw === undefined || raw === null || raw === '' || !Number.isFinite(Number(raw)) ? null : clamp(Math.round(Number(raw)), 0, 4)
  if (format === 'auto' && !prefix && !suffix && d === null) return { value: formatNumber, axis: axisNumber }
  const fixed = (n, digits) => n.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const up = (n, digits) => n.toLocaleString(locale(), { maximumFractionDigits: digits })
  const compact = (n, digits) => n.toLocaleString(locale(), { notation: 'compact', maximumFractionDigits: digits })
  const [value, axis] = {
    auto: [n => (d === null ? formatNumber(n) : fixed(n, d)), axisNumber],
    plain: [n => up(n, d ?? 2), n => up(n, d ?? 2)],
    percent: [n => `${d === null ? up(n, 1) : fixed(n, d)}%`, n => `${up(n, 1)}%`],
    compact: [n => compact(n, d ?? 1), n => compact(n, d ?? 1)],
    decimals: [n => fixed(n, d ?? 1), n => fixed(n, d ?? 1)],
  }[format]
  return {
    value: (v) => {
      const n = typeof v === 'number' ? (Number.isFinite(v) ? v : null) : toNumber(v)
      return n === null ? '–' : `${prefix}${value(n)}${suffix}`
    },
    axis: n => `${prefix}${axis(n)}${suffix}`,
  }
}

// ---- small helpers --------------------------------------------------------------

function text(value) {
  return value === undefined || value === null ? '' : String(value)
}

/**
 * Text for a tooltip written as HTML. ECharts puts a formatter's string into
 * the page as HTML, and names come from tables and the database (zone,
 * district and area names), so every name and number in one is escaped.
 */
export function escapeHtml(value) {
  return text(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n))
}

function oneOf(value, list, fallback) {
  const v = String(value ?? '').trim().toLowerCase()
  return list.includes(v) ? v : fallback
}

/** A number setting, or null when it is empty or not a number. */
function numberSetting(value) {
  if (value === undefined || value === null || value === '' || typeof value === 'boolean') return null
  const n = typeof value === 'number' ? value : toNumber(value)
  return n === null || !Number.isFinite(n) ? null : n
}

/** A list setting: an array, or text with commas between the entries. */
function listSetting(value) {
  if (Array.isArray(value)) return value.map(v => String(v ?? '').trim())
  if (typeof value === 'string' && value.trim()) return value.split(',').map(v => v.trim())
  return []
}

function round(value) {
  return Math.round(value * 100) / 100
}

/** A round number at or above `value` (1, 2, 2.5 or 5 times a power of ten). */
export function niceCeil(value) {
  if (!(value > 0)) return 1
  const power = 10 ** Math.floor(Math.log10(value))
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find(m => m * power >= value - 1e-9) ?? 10
  return round(step * power)
}

/** `color` blended toward `toward` by `share` (0–1); hex colours only. */
export function mix(color, toward, share) {
  const hex = c => {
    const m = String(c).trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
    if (!m) return null
    const h = m[1].length === 3 ? m[1].replace(/./g, x => x + x) : m[1]
    return [0, 2, 4].map(i => Number.parseInt(h.slice(i, i + 2), 16))
  }
  const a = hex(color), b = hex(toward)
  if (!a || !b) return null
  return `#${a.map((v, i) => Math.round(v + (b[i] - v) * share).toString(16).padStart(2, '0')).join('')}`
}

// ---- trend lines ------------------------------------------------------------------

export const TREND_METHODS = ['none', 'linear', 'polynomial', 'exponential', 'logarithmic', 'moving-average']

/**
 * The trend method for a setting. Empty and "none" mean no trend line;
 * "moving average", "rolling" and "ma" mean a moving average. Any other word
 * draws a straight (linear) trend, as it always did.
 */
export function trendMethod(value) {
  const t = String(value || 'none').trim().toLowerCase().replace(/[\s_]+/g, '-')
  if (!t || t === 'none') return 'none'
  if (['moving-average', 'movingaverage', 'moving', 'ma', 'rolling', 'rolling-average', 'average'].includes(t)) return 'moving-average'
  if (t === 'log') return 'logarithmic'
  if (t === 'exp') return 'exponential'
  return TREND_METHODS.includes(t) ? t : 'linear'
}

const DASHES = { dashed: [7, 5], dotted: [2, 4], solid: 'solid' }

/** The line pattern for `trendStyle` (dashed unless solid or dotted is chosen). */
function dash(style) {
  const pattern = DASHES[oneOf(style, Object.keys(DASHES), 'dashed')]
  return Array.isArray(pattern) ? [...pattern] : pattern
}

/** The value of a fitted curve at x, from ecStat's parameters. */
function curve(method, parameter, shift) {
  if (method === 'linear') return x => parameter.gradient * x + parameter.intercept
  if (method === 'exponential') return x => parameter.coefficient * Math.exp(parameter.index * x)
  if (method === 'logarithmic') return x => (x + shift > 0 ? parameter.gradient * Math.log(x + shift) + parameter.intercept : Number.NaN)
  if (method === 'polynomial') return x => parameter.reduce((sum, a, i) => sum + a * x ** i, 0)
  return () => Number.NaN
}

/**
 * A trailing moving average over `window` points (2–52, default 3): each
 * point is the mean of itself and the points before it. The forecast holds
 * the last average.
 */
function movingAverage(points, windowSetting, future) {
  const sorted = [...points].sort((a, b) => a[0] - b[0])
  const size = clamp(Math.round(numberSetting(windowSetting) ?? 3), 2, 52)
  if (sorted.length < size) return null
  const fitted = []
  for (let i = size - 1; i < sorted.length; i++) {
    let sum = 0
    for (let j = i - size + 1; j <= i; j++) sum += sorted[j][1]
    fitted.push([sorted[i][0], sum / size])
  }
  const last = fitted[fitted.length - 1][1]
  return { label: `moving average of ${size}`, points: fitted, future: future.map(x => [x, last]) }
}

/**
 * The trend line through `points` ([x, y], y never null). `future` lists the x
 * values of forecast periods. Null when the method cannot fit these numbers
 * (exponential needs values above 0; too few points).
 */
export function fitTrend(ecStat, points, trend, degree, options = {}) {
  const method = trendMethod(trend)
  if (method === 'none' || points.length < 2) return null
  const future = options.future ?? []
  if (method === 'moving-average') return movingAverage(points, options.window, future)
  let kind = method
  const order = Math.min(6, Math.max(2, Math.round(Number(degree) || 2)), points.length - 1)
  if (kind === 'polynomial' && order < 2) kind = 'linear'
  if (kind === 'exponential' && points.some(p => p[1] <= 0)) return null
  // A logarithm needs x above 0: category positions (0, 1, 2 …) are moved up by one.
  const shift = kind === 'logarithmic' ? (options.shift ?? 0) : 0
  if (kind === 'logarithmic' && points.some(p => p[0] + shift <= 0)) return null
  try {
    const input = shift ? points.map(([x, y]) => [x + shift, y]) : points
    const result = ecStat.regression(kind, input, order)
    const fitted = ((result?.points ?? [])).map(p => (shift ? [p[0] - shift, p[1]] : p))
    if (!fitted.length || fitted.some(p => !Number.isFinite(p[1]))) return null
    const at = curve(kind, result.parameter, shift)
    return {
      label: kind === 'linear' ? 'linear' : kind === 'polynomial' ? `polynomial, degree ${order}` : kind,
      points: fitted,
      future: future.map(x => [x, at(x)]).filter(p => Number.isFinite(p[1])),
    }
  }
  catch {
    return null
  }
}

/**
 * Labels for `count` periods after `labels`: numbers and ISO dates carry on
 * with the same step, anything else is "+1", "+2" ….
 */
export function futureLabels(labels, count) {
  if (!(count > 0)) return []
  const n = labels.length
  const iso = /^\d{4}-\d{2}-\d{2}$/
  if (n >= 2 && labels.slice(-2).every(l => iso.test(l))) {
    const [a, b] = labels.slice(-2).map(l => Date.parse(`${l}T00:00:00Z`))
    const step = b - a
    if (step > 0) return Array.from({ length: count }, (_, i) => new Date(b + step * (i + 1)).toISOString().slice(0, 10))
  }
  const mark = decimalMarkOf(labels)
  const numbers = labels.map(l => toNumber(l, mark))
  if (n >= 2 && numbers.every(v => v !== null)) {
    const step = numbers[n - 1] - numbers[n - 2]
    if (step !== 0) return Array.from({ length: count }, (_, i) => String(round(numbers[n - 1] + step * (i + 1))))
  }
  return Array.from({ length: count }, (_, i) => `+${i + 1}`)
}

// ---- the advanced override (`option`) ------------------------------------------------

const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype'])

function isPlain(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const proto = Object.getPrototypeOf(value)
  return proto === Object.prototype || proto === null
}

/**
 * Checks the advanced `option` setting: an object (or its JSON text) of ECharts
 * settings that is merged over the chart last. Answers { value, problem }:
 * value is a clean copy (no __proto__/constructor keys, at most 12 levels
 * and `limit` entries, 2000 unless given) or null, problem a sentence for the
 * writer or ''.
 */
export function readOverride(option, limit = 2000) {
  if (option === undefined || option === null || option === '') return { value: null, problem: '' }
  let value = option
  if (typeof option === 'string') {
    if (!option.trim()) return { value: null, problem: '' }
    try { value = JSON.parse(option) }
    catch { return { value: null, problem: 'The advanced chart settings are not valid JSON. Check the quotes and commas.' } }
  }
  if (!isPlain(value)) return { value: null, problem: 'The advanced chart settings must be a list of settings in { }, for example {"yAxis": {"min": 0}}.' }
  let entries = 0
  const copy = (v, depth) => {
    if (depth > 12) throw new Error('The advanced chart settings are nested too deeply.')
    if (Array.isArray(v)) return v.map(x => copy(x, depth + 1))
    if (isPlain(v)) {
      const out = {}
      for (const [k, x] of Object.entries(v)) {
        if (UNSAFE_KEYS.has(k)) continue
        if (++entries > limit) throw new Error('The advanced chart settings are too long.')
        out[k] = copy(x, depth + 1)
      }
      return out
    }
    if (v === null || ['string', 'number', 'boolean', 'function'].includes(typeof v)) return v
    return undefined
  }
  try { return { value: copy(value, 0), problem: '' } }
  catch (error) { return { value: null, problem: error.message } }
}

/**
 * Deep-merges `override` into `base` (neither is changed). Objects merge key
 * by key; a list of objects merges item by item (so `series: [{ smooth: true }]`
 * changes the first series); an object given for a list applies to every item
 * (`xAxis: {…}` for small multiples); `null` removes a setting; anything else
 * replaces.
 */
export function mergeOption(base, override) {
  if (!isPlain(override)) return base
  const out = { ...base }
  for (const [key, value] of Object.entries(override)) {
    if (UNSAFE_KEYS.has(key)) continue
    const current = out[key]
    if (value === null) delete out[key]
    else if (isPlain(value) && isPlain(current)) out[key] = mergeOption(current, value)
    else if (isPlain(value) && Array.isArray(current)) out[key] = current.map(item => (isPlain(item) ? mergeOption(item, value) : item))
    else if (Array.isArray(value) && Array.isArray(current) && value.some(isPlain) && current.some(isPlain))
      out[key] = [...current.map((item, i) => (isPlain(item) && isPlain(value[i]) ? mergeOption(item, value[i]) : item)), ...value.slice(current.length)]
    else out[key] = value
  }
  return out
}

// ---- options ----------------------------------------------------------------

function paletteFor(settings, dark) {
  const custom = Array.isArray(settings.colors) ? settings.colors : String(settings.colors ?? '').split(',')
  const chosen = custom.map(c => String(c).trim()).filter(Boolean)
  return chosen.length ? chosen : PALETTE[dark ? 'dark' : 'light']
}

/**
 * The ECharts option for a table and the chart's settings, or null when
 * there is nothing to draw. See README "Charts in slides" for every setting.
 * @param {ChartTable|null} table
 * @param {Record<string, any>} given
 * @param {ChartContext} ctx
 */
export function buildOption(table, given, ctx) {
  if (!table || chartProblem(table, given.type)) return null
  const settings = {
    ...given,
    type: chartType(given.type),
    trend: String(given.trend || 'none').trim().toLowerCase(),
  }
  const chrome = CHROME[ctx.dark ? 'dark' : 'light']
  const colors = paletteFor(settings, ctx.dark)
  const title = String(settings.title ?? '').trim()
  const fmt = numberFormat(settings)
  const base = {
    animation: ctx.animate,
    animationDuration: 500,
    color: colors,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: ctx.font, color: chrome.ink },
    title: title ? { text: title, left: 0, top: 0, textStyle: { color: chrome.ink, fontSize: 18, fontWeight: 600, fontFamily: ctx.font } } : undefined,
    tooltip: {
      confine: true,
      backgroundColor: chrome.tip,
      borderColor: chrome.tipLine,
      borderWidth: 1,
      textStyle: { color: chrome.ink, fontSize: 13, fontFamily: ctx.font },
      valueFormatter: fmt.value,
    },
  }
  const type = settings.type
  const parts = { base, table: withGoal(table, settings.goal), settings, chrome, colors, title, ctx, fmt }
  let option
  if (type === 'pie' || type === 'donut') option = pieOption(parts)
  else if (type === 'gauge') option = gaugeOption(parts)
  else if (type === 'tile') option = tileOption(parts)
  else if (type === 'heatmap') option = heatmapOption(parts)
  else if (type === 'radar') option = radarOption(parts)
  else if (type === 'funnel') option = funnelOption(parts)
  else if (type === 'treemap' || type === 'sunburst') option = hierarchyOption(parts)
  else if (type === 'boxplot') option = boxplotOption(parts)
  else if (type === 'waterfall') option = waterfallOption(parts)
  else if (settings.multiples && table.series.filter(s => s.role !== 'goal').length > 1) option = multiplesOption(parts)
  else option = cartesianOption(parts)
  if (!option) return null
  const override = readOverride(settings.option)
  return override.value ? mergeOption(option, override.value) : option
}

/** `goal`: the heading of the column to draw as the goal line (any capitalisation). */
function withGoal(table, goal) {
  const wanted = text(goal).trim().toLowerCase()
  if (!wanted || !table.series.some(s => s.name.trim().toLowerCase() === wanted)) return table
  return { ...table, series: table.series.map(s => (s.name.trim().toLowerCase() === wanted ? { ...s, role: 'goal' } : s)) }
}

const TYPE_WORDS = {
  line: 'Line chart', bar: 'Bar chart', area: 'Area chart', scatter: 'Scatter chart', pie: 'Pie chart', donut: 'Donut chart', gauge: 'Gauge',
  tile: 'Key number', heatmap: 'Heat map', radar: 'Radar chart', funnel: 'Funnel chart', treemap: 'Tree map', sunburst: 'Sunburst chart', boxplot: 'Box plot', waterfall: 'Waterfall chart',
}

// What a screen reader says for the chart. ECharts puts it on the chart's
// element as its aria-label (its own wording reads "The 0 series is…").
function spoken(type, title, parts) {
  const description = [`${TYPE_WORDS[type]}${title ? `: ${title}` : ''}.`, ...parts.filter(Boolean)].join(' ')
  return { enabled: true, label: { description } }
}

function describeSeries(labels, s, say = formatNumber) {
  const points = labels.map((label, i) => [label, s.values[i]]).filter(p => p[1] !== null && p[1] !== undefined)
  if (!points.length) return ''
  if (points.length <= 16) return `${s.name}: ${points.map(([label, value]) => `${label}: ${say(value)}`).join(', ')}.`
  const values = points.map(p => p[1])
  return `${s.name}: ${points.length} values from ${points[0][0]} to ${points[points.length - 1][0]}, lowest ${say(Math.min(...values))}, highest ${say(Math.max(...values))}, last ${say(values[values.length - 1])}.`
}

const LEGENDS = ['auto', 'top', 'bottom', 'right', 'none']
const VALUE_POSITIONS = ['auto', 'top', 'inside', 'bottom']

/**
 * The legend and the room it takes. `auto` shows it at the top-left when
 * there is more than one entry, as before.
 */
function legendFor(where, entries, chrome, title, data) {
  const show = where === 'none' ? false : where === 'auto' ? entries > 1 : entries > 0
  if (!show) return { legend: undefined, top: 0, bottom: 0, right: null }
  const common = { type: 'scroll', itemWidth: 24, itemHeight: 10, itemGap: 18, textStyle: { color: chrome.soft, fontSize: 13 }, pageTextStyle: { color: chrome.muted }, data }
  if (where === 'bottom') return { legend: { ...common, bottom: 0, left: 'center' }, top: 0, bottom: 28, right: null }
  if (where === 'right') return { legend: { ...common, orient: 'vertical', right: 0, top: 'middle', itemGap: 12 }, top: 0, bottom: 0, right: '24%' }
  return { legend: { ...common, top: title ? 34 : 0, left: 0 }, top: 28, bottom: 0, right: null }
}

function labelFor(settings, chrome, fmt, kind, horizontal) {
  if (!settings.showValues) return { show: false }
  const where = oneOf(settings.valuePosition, VALUE_POSITIONS, 'auto')
  const position = horizontal
    ? { auto: 'right', top: 'right', inside: 'inside', bottom: 'insideLeft' }[where]
    : kind === 'bar'
      ? { auto: 'top', top: 'top', inside: 'inside', bottom: 'insideBottom' }[where]
      : { auto: 'top', top: 'top', inside: 'right', bottom: 'bottom' }[where]
  return { show: true, position, color: where === 'inside' && kind === 'bar' ? '#ffffff' : chrome.soft, fontSize: 12, formatter: p => fmt.value(Array.isArray(p.value) ? p.value[horizontal ? 0 : 1] : p.value) }
}

/**
 * The data lines, bars or points of one table column, plus its trend line.
 * Shared by the ordinary chart and small multiples.
 */
function columnSeries(s, index, env) {
  const { settings, chrome, colors, fmt, ctx, xs, allXs, numericX, type, labelsCount, horizontal, many, stack, axes } = env
  const color = colors[index % colors.length]
  const pad = allXs.length - xs.length
  const data = numericX ? xs.map((x, i) => [x, s.values[i]]) : (pad > 0 ? [...s.values, ...Array(pad).fill(null)] : s.values)
  const out = []
  if (s.role === 'goal') {
    const goal = text(settings.goalColor).trim() || color
    out.push({
      type: 'line', name: s.name, data, color: goal, z: 3,
      symbol: 'rect', symbolSize: 7, showSymbol: labelsCount <= 40,
      lineStyle: { width: 2, color: goal }, itemStyle: { color: goal, borderColor: chrome.surface, borderWidth: 1 },
      label: labelFor(settings, chrome, fmt, 'line', false),
      ...axes,
    })
    return { series: out, trend: null }
  }
  const types = listSetting(settings.seriesTypes)
  const own = CARTESIAN.includes(String(types[index] || '').toLowerCase()) ? String(types[index]).toLowerCase() : type
  if (own === 'bar') {
    out.push({
      type: 'bar', name: s.name, data, color, barMaxWidth: 24, barGap: '15%',
      itemStyle: { color, borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] }, label: labelFor(settings, chrome, fmt, 'bar', horizontal),
      ...(stack ? { stack: 'total' } : {}),
      ...axes,
    })
    if (stack) out[0].itemStyle.borderRadius = 0
  }
  else if (own === 'scatter') {
    out.push({
      type: 'scatter', name: s.name, data, color, symbolSize: 11,
      itemStyle: { color, borderColor: chrome.surface, borderWidth: 2 }, label: labelFor(settings, chrome, fmt, 'scatter', false),
      ...axes,
    })
  }
  else {
    out.push({
      type: 'line', name: s.name, data, color, z: 4,
      symbol: 'circle', symbolSize: 8, showSymbol: labelsCount <= 30,
      lineStyle: { width: 2, color }, itemStyle: { color, borderColor: chrome.surface, borderWidth: 2 },
      areaStyle: own === 'area' ? { color, opacity: 0.12 } : undefined,
      emphasis: many ? { focus: 'series' } : undefined,
      label: labelFor(settings, chrome, fmt, 'line', false),
      ...(settings.smooth ? { smooth: true } : {}),
      ...(stack ? { stack: 'total' } : {}),
      ...axes,
    })
  }
  const reference = referenceLines(env, s, color, index)
  if (reference) out[0].markLine = reference
  if (stack) return { series: out, trend: null }
  const trend = trendSeries(s, color, env)
  return { series: out, trend }
}

/** Target and average lines on a data series (`target` only on the first one). */
function referenceLines(env, s, color, index) {
  const { settings, chrome, fmt, horizontal, firstMain } = env
  const data = []
  const target = numberSetting(settings.target)
  const axis = horizontal ? 'xAxis' : 'yAxis'
  if (target !== null && index === firstMain) {
    const c = text(settings.targetColor).trim() || chrome.soft
    data.push({
      [axis]: target, name: text(settings.targetLabel).trim() || 'Target',
      lineStyle: { color: c, width: 1.5, type: 'solid' },
      label: { color: c, formatter: `${text(settings.targetLabel).trim() || 'Target'} ${fmt.value(target)}` },
    })
  }
  if (settings.average) {
    const c = text(settings.averageColor).trim() || color
    // With several series, every other average is labelled at the start of
    // its line, so neighbouring labels do not sit on top of each other.
    const atStart = env.many && (index - firstMain) % 2 === 1
    data.push({
      type: 'average', name: 'Average',
      lineStyle: { color: c, width: 1.5, type: [2, 4] },
      label: { color: c, formatter: p => `${env.many ? `${s.name} average` : 'Average'} ${fmt.value(p.value)}`, ...(atStart ? { position: 'insideStartTop' } : {}) },
    })
  }
  if (!data.length) return null
  return { silent: true, symbol: 'none', label: { position: 'insideEndTop', fontSize: 12 }, data }
}

function trendSeries(s, color, env) {
  const { settings, ctx, xs, futureXs, numericX, many, axes, fmt } = env
  const points = xs.map((x, i) => [x, s.values[i]]).filter(p => p[1] !== null)
  const fit = fitTrend(ctx.ecStat, points, settings.trend, settings.degree, { window: settings.window, future: futureXs, shift: numericX ? 0 : 1 })
  if (!fit) return null
  const byX = new Map(fit.points.map(p => [p[0], round(p[1])]))
  for (const [x, y] of fit.future) byX.set(x, round(y))
  const custom = text(settings.trendLabel).trim()
  const name = custom
    ? (many ? `${s.name} – ${custom}` : custom)
    : (many ? `${s.name} trend (${fit.label})` : `Trend (${fit.label})`)
  const ends = [...fit.points].sort((a, b) => a[0] - b[0])
  const [from, to] = [round(ends[0][1]), round(ends[ends.length - 1][1])]
  const say = fmt.value
  const words = [`${name}: ${to > from ? 'rising' : to < from ? 'falling' : 'level'} from ${say(from)} to ${say(to)}.`]
  if (fit.future.length) words.push(`Forecast for ${fit.future.length} more ${fit.future.length === 1 ? 'period' : 'periods'}: ${say(round(fit.future[fit.future.length - 1][1]))}.`)
  const tint = text(settings.trendColor).trim() || color
  const width = numberSetting(settings.trendWidth)
  const series = {
    type: 'line',
    name,
    data: numericX ? [...fit.points, ...fit.future].sort((a, b) => a[0] - b[0]).map(p => [p[0], round(p[1])]) : env.allXs.map(x => byX.get(x) ?? null),
    color: tint, z: 5, symbol: 'none', showSymbol: false, connectNulls: true,
    smooth: fit.label !== 'linear',
    lineStyle: { width: width === null ? 2 : clamp(width, 0.5, 8), type: dash(settings.trendStyle), color: tint, opacity: 0.9 },
    itemStyle: { color: tint },
    emphasis: { disabled: true },
    ...axes,
  }
  return { series, words, future: fit.future.length }
}

/** The shaded "Forecast" band after the last real period. */
function forecastArea(env, count) {
  const { chrome, numericX, xs, futureXs, horizontal } = env
  if (!count || !futureXs.length) return undefined
  const axis = horizontal ? 'yAxis' : 'xAxis'
  const from = numericX ? xs[xs.length - 1] : xs.length - 1
  const to = numericX ? futureXs[futureXs.length - 1] : xs.length + futureXs.length - 1
  return {
    silent: true,
    itemStyle: { color: chrome.shade },
    label: { show: true, position: 'insideTop', color: chrome.muted, fontSize: 12, formatter: 'Forecast' },
    data: [[{ [axis]: from }, { [axis]: to }]],
  }
}

/** Positions, forecast positions and the chart type shared by the cartesian charts. */
function cartesianFrame(table, settings) {
  const type = CARTESIAN.includes(settings.type) ? settings.type : 'line'
  const labelMark = decimalMarkOf(table.labels)
  const numericX = type === 'scatter' && table.labels.every(label => toNumber(label, labelMark) !== null)
  const xs = table.labels.map((label, i) => (numericX ? toNumber(label, labelMark) : i))
  const trendOn = trendMethod(settings.trend) !== 'none'
  const count = trendOn ? clamp(Math.round(numberSetting(settings.forecast) ?? 0), 0, 52) : 0
  let futureXs = [], future = []
  if (count && numericX) {
    const sorted = [...xs].sort((a, b) => a - b)
    const step = sorted.length > 1 ? (sorted[sorted.length - 1] - sorted[0]) / (sorted.length - 1) : 1
    futureXs = Array.from({ length: count }, (_, i) => round(sorted[sorted.length - 1] + step * (i + 1)))
  }
  else if (count) {
    futureXs = Array.from({ length: count }, (_, i) => xs.length + i)
    future = Array.isArray(settings.futureLabels) && settings.futureLabels.length >= count ? settings.futureLabels.slice(0, count).map(String) : futureLabels(table.labels, count)
  }
  return { type, numericX, xs, futureXs, allXs: [...xs, ...(numericX ? [] : futureXs)], labels: [...table.labels, ...future] }
}

function cartesianOption({ base, table, settings, chrome, colors, title, ctx, fmt }) {
  const frame = cartesianFrame(table, settings)
  const { type, numericX } = frame
  const main = table.series.filter(s => s.role !== 'goal')
  const types = listSetting(settings.seriesTypes).map(t => t.toLowerCase())
  const anyBar = type === 'bar' || types.some((t, i) => t === 'bar' && table.series[i] && table.series[i].role !== 'goal')
  const horizontal = !!settings.horizontal && type === 'bar' && !numericX
  const stack = !!settings.stack && type !== 'scatter'
  const env = {
    settings, chrome, colors, fmt, ctx, ...frame, labelsCount: table.labels.length, horizontal,
    many: main.length > 1, stack, axes: {}, firstMain: table.series.findIndex(s => s.role !== 'goal'),
  }
  const { all, trendWords } = cartesianSeries(table, main, frame, env)
  const legendWhere = oneOf(settings.legend, LEGENDS, 'auto')
  // Trend keys are the dashed line alone; other keys drop the marker's
  // surface ring, which would otherwise cut a solid key into dashes.
  const legendData = all.map(s => ({ name: s.name, itemStyle: s.symbol === 'none' ? { opacity: 0 } : { borderWidth: 0 } }))
  const legend = legendFor(legendWhere, all.length, chrome, title, legendData)
  const zoom = !!settings.dataZoom && ctx.animate !== false
  const xTitle = text(settings.xTitle).trim(), yTitle = text(settings.yTitle).trim()
  const rotate = clamp(Math.round(numberSetting(settings.labelRotate) ?? 0), -90, 90)
  const top = (title ? 34 : 0) + legend.top + 14
  const categoryAxis = categoryAxisOf(frame, { settings, chrome, ctx, fmt, anyBar, horizontal, rotate, xTitle })
  const valueAxis = valueAxisOf(table, type, { settings, chrome, fmt, horizontal, yTitle })
  const option = {
    ...base,
    aria: spoken(type, title, [...table.series.map(s => describeSeries(table.labels, s, fmt.value === formatNumber ? formatNumber : fmt.value)), ...trendWords]),
    legend: legend.legend,
    tooltip: {
      ...base.tooltip,
      trigger: type === 'scatter' ? 'item' : 'axis',
      axisPointer: { type: anyBar ? 'shadow' : 'line', lineStyle: { color: chrome.axis }, shadowStyle: { color: chrome.shade } },
    },
    grid: {
      left: 4 + (yTitle ? 26 : 0), right: legend.right ?? 18, top, bottom: 4 + legend.bottom + (zoom ? 34 : 0) + (xTitle ? 24 : 0), containLabel: true,
    },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: all,
  }
  if (zoom) option.dataZoom = zoomOf(horizontal, legend, chrome)
  return option
}

// Every column's series, then the trend lines (a stacked chart gets one through the totals), the first trend
// line carrying the shaded forecast. Returns { all, trendWords } (trendWords: what the trends say, for aria).
function cartesianSeries(table, main, frame, env) {
  const { settings, chrome, stack } = env
  const series = []
  const trends = []
  const trendWords = []
  table.series.forEach((s, index) => {
    const built = columnSeries(s, index, env)
    series.push(...built.series)
    if (built.trend) {
      trends.push(built.trend.series)
      trendWords.push(...built.trend.words)
    }
  })
  // Stacked charts get one trend line through the totals.
  if (stack && trendMethod(settings.trend) !== 'none') {
    const totals = frame.xs.map((_, i) => {
      const present = main.map(s => s.values[i]).filter(v => v !== null)
      return present.length ? present.reduce((a, b) => a + b, 0) : null
    })
    const built = trendSeries({ name: main.length > 1 ? 'Total' : main[0].name, values: totals }, chrome.soft, { ...env, many: main.length > 1 })
    if (built) {
      trends.push(built.series)
      trendWords.push(...built.words)
    }
  }
  if (trends.length && frame.futureXs.length) trends[0].markArea = forecastArea(env, frame.futureXs.length)
  return { all: [...series, ...trends], trendWords }
}

// The axis of the labels (weeks, zones …): along the bottom, or down the side for sideways bars.
function categoryAxisOf(frame, { settings, chrome, ctx, fmt, anyBar, horizontal, rotate, xTitle }) {
  const { numericX } = frame
  // `labelWrap` (charts per zone, district or area): every name is shown,
  // broken between words when needed; names too long for their place (about
  // 7 px a letter) or too many are turned instead of cut.
  const wrap = !!settings.labelWrap && !numericX && !horizontal && !rotate
  const count = frame.labels.length
  const band = Math.floor(((ctx.width || 640) - 60) / Math.max(1, count))
  const longestWord = Math.max(0, ...frame.labels.map(l => Math.max(0, ...String(l).split(/\s+/).map(w => w.length))))
  const wrapped = wrap && count <= 12 && longestWord * 7 <= band - 4
  const turned = wrap && !wrapped
  return {
    type: numericX ? 'value' : 'category',
    data: numericX ? undefined : frame.labels,
    // A little room around scattered points, so none sits on an axis.
    boundaryGap: numericX ? ['6%', '6%'] : anyBar,
    scale: numericX,
    axisLine: { show: true, lineStyle: { color: chrome.axis } },
    axisTick: { show: false },
    splitLine: { show: numericX, lineStyle: { color: chrome.grid } },
    axisLabel: {
      color: chrome.muted, fontSize: 12, hideOverlap: true, formatter: numericX ? fmt.axis : undefined,
      // Line and area charts start and end on the chart's edges: keep the
      // first and last labels inside instead of cutting them in half.
      ...(!numericX && !anyBar && !rotate && !horizontal ? { alignMinLabel: 'left', alignMaxLabel: 'right' } : {}),
      ...(rotate ? { rotate } : {}),
      ...(wrapped ? { interval: 0, hideOverlap: false, width: band - 4, overflow: 'break', lineHeight: 14 } : {}),
      ...(turned ? { rotate: count <= 12 ? 30 : 45, ...(count <= 30 ? { interval: 0 } : {}) } : {}),
    },
    ...(horizontal ? { inverse: true } : {}),
    ...(xTitle ? axisTitle(xTitle, chrome, horizontal ? 'y' : 'x', rotate) : {}),
  }
}

// The axis of the numbers, with the chart's lowest and highest settings.
function valueAxisOf(table, type, { settings, chrome, fmt, horizontal, yTitle }) {
  const yMin = numberSetting(settings.yMin), yMax = numberSetting(settings.yMax)
  // A target above every value would sit outside the chart: make room for it.
  const target = numberSetting(settings.target)
  const highest = Math.max(...table.series.flatMap(s => s.values).filter(v => v !== null))
  const roomFor = target !== null && yMax === null && target > highest ? niceCeil(target * 1.05) : null
  return {
    type: 'value',
    scale: type === 'scatter',
    boundaryGap: type === 'scatter' ? ['8%', '8%'] : undefined,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: chrome.grid } },
    axisLabel: { color: chrome.muted, fontSize: 12, formatter: fmt.axis },
    ...(yMin !== null ? { min: yMin } : {}),
    ...(yMax !== null ? { max: yMax } : roomFor !== null ? { max: roomFor } : {}),
    ...(yTitle ? axisTitle(yTitle, chrome, horizontal ? 'x' : 'y', 0) : {}),
  }
}

// Zooming along the labels: with the mouse wheel and a slider under the chart.
function zoomOf(horizontal, legend, chrome) {
  const which = horizontal ? { yAxisIndex: 0 } : { xAxisIndex: 0 }
  return [
    { type: 'inside', ...which },
    { type: 'slider', ...which, height: 18, bottom: 4 + legend.bottom, borderColor: chrome.grid, fillerColor: chrome.shade, handleStyle: { color: chrome.surface, borderColor: chrome.axis }, textStyle: { color: chrome.muted, fontSize: 11 }, dataBackground: { lineStyle: { color: chrome.axis }, areaStyle: { color: chrome.shade } } },
  ]
}

function axisTitle(name, chrome, axis, rotate) {
  return {
    name, nameLocation: 'middle',
    nameGap: axis === 'x' ? 28 + (rotate ? Math.round(Math.abs(Math.sin((rotate * Math.PI) / 180)) * 24) : 0) : 44,
    nameTextStyle: { color: chrome.soft, fontSize: 13, fontWeight: 600 },
  }
}

/**
 * Small multiples: one small chart per column, side by side, on the same
 * scale so they can be compared. A goal column is drawn in every panel.
 */
function multiplesOption({ base, table, settings, chrome, colors, title, ctx, fmt }) {
  const frame = cartesianFrame(table, settings)
  const main = table.series.map((s, index) => ({ s, index })).filter(x => x.s.role !== 'goal')
  const goals = table.series.map((s, index) => ({ s, index })).filter(x => x.s.role === 'goal')
  const count = main.length
  const cols = count <= 2 ? count : count <= 4 ? 2 : 3
  const rows = Math.ceil(count / cols)
  const top0 = title ? 11 : 2
  const cellH = (98 - top0) / rows
  const cellW = 100 / cols
  const values = table.series.flatMap(s => s.values).filter(v => v !== null)
  const yMin = numberSetting(settings.yMin), yMax = numberSetting(settings.yMax)
  const high = yMax ?? niceCeil(Math.max(0, ...values))
  const low = yMin ?? Math.min(0, ...values)
  const grids = [], xAxes = [], yAxes = [], titles = title ? [base.title] : [], series = [], words = []
  main.forEach(({ s, index }, panel) => {
    const r = Math.floor(panel / cols), c = panel % cols
    grids.push({ left: `${c * cellW + 1}%`, width: `${cellW - 4}%`, top: `${top0 + r * cellH + 7}%`, height: `${cellH - 16}%`, containLabel: true })
    titles.push({ text: s.name, left: `${c * cellW + 1}%`, top: `${top0 + r * cellH}%`, textStyle: { color: chrome.soft, fontSize: 14, fontWeight: 600, fontFamily: ctx.font } })
    xAxes.push({
      gridIndex: panel, type: frame.numericX ? 'value' : 'category', data: frame.numericX ? undefined : frame.labels, boundaryGap: frame.type === 'bar',
      scale: frame.numericX, axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { show: false },
      axisLabel: {
        color: chrome.muted, fontSize: 11, hideOverlap: true, formatter: frame.numericX ? fmt.axis : undefined,
        // Panels sit side by side: keep the first and last labels inside their own panel.
        ...(!frame.numericX && frame.type !== 'bar' ? { alignMinLabel: 'left', alignMaxLabel: 'right' } : {}),
      },
      splitLine: { show: false },
    })
    yAxes.push({ gridIndex: panel, type: 'value', min: low, max: high, splitNumber: 3, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: chrome.grid } }, axisLabel: { color: chrome.muted, fontSize: 11, formatter: fmt.axis } })
    const env = {
      settings, chrome, colors, fmt, ctx, ...frame, labelsCount: table.labels.length, horizontal: false,
      many: false, stack: false, axes: { xAxisIndex: panel, yAxisIndex: panel }, firstMain: index,
    }
    const built = columnSeries(s, index, env)
    series.push(...built.series)
    if (built.trend) {
      if (frame.futureXs.length) built.trend.series.markArea = forecastArea(env, frame.futureXs.length)
      series.push(built.trend.series)
      words.push(...built.trend.words.map(w => `${s.name}: ${w}`))
    }
    for (const g of goals) series.push(...columnSeries(g.s, g.index, env).series)
  })
  return {
    ...base,
    title: titles,
    aria: spoken(frame.type, title, [`${count} small charts, one for each of: ${main.map(m => m.s.name).join(', ')}.`, ...table.series.map(s => describeSeries(table.labels, s, fmt.value)), ...words]),
    tooltip: { ...base.tooltip, trigger: frame.type === 'scatter' ? 'item' : 'axis', axisPointer: { type: frame.type === 'bar' ? 'shadow' : 'line', lineStyle: { color: chrome.axis }, shadowStyle: { color: chrome.shade } } },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series,
  }
}

function pieOption({ base, table, settings, chrome, title, fmt }) {
  const s = table.series[0]
  const data = table.labels
    .map((name, i) => ({ name, value: s.values[i] }))
    .filter(d => d.value !== null && d.value > 0)
  if (!data.length) return null
  const donut = settings.type === 'donut'
  const total = data.reduce((sum, d) => sum + d.value, 0)
  const legendWhere = oneOf(settings.legend, LEGENDS, 'auto')
  // A pie names its slices on the slices; a legend only when asked for.
  const legend = legendWhere === 'auto' || legendWhere === 'none' ? null : legendFor(legendWhere, data.length, chrome, title, undefined)
  const center = legend?.right ? ['38%', title ? '57%' : '50%'] : ['50%', title ? (legend?.top ? '60%' : '57%') : legend?.bottom ? '46%' : '50%']
  const option = {
    ...base,
    aria: spoken(settings.type, title, [`${data.map(d => `${d.name}: ${fmt.value(d.value)} (${Math.round((d.value / total) * 100)}%)`).join(', ')}.`]),
    tooltip: { ...base.tooltip, trigger: 'item' },
    series: [{
      type: 'pie', name: s.name, data,
      // Leaves room beside the pie for outside labels, even in a half-width column.
      radius: donut ? ['38%', '60%'] : [0, '60%'],
      center,
      avoidLabelOverlap: true,
      percentPrecision: 0,
      itemStyle: { borderColor: chrome.surface, borderWidth: 2, borderRadius: donut ? 4 : 2 },
      label: { color: chrome.soft, fontSize: 13, overflow: 'break', formatter: settings.showValues ? p => `${p.name}: ${fmt.value(p.value)} (${p.percent}%)` : '{b}' },
      labelLine: { lineStyle: { color: chrome.axis } },
      emphasis: { scaleSize: 4 },
    }],
  }
  if (legend?.legend) option.legend = legend.legend
  return option
}

function gaugeOption({ base, table, settings, chrome, colors, title, ctx, fmt }) {
  const s = table.series[0]
  let row = -1
  s.values.forEach((v, i) => { if (v !== null) row = i })
  if (row < 0) return null
  const value = s.values[row]
  const explicit = Number(settings.max)
  const fromData = table.series[1]?.values[row] ?? null
  const max = explicit > 0 ? explicit : fromData !== null && fromData > 0 ? fromData : 100
  const hasTarget = explicit > 0 || (fromData !== null && fromData > 0)
  const label = settings.seriesLabel || (table.labels.length > 1 || !table.labels[row] ? s.name : table.labels[row])
  const share = Math.round((value / max) * 100)
  return {
    ...base,
    aria: spoken('gauge', title, [`${label}: ${fmt.value(value)}${hasTarget ? `, ${share}% of ${fmt.value(max)}` : ''}.`]),
    tooltip: { show: false },
    series: [{
      type: 'gauge', min: 0, max,
      startAngle: 210, endAngle: -30, radius: '86%',
      center: ['50%', title ? '60%' : '55%'],
      progress: { show: true, width: 18, roundCap: true, itemStyle: { color: colors[0] } },
      axisLine: { roundCap: true, lineStyle: { width: 18, color: [[1, chrome.track]] } },
      pointer: { show: false }, anchor: { show: false },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      title: { show: true, offsetCenter: [0, '34%'], color: chrome.soft, fontSize: 14, fontFamily: ctx.font, lineHeight: 20 },
      detail: {
        offsetCenter: [0, '-4%'], valueAnimation: ctx.animate, fontSize: 40, fontWeight: 600,
        color: chrome.ink, fontFamily: ctx.font, formatter: v => fmt.value(v),
      },
      data: [{ value, name: hasTarget ? `${label}\n${share}% of ${fmt.value(max)}` : label }],
    }],
  }
}

/**
 * A key number: the latest value large, the change from the period before,
 * the share of the goal (the second column, or `target`) and a sparkline of
 * every period underneath.
 */
function tileOption({ base, table, settings, chrome, colors, title, ctx, fmt }) {
  const s = table.series.find(x => x.role !== 'goal') ?? table.series[0]
  const present = s.values.map((v, i) => (v === null ? -1 : i)).filter(i => i >= 0)
  if (!present.length) return null
  const last = present[present.length - 1], before = present.length > 1 ? present[present.length - 2] : -1
  const value = s.values[last]
  const goalSeries = table.series.find(x => x.role === 'goal') ?? table.series.find(x => x !== s)
  const goal = numberSetting(settings.target) ?? goalSeries?.values[last] ?? null
  const name = text(settings.seriesLabel).trim() || s.name
  const delta = before >= 0 ? value - s.values[before] : null
  const change = delta === null ? '' : delta === 0 ? `Same as ${table.labels[before]}` : `${delta > 0 ? '▲' : '▼'} ${fmt.value(Math.abs(delta))} from ${table.labels[before]}`
  const share = goal !== null && goal > 0 ? `${Math.round((value / goal) * 100)}% of the goal (${fmt.value(goal)})` : ''
  const h = ctx.height || 300
  const big = clamp(Math.round(h * 0.16), 28, 64)
  const top = title ? 34 : 0
  const color = colors[0]
  const titles = [
    ...(title ? [base.title] : []),
    { text: fmt.value(value), subtext: `${name}${table.labels[last] ? ` · ${table.labels[last]}` : ''}`, left: 0, top, itemGap: 6,
      textStyle: { color: chrome.ink, fontSize: big, fontWeight: 650, fontFamily: ctx.font },
      subtextStyle: { color: chrome.soft, fontSize: 14, fontFamily: ctx.font } },
    { text: [change, share].filter(Boolean).join('   ·   '), left: 0, top: top + big + 34, textStyle: { color: chrome.muted, fontSize: 13, fontWeight: 500, fontFamily: ctx.font } },
  ]
  const spark = top + big + 62
  return {
    ...base,
    title: titles,
    aria: spoken('tile', title, [`${name}: ${fmt.value(value)}${table.labels[last] ? ` in ${table.labels[last]}` : ''}.`, change ? `${change.replace(/^[▲▼] /, delta > 0 ? 'Up ' : 'Down ')}.` : '', share ? `${share}.` : '']),
    tooltip: { ...base.tooltip, trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: chrome.axis } } },
    grid: { left: 2, right: 2, top: spark, bottom: 4 },
    xAxis: { type: 'category', data: table.labels, boundaryGap: false, show: false },
    yAxis: { type: 'value', show: false, scale: true },
    series: [
      { type: 'line', name, data: s.values, color, symbol: 'none', smooth: !!settings.smooth, lineStyle: { width: 2, color }, areaStyle: { color, opacity: 0.12 }, z: 3 },
      { type: 'scatter', name, data: s.values.map((v, i) => (i === last ? v : null)), color, symbolSize: 9, itemStyle: { color, borderColor: chrome.surface, borderWidth: 2 }, tooltip: { show: false }, z: 4 },
    ],
  }
}

/** A grid of coloured cells: rows of the table across, columns down. */
function heatmapOption({ base, table, settings, chrome, colors, title, fmt }) {
  const cells = []
  table.series.forEach((s, y) => s.values.forEach((v, x) => { if (v !== null) cells.push([x, y, v]) }))
  const values = cells.map(c => c[2])
  const low = Math.min(...values), high = Math.max(...values)
  const pale = mix(colors[0], chrome.surface, 0.88) || chrome.track
  const rotate = clamp(Math.round(numberSetting(settings.labelRotate) ?? 0), -90, 90)
  return {
    ...base,
    aria: spoken('heatmap', title, [...table.series.map(s => describeSeries(table.labels, s, fmt.value))]),
    tooltip: { ...base.tooltip, trigger: 'item', formatter: p => `${escapeHtml(table.labels[p.value[0]])} · ${escapeHtml(table.series[p.value[1]]?.name)}<br><b>${escapeHtml(fmt.value(p.value[2]))}</b>` },
    grid: { left: 4, right: 18, top: (title ? 34 : 0) + 14, bottom: 46, containLabel: true },
    xAxis: { type: 'category', data: table.labels, axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { show: false }, splitArea: { show: false }, axisLabel: { color: chrome.muted, fontSize: 12, hideOverlap: true, ...(rotate ? { rotate } : {}) } },
    yAxis: { type: 'category', data: table.series.map(s => s.name), inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: chrome.soft, fontSize: 12 } },
    visualMap: {
      min: low, max: high === low ? low + 1 : high, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 140,
      text: [fmt.axis(high), fmt.axis(low)], textStyle: { color: chrome.muted, fontSize: 12 }, inRange: { color: [pale, colors[0]] },
    },
    series: [{
      type: 'heatmap', data: cells,
      label: { show: !!settings.showValues, color: chrome.ink, fontSize: 12, textBorderColor: chrome.surface, textBorderWidth: 2, formatter: p => fmt.value(p.value[2]) },
      itemStyle: { borderColor: chrome.surface, borderWidth: 2, borderRadius: 3 },
      emphasis: { itemStyle: { borderColor: chrome.ink, borderWidth: 1 } },
    }],
  }
}

/** One spoke per row, one shape per column. */
function radarOption({ base, table, settings, chrome, colors, title, fmt }) {
  const explicit = Number(settings.max)
  const indicator = table.labels.map((name, i) => {
    const top = Math.max(0, ...table.series.map(s => s.values[i] ?? 0))
    return { name, max: explicit > 0 ? explicit : niceCeil(top || 1) }
  })
  const legend = legendFor(oneOf(settings.legend, LEGENDS, 'auto'), table.series.length, chrome, title, table.series.map(s => s.name))
  const top = (title ? 34 : 0) + legend.top
  return {
    ...base,
    aria: spoken('radar', title, table.series.map(s => describeSeries(table.labels, s, fmt.value))),
    legend: legend.legend,
    tooltip: { ...base.tooltip, trigger: 'item' },
    radar: {
      indicator, radius: '56%', center: [legend.right ? '40%' : '50%', `${top ? 55 + Math.round(top / 12) : 52}%`],
      axisName: { color: chrome.soft, fontSize: 13, formatter: name => wrapWords(name, 16) }, splitNumber: 4,
      splitLine: { lineStyle: { color: chrome.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: chrome.axis } },
    },
    series: [{
      type: 'radar',
      data: table.series.map((s, i) => {
        const color = colors[i % colors.length]
        return {
          name: s.name, value: s.values.map(v => v ?? 0),
          symbol: 'circle', symbolSize: 6,
          itemStyle: { color, borderColor: chrome.surface, borderWidth: 1 }, lineStyle: { color, width: 2 }, areaStyle: { color, opacity: 0.12 },
          label: settings.showValues ? { show: true, color: chrome.soft, fontSize: 11, formatter: p => fmt.value(p.value) } : undefined,
        }
      }),
    }],
  }
}

/** Stages from top to bottom, in the table's order. */
function funnelOption({ base, table, settings, chrome, colors, title, fmt }) {
  const s = table.series[0]
  const data = table.labels.map((name, i) => ({ name, value: s.values[i] })).filter(d => d.value !== null && d.value > 0)
  if (!data.length) return null
  const first = data[0].value
  return {
    ...base,
    aria: spoken('funnel', title, [`${data.map(d => `${d.name}: ${fmt.value(d.value)}`).join(', ')}.`]),
    tooltip: { ...base.tooltip, trigger: 'item', formatter: p => `${escapeHtml(p.name)}<br><b>${escapeHtml(fmt.value(p.value))}</b> (${Math.round((p.value / first) * 100)}% of ${escapeHtml(data[0].name)})` },
    series: [{
      type: 'funnel', name: s.name, data, sort: 'none', gap: 3, minSize: '14%', left: '6%', width: '58%', top: title ? 44 : 8, bottom: 8,
      label: { show: true, position: 'right', color: chrome.soft, fontSize: 13, formatter: settings.showValues ? p => `${p.name}: ${fmt.value(p.value)}` : '{b}' },
      labelLine: { lineStyle: { color: chrome.axis } },
      itemStyle: { borderColor: chrome.surface, borderWidth: 1, color: p => colors[p.dataIndex % colors.length] },
    }],
  }
}

/**
 * Labels with levels ("North / Frankfurt 1", also > or ›) into a tree; each
 * row's first number is its size, and a level's size is the sum below it.
 */
export function treeFrom(labels, values) {
  const root = []
  labels.forEach((label, i) => {
    const value = values[i]
    if (value === null || value === undefined || !(value > 0)) return
    const path = String(label).split(/\s*[/>›]\s*/).map(p => p.trim()).filter(Boolean)
    if (!path.length) return
    let level = root
    path.forEach((name, depth) => {
      let node = level.find(n => n.name === name)
      if (!node) { node = { name }; level.push(node) }
      if (depth === path.length - 1) node.value = (node.value || 0) + value
      else { node.children ||= []; level = node.children }
    })
  })
  const total = node => {
    if (!node.children) return node.value || 0
    node.value = (node.value || 0) + node.children.reduce((sum, child) => sum + total(child), 0)
    return node.value
  }
  root.forEach(total)
  return root
}

function hierarchyOption({ base, table, settings, chrome, colors, title, fmt }) {
  const tree = treeFrom(table.labels, table.series[0].values)
  if (!tree.length) return null
  tree.forEach((node, i) => { node.itemStyle = { color: colors[i % colors.length] } })
  const deep = tree.some(n => n.children)
  const sunburst = settings.type === 'sunburst'
  const words = [`${tree.map(n => `${n.name}: ${fmt.value(n.value)}`).join(', ')}.`]
  const labelText = p => (settings.showValues ? `${p.name}\n${fmt.value(p.value)}` : p.name)
  const series = sunburst
    ? {
        type: 'sunburst', data: tree, radius: [0, '90%'], center: ['50%', title ? '56%' : '50%'], sort: null,
        itemStyle: { borderColor: chrome.surface, borderWidth: 2 },
        label: { color: '#ffffff', fontSize: 12, minAngle: 10, formatter: labelText, overflow: 'truncate' },
        emphasis: { focus: 'ancestor' },
      }
    : {
        type: 'treemap', data: tree, roam: false, nodeClick: false, breadcrumb: { show: false },
        top: title ? 40 : 2, left: 2, right: 2, bottom: 2, sort: false,
        label: { show: true, color: '#ffffff', fontSize: 13, formatter: labelText },
        upperLabel: { show: deep, height: 22, color: '#ffffff', fontSize: 12, fontWeight: 600 },
        itemStyle: { borderColor: chrome.surface, borderWidth: 2, gapWidth: 2 },
        levels: deep ? [{ itemStyle: { borderColor: chrome.surface, borderWidth: 3, gapWidth: 3 } }, { colorSaturation: [0.35, 0.6], itemStyle: { borderColorSaturation: 0.6, gapWidth: 1, borderWidth: 1 } }] : undefined,
      }
  return {
    ...base,
    aria: spoken(settings.type, title, words),
    tooltip: { ...base.tooltip, trigger: 'item', formatter: p => `${escapeHtml((p.treePathInfo ?? []).slice(1).map(x => x.name).join(' / ') || p.name)}<br><b>${escapeHtml(fmt.value(p.value))}</b>` },
    series: [series],
  }
}

/** Quartiles by linear interpolation (as spreadsheets' QUARTILE.INC). */
export function boxStats(values) {
  const sorted = values.filter(v => v !== null && v !== undefined && Number.isFinite(v)).sort((a, b) => a - b)
  if (!sorted.length) return null
  const q = p => {
    const at = (sorted.length - 1) * p, lo = Math.floor(at), hi = Math.ceil(at)
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo)
  }
  const q1 = q(0.25), median = q(0.5), q3 = q(0.75), reach = (q3 - q1) * 1.5
  const inside = sorted.filter(v => v >= q1 - reach && v <= q3 + reach)
  return { low: inside[0], q1, median, q3, high: inside[inside.length - 1], outliers: sorted.filter(v => v < q1 - reach || v > q3 + reach) }
}

/** One box per column: the spread of its values (weeks, areas …). */
function boxplotOption({ base, table, settings, chrome, colors, title, fmt }) {
  const stats = table.series.map(s => boxStats(s.values))
  const shown = table.series.map((s, i) => ({ s, i, st: stats[i] })).filter(x => x.st)
  if (!shown.length) return null
  const yMin = numberSetting(settings.yMin), yMax = numberSetting(settings.yMax)
  return {
    ...base,
    aria: spoken('boxplot', title, shown.map(({ s, st }) => `${s.name}: middle half from ${fmt.value(st.q1)} to ${fmt.value(st.q3)}, median ${fmt.value(st.median)}, range ${fmt.value(st.low)} to ${fmt.value(st.high)}${st.outliers.length ? `, ${st.outliers.length} unusual ${st.outliers.length === 1 ? 'value' : 'values'}` : ''}.`)),
    tooltip: {
      ...base.tooltip, trigger: 'item',
      formatter: (p) => {
        if (p.seriesType !== 'boxplot') return `${escapeHtml(p.name)}: ${escapeHtml(fmt.value(p.value[1]))} (unusual)`
        const [low, q1, median, q3, high] = p.data?.value ?? []
        const say = v => escapeHtml(fmt.value(v))
        return `${escapeHtml(p.name)}<br>Highest ${say(high)}<br>Upper quarter from ${say(q3)}<br><b>Median ${say(median)}</b><br>Lower quarter up to ${say(q1)}<br>Lowest ${say(low)}`
      },
    },
    grid: { left: 4, right: 18, top: (title ? 34 : 0) + 14, bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: shown.map(x => x.s.name), axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { show: false }, axisLabel: { color: chrome.muted, fontSize: 12, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: chrome.grid } }, axisLabel: { color: chrome.muted, fontSize: 12, formatter: fmt.axis }, ...(yMin !== null ? { min: yMin } : {}), ...(yMax !== null ? { max: yMax } : {}) },
    series: [
      {
        type: 'boxplot', name: 'Spread', boxWidth: [14, 56],
        data: shown.map(({ s, i, st }) => {
          const color = colors[i % colors.length]
          return { name: s.name, value: [st.low, st.q1, st.median, st.q3, st.high], itemStyle: { color: mix(color, chrome.surface, 0.8) || chrome.track, borderColor: color, borderWidth: 2 } }
        }),
      },
      {
        type: 'scatter', name: 'Unusual values', symbolSize: 8,
        data: shown.flatMap(({ s, i, st }, x) => st.outliers.map(v => ({ name: s.name, value: [x, v], itemStyle: { color: colors[i % colors.length] } }))),
      },
    ],
  }
}

/**
 * The first row is where it starts (last month's number), every other row a
 * change (+ or −) from the running total; a last "Total" bar shows where it
 * ends. Rises use the first colour, falls the second, the start and the
 * total the third. Every label is shown, over two lines when needed.
 */
function waterfallOption({ base, table, settings, chrome, colors, title, ctx, fmt }) {
  const s = table.series[0]
  const steps = table.labels.map((name, i) => ({ name, delta: s.values[i] })).filter(d => d.delta !== null)
  if (!steps.length) return null
  let run = 0
  const items = steps.map((d) => {
    const start = run
    run += d.delta
    return { name: d.name, start, end: run, delta: d.delta, total: false }
  })
  if (items.length > 1) items.push({ name: 'Total', start: 0, end: run, delta: run, total: true })
  const up = colors[0], down = colors[1 % colors.length], sum = colors[2 % colors.length]
  const showValues = !!settings.showValues
  // The first bar stands on 0: it is a level, not a change (when more follow).
  const level = i => items[i].total || (i === 0 && items.length > 1)
  // Room per bar, in characters of a 12 px label (about 7 px each).
  const perLine = Math.max(6, Math.floor((Math.floor(((ctx.width || 640) - 40) / items.length) - 4) / 7))
  const said = i => `${level(i) ? '' : items[i].delta >= 0 ? '+' : '−'}${fmt.value(Math.abs(items[i].delta))}`
  return {
    ...base,
    aria: spoken('waterfall', title, [`${steps.map((d, i) => (i === 0 && items.length > 1 ? `${d.name}: ${fmt.value(d.delta)}` : `${d.name}: ${d.delta >= 0 ? 'plus' : 'minus'} ${fmt.value(Math.abs(d.delta))}`)).join(', ')}.`, items.length > 1 ? `Total ${fmt.value(run)}.` : '']),
    tooltip: { ...base.tooltip, trigger: 'item', formatter: p => (level(p.dataIndex) ? `${escapeHtml(p.name)}<br><b>${escapeHtml(fmt.value(p.data.value[2]))}</b>` : `${escapeHtml(p.name)}<br><b>${escapeHtml(said(p.dataIndex))}</b> (now ${escapeHtml(fmt.value(p.data.value[2]))})`) },
    grid: { left: 4, right: 18, top: (title ? 34 : 0) + 14 + (showValues ? 8 : 0), bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: items.map(it => it.name), axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { show: false }, axisLabel: { color: chrome.muted, fontSize: 12, interval: 0, lineHeight: 15, formatter: name => wrapWords(name, perLine) } },
    yAxis: { type: 'value', axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: chrome.grid } }, axisLabel: { color: chrome.muted, fontSize: 12, formatter: fmt.axis } },
    series: [{
      type: 'custom', name: s.name,
      encode: { x: 0, y: [1, 2], tooltip: [3] },
      data: items.map((it, i) => ({ name: it.name, total: it.total, value: [i, it.start, it.end, it.delta], itemStyle: { color: level(i) ? sum : it.delta >= 0 ? up : down } })),
      renderItem: (params, api) => {
        const x = api.value(0)
        const a = api.coord([x, api.value(1)]), b = api.coord([x, api.value(2)])
        const width = Math.min(48, api.size([1, 0])[0] * 0.6)
        const top = Math.min(a[1], b[1]), height = Math.max(1, Math.abs(b[1] - a[1]))
        const rect = { type: 'rect', shape: { x: a[0] - width / 2, y: top, width, height, r: 3 }, style: { fill: api.visual('color') } }
        if (!showValues) return rect
        return {
          type: 'group',
          children: [rect, {
            type: 'text',
            style: { text: said(params.dataIndex), x: a[0], y: top - 4, align: 'center', verticalAlign: 'bottom', fill: chrome.soft, fontSize: 12, fontFamily: base.textStyle.fontFamily },
          }],
        }
      },
    }],
  }
}

// ---- live mission numbers ------------------------------------------------------

// The names people see. The ids stay as the weekly plans write them:
// friends_found is Preach My Gospel's "New people being taught".
export const KPI_NAMES = {
  friends_found: 'New people being taught',
  baptisms_confirmations: 'Baptisms and confirmations',
  baptismal_dates: 'Baptismal dates',
  sacrament_attendance: 'Sacrament attendance',
  members_at_lessons: 'Members at lessons',
  new_member_sacrament: 'New member sacrament attendance',
}

/**
 * The key indicator for an id (`sacrament_attendance`) or its name
 * (`Sacrament attendance`, any capitalisation); New people being taught
 * otherwise. The old name in decks written before the rename,
 * kpi="Friends found", is the id written with a space, so it still works.
 */
export function kpiId(value) {
  const text = String(value ?? '').trim()
  if (Object.hasOwn(KPI_NAMES, text)) return text
  const lower = text.toLowerCase()
  const id = lower.replace(/[\s-]+/g, '_')
  return Object.keys(KPI_NAMES).find(key => key === id || KPI_NAMES[key].toLowerCase() === lower) ?? 'friends_found'
}

export function weekLabels(weeks) {
  const dates = weeks.map(w => new Date(`${w}T00:00:00`))
  const years = new Set(dates.map(d => d.getFullYear()))
  const format = years.size > 1
    ? { day: 'numeric', month: 'short', year: '2-digit' }
    : { day: 'numeric', month: 'short' }
  return dates.map((d, i) => (Number.isNaN(d.getTime()) ? weeks[i] : d.toLocaleDateString(locale(), format)))
}

/** The Sundays after the last of `weeks` (YYYY-MM-DD), for a forecast. */
export function nextWeeks(weeks, count) {
  const last = weeks.length ? Date.parse(`${weeks[weeks.length - 1]}T00:00:00Z`) : Number.NaN
  if (!Number.isFinite(last) || !(count > 0)) return []
  return Array.from({ length: count }, (_, i) => new Date(last + (i + 1) * 7 * 86400000).toISOString().slice(0, 10))
}

/**
 * How many weeks one request for mission numbers asks for: the most any
 * chart can show, so every live chart in a deck shares one answer.
 */
export const KPI_FETCH_WEEKS = 104

/** `weeks` of a live chart: 1–104, 12 when empty or not a number. */
export function kpiWeekCount(value) {
  return Math.min(104, Math.max(1, Math.round(Number(value) || 12)))
}

/**
 * The table of a live chart: `Actual`, and `Goal` (drawn as the goal line)
 * unless `showGoal` is off. Mission totals count a goal nobody set as 0, so
 * those weeks are gaps in the goal line.
 */
export function kpiTable(list, kpi, showGoal, labels) {
  if (!list?.length) return null
  const pick = (w, field) => toNumber(w?.[kpi]?.[field])
  const actual = list.map(w => pick(w, 'actual'))
  if (actual.every(v => v === null)) return null
  const series = [{ name: 'Actual', values: actual }]
  const goals = list.map(w => pick(w, 'goal') || null)
  if (showGoal && goals.some(v => v !== null)) series.push({ name: 'Goal', values: goals, role: 'goal' })
  return { labels: labels ?? weekLabels(list.map(w => String(w.week))), series }
}

/** <MissionKpiChart> settings that are handed to the chart as they are. */
export const KPI_PASS_THROUGH = ['colors', 'goalColor', 'trendColor', 'trendWidth', 'trendStyle', 'trendLabel', 'window', 'target', 'targetLabel', 'targetColor', 'average', 'averageColor', 'legend', 'yMin', 'yMax', 'smooth', 'valuePosition', 'dataZoom', 'option']

/**
 * Table and chart settings for <MissionKpiChart>: the weeks of `list` (oldest
 * first) for one indicator, as a bar, line or area chart or a key number
 * (`chart="tile"`). A forecast is labelled with the Sundays that follow.
 */
export function kpiChart(list, props, heading) {
  const chart = String(props.chart ?? '').trim().toLowerCase()
  const type = chart === 'line' ? 'line' : chart === 'area' ? 'area' : chart === 'tile' ? 'tile' : 'bar'
  const weeks = (list ?? []).map(w => String(w.week))
  const count = trendMethod(props.trend) === 'none' ? 0 : clamp(Math.round(numberSetting(props.forecast) ?? 0), 0, 52)
  const labels = weekLabels([...weeks, ...nextWeeks(weeks, count)])
  const settings = { type, title: heading, trend: props.trend, degree: props.degree, showValues: props.showValues }
  for (const key of KPI_PASS_THROUGH) if (props[key] !== undefined) settings[key] = props[key]
  if (count) Object.assign(settings, { forecast: count, futureLabels: labels.slice(weeks.length) })
  return { table: kpiTable(list, kpiId(props.kpi), props.showGoal, labels.slice(0, weeks.length)), settings }
}

// ---- charts from the database (<MissionChart :query>) ----------------------------

// Settings of <MissionChart> that describe where the numbers come from, not how they look.
const DATA_PROPS = ['rows', 'csv', 'data', 'query']

/**
 * Table and chart settings for a database chart: `answer` is what
 * POST /api/charts/data returned ({ table: { labels, series }, meta }),
 * `props` the chart's settings. Weeks (ISO Sundays) become short dates in the
 * deck's language and a forecast is labelled with the Sundays that follow.
 * "% of goal" charts are written with a % sign and get a goal line at 100
 * unless the chart sets its own format or target.
 */
export function queryChart(answer, props = {}) {
  const meta = answer?.meta ?? {}
  const settings = {}
  for (const [key, value] of Object.entries(props)) if (!DATA_PROPS.includes(key) && value !== undefined) settings[key] = value
  settings.type = chartType(props.type)
  const raw = answer?.table
  if (!raw || !Array.isArray(raw.labels) || !Array.isArray(raw.series)) return { table: null, settings }
  const byWeek = meta.by !== 'unit'
  const weeks = byWeek ? raw.labels.map(String) : []
  const count = byWeek && CARTESIAN.includes(settings.type) && trendMethod(props.trend) !== 'none' ? clamp(Math.round(numberSetting(props.forecast) ?? 0), 0, 52) : 0
  const labels = byWeek ? weekLabels([...weeks, ...nextWeeks(weeks, count)]) : raw.labels.map(l => String(l ?? ''))
  if (count) Object.assign(settings, { forecast: count, futureLabels: labels.slice(weeks.length) })
  // One bar per zone, district or area: show every name.
  if (!byWeek) settings.labelWrap = true
  if (meta.unit === 'percent') {
    if (!props.format || props.format === 'auto') settings.format = 'percent'
    if (numberSetting(props.target) === null && CARTESIAN.includes(settings.type)) {
      settings.target = 100
      if (!text(props.targetLabel).trim() || props.targetLabel === 'Target') settings.targetLabel = 'Goal'
    }
  }
  const series = raw.series
    .filter(s => s && Array.isArray(s.values))
    .map(s => ({ name: String(s.name ?? ''), values: s.values.map(v => toNumber(v)), ...(s.role === 'goal' ? { role: 'goal' } : {}) }))
  return { table: { labels: byWeek ? labels.slice(0, weeks.length) : labels, series }, settings }
}

/** What a database chart says instead of a chart when it has no numbers to draw. */
export function queryProblem(answer) {
  const meta = answer?.meta ?? {}
  const series = answer?.table?.series ?? []
  if (meta.stewardship && !meta.units) return 'There are no numbers for your stewardship in this chart.'
  if (!series.length || !series.some(s => (s.values ?? []).some(v => v !== null && v !== undefined)))
    return meta.suppressed ? 'These numbers are too small to show. Fewer than 3 are hidden to protect privacy.' : 'No numbers for these weeks yet.'
  return ''
}
