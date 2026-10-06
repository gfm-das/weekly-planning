// Chart presets: the curated chart kinds a person chooses in GFM Studio (Trend, Goal vs actual, Ranked bar ...).
//
// A preset turns a chart's table into a good-looking ECharts option and, where the picture needs it, reshapes the table
// (sorted, cut to the top few, turned on its side). Everything it writes is plain ECharts plus the words the chart
// engine knows (`gfm.kind`, `gfm.goal`, `gfm.format`), so the result is an ordinary chart: a preset is a start, and any
// ECharts option written in the chart is merged over it (chart-engine.mjs chartView).
//
//   <MissionChart preset="ranked-bar" :query='{...}' />
//
// The mission look (colours, fonts, axes, spacing, labels sized for a call) is the engine's; presets add only what is
// particular to each kind: the orientation, the order, the labels and the number of things shown.
// Pure JavaScript, no imports (the caller passes the table; chart-engine.mjs merges the option).

const isNum = v => typeof v === 'number' && Number.isFinite(v)
const drawn = table => (table?.series ?? []).filter(s => s.role !== 'goal')
const goalOf = table => (table?.series ?? []).find(s => s.role === 'goal' || /\bgoal\b/i.test(s.name)) ?? null

/** The presets, in the order the picker shows them. `needs`: what the table must have for the preset to make sense. */
export const PRESETS = {
  trend: { label: 'Trend', description: 'How a number moves over the weeks, one line per number.', needs: 'weeks' },
  'goal-vs-actual': { label: 'Goal vs actual', description: 'Bars for the results with the goal drawn as a line across them.', needs: 'goal' },
  'ranked-bar': { label: 'Ranked bar', description: 'Zones, districts or areas from highest to lowest, with the numbers at the bars.', needs: 'units' },
  comparison: { label: 'Comparison', description: 'Two or three numbers side by side for each week or place.', needs: 'two numbers' },
  'big-number': { label: 'Big number', description: 'One number, large, with the change from before.', needs: 'one number' },
  progress: { label: 'Progress', description: 'How far each place is toward its goal, as a percentage.', needs: 'goal' },
  'cumulative-goal': { label: 'Cumulative goal', description: 'The running total against the running goal, to see whether the goal will be reached.', needs: 'weeks' },
  funnel: { label: 'Funnel', description: 'Steps from the first to the last, each narrower than the one before.', needs: 'several numbers' },
  'conversion-funnel': { label: 'Conversion funnel', description: 'A funnel that also says what share of the step before reached each step.', needs: 'several numbers' },
  leaderboard: { label: 'Leaderboard', description: 'A ranked list with place numbers (1, 2, 3 ...).', needs: 'units' },
  'small-multiples': { label: 'Small multiples', description: 'One small chart per number, side by side, on the same scale.', needs: 'several numbers' },
}

export const PRESET_IDS = Object.keys(PRESETS)

/** The preset named by a chart's settings (`preset`), or '' when it names none that exists. */
export function presetOf(props = {}) {
  const id = String(props?.preset ?? '').trim()
  return Object.hasOwn(PRESETS, id) ? id : ''
}

const copy = table => ({ ...table, labels: [...table.labels], series: table.series.map(s => ({ ...s, values: [...s.values] })) })

/** Rows in a new order and (top) cut short; every column follows. */
function reorder(table, order) {
  const labels = order.map(i => table.labels[i])
  const next = { ...table, labels, cells: undefined, series: table.series.map(s => ({ ...s, values: order.map(i => s.values[i]) })) }
  if (Array.isArray(table.weeks)) next.weeks = order.map(i => table.weeks[i])
  return next
}

/** The rows ordered by the first drawn column, highest first; rows without a number last. top = 0 keeps every row. */
function ranked(table, top, by = null) {
  const column = by ?? drawn(table)[0]
  if (!column) return table
  const order = column.values.map((v, i) => i).sort((a, b) => {
    const x = column.values[a], y = column.values[b]
    if (!isNum(x) && !isNum(y)) return a - b
    if (!isNum(x)) return 1
    if (!isNum(y)) return -1
    return y - x || a - b
  })
  const keep = order.filter(i => isNum(column.values[i]))
  const rows = (keep.length ? keep : order).slice(0, top > 0 ? top : undefined)
  return reorder(table, rows)
}

/**
 * Turns a table into a funnel: the steps are the drawn columns, one value each (the last row that has numbers, or the
 * total with `sum`). Returns the new one-column table.
 */
