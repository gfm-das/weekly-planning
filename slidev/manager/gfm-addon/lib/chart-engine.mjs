// The chart engine of round 6: a chart is its numbers (a table: `rows`,
// `csv`, `data`, or mission numbers from `query`) plus an ECharts option.
// The option is written as ECharts documents it; this file binds the table to
// it (a dataset, or data shaped for series that need their own), lays the
// mission look under it (colours, fonts, axes, spacing for every component)
// and turns the few things JSON cannot say into functions (number formats in
// the deck's language, trend lines, the waterfall and range drawings).
//
// Charts written with the older settings (`type`, `trend`, `goal` and forty
// more) are drawn by chart-core's buildOption exactly as before: chartView()
// decides which way a chart is drawn, and legacyToOption() turns the older
// settings into an option when the builder opens such a chart.
//
// Pure JavaScript (no Vue, Slidev or DOM), like chart-core: it runs in a slide
// (charts.ts), in the builder (/_manager/chart/chart-engine.mjs) and in Node
// for the tests (tests/chart-engine.test.mjs, which also draws every series
// type with the vendored ECharts in server-side mode).
//
// The GFM words an option may carry (everything else is plain ECharts):
//   gfm.format   {style: auto|plain|percent|compact|decimals, decimals, prefix, suffix}
//   gfm.kind     'tile' (a key number) or 'multiples' (one small chart per column)
//   gfm.goal     {column: 'Goal', ...series settings}: how goal columns are drawn
//   gfm.target   a number (the key number's goal)
//   series[i].gfm.trend {method, degree, window, forecast, color, width, style, label}
//   series[i].renderItem 'waterfall' | 'range' | 'errorbar' (custom series)
import {
  boxStats, buildOption, chartProblem, CHROME, fitTrend, futureLabels, mergeOption, mix,
  nextWeeks, niceCeil, numberFormat, PALETTE, parseCsv, parseData, parseRows, queryChart, queryProblem, readOverride,
  tableCells, toNumber, decimalMarkOf, trendMethod, treeFrom, weekLabels, wrapWords,
} from './chart-core.mjs'
import { applyCalculated } from './formula.mjs'
import { presetOf, presetOption, shapeTable } from './chart-presets.mjs'

/** Every ECharts series type a chart may use. `map` is left out: it needs a map file, and none is installed. */
export const SERIES_TYPES = ['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar', 'pie', 'funnel', 'gauge', 'radar', 'heatmap', 'tree', 'treemap', 'sunburst', 'boxplot', 'candlestick', 'graph', 'sankey', 'chord', 'themeRiver', 'parallel', 'lines', 'custom']

/** The drawings a custom series can name as its renderItem (JSON cannot hold a function). */
export const RENDERERS = ['waterfall', 'range', 'errorbar']

// Series that sit on x and y axes unless they say otherwise.
const ON_AXES = new Set(['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar', 'candlestick', 'boxplot', 'heatmap', 'custom', 'lines'])
// Series that take one column each and can repeat for the columns after them.
const ONE_COLUMN = new Set(['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar'])
const BAR_LIKE = new Set(['bar', 'pictorialBar', 'boxplot', 'candlestick', 'heatmap', 'custom'])
const MULTI = ['title', 'legend', 'grid', 'xAxis', 'yAxis', 'polar', 'angleAxis', 'radiusAxis', 'radar', 'dataZoom', 'visualMap', 'singleAxis', 'parallel', 'parallelAxis', 'calendar', 'dataset', 'series']
const POSITION_KEYS = ['left', 'right', 'top', 'bottom', 'width', 'height']
const LIMIT = 5000

function text(value) {
  return value === undefined || value === null ? '' : String(value)
}

function plain(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
}

function list(value) {
  if (value === undefined || value === null) return []
  return Array.isArray(value) ? value : [value]
}

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n))
}

function num(value) {
  if (value === undefined || value === null || value === '' || typeof value === 'boolean') return null
  const n = typeof value === 'number' ? value : toNumber(value)
  return n === null || !Number.isFinite(n) ? null : n
}

function round(value) {
  return Math.round(value * 100) / 100
}

function hasPosition(obj) {
  return plain(obj) && POSITION_KEYS.some(k => obj[k] !== undefined)
}

/** A deep copy of plain data (functions kept). */
function copy(value) {
  if (Array.isArray(value)) return value.map(copy)
  if (plain(value)) return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, copy(v)]))
  return value
}

// ---- which way a chart is drawn --------------------------------------------------

/**
 * An option as the chart may use it: { value, problem } (see readOverride; a
 * larger limit, since here the option is the whole chart, not a few changes).
 */
export function readOption(option) {
  return readOverride(option, LIMIT)
}

/** Whether every series of an option names its ECharts type. */
function typedSeries(option) {
  const series = list(option?.series)
  return series.length > 0 && series.every(s => plain(s) && typeof s.type === 'string' && s.type.trim())
}

/**
 * Whether a chart is drawn from its ECharts option (charts made by the round-6
 * builder: no `type`, and an option whose series name their types) rather
 * than from the older settings. A chart with `type` is always drawn the old
 * way, so every existing deck looks exactly as before.
 */
export function isOptionChart(props = {}) {
  if (text(props.type).trim() && !text(props.chartId).trim()) return false
  // A chart kind from GFM Studio's picker (`preset`) is drawn from its option (the preset's, with the chart's own on top).
  if (presetOf(props) && !text(props.type).trim()) return true
  const option = readOption(props.option).value
  return !!option && (typedSeries(option) || (plain(option.gfm) && ['tile', 'multiples'].includes(option.gfm.kind)))
}

function hasQuery(props) {
  return props.query !== undefined && props.query !== null && props.query !== ''
}

/**
 * A chart's own numbers as a table for the engine: chart-core's table plus
 * `head` (the first column's heading) and `cells` (every cell as text).
 */
export function ownTable(props = {}) {
  const table = parseRows(props.rows) ?? parseCsv(props.csv) ?? parseData(props.data)
  if (!table || table.problem) return table
  const cells = tableCells(Array.isArray(props.rows) && props.rows.length ? { rows: props.rows } : { csv: props.csv }) ?? null
  const head = cells?.[0]?.[0] || (Array.isArray(props.data) && props.data[0] ? Object.keys(props.data[0])[0] : '') || 'Label'
  return { ...table, head, cells }
}

/**
 * The table of mission numbers (POST /api/charts/data): weeks as short dates
 * in the deck's language (the ISO weeks kept for forecasts), goal columns
 * marked, and what the numbers are (`unit`, `byUnit`).
 */
export function answerTable(answer) {
  const raw = answer?.table
  if (!raw || !Array.isArray(raw.labels) || !Array.isArray(raw.series)) return null
  const meta = answer.meta ?? {}
  const byUnit = meta.by === 'unit'
  const weeks = byUnit ? null : raw.labels.map(String)
  const series = raw.series
    .filter(s => s && Array.isArray(s.values))
    .map(s => ({ name: String(s.name ?? ''), values: s.values.map(v => toNumber(v)), ...(s.role === 'goal' ? { role: 'goal' } : {}) }))
  const level = { zone: 'Zone', district: 'District', area: 'Area' }[meta.level] || 'Unit'
  return {
    labels: byUnit ? raw.labels.map(l => String(l ?? '')) : weekLabels(weeks),
    series,
    head: byUnit ? level : 'Week',
    weeks,
    byUnit,
    unit: meta.unit || 'count',
  }
}

/**
 * Everything a chart needs to draw, from its settings and (for `query`) the
 * mission numbers: { mode: 'legacy'|'option', table, settings | option,
 * problem }. `problem` is the sentence the chart area shows instead.
 */
export function chartView(props = {}, answer = null) {
  const query = hasQuery(props)
  if (!isOptionChart(props)) {
    if (query) {
      if (!answer) return { mode: 'legacy', table: null, settings: { ...props }, problem: '' }
      const live = queryChart(answer, { ...props })
      return { mode: 'legacy', table: live.table, settings: live.settings, problem: queryProblem(answer) || chartProblem(live.table, props.type) }
    }
    const table = parseRows(props.rows) ?? parseCsv(props.csv) ?? parseData(props.data)
    return { mode: 'legacy', table, settings: { ...props }, problem: chartProblem(table, props.type) }
  }
  const read = readOption(props.option)
  let option = read.value ?? {}
  if (query && !answer) return { mode: 'option', table: null, option, problem: read.problem }
  let table = query ? answerTable(answer) : ownTable(props)
  // Calculated fields (formula.mjs) are added to the numbers; a mistake in one is listed in `calc` and the chart is
  // still drawn without that field.
  let calc = { problems: [], notes: [] }
  if (table && !table.problem && hasCalc(props)) {
    const done = applyCalculated(table, props.calc)
    table = done.table
    calc = { problems: done.problems, notes: done.notes }
  }
  // The numbers with the calculated fields, before a step or kind picks some of them: the editor lists these as fields.
  const source = table
  // Which numbers are shown (`shape`: only, hide, sort, top; a story step changes it).
  if (table && !table.problem && props.shape) table = shapeTable(table, props.shape)
  // A chart kind (chart-presets.mjs): its option goes under the chart's own, and it may reshape the table.
  let presetProblem = ''
  const preset = presetOf(props)
  if (preset && table && !table.problem) {
    const made = presetOption(preset, table, presetSettings(props))
    table = made.table
    option = mergeOption(made.option, option)
    presetProblem = made.problem
  }
  // When every number drawn is a percentage (a calculated field in percent, the others left out) the axis and the
  // tooltips say %.
  if (table?.series) {
    const shown = table.series.filter(s => s.role !== 'goal')
    if (shown.length && shown.every(s => s.format === 'percent') && table.unit !== 'percent') table = { ...table, unit: 'percent' }
  }
  const problem = read.problem || (query ? queryProblem(answer) : '') || presetProblem || optionIssue(table, option)
  return { mode: 'option', table, option, problem, calc, source }
}

function hasCalc(props) {
  const c = props.calc
  return (Array.isArray(c) && c.length > 0) || (typeof c === 'string' && c.trim() !== '')
}

// The few settings a preset reads (`presetTop`, `presetAggregate`, `presetTarget`), as chart-presets.mjs names them.
function presetSettings(props) {
  const n = v => (v === undefined || v === null || v === '' ? undefined : Number(v))
  return { top: n(props.presetTop), aggregate: props.presetAggregate, target: n(props.presetTarget) }
}

/** The ECharts option for a view from chartView (null when there is nothing to draw). */
export function viewOption(view, ctx) {
  if (!view || view.problem) return null
  if (view.mode === 'legacy') return buildOption(view.table, view.settings, ctx)
  return composeOption(view.table, view.option, ctx)
}

/** The ECharts option for a chart's settings (and the mission numbers of a `query`), or null. */
export function chartOption(props, ctx, answer = null) {
  return viewOption(chartView(props, answer), ctx)
}

// ---- checking an option ------------------------------------------------------------

