// The chart builder's non-visual parts: reading a chart written in a slide,
// writing the <MissionChart> tag for it (with its chart-id), finding it again
// on the slide, and the chart types of the type picker. Pure JavaScript (no
// DOM, no Vue), so it runs in /studio (the manager serves it at
// /_manager/chart/ for manager/chart-builder.mjs) and in plain Node for the
// tests (slidev/tests/chart-builder.test.mjs). No slide imports it.
import { canonicalJson, normalizeSpec, parseLoose } from './chart-spec.mjs'
import { KPI_NAMES, kpiId, readOverride } from './chart-core.mjs'
import { isOptionChart, legacyToOption, readOption, SERIES_TYPES } from './chart-engine.mjs'

// How each setting of <MissionChart> is written, and its default (a setting
// at its default is left out of the tag, as someone writing by hand would).
export const PROPS = {
  type: ['text', 'line'],
  title: ['text', ''],
  trend: ['text', 'none'],
  degree: ['number', 2],
  trendColor: ['text', ''],
  colors: ['list', null],
  showValues: ['switch', false],
  height: ['number', 360],
  max: ['number', null],
  trendStyle: ['text', 'dashed'],
  trendWidth: ['number', 2],
  trendLabel: ['text', ''],
  window: ['number', 3],
  forecast: ['number', 0],
  goal: ['text', ''],
  goalColor: ['text', ''],
  target: ['number', null],
  // The name of a line at a set number. Charts written without one keep "Target" (changing it would change
  // their legends); the builder suggests "Goal" for a new line (Preach My Gospel: goals, not targets).
  targetLabel: ['text', 'Target'],
  targetColor: ['text', ''],
  average: ['switch', false],
  averageColor: ['text', ''],
  legend: ['text', 'auto'],
  xTitle: ['text', ''],
  yTitle: ['text', ''],
  yMin: ['number', null],
  yMax: ['number', null],
  labelRotate: ['number', 0],
  format: ['text', 'auto'],
  decimals: ['number', null],
  prefix: ['text', ''],
  suffix: ['text', ''],
  valuePosition: ['text', 'auto'],
  stack: ['switch', false],
  horizontal: ['switch', false],
  smooth: ['switch', false],
  seriesTypes: ['list', null],
  multiples: ['switch', false],
  dataZoom: ['switch', false],
}
// Where the numbers come from; written after the look.
const DATA = ['query', 'rows', 'csv', 'data', 'option']
// <MissionKpiChart> settings with the same meaning in <MissionChart>.
const KPI_SHARED = ['trend', 'degree', 'trendColor', 'colors', 'goalColor', 'title', 'height', 'showValues', 'trendStyle', 'trendWidth', 'trendLabel', 'window', 'forecast', 'target', 'targetLabel', 'targetColor', 'average', 'averageColor', 'legend', 'yMin', 'yMax', 'smooth', 'valuePosition', 'dataZoom']

/** The key indicators, in Call-ins order (ids as the query writes them). */
export const KEY_INDICATORS = Object.keys(KPI_NAMES)

/** The week counts offered as chips (any other number can be typed). */
export const WEEK_CHOICES = [1, 4, 8, 12, 26, 52]

// What a transform adds to a title (the numbers as they are add nothing).
const TRANSFORM_TITLES = { pct_of_goal: ': % of goal', cumulative: ': running total', rolling4: ': average of 4 weeks', per_area: ', per area' }

/**
 * A title that says what the chart shows, for a normalised query and the
 * name of its number: "Sacrament attendance by zone, last 4 weeks".
 */
export function chartTitle(spec, name) {
  const unit = spec.level === 'mission' ? '' : ` by ${spec.level}`
  const how = TRANSFORM_TITLES[spec.transform] || ''
  if (spec.by !== 'unit') return `${name}${unit}${how}`
  const weeks = spec.weeks.last === 1 ? 'this week' : `last ${spec.weeks.last} weeks`
  return `${name}${unit}${how}, ${weeks}`
}

/**
 * The names of the numbers in a chart, for its title: "New members",
 * "New members and new members at church", "A, b and c". Sentence case: a
 * later name starts with a small letter unless it begins with an
 * abbreviation (GEMIKO). More than three names make a title too long: ''.
 */
export function numbersName(names) {
  const list = names.map(n => String(n ?? '').trim())
  if (!list.length || list.length > 3 || list.some(n => !n)) return ''
  const small = n => /^[A-Z]{2}/.test(n) ? n : n.charAt(0).toLowerCase() + n.slice(1)
  const [first, ...rest] = list
  if (!rest.length) return first
  const later = rest.map(small)
  return `${[first, ...later.slice(0, -1)].join(', ')} and ${later.at(-1)}`
}

function kebab(name) {
  return name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)
}

function camel(name) {
  return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
}