function stepsTable(table, aggregate = 'last') {
  const steps = drawn(table)
  const value = s => {
    const numbers = s.values.filter(isNum)
    if (!numbers.length) return null
    return aggregate === 'sum' ? numbers.reduce((a, b) => a + b, 0) : numbers[numbers.length - 1]
  }
  return { ...table, labels: steps.map(s => s.name), series: [{ name: 'Value', values: steps.map(value) }], head: 'Step', weeks: null, byUnit: true, cells: undefined }
}

/**
 * The option and (reshaped) table of a preset.
 *   opts.top        ranked kinds: how many to show (default 12; 0 = all)
 *   opts.aggregate  funnels: 'last' (the latest week, default) or 'sum' (all weeks)
 *   opts.target     big-number: the goal to compare with
 * Returns { table, option, problem }. `problem` is a sentence when the table does not suit the preset (the chart then
 * says so, instead of drawing something misleading).
 */
export function presetOption(id, table, opts = {}) {
  if (!Object.hasOwn(PRESETS, id)) return { table, option: {}, problem: `There is no chart kind called “${id}”.` }
  if (!table || !Array.isArray(table.series) || !drawn(table).length) return { table, option: {}, problem: '' }
  const many = drawn(table).length
  const top = Number.isInteger(opts.top) && opts.top >= 0 ? opts.top : 12
  const label = { show: true }

  switch (id) {
    case 'trend':
      return {
        table,
        option: {
          series: [{ type: 'line', smooth: false, showSymbol: true, symbolSize: 8, lineStyle: { width: 3 }, ...(many === 1 ? { endLabel: { show: true } } : {}) }],
          xAxis: { type: 'category', boundaryGap: false },
          yAxis: { type: 'value' },
        },
      }
    case 'goal-vs-actual': {
      const goal = goalOf(table)
      if (!goal) return { table, option: {}, problem: 'Goal vs actual needs a goal column: add a number named “Goal”, or use the mission goal.' }
      return {
        table,
        option: {
          series: [{ type: 'bar', label: { ...label, position: 'top' }, barMaxWidth: 56 }],
          gfm: { goal: { column: goal.name } },
        },
      }
    }
    case 'ranked-bar':
    case 'leaderboard': {
      const sorted = ranked(table, top)
      let shown = sorted
      if (id === 'leaderboard') shown = { ...sorted, labels: sorted.labels.map((l, i) => `${i + 1}. ${l}`) }
      return {
        table: shown,
        option: {
          series: [{ type: 'bar', label: { ...label, position: 'right' }, barMaxWidth: 34, itemStyle: { borderRadius: [0, 6, 6, 0] } }],
          xAxis: { type: 'value' },
          yAxis: { type: 'category', inverse: true, axisLabel: { interval: 0 } },
          ...(id === 'ranked-bar' && drawn(table).length > 1 ? { legend: { show: true } } : {}),
        },
      }
    }
    case 'comparison':
      if (many < 2) return { table, option: {}, problem: 'Comparison needs at least two numbers to put side by side.' }
      return {
        table: { ...table, series: [...drawn(table).slice(0, 3), ...table.series.filter(s => s.role === 'goal')] },
        option: { series: [{ type: 'bar', label: { ...label, position: 'top' }, barMaxWidth: 44, barGap: '8%' }] },
      }
    case 'big-number':
      return { table, option: { gfm: { kind: 'tile', ...(isNum(opts.target) ? { target: opts.target } : {}) } } }
    case 'progress': {
      const goal = goalOf(table)
      if (!goal) return { table, option: {}, problem: 'Progress needs a goal column: add a number named “Goal”, or use the mission goal.' }
      const actual = drawn(table)[0]
      const rows = actual.values.map((v, i) => (isNum(v) && isNum(goal.values[i]) && goal.values[i] > 0 ? (v / goal.values[i]) * 100 : null))
      const base = { ...table, series: [{ name: `${actual.name} (% of goal)`, values: rows }], unit: 'percent', cells: undefined }
      return {
        table: ranked(base, top),
        option: {
          series: [{ type: 'bar', label: { ...label, position: 'right' }, barMaxWidth: 34, itemStyle: { borderRadius: [0, 6, 6, 0] } }],
          xAxis: { type: 'value', max: 120 },
          yAxis: { type: 'category', inverse: true, axisLabel: { interval: 0 } },
          gfm: { format: { style: 'percent', decimals: 0 } },
        },
      }
    }
    case 'cumulative-goal': {
      const running = copy(table)
      for (const s of running.series) {
        let total = 0
        s.values = s.values.map(v => { if (isNum(v)) total += v; return isNum(v) ? total : null })
      }
      return {
        table: { ...running, cells: undefined },
        option: {
          series: [{ type: 'line', smooth: false, showSymbol: false, lineStyle: { width: 3 }, areaStyle: { opacity: 0.12 } }],
          xAxis: { type: 'category', boundaryGap: false },
          yAxis: { type: 'value' },
        },
      }
    }
    case 'funnel':
    case 'conversion-funnel': {
      if (many < 2) return { table, option: {}, problem: 'A funnel needs at least two steps: choose two or more numbers.' }
      const steps = stepsTable(table, opts.aggregate === 'sum' ? 'sum' : 'last')
      let shown = steps
      if (id === 'conversion-funnel') {
        const v = steps.series[0].values
        shown = { ...steps, labels: steps.labels.map((l, i) => (i === 0 || !isNum(v[i]) || !isNum(v[i - 1]) || v[i - 1] === 0 ? l : `${l} (${Math.round((v[i] / v[i - 1]) * 100)}% of the step before)`)) }
      }
      return {
        table: shown,
        option: { series: [{ type: 'funnel', sort: 'descending', gap: 4, label: { show: true, position: 'inside' }, left: '8%', width: '84%' }] },
      }
    }
    case 'small-multiples':
      return { table, option: { gfm: { kind: 'multiples' }, series: [{ type: 'bar' }] } }
    default:
      return { table, option: typeKindOption(id) ?? {}, problem: '' }
  }
}