/** What is wrong with an option's series types, or ''. */
export function seriesProblem(option) {
  for (const s of list(option?.series)) {
    if (!plain(s)) return 'Each entry of "series" must be a list of settings in { }.'
    const type = text(s.type).trim()
    if (type === 'map') return 'Map charts need a map file, and none is installed. Use a different chart type.'
    if (type && !SERIES_TYPES.includes(type)) return `“${type}” is not a chart type ECharts knows. Use one of: ${SERIES_TYPES.join(', ')}.`
    if (type === 'custom' && s.data === undefined && !RENDERERS.includes(text(s.renderItem))) return `A custom series draws one of: ${RENDERERS.join(', ')} ("renderItem").`
  }
  return ''
}

function inlineData(option) {
  return list(option?.series).some(s => plain(s) && (s.data !== undefined || s.links !== undefined))
    || list(option?.dataset).some(d => plain(d) && d.source !== undefined)
}

/** What a chart drawn from an option says instead of a chart, or ''. */
export function optionIssue(table, option) {
  const problem = seriesProblem(option)
  if (problem) return problem
  if (table?.problem) return table.problem
  const hasTable = !!table && table.labels.length > 0 && table.series.length > 0
  if (!hasTable) return inlineData(option) ? '' : 'Add data to show this chart.'
  if (!table.series.some(s => s.values.some(v => v !== null))) return 'Add numbers to show this chart.'
  const types = list(option.series).map(s => s?.type)
  if (types.some(t => t === 'graph' || t === 'sankey' || t === 'chord') && !links(table).length && !list(option.series).some(s => s?.links || s?.edges))
    return 'A network or flow chart needs a table with three columns: from, to and a number.'
  return ''
}

// ---- the table as ECharts data ------------------------------------------------------

function uniqueNames(names) {
  const seen = new Map()
  return names.map((name) => {
    const n = (seen.get(name) ?? 0) + 1
    seen.set(name, n)
    return n > 1 ? `${name} (${n})` : name
  })
}

/** The table as dataset 0: the label column, then one number column per series. */
function tableDataset(table, numericLabels) {
  const names = uniqueNames([table.head || 'Label', ...table.series.map(s => s.name || 'Value')])
  const mark = numericLabels ? decimalMarkOf(table.labels) : null
  return {
    id: 'table',
    dimensions: names.map((name, i) => ({ name, type: i === 0 ? (numericLabels ? 'number' : 'ordinal') : 'number' })),
    source: table.labels.map((label, i) => [numericLabels ? toNumber(label, mark) : label, ...table.series.map(s => s.values[i] ?? null)]),
  }
}

/** Rows of a table as links: from (first column), to (second, as text) and a number (third, or 1). */
function links(table) {
  const cells = table?.cells
  if (!cells || cells.length < 2 || cells[0].length < 2) return []
  return cells.slice(1)
    .map(row => ({ source: text(row[0]).trim(), target: text(row[1]).trim(), value: num(row[2]) ?? 1 }))
    .filter(l => l.source && l.target && l.source !== l.target && toNumber(l.target) === null)
}

function lastValue(values) {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null && values[i] !== undefined) return values[i]
  return null
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** Dates for a calendar: the table's ISO weeks, or labels written as dates. */
function datesOf(table) {
  if (table.weeks) return table.weeks
  return table.labels.map((l) => {
    if (ISO_DAY.test(l)) return l
    const d = new Date(l)
    return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10)
  })
}

// ---- trend lines, the waterfall and ranges -------------------------------------------

/** Labels for `count` periods after the table (Sundays for mission weeks). */
function nextLabels(table, count) {
  if (!(count > 0)) return []
  if (table.weeks?.length) return weekLabels([...table.weeks, ...nextWeeks(table.weeks, count)]).slice(table.weeks.length)
  return futureLabels(table.labels, count)
}

/**
 * A trend series for one bound series (`series.gfm.trend`), with its own
 * dataset (label, value) and a shaded "Forecast" band after the last period.
 */
function trendFor(s, column, env) {
  const config = s.gfm.trend
  const method = trendMethod(config === true ? 'linear' : config.method ?? 'linear')
  if (method === 'none') return null
  const { table, numericX, horizontal } = env
  const xs = numericX ? table.labels.map(l => toNumber(l, decimalMarkOf(table.labels))) : table.labels.map((_, i) => i)
  const count = numericX ? 0 : clamp(Math.round(num(config.forecast) ?? 0), 0, 52)
  const futureXs = Array.from({ length: count }, (_, i) => xs.length + i)
  const points = xs.map((x, i) => [x, column.values[i]]).filter(p => p[0] !== null && p[1] !== null)
  const fit = fitTrend(env.ctx.ecStat, points, method, config.degree, { window: config.window, future: futureXs, shift: numericX ? 0 : 1 })
  if (!fit) return null
  const future = nextLabels(table, count)
  const labelAt = x => (numericX ? x : x < table.labels.length ? table.labels[x] : future[x - table.labels.length])
  const rows = [...fit.points, ...fit.future].sort((a, b) => a[0] - b[0]).map(([x, y]) => [labelAt(x), round(y)])
  env.trendSets.push({ id: `trend-${env.trendSets.length}`, dimensions: [{ name: table.head || 'Label', type: numericX ? 'number' : 'ordinal' }, { name: 'Trend', type: 'number' }], source: rows })
  const custom = text(config.label).trim()
  const many = env.bound > 1
  const name = custom ? (many ? `${column.name} – ${custom}` : custom) : (many ? `${column.name} trend (${fit.label})` : `Trend (${fit.label})`)
  const color = text(config.color).trim() || s.itemStyle?.color || s.lineStyle?.color || s.color || env.colors[env.colorIndex(s) % env.colors.length]
  const width = num(config.width)
  const dash = { solid: 'solid', dotted: [2, 4], dashed: [7, 5] }[text(config.style) || 'dashed'] ?? [7, 5]
  const out = {
    type: 'line', name, datasetIndex: 1 + env.userSets.length + env.trendSets.length - 1,
    encode: horizontal ? { y: 0, x: 1 } : { x: 0, y: 1 },
    color, symbol: 'none', showSymbol: false, connectNulls: true, z: 5,
    smooth: fit.label !== 'linear',
    lineStyle: { width: width === null ? 2 : clamp(width, 0.5, 8), type: dash, color, opacity: 0.9 },
    itemStyle: { color }, emphasis: { disabled: true }, tooltip: { show: true },
    ...(s.xAxisIndex !== undefined ? { xAxisIndex: s.xAxisIndex } : {}),
    ...(s.yAxisIndex !== undefined ? { yAxisIndex: s.yAxisIndex } : {}),
    gfmTrend: true,
  }
  if (future.length) {
    const axis = horizontal ? 'yAxis' : 'xAxis'
    out.markArea = { silent: true, itemStyle: { color: env.chrome.shade }, label: { show: true, position: 'insideTop', color: env.chrome.muted, fontSize: 12, formatter: 'Forecast' }, data: [[{ [axis]: table.labels[table.labels.length - 1] }, { [axis]: future[future.length - 1] }]] }
  }
  return out
}

/** The waterfall of one column: the first row is the level it starts at, the others changes, then a Total bar. */
function waterfallItems(labels, values) {
  const steps = labels.map((name, i) => ({ name, delta: values[i] })).filter(d => d.delta !== null && d.delta !== undefined)
  let run = 0
  const items = steps.map((d) => {
    const start = run
    run += d.delta
    return { name: d.name, start, end: run, delta: d.delta, total: false }
  })
  if (items.length > 1) items.push({ name: 'Total', start: 0, end: run, delta: run, total: true })
  return items
}

/** The functions behind renderItem: "waterfall", "range" and "errorbar". */
function renderer(kind, env) {
  const say = env.fmt.value
  if (kind === 'waterfall') {
    return (params, api) => {
      const x = api.value(0)
      const a = api.coord([x, api.value(1)]), b = api.coord([x, api.value(2)])
      const width = Math.min(48, api.size([1, 0])[0] * 0.6)
      const top = Math.min(a[1], b[1]), height = Math.max(1, Math.abs(b[1] - a[1]))
      const rect = { type: 'rect', shape: { x: a[0] - width / 2, y: top, width, height, r: 3 }, style: { fill: api.visual('color') } }
      if (!env.labels) return rect
      const level = api.value(4) === 1
      const delta = api.value(3)
      return { type: 'group', children: [rect, { type: 'text', style: { text: `${level ? '' : delta >= 0 ? '+' : '−'}${say(Math.abs(delta))}`, x: a[0], y: top - 4, align: 'center', verticalAlign: 'bottom', fill: env.chrome.soft, fontSize: 12 } }] }
    }
  }
  return (params, api) => {
    const x = api.value(0)
    const low = api.coord([x, api.value(1)]), high = api.coord([x, api.value(2)])
    const band = api.size([1, 0])[0]
    const color = api.visual('color')
    if (kind === 'range') {
      const width = Math.min(36, band * 0.5)
      return { type: 'rect', shape: { x: low[0] - width / 2, y: high[1], width, height: Math.max(1, low[1] - high[1]), r: 4 }, style: { fill: color, opacity: 0.85 } }
    }
    const cap = Math.min(16, band * 0.3)
    const line = (x1, y1, x2, y2) => ({ type: 'line', shape: { x1, y1, x2, y2 }, style: { stroke: color, lineWidth: 2 } })
    return { type: 'group', children: [line(low[0], low[1], high[0], high[1]), line(low[0] - cap / 2, low[1], low[0] + cap / 2, low[1]), line(high[0] - cap / 2, high[1], high[0] + cap / 2, high[1])] }
  }
}

// ---- binding the table to the series ---------------------------------------------------

function coordinateOf(s) {
  if (s.coordinateSystem) return s.coordinateSystem
  if (s.type === 'themeRiver') return 'singleAxis'
  if (s.type === 'parallel') return 'parallel'
  if (s.type === 'radar') return 'radar'
  return ON_AXES.has(s.type) ? 'cartesian2d' : 'none'
}

function bound(s) {
  return s.data !== undefined || s.datasetIndex !== undefined || s.datasetId !== undefined || s.links !== undefined || s.edges !== undefined
}

/**
 * Binds the table to every series that has no data of its own and returns
 * the option with explicit axes, datasets and the extra series (trends,
 * unusual values). Series of one column repeat for the columns left over, so
 * `series: [{"type":"line"}]` draws every column as a line.
 */
function bindTable(option, table, env) {
  const out = option
  const series = list(out.series).map(s => ({ ...s }))
  const columns = tableColumns(table, env)
  env.bound = columns.filter(c => c.role !== 'goal').length
  const binder = newBinder(out, table, env, columns)
  claimEncodedColumns(series, binder)
  for (const s of series) {
    if (!plain(s) || bound(s) || s.gfmClaimed) continue
    SERIES_BINDERS.get(s.type)?.(s, binder)
  }
  repeatLastSeries(series, binder)
  out.series = [...series.filter(s => !s.gfmEmpty), ...binder.extra, ...trendLines(series, columns, env)]
  return out
}

// The table's columns: { name, values, index } and role 'goal' for a goal column. A column named as the goal
// (gfm.goal.column, any capitalisation) is a goal column, like mission goals.
function tableColumns(table, env) {
  const goalName = text(env.gfm.goal?.column).trim().toLowerCase()
  return table ? table.series.map((s, i) => ({ ...s, index: i, ...(goalName && s.name.trim().toLowerCase() === goalName ? { role: 'goal' } : {}) })) : []
}