/** Text for a double-quoted attribute: quotes, tags and ampersands as entities. */
function attrText(value) {
  return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** A JavaScript string in single quotes that is safe inside a double-quoted attribute. */
function jsString(value) {
  return `'${String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\x22').replace(/</g, '\\x3c').replace(/>/g, '\\x3e').replace(/&/g, '\\x26').replace(/\r?\n/g, '\\n').replace(/\t/g, '\\t')}'`
}

/** JSON that is safe inside a single-quoted attribute (quote, tags and & as \u escapes). */
function jsonAttr(value) {
  return JSON.stringify(value).replace(/'/g, '\\u0027').replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
}

function empty(value) {
  return value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)
}

/**
 * A pasted table as `:rows` entries: one string per row, as it was typed or
 * pasted (tabs from a spreadsheet stay tabs). parseRows reads each row with
 * its own separator. Null when there are not at least a heading and a row.
 */
export function tableRows(text) {
  const source = String(text ?? '').replace(/\r\n?/g, '\n').trim()
  if (!source) return null
  const rows = (source.includes('\n') ? source.split('\n') : source.split(';')).map(l => l.trim()).filter(Boolean)
  return rows.length >= 2 ? rows : null
}

/**
 * The <MissionChart> tag for a builder model:
 * { props: {...look}, spec (a normalised query) or rows (a table), option (JSON text), keep: [raw attributes] }.
 */
export function chartTag(model) {
  const parts = ['<MissionChart']
  const props = model.props ?? {}
  const type = props.type || 'line'
  parts.push(`type="${attrText(type)}"`)
  for (const [name, [kind, fallback]] of Object.entries(PROPS)) {
    if (name === 'type') continue
    const value = props[name]
    if (empty(value) || value === fallback || (kind === 'number' && !Number.isFinite(Number(value)))) continue
    if (kind === 'number' && Number(value) === fallback) continue
    if (kind === 'switch') { if (value === true) parts.push(kebab(name)); continue }
    if (kind === 'number') parts.push(`:${kebab(name)}="${Number(value)}"`)
    else if (kind === 'list') parts.push(`:${kebab(name)}="[${value.map(jsString).join(', ')}]"`)
    else parts.push(`${kebab(name)}="${attrText(value)}"`)
  }
  if (model.spec) parts.push(`:query='${canonicalJson(normalizeSpec(model.spec))}'`)
  else if (model.rows?.length) parts.push(`:rows="[${model.rows.map(jsString).join(', ')}]"`)
  const option = readOverride(model.option)
  if (option.value && Object.keys(option.value).length) parts.push(`:option='${jsonAttr(option.value)}'`)
  for (const raw of model.keep ?? []) parts.push(raw)
  return `${parts.join(' ')} />`
}

// ---- reading a chart written in a slide ------------------------------------------

const RE_OPEN = /<(MissionChart|MissionKpiChart|mission-chart|mission-kpi-chart)(?=[\s/>])/g
// How Studio's scanner (slidev-addon-studio node/html-scan.ts) reads an
// opening tag; its fingerprint is taken from "<Name" plus the attributes.
const RE_STUDIO_OPEN = /<([A-Za-z][\w.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/y

/**
 * Studio's fingerprint of an opening tag, copied from slidev-addon-studio
 * (shared/signature.ts). Studio stamps it on every tag it lets people select
 * (`data-studio-sig`), so the builder can tell two charts on the same line
 * apart: they share the line range Studio's selection gives.
 */
export function tagSignature(openingTag) {
  const normalised = String(openingTag ?? '')
    .replace(/\sdata-studio-[\w-]+="[^"]*"/g, '')
    .replace(/\s:?markdownSource="[^"]*"/g, '')
    .replace(/\sv-drag(?:="[^"]*")?/g, '')
    .replace(/\s:?pos="[^"]*"/g, '')
    .replace(/\/\s*>?\s*$/, '')
    .replace(/>\s*$/, '')
    .replace(/\s+/g, ' ')
    .trim()
  // FNV-1a, as in Studio.
  let hash = 0x811C9DC5
  for (let i = 0; i < normalised.length; i++) {
    hash ^= normalised.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash.toString(36)
}

/**
 * Every chart tag in `text`, in order: { tag, start, end, attrs: [{ name, value, raw }], sig }
 * (end is just after "/>" or "</MissionChart>"; sig is Studio's fingerprint of
 * the opening tag). Tags inside HTML comments are left out, as Studio does.
 */
export function findChartTags(text) {
  const source = String(text ?? '')
  const visible = source.replace(/<!--[\s\S]*?-->/g, c => ' '.repeat(c.length))
  const re = new RegExp(RE_OPEN.source, 'g')
  const found = []
  let open
  while ((open = re.exec(visible))) {
    const chart = readChartTag(source, open)
    if (chart) found.push(chart)
  }
  return found
}

/** The first chart tag in `text` (see findChartTags), or null. */
export function findChartTag(text) {
  return findChartTags(text)[0] ?? null
}

/**
 * The chart Studio's selection points at, among the chart tags in `text` (the
 * selected lines): { found, index, count } or { problem, count } (problem is a
 * key of PICK_PROBLEMS). With Studio's fingerprint `sig`, the one chart with
 * that fingerprint: charts written side by side on one line share the line
 * range, so the lines alone cannot say which was clicked. Without a
 * fingerprint, only when the lines hold a single chart.
 */
export function pickChartTag(text, sig = '') {
  const tags = findChartTags(text)
  const count = tags.length
  if (!count) return { problem: 'none', count }
  if (sig) {
    const same = tags.filter(t => t.sig === sig)
    if (same.length === 1) return { found: same[0], index: tags.indexOf(same[0]), count }
    return { problem: same.length ? 'twins' : 'gone', count }
  }
  return count === 1 ? { found: tags[0], index: 0, count } : { problem: 'several', count }
}

/** What Edit chart says when pickChartTag cannot tell which chart is meant. */
export const PICK_PROBLEMS = {
  none: 'The selected element is not a chart any more. Click the chart on the slide and choose Edit chart again.',
  gone: 'The builder cannot find the chart you clicked in the slide (it may have just changed). Click it again and choose Edit chart.',
  twins: 'This slide has two identical charts on the same line, so the builder cannot tell which one you clicked. In Source, put each chart on its own line, then try again.',
  several: 'There are several charts on this line, so the builder cannot tell which one you clicked. In Source, put each chart on its own line, then try again.',
}

const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth']
const COUNTS = ['', 'one', 'two', 'three', 'four', 'five', 'six']

/**
 * Which chart the builder is editing, for its header: “New people being taught”, or
 * "the selected chart"; with more charts on the same line also which one
 * ("the second of two charts on that line").
 */
export function chartName(title, index = 0, count = 1) {
  const name = String(title ?? '').trim()
  const quoted = name ? `“${name}”` : 'the selected chart'
  if (!(count > 1)) return quoted
  const which = index < ORDINALS.length && count < COUNTS.length ? `the ${ORDINALS[index]} of ${COUNTS[count]} charts on that line` : `chart ${index + 1} of ${count} on that line`
  return `${quoted} (${which})`
}

function readChartTag(source, open) {
  const tag = open[1].includes('-') ? (open[1] === 'mission-chart' ? 'MissionChart' : 'MissionKpiChart') : open[1]
  RE_STUDIO_OPEN.lastIndex = open.index
  const studio = RE_STUDIO_OPEN.exec(source)
  const sig = studio ? tagSignature(source.slice(open.index, open.index + 1 + studio[1].length + studio[2].length)) : ''
  let i = open.index + open[0].length
  const attrs = []
  while (i < source.length) {
    while (/\s/.test(source[i] ?? '')) i++
    if (source.startsWith('/>', i)) return { tag, start: open.index, end: i + 2, attrs, sig }
    if (source[i] === '>') {
      const close = source.indexOf(`</${open[1]}>`, i)
      return close < 0 ? null : { tag, start: open.index, end: close + open[1].length + 3, attrs, sig }
    }
    const name = source.slice(i).match(/^[^\s=/>"']+/)?.[0]
    if (!name) return null
    const from = i
    i += name.length
    let value = null
    let j = i
    while (/\s/.test(source[j] ?? '')) j++
    if (source[j] === '=') {
      j++
      while (/\s/.test(source[j] ?? '')) j++
      const quote = source[j]
      if (quote === '"' || quote === "'") {
        const endQuote = source.indexOf(quote, j + 1)
        if (endQuote < 0) return null
        value = source.slice(j + 1, endQuote)
        i = endQuote + 1
      }
      else {
        const bare = source.slice(j).match(/^[^\s/>]+/)?.[0] ?? ''
        value = bare
        i = j + bare.length
      }
    }
    attrs.push({ name, value, raw: source.slice(from, i) })
  }
  return null
}

function decode(text) {
  return String(text).replace(/&(quot|#34|apos|#39|lt|gt|amp);/g, (_, e) => ({ quot: '"', '#34': '"', apos: "'", '#39': "'", lt: '<', gt: '>', amp: '&' })[e])
}

/** An attribute's value: bound ones (":x") are read as JSON or a simple JavaScript literal. */
function attrValue(attr) {
  if (attr.value === null) return true
  if (!attr.bound) return decode(attr.value)
  const text = decode(attr.value).trim()
  if (text === 'true') return true
  if (text === 'false') return false
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text)
  const parsed = parseLoose(text)
  return parsed === undefined ? parseLiteral(text) : parsed
}

/**
 * A JavaScript literal of plain data (lists, objects, strings in single or
 * double quotes with their escapes \t \' \x3c ' …, numbers, true, false,
 * null), as the builder writes :rows and Studio writes lists. Tables pasted
 * from a spreadsheet keep their tabs as \t, which a plain JSON reading
 * refused, so Edit chart opened such a chart without its numbers.
 */
export function parseLiteral(text) {
  const source = String(text ?? '')
  // Bare keys are quoted and trailing commas dropped only outside strings: a
  // pasted cell like 'New people, goal: 10' must stay exactly as it is.
  const fix = plain => plain.replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":').replace(/,\s*([}\]])/g, '$1')
  let out = ''
  let plain = ''
  for (let i = 0; i < source.length; i++) {
    const c = source[i]
    if (c !== "'" && c !== '"') { plain += c; continue }
    out += fix(plain)
    plain = ''
    let value = ''
    let j = i + 1
    for (; j < source.length && source[j] !== c; j++) {
      if (source[j] !== '\\') { value += source[j]; continue }
      const e = source[++j]
      if (e === 'x') { value += String.fromCharCode(Number.parseInt(source.slice(j + 1, j + 3), 16)); j += 2 }
      else if (e === 'u') { value += String.fromCharCode(Number.parseInt(source.slice(j + 1, j + 5), 16)); j += 4 }
      else value += { n: '\n', t: '\t', r: '\r', b: '\b', f: '\f', v: '\v', 0: '\0' }[e] ?? e
    }
    if (j >= source.length) return undefined
    out += JSON.stringify(value)
    i = j
  }
  try { return JSON.parse(out + fix(plain)) }
  catch { return undefined }
}

/**
 * What the builder needs to edit a chart tag: { tag, model, notes }. A
 * <MissionKpiChart> becomes the same chart from the database (it is saved as a
 * <MissionChart>). Attributes the builder does not know (class, v-click …) are
 * kept as they are.
 */
export function tagToModel(found) {
  const props = {}
  const keep = []
  const values = {}
  for (const attr of found.attrs) {
    const bound = attr.name.startsWith(':') || attr.name.startsWith('v-bind:')
    const name = camel(attr.name.replace(/^(:|v-bind:)/, ''))
    const value = attrValue({ ...attr, bound })
    if (value === undefined) { keep.push(attr.raw); continue }
    values[name] = { value, raw: attr.raw }
  }
  const model = { source: 'mission', props, spec: null, rows: null, option: '', keep }
  const notes = []
  if (found.tag === 'MissionKpiChart') {
    const kpi = kpiId(values.kpi?.value)
    const showGoal = values.showGoal ? values.showGoal.value !== false : true
    const weeks = Math.min(104, Math.max(1, Math.round(Number(values.weeks?.value) || 12)))
    model.spec = normalizeSpec({ measures: showGoal ? [`${kpi}.actual`, `${kpi}.previous_goal`] : [`${kpi}.actual`], weeks })
    const chart = String(values.chart?.value ?? 'bar').toLowerCase()
    props.type = ['line', 'area', 'tile'].includes(chart) ? chart : 'bar'
    props.trend = 'linear'
    for (const key of KPI_SHARED) if (values[key] !== undefined) props[key] = values[key].value
    if (values.option) model.option = typeof values.option.value === 'string' ? values.option.value : JSON.stringify(values.option.value, null, 2)
    for (const [name, { raw }] of Object.entries(values)) if (!KPI_SHARED.includes(name) && !['kpi', 'showGoal', 'weeks', 'chart', 'option'].includes(name)) keep.push(raw)
    notes.push('This live key indicator chart will be saved as a chart from mission numbers, with the same look.')
    return { tag: found.tag, model, notes }
  }
  for (const [name, { value, raw }] of Object.entries(values)) {
    if (name === 'query') {
      try { model.spec = normalizeSpec(value) }
      catch (error) { notes.push(`Its query had a mistake (${error.message}), so the builder starts with a new one.`) }
    }
    else if (name === 'rows') model.rows = Array.isArray(value) ? value.map(String) : null
    else if (name === 'csv') model.csv = String(value)
    else if (name === 'data') keep.push(raw)
    else if (name === 'option') model.option = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
    else if (Object.hasOwn(PROPS, name)) props[name] = value
    else keep.push(raw)
  }
  if (!model.spec) {
    model.source = model.rows || model.csv ? 'table' : 'mission'
    if (model.csv && !model.rows) model.rows = tableRows(model.csv)
  }
  if (values.data) notes.push('Its numbers are written as `data`; the builder keeps them and changes only the look.')
  return { tag: found.tag, model, notes }
}

// ---- the slide's lines ---------------------------------------------------------

export function toLines(content) {
  return String(content ?? '').split(/\r?\n/)
}

/** The lines [start, end) of a slide, as Studio's selection gives them. */
export function blockAt(content, range) {
  return toLines(content).slice(range[0], range[1]).join('\n')
}

/**
 * Where the chart being edited is now: its lines if they are unchanged, else
 * the only place the same text appears. Null when it was changed or moved and
 * cannot be found for sure.
 */
export function locateBlock(content, range, block) {
  const lines = toLines(content)
  if (lines.slice(range[0], range[1]).join('\n') === block) return range
  const wanted = toLines(block)
  const found = []
  for (let i = 0; i + wanted.length <= lines.length; i++)
    if (lines.slice(i, i + wanted.length).join('\n') === block) found.push(i)
  return found.length === 1 ? [found[0], found[0] + wanted.length] : null
}

/**
 * The slide with the chart tag inside lines `range` replaced by `tag`
 * (everything around it kept). `sig` (Studio's fingerprint, see pickChartTag)
 * says which chart when there are several; null when it is not clear.
 */
export function replaceChart(content, range, tag, sig = '') {
  const lines = toLines(content)
  const block = lines.slice(range[0], range[1]).join('\n')
  const { found } = pickChartTag(block, sig)
  if (!found) return null
  const next = block.slice(0, found.start) + tag + block.slice(found.end)
  lines.splice(range[0], range[1] - range[0], ...toLines(next))
  return lines.join('\n')
}

/** The slide with `text` added after lines `range` (or at the end), with a blank line before it. */
export function insertChart(content, text, range = null) {
  const lines = toLines(content)
  const at = range ? range[1] : lines.length
  while (!range && lines.length && lines[lines.length - 1].trim() === '') lines.pop()
  const before = range ? at : lines.length
  lines.splice(before, 0, '', ...toLines(text.trim()))
  return lines.join('\n')
}

// ---- round 6: chart ids, a chart as numbers plus an option ---------------------------

/**
 * A new chart-id: "c" and six letters or digits, not one of `taken`. Written
 * into the tag, so Edit chart always finds (and changes) the chart it opened,
 * wherever Studio's selection or the lines have moved.
 */
export function newChartId(taken = [], random = Math.random) {
  for (;;) {
    let id = 'c'
    while (id.length < 7) id += '0123456789abcdefghijklmnopqrstuvwxyz'[Math.floor(random() * 36)]
    if (!taken.includes(id)) return id
  }
}

/** A chart tag's chart-id (from findChartTags), or ''. */
export function chartIdOf(found) {
  const attr = found?.attrs?.find(a => a.name === 'chart-id' || a.name === 'chartId')
  return attr && attr.value !== null ? decode(attr.value).trim() : ''
}

/** Every chart-id on a slide. */
export function chartIds(text) {
  return findChartTags(text).map(chartIdOf).filter(Boolean)
}

function lineStart(content, line) {
  let at = 0
  for (let i = 0; i < line; i++) {
    const next = content.indexOf('\n', at)
    if (next < 0) return content.length
    at = next + 1
  }
  return at
}

/** What Edit chart says when locateChart cannot find the chart for sure. */
export const LOCATE_PROBLEMS = {
  ...PICK_PROBLEMS,
  changed: 'This chart was changed somewhere else while you were editing it, so nothing was saved. Close the builder, select the chart again and choose Edit chart.',
  missing: 'The chart is not on the slide any more (it was moved or deleted), so nothing was saved.',
}

/**
 * Where a chart is on a slide now: { found, duplicate } (found with start and
 * end in `content`) or { problem } (a key of LOCATE_PROBLEMS). `target` is
 * { id, range, block, sig }: with a chart-id, the one tag with that id
 * (when a copy kept the id, the copy on the opened lines with Studio's
 * fingerprint, and `duplicate` says the id must change); without one (older
 * charts), the opened lines if unchanged and Studio's fingerprint, as before.
 */
export function locateChart(content, target) {
  const text = String(content ?? '')
  if (target.id) {
    const same = findChartTags(text).filter(t => chartIdOf(t) === target.id)
    if (same.length === 1) return { found: same[0], duplicate: false }
    if (!same.length) return { problem: 'missing' }
  }
  if (!Array.isArray(target.range)) return { problem: target.id ? 'twins' : 'none' }
  const at = locateBlock(text, target.range, target.block ?? blockAt(text, target.range))
  if (!at) return { problem: 'changed' }
  const offset = lineStart(text, at[0])
  const lines = text.slice(offset).split('\n').slice(0, at[1] - at[0]).join('\n')
  const picked = pickChartTag(lines, target.sig)
  if (!picked.found) return { problem: picked.problem }
  const found = { ...picked.found, start: picked.found.start + offset, end: picked.found.end + offset }
  return { found, duplicate: !!target.id }
}

/** The slide with the chart `found` (from locateChart) replaced by `tag`; everything around it stays as it was. */
export function replaceTag(content, found, tag) {
  return String(content).slice(0, found.start) + tag + String(content).slice(found.end)
}

const DATA_ATTRS = new Set(['query', 'rows', 'csv', 'data', 'option', 'height', 'chartId'])

/**
 * A chart tag as the round-6 builder edits it: { tag, chartId, source
 * ('mission' | 'table' | 'data'), spec, rows, option (an object), height,
 * keep, legacy, notes }. A chart written with the older settings (or a
 * <MissionKpiChart>) becomes the same chart as an ECharts option
 * (legacyToOption); it is saved that way.
 */
export function readChart(found) {
  const values = {}
  const keep = []
  for (const attr of found.attrs) {
    const bound = attr.name.startsWith(':') || attr.name.startsWith('v-bind:')
    const name = camel(attr.name.replace(/^(:|v-bind:)/, ''))
    const value = attrValue({ ...attr, bound })
    if (value === undefined) { keep.push(attr.raw); continue }
    values[name] = { value, raw: attr.raw }
  }
  const model = { tag: found.tag, chartId: chartIdOf(found), source: 'mission', spec: null, rows: null, option: {}, height: 360, keep, legacy: false, notes: [] }
  const height = Number(values.height?.value)
  if (Number.isFinite(height) && height > 0) model.height = height
  if (found.tag === 'MissionKpiChart') {
    const kpi = kpiId(values.kpi?.value)
    const showGoal = values.showGoal ? values.showGoal.value !== false : true
    const weeks = Math.min(104, Math.max(1, Math.round(Number(values.weeks?.value) || 12)))
    model.spec = normalizeSpec({ measures: showGoal ? [`${kpi}.actual`, `${kpi}.previous_goal`] : [`${kpi}.actual`], weeks })
    const props = { title: KPI_NAMES[kpi], trend: 'linear' }
    for (const key of KPI_SHARED) if (values[key] !== undefined) props[key] = values[key].value
    const chart = String(values.chart?.value ?? 'bar').toLowerCase()
    props.type = ['line', 'area', 'tile'].includes(chart) ? chart : 'bar'
    if (values.option) props.option = values.option.value
    model.option = legacyToOption(props)
    model.legacy = true
    for (const [name, { raw }] of Object.entries(values)) if (!KPI_SHARED.includes(name) && !['kpi', 'showGoal', 'weeks', 'chart', 'option', 'height', 'chartId'].includes(name)) keep.push(raw)
    model.notes.push('This live key indicator chart will be saved as a chart from mission numbers, with the same look.')
    return model
  }
  const props = {}
  for (const [name, { value }] of Object.entries(values)) if (Object.hasOwn(PROPS, name)) props[name] = value
  if (values.option) props.option = values.option.value
  if (values.chartId) props.chartId = values.chartId.value
  if (isOptionChart(props)) {
    // Studio's Title and Colours draw an option chart whose option has none of
    // its own (MissionChart.vue); they move into the option so saving keeps them.
    const option = readOption(values.option.value).value ?? {}
    const title = String(props.title ?? '').trim()
    if (title && option.title === undefined) option.title = { text: title }
    if (Array.isArray(props.colors) && props.colors.length && option.color === undefined) option.color = props.colors.map(String)
    model.option = option
  }
  else {
    model.option = legacyToOption(props)
    model.legacy = true
    model.notes.push('This chart was made the older way; it is saved as an ECharts option with the same look.')
  }
  for (const [name, { raw }] of Object.entries(values)) if (!Object.hasOwn(PROPS, name) && !DATA_ATTRS.has(name)) keep.push(raw)
  if (values.query) {
    try { model.spec = normalizeSpec(values.query.value) }
    catch (error) { model.notes.push(`Its query had a mistake (${error.message}), so the builder starts with a new one.`) }
  }
  if (!model.spec) {
    // Numbers the builder cannot read must not quietly become mission numbers:
    // saving would then write a query beside them, and the query wins.
    const unread = found.attrs.find(attr => ['rows', 'csv'].includes(camel(attr.name.replace(/^(:|v-bind:)/, ''))) && values[camel(attr.name.replace(/^(:|v-bind:)/, ''))] === undefined)
    if (unread || (values.rows && !Array.isArray(values.rows.value))) throw new Error("The builder cannot read this chart's numbers. Open the slide's text and check its rows, or make the chart again.")
    if (Array.isArray(values.rows?.value) && values.rows.value.length) { model.source = 'table'; model.rows = values.rows.value.map(String) }
    else if (values.csv) { model.source = 'table'; model.rows = tableRows(String(values.csv.value)) }
    else if (values.data) { model.source = 'data'; keep.push(values.data.raw); model.notes.push('Its numbers are written as `data`; the builder keeps them and changes only the look.') }
  }
  return model
}

/**
 * The <MissionChart> tag for a model from readChart (or the builder): its
 * chart-id first, then the height, the numbers (a pinned query or rows) and
 * the option, then the attributes the builder does not know, as they were.
 */
export function writeChart(model) {
  const parts = ['<MissionChart', `chart-id="${attrText(model.chartId)}"`]
  const height = Number(model.height)
  if (Number.isFinite(height) && height > 0 && height !== 360) parts.push(`:height="${Math.round(height)}"`)
  if (model.source === 'mission' && model.spec) parts.push(`:query='${canonicalJson(normalizeSpec(model.spec))}'`)
  else if (model.source === 'table' && model.rows?.length) parts.push(`:rows="[${model.rows.map(jsString).join(', ')}]"`)
  const option = readOption(model.option).value ?? {}
  parts.push(`:option='${jsonAttr(option)}'`)
  for (const raw of model.keep ?? []) parts.push(raw)
  return `${parts.join(' ')} />`
}

// ---- the type picker -------------------------------------------------------------------

/**
 * The chart types the builder offers: every ECharts series type (map needs a
 * map file, which is not installed) and a few ways of drawing them, in plain
 * words. `group` orders the picker.
 */
export const CHART_KINDS = [
  { id: 'bar', label: 'Bars', group: 'Everyday' },
  { id: 'line', label: 'Line', group: 'Everyday' },
  { id: 'area', label: 'Area', group: 'Everyday' },
  { id: 'pie', label: 'Pie', group: 'Everyday' },
  { id: 'donut', label: 'Donut', group: 'Everyday' },
  { id: 'tile', label: 'Key number', group: 'Everyday' },
  { id: 'gauge', label: 'Gauge', group: 'Everyday' },
  { id: 'stacked', label: 'Stacked bars', group: 'Compare' },
  { id: 'sideways', label: 'Sideways bars', group: 'Compare' },
  { id: 'combo', label: 'Bars and a line', group: 'Compare' },
  { id: 'pictorial', label: 'Picture bars', group: 'Compare' },
  { id: 'polar', label: 'Round bars', group: 'Compare' },
  { id: 'rose', label: 'Rose', group: 'Compare' },
  { id: 'radar', label: 'Radar', group: 'Compare' },
  { id: 'funnel', label: 'Funnel', group: 'Compare' },
  { id: 'multiples', label: 'Small charts', group: 'Compare' },
  { id: 'scatter', label: 'Dots', group: 'Spread and time' },
  { id: 'ripple', label: 'Pulsing dots', group: 'Spread and time' },
  { id: 'heatmap', label: 'Heat map', group: 'Spread and time' },
  { id: 'calendar', label: 'Calendar', group: 'Spread and time' },
  { id: 'river', label: 'Theme river', group: 'Spread and time' },
  { id: 'boxplot', label: 'Box plot', group: 'Spread and time' },
  { id: 'candlestick', label: 'Candlestick', group: 'Spread and time' },
  { id: 'range', label: 'Ranges', group: 'Spread and time' },
  { id: 'waterfall', label: 'Waterfall', group: 'Spread and time' },
  { id: 'timeline', label: 'Play through', group: 'Spread and time' },
  { id: 'treemap', label: 'Tree map', group: 'Parts and flows' },
  { id: 'sunburst', label: 'Sunburst', group: 'Parts and flows' },
  { id: 'tree', label: 'Tree', group: 'Parts and flows' },
  { id: 'sankey', label: 'Flow', group: 'Parts and flows' },
  { id: 'chord', label: 'Chord', group: 'Parts and flows' },
  { id: 'graph', label: 'Network', group: 'Parts and flows' },
  { id: 'parallel', label: 'Parallel lines', group: 'Parts and flows' },
  { id: 'lines', label: 'Lines between points', group: 'Parts and flows' },
]

/** What each kind needs from the table, for the picker's hint. */
export const KIND_HINTS = {
  candlestick: 'Four columns: open, close, lowest, highest.',
  range: 'Two columns: the lowest and the highest number.',
  waterfall: 'The first row is where it starts; the others are changes.',
  sankey: 'Three columns: from, to and a number.',
  chord: 'Three columns: from, to and a number.',
  graph: 'Three columns: from, to and a number.',
  lines: 'Four columns: from x, from y, to x, to y.',
  calendar: 'Dates in the first column.',
  treemap: 'Levels in the first column, like "North / Frankfurt 1".',
  sunburst: 'Levels in the first column, like "North / Frankfurt 1".',
  tree: 'Levels in the first column, like "North / Frankfurt 1".',
  timeline: 'Shows one row at a time, with a play button.',
  gauge: 'The last row: the number, and its goal in the next column.',
  tile: 'The last row, large, with the change from the row before.',
}

const CARTESIAN_KINDS = new Set(['bar', 'line', 'area', 'stacked', 'sideways', 'combo', 'pictorial', 'scatter', 'ripple', 'multiples'])
// Settings of an option that belong to the chart as a whole and survive a change of type.
const KEEP_ON_TYPE = ['title', 'legend', 'tooltip', 'color', 'toolbox', 'graphic', 'aria', 'textStyle', 'backgroundColor', 'animation', 'animationDuration', 'animationDurationUpdate', 'animationEasing', 'animationEasingUpdate', 'animationDelay']
const WHOLE_CHART = new Set(['pie', 'donut', 'rose', 'funnel', 'tile', 'gauge', 'treemap', 'sunburst', 'tree', 'sankey', 'chord', 'graph', 'lines', 'calendar', 'heatmap'])

function plainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function asList(value) {
  return value === undefined ? [] : Array.isArray(value) ? value : [value]
}

/** The kind an option is drawn as (the picker's pressed button), or ''. */
export function kindOf(option) {
  const o = plainObject(option) ? option : {}
  if (o.gfm?.kind === 'tile') return 'tile'
  if (o.gfm?.kind === 'multiples') return 'multiples'
  if (o.timeline !== undefined) return 'timeline'
  const series = asList(o.series)
  const s = series[0] ?? {}
  const horizontal = asList(o.yAxis)[0]?.type === 'category'
  switch (s.type) {
    case 'bar':
      if (s.coordinateSystem === 'polar') return 'polar'
      if (horizontal) return 'sideways'
      if (series.some(x => x?.type === 'line')) return 'combo'
      return s.stack ? 'stacked' : 'bar'
    case 'line': return s.areaStyle ? 'area' : 'line'
    case 'pie': return s.roseType ? 'rose' : Array.isArray(s.radius) && Number.parseFloat(s.radius[0]) > 0 ? 'donut' : 'pie'
    case 'pictorialBar': return 'pictorial'
    case 'effectScatter': return 'ripple'
    case 'heatmap': return s.coordinateSystem === 'calendar' ? 'calendar' : 'heatmap'
    case 'themeRiver': return 'river'
    case 'custom': return s.renderItem === 'waterfall' ? 'waterfall' : 'range'
    default: return SERIES_TYPES.includes(s.type) ? s.type : ''
  }
}

/**
 * The option drawn as another kind: the whole-chart settings (title, legend,
 * colours, tooltip, toolbox, animation …) stay, and for charts on x and y
 * axes also the axes' names and limits, zoom, labels, reference lines and the
 * trend line.
 */
export function applyKind(option, kind) {
  const old = plainObject(option) ? option : {}
  const o = {}
  for (const key of KEEP_ON_TYPE) if (old[key] !== undefined) o[key] = clone(old[key])
  const gfm = plainObject(old.gfm) ? clone(old.gfm) : {}
  delete gfm.kind
  const first = asList(old.series)[0] ?? {}
  const carry = {}
  for (const key of ['label', 'markLine', 'markPoint', 'markArea', 'gfm', 'smooth', 'universalTransition', 'emphasis']) if (first[key] !== undefined) carry[key] = clone(first[key])
  if (CARTESIAN_KINDS.has(kind)) {
    // The axes by what they hold (categories or numbers), turned for sideways bars.
    const axes = [...asList(old.xAxis), ...asList(old.yAxis)]
    const category = clone(axes.find(a => a?.type === 'category') ?? {}) ?? {}
    const value = clone(axes.find(a => a?.type === 'value' || a?.type === 'log') ?? asList(old.yAxis)[0] ?? {}) ?? {}
    delete category.inverse
    delete category.type
    const valueType = value.type === 'log' ? 'log' : 'value'
    delete value.type
    if (kind === 'sideways') { o.xAxis = { ...value, type: valueType }; o.yAxis = { ...category, type: 'category', inverse: true } }
    else {
      if (Object.keys(category).length) o.xAxis = kind === 'scatter' || kind === 'ripple' ? category : { ...category, type: 'category' }
      if (Object.keys(value).length || valueType === 'log') o.yAxis = { ...value, type: valueType }
    }
    if (old.dataZoom !== undefined) o.dataZoom = clone(old.dataZoom)
    if (old.brush !== undefined) o.brush = clone(old.brush)
    if (old.visualMap !== undefined && !['heatmap', 'calendar'].includes(kindOf(old))) o.visualMap = clone(old.visualMap)
    const base = { ...carry }
    if (kind !== 'line' && kind !== 'area' && kind !== 'multiples') delete base.smooth
    o.series = {
      bar: [{ type: 'bar', ...base }],
      line: [{ type: 'line', ...base }],
      area: [{ type: 'line', areaStyle: {}, ...base }],
      stacked: [{ type: 'bar', stack: 'total', ...base }],
      sideways: [{ type: 'bar', ...base }],
      combo: [{ type: 'bar', ...base }, { type: 'line', ...(base.gfm ? { gfm: base.gfm } : {}) }],
      pictorial: [{ type: 'pictorialBar', ...base }],
      scatter: [{ type: 'scatter', ...base }],
      ripple: [{ type: 'effectScatter', ...base }],
      multiples: [{ type: 'line', ...base }],
    }[kind]
    if (kind === 'multiples') gfm.kind = 'multiples'
  }
  else {
    const label = carry.label ? { label: carry.label } : {}
    o.series = [{
      pie: { type: 'pie', ...label },
      donut: { type: 'pie', radius: ['40%', '64%'], ...label },
      rose: { type: 'pie', roseType: 'radius', radius: ['16%', '66%'], ...label },
      tile: { type: 'line' },
      gauge: { type: 'gauge' },
      polar: { type: 'bar', coordinateSystem: 'polar', ...label },
      radar: { type: 'radar', ...label },
      funnel: { type: 'funnel', ...label },
      heatmap: { type: 'heatmap', ...label },
      calendar: { type: 'heatmap', coordinateSystem: 'calendar' },
      river: { type: 'themeRiver' },
      boxplot: { type: 'boxplot' },
      candlestick: { type: 'candlestick' },
      range: { type: 'custom', renderItem: 'range' },
      waterfall: { type: 'custom', renderItem: 'waterfall', ...label },
      timeline: { type: 'bar', ...label },
      treemap: { type: 'treemap' },
      sunburst: { type: 'sunburst' },
      tree: { type: 'tree' },
      sankey: { type: 'sankey' },
      chord: { type: 'chord' },
      graph: { type: 'graph' },
      parallel: { type: 'parallel' },
      lines: { type: 'lines', coordinateSystem: 'cartesian2d' },
    }[kind] ?? { type: 'bar' }]
    if (kind === 'tile') gfm.kind = 'tile'
    if (kind === 'timeline') o.timeline = {}
    if (kind === 'polar') { o.angleAxis = { type: 'category' }; o.radiusAxis = { type: 'value' } }
    if (kind === 'heatmap' || kind === 'calendar') o.visualMap = clone(old.visualMap) ?? {}
    // A whole-chart kind names its parts on the chart: an empty legend setting goes.
    if (WHOLE_CHART.has(kind) && plainObject(o.legend) && !Object.keys(o.legend).length) delete o.legend
  }
  if (Object.keys(gfm).length) o.gfm = gfm
  return o
}

// ---- reading and writing settings by path ---------------------------------------------------

/** The value at a path such as "series.0.label.show" (numbers index lists), or undefined. */
export function getPath(object, path) {
  let at = object
  for (const key of String(path).split('.')) {
    if (at === undefined || at === null) return undefined
    at = Array.isArray(at) && /^\d+$/.test(key) ? at[Number(key)] : at[key]
  }
  return at
}

// Settings that mean something even when empty ({} shows a legend, fills an area …).
const KEEP_EMPTY = new Set(['areaStyle', 'legend', 'tooltip', 'toolbox', 'brush', 'visualMap', 'timeline', 'polar', 'radar', 'angleAxis', 'radiusAxis', 'singleAxis', 'calendar', 'parallel', 'xAxis', 'yAxis', 'grid', 'dataZoom', 'saveAsImage', 'dataView', 'restore', 'magicType'])

/**
 * A copy of `object` with `value` at `path` (lists and objects are made on
 * the way). undefined removes the setting, and the objects on the path that
 * it leaves empty go too, except those that mean something when empty
 * ("areaStyle": {} fills the area).
 */
export function setPath(object, path, value) {
  const keys = String(path).split('.')
  const root = clone(plainObject(object) ? object : {})
  const trail = [root]
  let at = root
  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i]
    if (at[key] === undefined || at[key] === null || typeof at[key] !== 'object') {
      if (value === undefined) return root
      at[key] = /^\d+$/.test(keys[i + 1]) ? [] : {}
    }
    at = at[key]
    trail.push(at)
  }
  const last = keys[keys.length - 1]
  if (value !== undefined) {
    at[last] = value
    // A list filled up to a position gets empty settings in the gaps.
    for (const list of [...trail, at]) if (Array.isArray(list)) for (let i = 0; i < list.length; i++) if (list[i] === undefined || list[i] === null) list[i] = {}
    return root
  }
  if (Array.isArray(at)) at[Number(last)] = {}
  else delete at[last]
  for (let i = keys.length - 2; i >= 0; i--) {
    const holder = trail[i], child = trail[i + 1]
    if (Array.isArray(holder) || !plainObject(child) || Object.keys(child).length || KEEP_EMPTY.has(keys[i])) break
    delete holder[keys[i]]
  }
  return root
}