/**
 * Which numbers of a table a chart shows (a story step uses this to bring numbers in one by one): `only` names the
 * columns to keep, `hide` the columns to leave out, `sort` orders the rows by the first column left ('desc'|'asc'),
 * `top` keeps the first rows. Goal columns stay with the columns they belong to unless named in `hide`. Names are
 * matched without regard to capitals. An `only` that names nothing that exists leaves the table as it is.
 */
export function shapeTable(table, shape) {
  if (!table || !Array.isArray(table.series) || !shape || typeof shape !== 'object' || Array.isArray(shape)) return table
  const names = list => (Array.isArray(list) ? list : typeof list === 'string' && list.trim() ? list.split(',') : []).map(n => String(n).trim().toLowerCase()).filter(Boolean)
  const only = names(shape.only)
  const hide = new Set(names(shape.hide))
  let series = table.series
  if (only.length) {
    const kept = series.filter(s => s.role !== 'goal' && only.includes(s.name.trim().toLowerCase()))
    if (kept.length) series = series.filter(s => s.role === 'goal' || kept.includes(s))
  }
  if (hide.size) series = series.filter(s => !hide.has(s.name.trim().toLowerCase()))
  let next = series === table.series ? table : { ...table, series }
  if (shape.sort === 'desc' || shape.sort === 'asc') {
    const first = drawn(next)[0]
    if (first) {
      const order = first.values.map((v, i) => i).sort((a, b) => {
        const x = first.values[a], y = first.values[b]
        if (!isNum(x) && !isNum(y)) return a - b
        if (!isNum(x)) return 1
        if (!isNum(y)) return -1
        return (shape.sort === 'desc' ? y - x : x - y) || a - b
      })
      next = reorder(next, order)
    }
  }
  const top = Number(shape.top)
  if (Number.isInteger(top) && top > 0 && top < next.labels.length) next = reorder(next, next.labels.slice(0, top).map((_, i) => i))
  return next
}

// ---- every chart type -----------------------------------------------------------------------------------------------
// Besides the curated kinds above, every chart type the engine can draw is a kind of its own (`type-<name>`): the plain
// chart with the mission look, to start from. `needs` says what the numbers must look like for that type.
// (The group tells the picker where to list it: 'kind' = curated, 'type' = plain chart type.)