// What every series binder below works with: the option (out), the table, env, the columns not bound yet (queue;
// take() takes the first one), the extra series to add after them (unusual values), and two small helpers.
function newBinder(out, table, env, columns) {
  const queue = [...columns]
  return {
    out, table, env, columns, queue, extra: [],
    take: () => queue.shift() ?? null,
    colorOf: i => env.colors[i % env.colors.length],
    axisOf: s => ({ x: list(out.xAxis)[s.xAxisIndex ?? 0] ?? {}, y: list(out.yAxis)[s.yAxisIndex ?? 0] ?? {} }),
  }
}

// Binds one column to a series of one column (line, bar, scatter …) through dataset 0. repeated: a copy of the last
// series, made for a column that was left over.
function bindColumn(s, column, repeated, { out, axisOf }) {
  if (ONE_COLUMN.has(s.type)) {
    s.datasetIndex = 0
    if (coordinateOf(s) === 'polar') {
      const radiusCategory = list(out.radiusAxis)[s.radiusAxisIndex ?? 0]?.type === 'category'
      s.encode = radiusCategory ? { radius: 0, angle: column.index + 1 } : { angle: 0, radius: column.index + 1 }
    }
    else {
      const horizontal = axisOf(s).y.type === 'category'
      s.encode = horizontal ? { y: 0, x: column.index + 1, tooltip: [column.index + 1] } : { x: 0, y: column.index + 1, tooltip: [column.index + 1] }
    }
    s.seriesLayoutBy = 'column'
    if (s.name === undefined) s.name = column.name
    if (column.role === 'goal') s.gfmGoal = true
    s.gfmColumn = column.index
    if (repeated) s.gfmRepeated = true
  }
  return s
}

// A series whose encode names its columns (numbers or headings) reads the table as written; those columns are no
// longer free for the other series.
function claimEncodedColumns(series, { table, columns, queue }) {
  const byName = new Map(uniqueNames([table.head || 'Label', ...columns.map(c => c.name || 'Value')]).map((n, i) => [n, i]))
  for (const s of series) {
    if (!plain(s) || !plain(s.encode) || s.data !== undefined || s.datasetId !== undefined || (s.datasetIndex ?? 0) !== 0) continue
    s.datasetIndex = 0
    const dims = Object.entries(s.encode).filter(([k]) => k !== 'tooltip' && k !== 'itemName').flatMap(([, d]) => d).map(d => (typeof d === 'number' ? d : byName.get(d))).filter(d => d > 0)
    for (const d of dims) {
      const i = queue.findIndex(c => c.index === d - 1)
      if (i >= 0) queue.splice(i, 1)
    }
    if (dims.length && s.name === undefined) s.name = columns[dims[dims.length - 1] - 1]?.name
    if (s.gfmColumn === undefined && dims.length) s.gfmColumn = dims[dims.length - 1] - 1
    s.gfmClaimed = true
  }
}

// ---- one binder per series type: each takes the columns it needs from the queue ----

// line, bar, scatter, effectScatter, pictorialBar: one column each (on a calendar or a single axis too).
function bindOneColumnSeries(s, binder) {
  const where = coordinateOf(s)
  if (where === 'calendar') return bindCalendar(s, binder)
  const column = binder.take()
  if (where === 'singleAxis') {
    if (!column) return
    s.data = column.values.map((v, i) => [i, v]).filter(p => p[1] !== null)
    s.name ??= column.name
    return
  }
  if (column) bindColumn(s, column, false, binder)
  else s.gfmEmpty = true
}

// A series on a calendar: one column, one day per label (the labels are dates).
function bindCalendar(s, { take, table }) {
  const column = take()
  if (!column) return
  const dates = datesOf(table)
  s.data = dates.map((d, i) => [d, column.values[i]]).filter(p => p[0] && p[1] !== null)
  s.name ??= column.name
}

// pie, funnel: one column; a slice per label (zero and empty values left out).
function bindPie(s, { take, table }) {
  const column = take()
  if (!column) { s.gfmEmpty = true; return }
  s.name ??= column.name
  s.data = table.labels.map((name, i) => ({ name, value: column.values[i] })).filter(d => d.value !== null && d.value > 0)
}

// gauge: the last value of one column; the next column's last value is the gauge's end (its goal).
function bindGauge(s, { take, queue }) {
  const column = take()
  if (!column) { s.gfmEmpty = true; return }
  const value = lastValue(column.values)
  const goal = queue[0] && lastValue(queue[0].values)
  if (s.max === undefined && goal > 0) { s.max = goal; take() }
  s.data = [{ value, name: s.name ?? column.name }]
}

// radar: every column is one shape; the labels are the corners (each corner's end rounded up from its largest value).
function bindRadar(s, { queue, out, table, colorOf }) {
  const cols = queue.splice(0)
  if (!cols.length) { s.gfmEmpty = true; return }
  s.data = cols.map((c, i) => ({ name: c.name, value: c.values.map(v => v ?? 0), itemStyle: { color: colorOf(i) }, lineStyle: { color: colorOf(i) }, areaStyle: { color: colorOf(i) } }))
  const radars = list(out.radar)
  const radar = radars[s.radarIndex ?? 0] ?? {}
  if (!radar.indicator) {
    const top = Number(radar.max) > 0 ? Number(radar.max) : null
    const indicator = table.labels.map((name, i) => ({ name, max: top ?? niceCeil(Math.max(0, ...cols.map(c => c.values[i] ?? 0)) || 1) }))
    const next = { ...radar, indicator }
    delete next.max
    radars[s.radarIndex ?? 0] = next
    out.radar = radars
  }
}

// heatmap: every column; a cell per label and column (on a calendar: one column, a cell per day).
function bindHeatmap(s, binder) {
  const where = coordinateOf(s)
  if (where === 'calendar') return bindCalendar(s, binder)
  const { queue, out, table, env } = binder
  const cols = queue.splice(0)
  s.data = []
  if (where === 'matrix') {
    // ECharts 6's matrix: one cell per label and column, by name.
    cols.forEach(c => c.values.forEach((v, x) => { if (v !== null) s.data.push([table.labels[x], c.name, v]) }))
    const matrix = list(out.matrix)[0] ?? {}
    out.matrix = { ...matrix, x: { data: table.labels, ...matrix.x }, y: { data: cols.map(c => c.name), ...matrix.y } }
    env.heat.push(...s.data.map(d => d[2]))
    return
  }
  cols.forEach((c, y) => c.values.forEach((v, x) => { if (v !== null) s.data.push([x, y, v]) }))
  env.axisData.push({ axis: 'xAxis', index: s.xAxisIndex ?? 0, data: table.labels })
  env.axisData.push({ axis: 'yAxis', index: s.yAxisIndex ?? 0, data: cols.map(c => c.name) })
  env.heat.push(...s.data.map(d => d[2]))
}

// tree: one column; labels written as paths ("North / Frankfurt 1") are the branches, under the chart's title.
function bindTree(s, { take, out, table }) {
  const column = take()
  if (!column) { s.gfmEmpty = true; return }
  const nodes = treeFrom(table.labels, column.values)
  s.data = nodes.length === 1 ? nodes : [{ name: text(list(out.title)[0]?.text) || column.name, children: nodes }]
}

// treemap, sunburst: one column; labels written as paths are the branches.
function bindTreemap(s, { take, table }) {
  const column = take()
  if (!column) { s.gfmEmpty = true; return }
  s.data = treeFrom(table.labels, column.values)
  s.name ??= column.name
}

// boxplot: one box per column (goal columns left out); unusual values become an extra scatter series.
function bindBoxplot(s, { queue, env, extra, colorOf, axisOf }) {
  const cols = queue.splice(0).filter(c => c.role !== 'goal')
  const shown = cols.map((c, i) => ({ c, i, st: boxStats(c.values) })).filter(x => x.st)
  s.data = shown.map(({ c, i, st }) => ({ name: c.name, value: [st.low, st.q1, st.median, st.q3, st.high], itemStyle: { color: mix(colorOf(i), env.chrome.surface, 0.8) || env.chrome.track, borderColor: colorOf(i) } }))
  s.name ??= 'Spread'
  const horizontal = axisOf(s).y.type === 'category'
  env.axisData.push({ axis: horizontal ? 'yAxis' : 'xAxis', index: horizontal ? s.yAxisIndex ?? 0 : s.xAxisIndex ?? 0, data: shown.map(x => x.c.name) })
  const outliers = shown.flatMap(({ i, st }, x) => st.outliers.map(v => ({ value: horizontal ? [v, x] : [x, v], itemStyle: { color: colorOf(i) } })))
  if (outliers.length) extra.push({ type: 'scatter', name: 'Unusual values', data: outliers, symbolSize: 8, xAxisIndex: s.xAxisIndex, yAxisIndex: s.yAxisIndex, gfmExtra: true })
}

// candlestick: four columns (open, close, lowest, highest) through dataset 0.
function bindCandlestick(s, { queue, env, table }) {
  const cols = queue.splice(0, 4)
  if (cols.length < 4) { s.gfmEmpty = true; env.problems.push('A candlestick chart needs four columns: open, close, lowest and highest.'); return }
  s.datasetIndex = 0
  s.encode = { x: 0, y: cols.map(c => c.index + 1), tooltip: cols.map(c => c.index + 1) }
  s.name ??= table.head
}

// graph, sankey, chord: the rows are links (from, to, a number); a node per name, sized by its links in a graph.
function bindGraph(s, { queue, table, colorOf }) {
  queue.splice(0)
  const edges = links(table)
  const names = [...new Set(edges.flatMap(l => [l.source, l.target]))]
  const weight = new Map(names.map(n => [n, 0]))
  for (const l of edges) { weight.set(l.source, weight.get(l.source) + l.value); weight.set(l.target, weight.get(l.target) + l.value) }
  const top = Math.max(1, ...weight.values())
  s.links = edges
  s.data = names.map((name, i) => (s.type === 'graph'
    ? { name, value: weight.get(name), symbolSize: Math.round(12 + 30 * Math.sqrt(weight.get(name) / top)), itemStyle: { color: colorOf(i) } }
    : { name, itemStyle: { color: colorOf(i) } }))
}

// themeRiver: every column (goal columns left out) is one stream along the labels.
function bindThemeRiver(s, { queue, env, table }) {
  const cols = queue.splice(0).filter(c => c.role !== 'goal')
  s.data = cols.flatMap(c => c.values.map((v, i) => [i, v ?? 0, c.name]))
  env.axisData.push({ axis: 'singleAxis', index: s.singleAxisIndex ?? 0, data: table.labels })
}

// parallel: every column is an axis; every label is one line across them.
function bindParallel(s, { queue, out, table }) {
  const cols = queue.splice(0)
  s.data = table.labels.map((name, i) => ({ name, value: cols.map(c => c.values[i]) }))
  if (!out.parallelAxis) out.parallelAxis = cols.map((c, dim) => ({ dim, name: c.name }))
}

// lines: four columns (from x, from y, to x, to y); a line per label.
function bindLines(s, { queue, env, table }) {
  const cols = queue.splice(0, 4)
  if (cols.length < 4) { s.gfmEmpty = true; env.problems.push('A lines chart needs four columns: from x, from y, to x and to y.'); return }
  s.coordinateSystem ??= 'cartesian2d'
  s.data = table.labels.map((name, i) => ({ name, coords: [[cols[0].values[i], cols[1].values[i]], [cols[2].values[i], cols[3].values[i]]] })).filter(d => d.coords.flat().every(v => v !== null))
}

// custom: the drawings a custom series names as its renderItem (a waterfall, or a range between two columns).
function bindCustom(s, binder) {
  const kind = text(s.renderItem)
  if (kind === 'waterfall') bindWaterfall(s, binder)
  else if (kind === 'range' || kind === 'errorbar') bindRange(s, kind, binder)
}

// A waterfall: one column of changes; each bar starts where the one before ended, with a total at the end.
function bindWaterfall(s, { take, env, table, colorOf }) {
  const column = take()
  if (!column) { s.gfmEmpty = true; return }
  const items = waterfallItems(table.labels, column.values)
  const level = i => items[i].total || (i === 0 && items.length > 1)
  const [up, down, sum] = [colorOf(0), colorOf(1), colorOf(2)]
  s.name ??= column.name
  s.encode = { x: 0, y: [1, 2], tooltip: [3] }
  s.data = items.map((it, i) => ({ name: it.name, value: [i, it.start, it.end, it.delta, level(i) ? 1 : 0], itemStyle: { color: level(i) ? sum : it.delta >= 0 ? up : down } }))
  s.renderItem = renderer('waterfall', { ...env, labels: !!s.label?.show })
  delete s.label
  env.axisData.push({ axis: 'xAxis', index: s.xAxisIndex ?? 0, data: items.map(it => it.name) })
  env.waterfall = true
}

// A range or error bars: two columns, the lowest and the highest number per label.
function bindRange(s, kind, { queue, env, table }) {
  const cols = queue.splice(0, 2)
  if (cols.length < 2) { s.gfmEmpty = true; env.problems.push('A range needs two columns: the lowest and the highest number.'); return }
  s.name ??= `${cols[0].name} – ${cols[1].name}`
  s.encode = { x: 0, y: [1, 2], tooltip: [1, 2] }
  s.data = table.labels.map((_, i) => [i, cols[0].values[i], cols[1].values[i]]).filter(d => d[1] !== null && d[2] !== null)
  s.renderItem = renderer(kind, env)
  env.axisData.push({ axis: 'xAxis', index: s.xAxisIndex ?? 0, data: table.labels })
}

// Which binder a series type uses (a type not listed gets no numbers from the table).
const SERIES_BINDERS = new Map([
  ...[...ONE_COLUMN].map(type => [type, bindOneColumnSeries]),
  ['pie', bindPie], ['funnel', bindPie],
  ['gauge', bindGauge],
  ['radar', bindRadar],
  ['heatmap', bindHeatmap],
  ['tree', bindTree],
  ['treemap', bindTreemap], ['sunburst', bindTreemap],
  ['boxplot', bindBoxplot],
  ['candlestick', bindCandlestick],
  ['graph', bindGraph], ['sankey', bindGraph], ['chord', bindGraph],
  ['themeRiver', bindThemeRiver],
  ['parallel', bindParallel],
  ['lines', bindLines],
  ['custom', bindCustom],
])

// The last one-column series repeats for the columns that are left. A goal column's copy is always a line.
function repeatLastSeries(series, binder) {
  const template = [...series].reverse().find(s => ONE_COLUMN.has(s?.type) && s.gfmColumn !== undefined && !s.gfmRepeated && !s.gfmClaimed)
  if (!template) return
  for (const column of binder.queue.splice(0)) {
    const clone = copy(template)
    for (const key of ['name', 'id', 'data', 'encode', 'datasetIndex', 'gfmGoal', 'gfmColumn', 'markLine', 'markPoint', 'markArea']) delete clone[key]
    // The template's reference lines are drawn once; averages go with every series.
    const averages = list(template.markLine?.data).filter(d => plain(d) && d.type)
    if (averages.length) clone.markLine = { ...template.markLine, data: averages }
    if (column.role === 'goal' && clone.type !== 'line') {
      for (const key of ['type', 'stack', 'areaStyle', 'barWidth', 'barMaxWidth', 'symbolRepeat', 'symbol', 'symbolSize']) delete clone[key]
      clone.type = 'line'
    }
    if (column.role === 'goal') { delete clone.areaStyle; delete clone.stack; delete clone.gfm }
    series.push(bindColumn(clone, column, true, binder))
  }
}

// Trend lines, after every series (as the older charts drew them): one per series that asks for one (gfm.trend).
function trendLines(series, columns, env) {
  const trends = []
  for (const s of series) {
    if (!plain(s?.gfm?.trend) && s?.gfm?.trend !== true) continue
    if (s.gfmColumn === undefined || s.gfmGoal) continue
    const trend = trendFor(s, columns[s.gfmColumn], env)
    if (trend) trends.push(trend)
  }
  return trends
}

// ---- small multiples and key numbers ------------------------------------------------------

/** One small chart per column, side by side on one scale; goal columns are drawn in every panel. */
function multiples(option, table, env) {
  const main = table.series.map((s, index) => ({ s, index })).filter(x => x.s.role !== 'goal')
  const goals = table.series.map((s, index) => ({ s, index })).filter(x => x.s.role === 'goal')
  const count = Math.max(1, main.length)
  const cols = count <= 2 ? count : count <= 4 ? 2 : 3
  const rows = Math.ceil(count / cols)
  const hasTitle = !!text(list(option.title)[0]?.text).trim()
  const top0 = hasTitle ? 11 : 2
  const cellH = (98 - top0) / rows, cellW = 100 / cols
  const values = table.series.flatMap(s => s.values).filter(v => v !== null)
  const high = niceCeil(Math.max(0, ...values)), low = Math.min(0, ...values)
  const template = list(option.series)[0] ?? { type: 'line' }
  const out = { ...option, grid: [], xAxis: [], yAxis: [], title: hasTitle ? [list(option.title)[0]] : [], series: [] }
  main.forEach(({ s, index }, panel) => {
    const r = Math.floor(panel / cols), c = panel % cols
    out.grid.push({ left: `${c * cellW + 1}%`, width: `${cellW - 4}%`, top: `${top0 + r * cellH + 7}%`, height: `${cellH - 16}%`, containLabel: true })
    out.title.push({ text: s.name, left: `${c * cellW + 1}%`, top: `${top0 + r * cellH}%`, textStyle: { color: env.chrome.soft, fontSize: 14, fontWeight: 600 } })
    out.xAxis.push({ gridIndex: panel, type: 'category', axisLabel: { fontSize: 11 } })
    out.yAxis.push({ gridIndex: panel, type: 'value', min: low, max: high, splitNumber: 3, axisLabel: { fontSize: 11 } })
    const one = { ...copy(template), xAxisIndex: panel, yAxisIndex: panel, name: s.name, datasetIndex: 0, encode: { x: 0, y: index + 1, tooltip: [index + 1] }, gfmColumn: index }
    out.series.push(one)
    for (const g of goals) out.series.push({ type: 'line', xAxisIndex: panel, yAxisIndex: panel, name: g.s.name, datasetIndex: 0, encode: { x: 0, y: g.index + 1 }, gfmGoal: true, gfmColumn: g.index })
  })
  out.legend = option.legend ?? { show: false }
  return out
}

/** A key number: the older tile, with the option's title, colours, format and anything else laid over it. */
function tile(table, option, ctx) {
  const gfm = option.gfm ?? {}
  const format = plain(gfm.format) ? gfm.format : {}
  const settings = {
    type: 'tile',
    title: text(list(option.title)[0]?.text),
    colors: Array.isArray(option.color) ? option.color : undefined,
    target: gfm.target,
    smooth: !!list(option.series)[0]?.smooth,
    format: format.style, decimals: format.decimals, prefix: format.prefix, suffix: format.suffix,
  }
  const base = buildOption(table, settings, ctx)
  if (!base) return null
  const rest = { ...option }
  for (const key of ['title', 'series', 'dataset', 'gfm', 'color']) delete rest[key]
  return mergeOption(base, rest)
}

// ---- the mission look ------------------------------------------------------------------------

function spoken(title, table, fmt) {
  const say = v => fmt.value(v)
  const parts = [`${title ? `${title}.` : 'Chart.'}`]
  if (table) {
    for (const s of table.series) {
      const points = table.labels.map((label, i) => [label, s.values[i]]).filter(p => p[1] !== null && p[1] !== undefined)
      if (!points.length) continue
      if (points.length <= 16) parts.push(`${s.name}: ${points.map(([l, v]) => `${l}: ${say(v)}`).join(', ')}.`)
      else {
        const values = points.map(p => p[1])
        parts.push(`${s.name}: ${points.length} values from ${points[0][0]} to ${points[points.length - 1][0]}, lowest ${say(Math.min(...values))}, highest ${say(Math.max(...values))}, last ${say(values[values.length - 1])}.`)
      }
    }
  }
  return parts.join(' ')
}

/** Position defaults, only when the setting chose none of its own. */
function at(user, position) {
  return hasPosition(user) ? {} : position
}

function valueOfParams(p, dim) {
  if (Array.isArray(p?.value)) return p.value[dim ?? p.value.length - 1]
  return p?.value
}

/**
 * The mission look for a bound option: an option of the same shape (arrays
 * where it has arrays) that is merged under it, so every setting the chart
 * writes wins.
 */
function missionLook(o, table, env) {
  const layout = pageLayout(o)
  const look = baseLook(o, table, env)
  for (const [key, lookOf] of COMPONENT_LOOKS) if (o[key] !== undefined) look[key] = lookOf(o, table, env, layout)
  if (layout.timeline) look.timeline = timelineLook(env)
  const series = list(o.series)
  const pies = series.filter(s => s?.type === 'pie')
  look.series = series.map(s => seriesLook(s, { ...env, hasTitle: layout.hasTitle, pies, top: layout.top }))
  return look
}

// Where the plot sits: room at the top for the title and a legend, and at the bottom for a legend, a zoom slider, a
// colour scale and a timeline.
function pageLayout(o) {
  const hasTitle = list(o.title).some(t => plain(t) && t.show !== false && text(t.text).trim())
  const legends = list(o.legend)
  const legendShown = legends.some(l => plain(l) && l.show !== false)
  const legendBottom = legends.some(l => plain(l) && l.show !== false && (l.bottom !== undefined || l.top === 'bottom'))
  const legendSide = legends.some(l => plain(l) && l.show !== false && (l.orient === 'vertical' || l.right !== undefined))
  const legendTop = legendShown && !legendBottom && !legendSide
  const sliders = list(o.dataZoom).filter(z => plain(z) && z.type === 'slider' && z.show !== false)
  const visualMaps = list(o.visualMap).filter(v => plain(v) && v.show !== false)
  const timeline = plain(o.timeline) || Array.isArray(o.timeline)
  const top = (hasTitle ? 34 : 0) + (legendTop ? 28 : 0) + 14
  const bottom = 6 + (legendBottom ? 28 : 0) + (sliders.length ? 34 : 0) + (visualMaps.some(v => v.orient !== 'vertical' && !hasPosition(v)) ? 44 : 0) + (timeline ? 56 : 0)
  return { hasTitle, legendBottom, legendSide, timeline, top, bottom }
}