const TYPE_KINDS = {
  line: { label: 'Line', needs: 'weeks or places', option: { series: [{ type: 'line' }] } },
  area: { label: 'Area', needs: 'weeks or places', option: { series: [{ type: 'line', areaStyle: {} }] } },
  'stacked-area': { label: 'Stacked area', needs: 'weeks or places, two or more numbers', option: { series: [{ type: 'line', stack: 'total', areaStyle: {} }] } },
  bar: { label: 'Bar', needs: 'weeks or places', option: { series: [{ type: 'bar' }] } },
  'stacked-bar': { label: 'Stacked bar', needs: 'two or more numbers', option: { series: [{ type: 'bar', stack: 'total' }] } },
  'horizontal-bar': { label: 'Horizontal bar', needs: 'places', option: { series: [{ type: 'bar' }], xAxis: { type: 'value' }, yAxis: { type: 'category', inverse: true } } },
  scatter: { label: 'Scatter', needs: 'two numbers (x and y)', option: { series: [{ type: 'scatter' }] } },
  'effect-scatter': { label: 'Scatter, ripples', needs: 'two numbers (x and y)', option: { series: [{ type: 'effectScatter' }] } },
  'pictorial-bar': { label: 'Pictorial bar', needs: 'weeks or places', option: { series: [{ type: 'pictorialBar' }] } },
  pie: { label: 'Pie', needs: 'one number for each part', option: { series: [{ type: 'pie' }] } },
  donut: { label: 'Donut', needs: 'one number for each part', option: { series: [{ type: 'pie', radius: ['38%', '60%'] }] } },
  gauge: { label: 'Gauge', needs: 'one number (and a goal)', option: { series: [{ type: 'gauge' }] } },
  radar: { label: 'Radar', needs: 'several numbers', option: { series: [{ type: 'radar' }] } },
  heatmap: { label: 'Heat map', needs: 'rows and several numbers', option: { series: [{ type: 'heatmap' }] } },
  'matrix-heatmap': { label: 'Heat map matrix', needs: 'rows and several numbers', option: { series: [{ type: 'heatmap', coordinateSystem: 'matrix' }] } },
  'calendar-heatmap': { label: 'Calendar heat map', needs: 'dates and one number', option: { series: [{ type: 'heatmap', coordinateSystem: 'calendar' }] } },
  treemap: { label: 'Tree map', needs: 'one number for each part (names may use " / " for groups)', option: { series: [{ type: 'treemap' }] } },
  sunburst: { label: 'Sunburst', needs: 'one number for each part (names may use " / " for groups)', option: { series: [{ type: 'sunburst' }] } },
  boxplot: { label: 'Box plot', needs: 'several numbers, many rows', option: { series: [{ type: 'boxplot' }] } },
  candlestick: { label: 'Candlestick', needs: 'open, close, low and high', option: { series: [{ type: 'candlestick' }] } },
  waterfall: { label: 'Waterfall', needs: 'steps with gains and losses', option: { series: [{ type: 'custom', renderItem: 'waterfall' }] } },
  range: { label: 'Range', needs: 'the lowest and the highest number', option: { series: [{ type: 'custom', renderItem: 'range' }] } },
  errorbar: { label: 'Error bars', needs: 'the lowest and the highest number', option: { series: [{ type: 'custom', renderItem: 'errorbar' }] } },
  tree: { label: 'Tree', needs: 'names with " / " for groups, and a number', option: { series: [{ type: 'tree' }] } },
  graph: { label: 'Network', needs: 'from, to and a number', option: { series: [{ type: 'graph', layout: 'circular' }] } },
  sankey: { label: 'Sankey (flows)', needs: 'from, to and a number', option: { series: [{ type: 'sankey' }] } },
  chord: { label: 'Chord', needs: 'from, to and a number', option: { series: [{ type: 'chord' }] } },
  'theme-river': { label: 'Theme river', needs: 'weeks and several numbers', option: { series: [{ type: 'themeRiver' }] } },
  parallel: { label: 'Parallel coordinates', needs: 'several numbers', option: { series: [{ type: 'parallel' }] } },
  'polar-bar': { label: 'Polar bar', needs: 'weeks or places', option: { series: [{ type: 'bar', coordinateSystem: 'polar' }] } },
}

for (const [name, kind] of Object.entries(TYPE_KINDS)) {
  PRESETS[`type-${name}`] = { label: kind.label, description: `A plain ${kind.label.toLowerCase()} chart with the mission look.`, needs: kind.needs, group: 'type' }
}
for (const id of Object.keys(PRESETS)) PRESETS[id].group ??= 'kind'
PRESET_IDS.splice(0, PRESET_IDS.length, ...Object.keys(PRESETS))

/** The option of a plain chart type preset (`type-<name>`), or null. */
export function typeKindOption(id) {
  const name = String(id).startsWith('type-') ? String(id).slice(5) : ''
  return Object.hasOwn(TYPE_KINDS, name) ? JSON.parse(JSON.stringify(TYPE_KINDS[name].option)) : null
}