// What every chart gets: the colours, the font, calm animations, a spoken description and the pointing box.
function baseLook(o, table, env) {
  const { chrome, colors, fmt, ctx } = env
  return {
    color: colors,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: ctx.font, color: chrome.ink },
    animationDuration: 500,
    animationDurationUpdate: 450,
    animationEasingUpdate: 'cubicInOut',
    aria: { enabled: true, label: { description: spoken(text(list(o.title)[0]?.text).trim(), table, fmt) } },
    tooltip: {
      confine: true, backgroundColor: chrome.tip, borderColor: chrome.tipLine, borderWidth: 1,
      textStyle: { color: chrome.ink, fontSize: 13, fontFamily: ctx.font }, valueFormatter: fmt.value,
      trigger: env.axisTrigger ? 'axis' : 'item',
      axisPointer: { type: env.anyBar ? 'shadow' : 'line', lineStyle: { color: chrome.axis }, shadowStyle: { color: chrome.shade } },
    },
  }
}

// ---- the look of each component (only for components the option has) ----

function titleLook(o, table, { chrome, ctx }) {
  return list(o.title).map((t, i) => ({
    ...(i === 0 ? at(t, { left: 0, top: 0 }) : {}),
    textStyle: { color: i === 0 ? chrome.ink : chrome.soft, fontSize: i === 0 ? 18 : 14, fontWeight: 600, fontFamily: ctx.font },
    subtextStyle: { color: chrome.soft, fontSize: 13, fontFamily: ctx.font },
  }))
}

function legendLook(o, table, { chrome }, { hasTitle }) {
  return list(o.legend).map(l => ({
    type: 'scroll', itemWidth: 24, itemHeight: 10, itemGap: 18, textStyle: { color: chrome.soft, fontSize: 13 }, pageTextStyle: { color: chrome.muted },
    pageIconColor: chrome.soft, pageIconInactiveColor: chrome.axis,
    ...(plain(l) && !hasPosition(l) && l.orient !== 'vertical' ? { top: hasTitle ? 34 : 0, left: 0 } : {}),
    ...(plain(l) && l.orient === 'vertical' && !hasPosition(l) ? { right: 0, top: 'middle', itemGap: 12 } : {}),
  }))
}

function gridLook(o, table, env, { legendSide, top, bottom }) {
  const grids = list(o.grid)
  return grids.map(g => (grids.length > 1 ? { containLabel: true } : {
    containLabel: true,
    ...at(g, { left: 8 + (env.yName ? 26 : 0), right: legendSide ? '24%' : 18, top, bottom: bottom + (env.xName ? 24 : 0) }),
  }))
}

// One axis (which: 'x' or 'y'). A category axis: labels that fit (week and unit names), no grid lines. A value
// axis: grid lines and numbers in the chart's number format.
function axisLook(a, which, table, env) {
  const { chrome, fmt, ctx } = env
  const type = a.type ?? (which === 'x' ? 'category' : 'value')
  const named = text(a.name).trim()
  const common = { nameTextStyle: { color: chrome.soft, fontSize: 13, fontWeight: 600 }, ...(named && a.nameLocation === undefined ? { nameLocation: 'middle', nameGap: which === 'x' ? 28 : 44 } : {}) }
  if (type === 'category') {
    const barOn = env.barAxes.has(`${which}:${a.gfmIndex}`)
    const label = { color: chrome.muted, fontSize: 12, hideOverlap: true }
    if (which === 'x' && !barOn && !a.axisLabel?.rotate) Object.assign(label, { alignMinLabel: 'left', alignMaxLabel: 'right' })
    if (which === 'x' && table?.weeks) label.showMaxLabel = true
    if (which === 'x' && table?.byUnit) {
      const count = table.labels.length
      const band = Math.floor(((ctx.width || 640) - 60) / Math.max(1, count))
      const longest = Math.max(0, ...table.labels.map(l => Math.max(0, ...String(l).split(/\s+/).map(w => w.length))))
      if (count <= 12 && longest * 7 <= band - 4) Object.assign(label, { interval: 0, hideOverlap: false, width: band - 4, overflow: 'break', lineHeight: 14 })
      else Object.assign(label, { rotate: count <= 12 ? 30 : 45, ...(count <= 30 ? { interval: 0 } : {}) })
    }
    return { ...common, boundaryGap: barOn, axisLine: { show: true, lineStyle: { color: chrome.axis } }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: label }
  }
  return {
    ...common,
    ...(env.scatterOnly && type === 'value' ? { scale: true } : {}),
    axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: chrome.grid } },
    axisLabel: { color: chrome.muted, fontSize: 12, ...(type === 'time' ? {} : { formatter: fmt.axis }) },
  }
}

function polarLook(o, table, env, { hasTitle }) {
  return list(o.polar).map(p => (p.center || p.radius ? {} : { center: ['50%', hasTitle ? '56%' : '52%'], radius: '70%' }))
}

function angleAxisLook(o, table, { chrome }) {
  return list(o.angleAxis).map(a => ({ axisLine: { lineStyle: { color: chrome.axis } }, axisLabel: { color: chrome.muted }, splitLine: { lineStyle: { color: chrome.grid } }, axisTick: { show: false } }))
}

function radiusAxisLook(o, table, { chrome, fmt }) {
  return list(o.radiusAxis).map(a => ({ axisLine: { lineStyle: { color: chrome.axis } }, axisLabel: { color: chrome.muted, ...(a.type === 'category' ? {} : { formatter: fmt.axis }) }, splitLine: { lineStyle: { color: chrome.grid } }, axisTick: { show: false } }))
}

function radarLook(o, table, { chrome }, { legendSide, top }) {
  return list(o.radar).map(r => ({
    radius: '58%', center: [legendSide ? '40%' : '50%', `${top > 20 ? 55 + Math.round(top / 12) : 52}%`], splitNumber: 4,
    axisName: { color: chrome.soft, fontSize: 13, formatter: name => wrapWords(name, 16) },
    splitLine: { lineStyle: { color: chrome.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: chrome.axis } },
  }))
}

function singleAxisLook(o, table, { chrome }, { hasTitle, timeline }) {
  return list(o.singleAxis).map(a => ({
    ...at(a, { top: hasTitle ? 60 : 24, bottom: 36 + (timeline ? 56 : 0), left: 24, right: 24 }),
    type: 'category', axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { show: false }, axisLabel: { color: chrome.muted, fontSize: 12, hideOverlap: true },
    splitLine: { show: true, lineStyle: { color: chrome.grid } }, axisPointer: { animation: true, label: { show: true, color: chrome.ink, backgroundColor: chrome.tip } },
  }))
}

function parallelLook(o, table, env, { hasTitle }) {
  return list(o.parallel).map(p => at(p, { left: 40, right: 70, top: hasTitle ? 64 : 30, bottom: 30 }))
}

function parallelAxisLook(o, table, { chrome }) {
  return list(o.parallelAxis).map(() => ({ nameTextStyle: { color: chrome.soft, fontSize: 12, fontWeight: 600 }, axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { lineStyle: { color: chrome.axis } }, axisLabel: { color: chrome.muted }, areaSelectStyle: { color: chrome.shade, borderColor: chrome.axis } }))
}

function calendarLook(o, table, { chrome }, { hasTitle }) {
  return list(o.calendar).map(c => ({
    ...at(c, { top: hasTitle ? 70 : 36, left: 44, right: 16 }),
    cellSize: ['auto', 16], itemStyle: { color: chrome.surface, borderColor: chrome.grid, borderWidth: 1 },
    splitLine: { lineStyle: { color: chrome.axis, width: 1 } }, dayLabel: { color: chrome.muted, firstDay: 1, fontSize: 11 },
    monthLabel: { color: chrome.soft, fontSize: 12 }, yearLabel: { show: false },
  }))
}

function dataZoomLook(o, table, { chrome }, { legendBottom }) {
  return list(o.dataZoom).map(z => (z.type === 'slider'
    ? { ...at(z, { bottom: 4 + (legendBottom ? 28 : 0), height: 18 }), borderColor: chrome.grid, fillerColor: chrome.shade, handleStyle: { color: chrome.surface, borderColor: chrome.axis }, moveHandleStyle: { color: chrome.axis }, textStyle: { color: chrome.muted, fontSize: 11 }, dataBackground: { lineStyle: { color: chrome.axis }, areaStyle: { color: chrome.shade } } }
    : {}))
}

// A colour scale: from the lowest to the highest number shown (a heat map's cells, or every number of the table).
function visualMapLook(o, table, env, { timeline }) {
  const { chrome, colors, fmt } = env
  const values = env.heat.length ? env.heat : (table?.series ?? []).flatMap(s => s.values).filter(v => v !== null)
  const low = values.length ? Math.min(...values) : 0
  const high = values.length ? Math.max(...values) : 1
  return list(o.visualMap).map(v => ({
    ...(v.type === 'piecewise' ? {} : { min: low, max: high === low ? low + 1 : high, itemWidth: 12, itemHeight: 140 }),
    ...(v.orient === 'vertical' ? at(v, { right: 0, top: 'middle' }) : { orient: 'horizontal', ...at(v, { left: 'center', bottom: timeline ? 56 : 0 }) }),
    textStyle: { color: chrome.muted, fontSize: 12 },
    ...(v.inRange || v.pieces ? {} : { inRange: { color: [mix(colors[0], chrome.surface, 0.88) || chrome.track, colors[0]] } }),
    ...(v.type === 'piecewise' ? {} : { text: [fmt.axis(high), fmt.axis(low)] }),
  }))
}

function toolboxLook(o, table, { chrome, colors }) {
  return list(o.toolbox).map(t => ({ ...at(t, { right: 0, top: 0 }), iconStyle: { borderColor: chrome.muted }, emphasis: { iconStyle: { borderColor: colors[0], textFill: chrome.ink } } }))
}

function brushLook(o, table, { chrome }) {
  return list(o.brush).map(() => ({ brushStyle: { color: chrome.shade, borderColor: chrome.axis, borderWidth: 1 } }))
}

function timelineLook({ chrome, colors }) {
  return {
    axisType: 'category', autoPlay: false, playInterval: 1600, left: 24, right: 24, bottom: 0, height: 44,
    label: { color: chrome.muted, fontSize: 12 }, lineStyle: { color: chrome.axis }, itemStyle: { color: chrome.axis },
    checkpointStyle: { color: colors[0], borderColor: chrome.surface }, controlStyle: { color: chrome.muted, borderColor: chrome.muted },
    progress: { lineStyle: { color: colors[0] }, itemStyle: { color: colors[0] } }, emphasis: { itemStyle: { color: colors[0] } },
  }
}

// Each component's look, in the order they are laid out: [the option's key, its look].
const COMPONENT_LOOKS = [
  ['title', titleLook],
  ['legend', legendLook],
  ['grid', gridLook],
  ['xAxis', (o, table, env) => list(o.xAxis).map(a => axisLook(a, 'x', table, env))],
  ['yAxis', (o, table, env) => list(o.yAxis).map(a => axisLook(a, 'y', table, env))],
  ['polar', polarLook],
  ['angleAxis', angleAxisLook],
  ['radiusAxis', radiusAxisLook],
  ['radar', radarLook],
  ['singleAxis', singleAxisLook],
  ['parallel', parallelLook],
  ['parallelAxis', parallelAxisLook],
  ['calendar', calendarLook],
  ['dataZoom', dataZoomLook],
  ['visualMap', visualMapLook],
  ['toolbox', toolboxLook],
  ['brush', brushLook],
]

// ---- the look of each series ----

const MARK_TYPES = { min: 'Lowest', max: 'Highest', average: 'Average', median: 'Median' }

// One series' look: a goal column's, or its type's; then its value labels and its reference lines, points and areas.
function seriesLook(s, env) {
  if (!plain(s)) return {}
  const dim = encodedColumn(s)
  const out = s.gfmGoal ? goalLook(s, env) : (SERIES_LOOKS.get(s.type)?.(s, env, dim) ?? {})
  addValueLabels(out, s, env, dim)
  addMarkLooks(out, s, env)
  return out
}

// The column a series shows, from its encode (dataset series), for its value labels: { dim, horizontal } or undefined.
function encodedColumn(s) {
  const enc = plain(s.encode) ? s.encode : null
  return enc && typeof enc.x === 'number' && typeof enc.y === 'number' ? (enc.y === 0 && enc.x !== 0 ? { dim: enc.x, horizontal: true } : { dim: enc.y, horizontal: false }) : undefined
}

// A goal column: a line of small squares in the goal colour, drawn above the other series.
function goalLook(s, env) {
  const { chrome, colors } = env
  const goal = env.goalColor || colors[s.gfmColumn % colors.length]
  return { color: goal, z: 3, symbol: 'rect', symbolSize: 7, showSymbol: (env.table?.labels.length ?? 0) <= 40, lineStyle: { width: 2, color: goal }, itemStyle: { color: goal, borderColor: chrome.surface, borderWidth: 1 } }
}

function lineLook(s, { chrome, table }) {
  return {
    symbol: 'circle', symbolSize: 8, showSymbol: (table?.labels.length ?? 0) <= 30, z: 4, lineStyle: { width: 2 }, itemStyle: { borderColor: chrome.surface, borderWidth: 2 }, emphasis: { focus: 'series' }, universalTransition: { enabled: true },
    ...(s.areaStyle ? { areaStyle: { opacity: 0.14 } } : {}),
  }
}

function barLook(s, env, dim) {
  const horizontal = dim?.horizontal
  return { barMaxWidth: 28, barGap: '15%', itemStyle: { borderRadius: s.stack ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] }, emphasis: { focus: 'series' }, universalTransition: { enabled: true } }
}

function scatterLook(s, { chrome }) {
  return { symbolSize: 11, itemStyle: { borderColor: chrome.surface, borderWidth: 1.5 }, universalTransition: { enabled: true }, ...(s.type === 'effectScatter' ? { rippleEffect: { brushType: 'stroke', scale: 3 } } : {}) }
}

function pictorialBarLook() {
  return { symbol: 'roundRect', symbolRepeat: true, symbolSize: [18, 7], symbolMargin: 2, symbolClip: true, barCategoryGap: '35%', universalTransition: { enabled: true } }
}

// Pies side by side when there are several.
function pieLook(s, env) {
  const { chrome } = env
  const n = env.pies.length, k = env.pies.indexOf(s)
  const donut = Array.isArray(s.radius) && parseFloat(s.radius[0]) > 0
  return {
    radius: n > 1 ? [0, `${Math.round(60 / Math.max(1, n - 0.4))}%`] : [0, '62%'],
    center: [n > 1 ? `${Math.round(((k + 0.5) / n) * 100)}%` : '50%', env.hasTitle ? '57%' : '52%'],
    avoidLabelOverlap: true, percentPrecision: 0,
    itemStyle: { borderColor: chrome.surface, borderWidth: 2, borderRadius: donut ? 4 : 2 },
    label: { color: chrome.soft, fontSize: 13, overflow: 'break' }, labelLine: { lineStyle: { color: chrome.axis } },
    emphasis: { scaleSize: 4 }, universalTransition: { enabled: true },
  }
}

function funnelLook(s, env) {
  const { chrome } = env
  return { sort: 'none', gap: 3, minSize: '14%', left: '6%', width: '58%', top: env.hasTitle ? 44 : 8, bottom: 8, label: { show: true, position: 'right', color: chrome.soft, fontSize: 13 }, labelLine: { lineStyle: { color: chrome.axis } }, itemStyle: { borderColor: chrome.surface, borderWidth: 1 } }
}

// A gauge: an arc that fills up to the value, with the number large in the middle.
function gaugeLook(s, env) {
  const { chrome, colors, fmt, ctx } = env
  return {
    min: 0, startAngle: 210, endAngle: -30, radius: '86%', center: ['50%', env.hasTitle ? '60%' : '55%'],
    progress: { show: true, width: 18, roundCap: true, itemStyle: { color: colors[0] } },
    axisLine: { roundCap: true, lineStyle: { width: 18, color: [[1, chrome.track]] } },
    pointer: { show: false }, anchor: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
    title: { show: true, offsetCenter: [0, '34%'], color: chrome.soft, fontSize: 14, fontFamily: ctx.font },
    detail: { offsetCenter: [0, '-4%'], valueAnimation: ctx.animate !== false, fontSize: 40, fontWeight: 600, color: chrome.ink, fontFamily: ctx.font, formatter: v => fmt.value(v) },
  }
}

function radarSeriesLook(s, { chrome }) {
  return { symbol: 'circle', symbolSize: 6, lineStyle: { width: 2 }, areaStyle: { opacity: 0.12 }, itemStyle: { borderColor: chrome.surface, borderWidth: 1 } }
}

function heatmapLook(s, { chrome, fmt }) {
  return { itemStyle: { borderColor: chrome.surface, borderWidth: 2, borderRadius: 3 }, emphasis: { itemStyle: { borderColor: chrome.ink, borderWidth: 1 } }, label: { color: chrome.ink, fontSize: 12, textBorderColor: chrome.surface, textBorderWidth: 2, formatter: p => fmt.value(valueOfParams(p)) } }
}

function treeLook(s, env) {
  const { chrome, colors } = env
  return {
    top: env.hasTitle ? 48 : 16, left: '14%', bottom: 16, right: '20%', symbolSize: 9, orient: 'LR', expandAndCollapse: true, initialTreeDepth: 3,
    itemStyle: { color: colors[0], borderColor: colors[0] }, lineStyle: { color: chrome.axis, width: 1.5 },
    label: { position: 'left', verticalAlign: 'middle', align: 'right', color: chrome.soft, fontSize: 13 },
    leaves: { label: { position: 'right', verticalAlign: 'middle', align: 'left' } }, emphasis: { focus: 'descendant' },
  }
}

function treemapLook(s, env) {
  const { chrome } = env
  return { roam: false, nodeClick: 'zoomToNode', breadcrumb: { show: true, bottom: 0, itemStyle: { color: chrome.track, textStyle: { color: chrome.ink } } }, top: env.hasTitle ? 40 : 2, left: 2, right: 2, bottom: 26, label: { show: true, color: '#ffffff', fontSize: 13 }, upperLabel: { show: true, height: 22, color: '#ffffff', fontSize: 12, fontWeight: 600 }, itemStyle: { borderColor: chrome.surface, borderWidth: 2, gapWidth: 2 }, levels: [{ itemStyle: { borderColor: chrome.surface, borderWidth: 3, gapWidth: 3 } }, { colorSaturation: [0.35, 0.6], itemStyle: { borderColorSaturation: 0.6, gapWidth: 1, borderWidth: 1 } }] }
}

function sunburstLook(s, env) {
  const { chrome } = env
  return { radius: [0, '90%'], center: ['50%', env.hasTitle ? '56%' : '50%'], sort: null, itemStyle: { borderColor: chrome.surface, borderWidth: 2 }, label: { color: '#ffffff', fontSize: 12, minAngle: 10, overflow: 'truncate' }, emphasis: { focus: 'ancestor' } }
}

function boxplotLook() {
  return { boxWidth: [14, 56], itemStyle: { borderWidth: 2 } }
}

// Candles: the palette's green for up and red for down.
function candlestickLook(s, { ctx }) {
  const pal = PALETTE[ctx.dark ? 'dark' : 'light']
  return { barMaxWidth: 24, itemStyle: { color: pal[5], color0: pal[7], borderColor: pal[5], borderColor0: pal[7] } }
}

function graphLook(s, env) {
  const { chrome, ctx } = env
  return {
    layout: 'force', roam: true, top: env.hasTitle ? 48 : 12, bottom: 12, left: 12, right: 12,
    force: { repulsion: 220, edgeLength: [60, 140], gravity: 0.08, layoutAnimation: ctx.animate !== false },
    label: { show: true, position: 'right', color: chrome.soft, fontSize: 12 }, edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 7,
    lineStyle: { color: 'source', curveness: 0.15, opacity: 0.6, width: 1.5 }, emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
  }
}

function chordLook(s, env) {
  const { chrome } = env
  return { center: ['50%', env.hasTitle ? '56%' : '52%'], radius: ['62%', '70%'], padAngle: 2, label: { show: true, color: chrome.soft, fontSize: 12 }, lineStyle: { color: 'source', opacity: 0.45 }, emphasis: { focus: 'adjacency' }, itemStyle: { borderColor: chrome.surface, borderWidth: 1 } }
}

function sankeyLook(s, env) {
  const { chrome } = env
  return { left: 8, right: 110, top: env.hasTitle ? 48 : 10, bottom: 10, nodeAlign: 'justify', nodeGap: 12, nodeWidth: 16, emphasis: { focus: 'adjacency' }, lineStyle: { color: 'gradient', opacity: 0.35, curveness: 0.5 }, label: { color: chrome.ink, fontSize: 12 }, itemStyle: { borderWidth: 0 } }
}

function themeRiverLook() {
  return { label: { show: false }, emphasis: { itemStyle: { shadowBlur: 12, shadowColor: 'rgba(0,0,0,0.25)' } } }
}

function parallelSeriesLook() {
  return { lineStyle: { width: 1.5, opacity: 0.55 }, emphasis: { lineStyle: { width: 3, opacity: 1 } }, inactiveOpacity: 0.08, activeOpacity: 1 }
}

function linesLook() {
  return { lineStyle: { width: 2, curveness: 0.2, opacity: 0.8 } }
}

// Which look a series type gets (a type not listed keeps ECharts' own).
const SERIES_LOOKS = new Map([
  ['line', lineLook],
  ['bar', barLook],
  ['scatter', scatterLook], ['effectScatter', scatterLook],
  ['pictorialBar', pictorialBarLook],
  ['pie', pieLook],
  ['funnel', funnelLook],
  ['gauge', gaugeLook],
  ['radar', radarSeriesLook],
  ['heatmap', heatmapLook],
  ['tree', treeLook],
  ['treemap', treemapLook],
  ['sunburst', sunburstLook],
  ['boxplot', boxplotLook],
  ['candlestick', candlestickLook],
  ['graph', graphLook],
  ['chord', chordLook],
  ['sankey', sankeyLook],
  ['themeRiver', themeRiverLook],
  ['parallel', parallelSeriesLook],
  ['lines', linesLook],
])

// Value labels a series switched on without a formatter of its own: numbers in the chart's number format.
function addValueLabels(out, s, { chrome, fmt }, dim) {
  const valueLabel = p => fmt.value(valueOfParams(p, dim?.dim))
  if (plain(s.label) && s.label.show && s.label.formatter === undefined && ['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar', 'radar', 'funnel'].includes(s.type))
    out.label = { color: chrome.soft, fontSize: 12, formatter: s.type === 'funnel' ? p => `${p.name}: ${fmt.value(p.value)}` : valueLabel }
  if (plain(s.label) && s.label.show && s.label.formatter === undefined && s.type === 'pie')
    out.label = { ...out.label, formatter: p => `${p.name}: ${fmt.value(p.value)} (${p.percent}%)` }
}

// Reference lines (dashed, with their number), marked points (lowest, highest …) and shaded areas.
function addMarkLooks(out, s, env) {
  const { chrome, fmt } = env
  if (plain(s.markLine)) {
    const data = list(s.markLine.data)
    out.markLine = {
      symbol: ['none', 'none'], silent: true,
      label: { color: chrome.soft, fontSize: 12, position: 'insideEndTop', formatter: p => `${p.name ? `${p.name} ` : ''}${fmt.value(p.value)}` },
      lineStyle: { color: chrome.soft, width: 1.5, type: 'dashed' },
      data: data.map(d => (plain(d) && d.type === 'average' && d.name === undefined ? { name: env.bound > 1 ? `${s.name} average` : 'Average' } : {})),
    }
  }
  if (plain(s.markPoint)) out.markPoint = { symbolSize: 46, label: { color: '#ffffff', fontSize: 11, formatter: p => fmt.value(p.value) }, data: list(s.markPoint.data).map(d => (plain(d) && d.type && d.name === undefined ? { name: MARK_TYPES[d.type] ?? d.type } : {})) }
  if (plain(s.markArea)) out.markArea = { itemStyle: { color: chrome.shade }, label: { color: chrome.muted, fontSize: 12 } }
}

// ---- putting it together -------------------------------------------------------------------

/** The option as arrays for the components that can appear more than once (ECharts takes both). */
function normalise(option) {
  const out = { ...option }
  for (const key of MULTI) if (out[key] !== undefined && !Array.isArray(out[key])) out[key] = [out[key]]
  return out
}

/** Axes and coordinate systems the series need but the option does not give. */
function addCoordinates(o, table, env) {
  const series = list(o.series)
  const on = type => series.some(s => plain(s) && coordinateOf(s) === type)
  if (on('cartesian2d')) {
    const cart = series.filter(s => plain(s) && coordinateOf(s) === 'cartesian2d')
    const numericLabels = !!table && table.labels.length > 0 && table.labels.every(l => toNumber(l, decimalMarkOf(table.labels)) !== null)
    const pointsOnly = cart.every(s => ['scatter', 'effectScatter', 'lines'].includes(s.type))
    const xType = (pointsOnly && numericLabels) || cart.every(s => s.type === 'lines') ? 'value' : 'category'
    const heat = cart.some(s => s.type === 'heatmap')
    if (o.grid === undefined) o.grid = [{}]
    // An axis without a type: categories along x (numbers for scattered points), values up y.
    o.xAxis = list(o.xAxis === undefined ? {} : o.xAxis).map(a => (a.type ? a : { ...a, type: xType }))
    o.yAxis = list(o.yAxis === undefined ? {} : o.yAxis).map(a => (a.type ? a : { ...a, type: heat ? 'category' : 'value' }))
    env.scatterOnly = pointsOnly
    env.numericX = pointsOnly && o.xAxis[0].type === 'value'
  }
  if (on('polar')) {
    if (o.polar === undefined) o.polar = [{}]
    if (o.angleAxis === undefined) o.angleAxis = [{ type: 'category' }]
    if (o.radiusAxis === undefined) o.radiusAxis = [{ type: 'value' }]
  }
  if (on('radar') && o.radar === undefined) o.radar = [{}]
  if (on('singleAxis') && o.singleAxis === undefined) o.singleAxis = [{ type: 'category' }]
  if (on('parallel') && o.parallel === undefined) o.parallel = [{}]
  if (on('calendar') && o.calendar === undefined && table) {
    const dates = datesOf(table).filter(Boolean).sort()
    o.calendar = [{ range: dates.length ? [dates[0], dates[dates.length - 1]] : new Date().getFullYear() }]
  }
  if (series.some(s => plain(s) && s.type === 'heatmap') && o.visualMap === undefined) o.visualMap = [{ calculable: true }]
  if (o.xAxis) o.xAxis = o.xAxis.map((a, i) => ({ ...a, gfmIndex: i }))
  if (o.yAxis) o.yAxis = o.yAxis.map((a, i) => ({ ...a, gfmIndex: i }))
}

function strip(value) {
  if (Array.isArray(value)) return value.map(strip)
  if (!plain(value)) return value
  const out = {}
  for (const [k, v] of Object.entries(value)) if (!k.startsWith('gfm')) out[k] = strip(v)
  return out
}

/**
 * The ECharts option for a table and a chart's option: the table bound to the
 * series, the mission look under it and the option on top. Null when there is
 * nothing to draw. `ctx` as for buildOption ({ dark, font, animate, ecStat,
 * width, height }).
 */
export function composeOption(table, given, ctx) {
  if (!plain(given)) return null
  if (optionIssue(table, given)) return null
  let option = copy(given)
  const gfm = plain(option.gfm) ? option.gfm : {}
  if (gfm.kind === 'tile') return tile(table, option, ctx)
  const chrome = CHROME[ctx.dark ? 'dark' : 'light']
  const colors = Array.isArray(option.color) && option.color.length ? option.color : PALETTE[ctx.dark ? 'dark' : 'light']
  const format = plain(gfm.format) ? gfm.format : {}
  const fmt = numberFormat({ format: format.style ?? (table?.unit === 'percent' ? 'percent' : 'auto'), decimals: format.decimals, prefix: format.prefix, suffix: format.suffix })
  if (gfm.kind === 'multiples' && table) option = multiples(option, table, { chrome })
  // A timeline shows one row of the table at a time (see timelineOption).
  if ((plain(option.timeline) || Array.isArray(option.timeline)) && option.options === undefined && table) return timelineOption(option, table, ctx, { chrome, colors, fmt, gfm })
  option = normalise(option)
  // Dataset 0 is the table; the option's own datasets follow (1, 2 …), then the trend lines'.
  const userSets = list(option.dataset).filter(d => plain(d) && (d.source !== undefined || d.transform !== undefined))
  const env = { table, ctx, chrome, colors, fmt, gfm, userSets, trendSets: [], axisData: [], heat: [], problems: [], barAxes: new Set(), colorIndex: s => s.gfmColumn ?? 0 }
  addCoordinates(option, table, env)
  env.horizontal = option.yAxis?.[0]?.type === 'category' && option.xAxis?.[0]?.type !== 'category'
  if (table) option = bindTable(option, table, env)
  if (env.problems.length && !list(option.series).length) return null
  if (table) option.dataset = [tableDataset(table, env.numericX), ...userSets, ...env.trendSets]
  for (const { axis, index, data } of env.axisData) {
    const axes = list(option[axis])
    if (axes[index] && axes[index].data === undefined) axes[index] = { ...axes[index], data }
    option[axis] = axes
  }
  const series = list(option.series)
  env.anyBar = series.some(s => BAR_LIKE.has(s?.type))
  for (const s of series) if (BAR_LIKE.has(s?.type)) { env.barAxes.add(`x:${s.xAxisIndex ?? 0}`); env.barAxes.add(`y:${s.yAxisIndex ?? 0}`) }
  const categoryX = list(option.xAxis).some(a => a.type === 'category')
  env.axisTrigger = series.length > 0 && series.every(s => ['line', 'bar', 'pictorialBar', 'candlestick', 'custom'].includes(s?.type) && coordinateOf(s) === 'cartesian2d') && (categoryX || list(option.yAxis).some(a => a.type === 'category'))
  env.xName = list(option.xAxis).some(a => text(a.name).trim())
  env.yName = list(option.yAxis).some(a => text(a.name).trim())
  env.goalColor = text(gfm.goal?.lineStyle?.color || gfm.goal?.color).trim()
  if (option.legend === undefined) {
    const named = series.filter(s => plain(s) && ['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar', 'boxplot', 'candlestick', 'custom', 'radar', 'themeRiver'].includes(s.type))
    const entries = named.reduce((n, s) => n + (s.type === 'radar' ? list(s.data).length : 1), 0) + (series.some(s => s?.type === 'themeRiver') ? 1 : 0)
    if (entries > 1) option.legend = [{}]
  }
  const look = missionLook(option, table, env)
  // Goal columns: the goal look, then gfm.goal's own settings.
  if (plain(gfm.goal)) {
    const own = { ...gfm.goal }
    delete own.column
    delete own.color
    option.series = list(option.series).map(s => (s?.gfmGoal ? mergeOption(own, s) : s))
  }
  let out = mergeOption(look, option)
  // Legend keys: a trend is its dashed line alone; the others drop the marker's ring.
  if (list(out.legend).length && series.some(s => s?.gfmTrend)) {
    out.legend = list(out.legend).map(l => (l.data !== undefined ? l : { ...l, data: list(out.series).filter(s => plain(s) && ['line', 'bar', 'scatter', 'effectScatter', 'pictorialBar', 'custom'].includes(s.type) && s.name).map(s => ({ name: s.name, itemStyle: s.gfmTrend ? { opacity: 0 } : { borderWidth: 0 } })) }))
  }
  out = strip(out)
  delete out.gfm
  if (ctx.animate === false) out.animation = false
  return out
}

/**
 * A timeline: one step per row of the table (a week, a zone …), each showing
 * that row's numbers across the columns, with ECharts' play button. The
 * option's first series decides the look of every step.
 */
function timelineOption(option, table, ctx, parts) {
  const { chrome, colors, fmt } = parts
  const template = { ...(list(option.series)[0] ?? { type: 'bar' }) }
  const names = table.series.filter(s => s.role !== 'goal').map(s => s.name)
  const columns = table.series.filter(s => s.role !== 'goal')
  const pie = template.type === 'pie' || template.type === 'funnel'
  const hasTitle = !!text(list(option.title)[0]?.text).trim()
  const base = { ...option }
  delete base.timeline
  delete base.gfm
  const cartesian = !pie && ON_AXES.has(template.type)
  const baseOption = mergeOption({
    color: colors, backgroundColor: 'transparent', textStyle: { fontFamily: ctx.font, color: chrome.ink },
    animationDurationUpdate: 600, animationEasingUpdate: 'cubicInOut',
    aria: { enabled: true, label: { description: spoken(text(list(option.title)[0]?.text).trim(), table, fmt) } },
    tooltip: { confine: true, trigger: 'item', backgroundColor: chrome.tip, borderColor: chrome.tipLine, borderWidth: 1, textStyle: { color: chrome.ink, fontSize: 13 }, valueFormatter: fmt.value },
    timeline: {
      axisType: 'category', autoPlay: false, playInterval: 1600, left: 24, right: 24, bottom: 0, height: 44, data: table.labels,
      label: { color: chrome.muted, fontSize: 12 }, lineStyle: { color: chrome.axis }, itemStyle: { color: chrome.axis },
      checkpointStyle: { color: colors[0], borderColor: chrome.surface }, controlStyle: { color: chrome.muted, borderColor: chrome.muted },
      progress: { lineStyle: { color: colors[0] }, itemStyle: { color: colors[0] } },
    },
    ...(hasTitle ? { title: { left: 0, top: 0, textStyle: { color: chrome.ink, fontSize: 18, fontWeight: 600 } } } : {}),
    ...(cartesian ? {
      grid: { left: 8, right: 18, top: (hasTitle ? 34 : 0) + 14, bottom: 64, containLabel: true },
      xAxis: { type: 'category', data: names, axisLine: { lineStyle: { color: chrome.axis } }, axisTick: { show: false }, axisLabel: { color: chrome.muted, fontSize: 12, interval: 0, hideOverlap: true } },
      yAxis: { type: 'value', axisLine: { show: false }, splitLine: { lineStyle: { color: chrome.grid } }, axisLabel: { color: chrome.muted, fontSize: 12, formatter: fmt.axis }, max: niceCeil(Math.max(0, ...columns.flatMap(c => c.values).filter(v => v !== null))) },
    } : {}),
    series: [mergeOption(pie
      ? { type: template.type, radius: [0, '58%'], center: ['50%', hasTitle ? '52%' : '46%'], itemStyle: { borderColor: chrome.surface, borderWidth: 2 }, label: { color: chrome.soft } }
      : { type: template.type, barMaxWidth: 36, itemStyle: { borderRadius: [4, 4, 0, 0] }, colorBy: 'data', universalTransition: { enabled: true } }, template)],
  }, base)
  const options = table.labels.map((label, i) => ({
    series: [{ name: label, data: pie ? columns.map(c => ({ name: c.name, value: c.values[i] })).filter(d => d.value !== null && d.value > 0) : columns.map(c => c.values[i]) }],
  }))
  const out = { baseOption: strip(baseOption), options }
  if (ctx.animate === false) out.baseOption.animation = false
  return out
}

// ---- the older settings as an option (for the builder) ------------------------------------------------

function listOf(value) {
  if (Array.isArray(value)) return value.map(v => String(v ?? '').trim()).filter(Boolean)
  if (typeof value === 'string' && value.trim()) return value.split(',').map(v => v.trim()).filter(Boolean)
  return []
}

/**
 * A chart written with the older settings as an option for the round-6
 * engine: what the builder opens when it edits such a chart (and writes back
 * when it is saved). Drawing an older chart never goes through here: the
 * slides draw it with buildOption, exactly as before.
 */
export function legacyToOption(props = {}) {
  const type = String(props.type ?? '').trim().toLowerCase() || 'line'
  const o = {}
  const gfm = {}
  addLegacyLook(props, o, gfm)
  const showValues = props.showValues === true || props.showValues === 'true'
  if (NOT_ON_AXES.includes(type)) addLegacyOtherChart(props, type, showValues, o, gfm)
  else addLegacyAxisChart(props, type, showValues, o, gfm)
  if (Object.keys(gfm).length) o.gfm = gfm
  const override = readOverride(props.option).value
  return override ? mergeOption(o, override) : o
}

// The older types that are not drawn on axes. Every other type (line, bar, area, scatter, and anything unknown)
// becomes a chart on axes.
const NOT_ON_AXES = ['pie', 'donut', 'gauge', 'tile', 'heatmap', 'radar', 'funnel', 'treemap', 'sunburst', 'boxplot', 'waterfall']

// What every older chart may set: its title, colours, number format, legend and goal column.
function addLegacyLook(props, o, gfm) {
  const title = text(props.title).trim()
  if (title) o.title = { text: title }
  const colors = listOf(props.colors)
  if (colors.length) o.color = colors
  const style = text(props.format).trim()
  const decimals = num(props.decimals)
  if ((style && style !== 'auto') || decimals !== null || text(props.prefix) || text(props.suffix)) {
    gfm.format = { ...(style && style !== 'auto' ? { style } : {}), ...(decimals !== null ? { decimals } : {}), ...(text(props.prefix) ? { prefix: text(props.prefix) } : {}), ...(text(props.suffix) ? { suffix: text(props.suffix) } : {}) }
  }
  const legend = text(props.legend).trim()
  if (legend === 'none') o.legend = { show: false }
  else if (legend === 'bottom') o.legend = { bottom: 0, left: 'center' }
  else if (legend === 'right') o.legend = { orient: 'vertical', right: 0, top: 'middle' }
  else if (legend === 'top') o.legend = {}
  const goalColumn = text(props.goal).trim()
  const goalColor = text(props.goalColor).trim()
  if (goalColumn || goalColor) gfm.goal = { ...(goalColumn ? { column: goalColumn } : {}), ...(goalColor ? { lineStyle: { color: goalColor }, itemStyle: { color: goalColor } } : {}) }
}

// A line, bar, area or scatter chart (also several of them mixed: seriesTypes), with its target line, axes and zoom.
function addLegacyAxisChart(props, type, showValues, o, gfm) {
  const kind = ['bar', 'area', 'scatter'].includes(type) ? type : 'line'
  const horizontal = (props.horizontal === true || props.horizontal === 'true') && kind === 'bar'
  const stack = (props.stack === true || props.stack === 'true') && kind !== 'scatter'
  const types = listOf(props.seriesTypes).map(t => t.toLowerCase()).filter(t => ['line', 'bar', 'area', 'scatter'].includes(t))
  o.series = (types.length ? types : [kind]).map(t => legacySeries(t, props, { horizontal, stack, showValues }))
  addLegacyTarget(props, o, horizontal)
  addLegacyAxes(props, o, kind, horizontal)
  if (props.dataZoom === true || props.dataZoom === 'true') o.dataZoom = [{ type: 'inside' }, { type: 'slider' }]
  if (props.multiples === true || props.multiples === 'true') gfm.kind = 'multiples'
}

// One series of an older chart on axes (t: line, bar, area or scatter), with its value labels, trend and average.
function legacySeries(t, props, { horizontal, stack, showValues }) {
  const s = { type: t === 'area' ? 'line' : t }
  if (t === 'area') s.areaStyle = {}
  if ((props.smooth === true || props.smooth === 'true') && s.type === 'line') s.smooth = true
  if (stack) s.stack = 'total'
  const position = { top: 'top', inside: 'inside', bottom: s.type === 'bar' ? 'insideBottom' : 'bottom' }[text(props.valuePosition).trim()]
  const where = horizontal && !position ? 'right' : position
  if (showValues) s.label = { show: true, ...(where ? { position: where } : {}) }
  const trend = trendMethod(props.trend)
  if (trend !== 'none' && !stack) s.gfm = { trend: legacyTrend(props, trend) }
  if (props.average === true || props.average === 'true') {
    const c = text(props.averageColor).trim()
    s.markLine = { data: [{ type: 'average', ...(c ? { lineStyle: { color: c, type: [2, 4] }, label: { color: c } } : {}) }] }
  }
  return s
}

// The trend line settings of an older chart (only those that differ from the defaults).
function legacyTrend(props, method) {
  const trend = { method }
  if (method === 'polynomial' && num(props.degree) !== null) trend.degree = num(props.degree)
  if (method === 'moving-average' && num(props.window) !== null) trend.window = num(props.window)
  if (num(props.forecast)) trend.forecast = num(props.forecast)
  if (text(props.trendColor).trim()) trend.color = text(props.trendColor).trim()
  if (num(props.trendWidth) !== null && num(props.trendWidth) !== 2) trend.width = num(props.trendWidth)
  if (text(props.trendStyle).trim() && text(props.trendStyle).trim() !== 'dashed') trend.style = text(props.trendStyle).trim()
  if (text(props.trendLabel).trim()) trend.label = text(props.trendLabel).trim()
  return trend
}

// The target of an older chart: a solid reference line on the first series, before its own reference lines.
function addLegacyTarget(props, o, horizontal) {
  const target = num(props.target)
  if (target === null) return
  const name = text(props.targetLabel).trim() || 'Target'
  const c = text(props.targetColor).trim()
  const first = o.series[0]
  first.markLine = { data: [{ [horizontal ? 'xAxis' : 'yAxis']: target, name, lineStyle: { type: 'solid', ...(c ? { color: c } : {}) }, ...(c ? { label: { color: c } } : {}) }, ...list(first.markLine?.data)] }
}

// The axes of an older chart: written only when they carry a setting (a title, a range, turned labels, sideways).
function addLegacyAxes(props, o, kind, horizontal) {
  // Scattered points keep an axis without a type: numbers when the labels are numbers.
  const category = kind === 'scatter' && !horizontal ? {} : { type: 'category' }
  const value = { type: 'value' }
  const rotate = num(props.labelRotate)
  if (rotate) category.axisLabel = { rotate: clamp(Math.round(rotate), -90, 90) }
  if (num(props.yMin) !== null) value.min = num(props.yMin)
  if (num(props.yMax) !== null) value.max = num(props.yMax)
  if (text(props.xTitle).trim()) category.name = text(props.xTitle).trim()
  if (text(props.yTitle).trim()) value.name = text(props.yTitle).trim()
  if (horizontal) { category.inverse = true; o.xAxis = value; o.yAxis = category }
  else {
    if (Object.keys(category).some(k => k !== 'type')) o.xAxis = category
    if (Object.keys(value).length > 1) o.yAxis = value
  }
}

// Every other older type: one series of the same kind.
function addLegacyOtherChart(props, type, showValues, o, gfm) {
  if (type === 'pie' || type === 'donut') {
    o.series = [{ type: 'pie', ...(type === 'donut' ? { radius: ['38%', '60%'] } : {}), ...(showValues ? { label: { show: true } } : {}) }]
  }
  else if (type === 'gauge') o.series = [{ type: 'gauge', ...(num(props.max) > 0 ? { max: num(props.max) } : {}) }]
  else if (type === 'tile') {
    gfm.kind = 'tile'
    if (num(props.target) !== null) gfm.target = num(props.target)
    o.series = [{ type: 'line', ...(props.smooth === true ? { smooth: true } : {}) }]
  }
  else if (type === 'heatmap') o.series = [{ type: 'heatmap', ...(showValues ? { label: { show: true } } : {}) }]
  else if (type === 'radar') {
    o.series = [{ type: 'radar', ...(showValues ? { label: { show: true } } : {}) }]
    if (num(props.max) > 0) o.radar = { max: num(props.max) }
  }
  else if (type === 'funnel') o.series = [{ type: 'funnel', ...(showValues ? { label: { show: true } } : {}) }]
  else if (type === 'treemap' || type === 'sunburst') o.series = [{ type, ...(showValues ? { label: { formatter: '{b}\n{c}' } } : {}) }]
  else if (type === 'boxplot') o.series = [{ type: 'boxplot' }]
  else if (type === 'waterfall') o.series = [{ type: 'custom', renderItem: 'waterfall', ...(showValues ? { label: { show: true } } : {}) }]
}
