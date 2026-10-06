// The chart frame of the portal's Whiteboard: GET /whiteboard/chart on the Presentation Manager (managers only,
// whiteboard-frames.mjs). One chart or key number, drawn by the same chart engine as the slides (chart-engine.mjs,
// round 6) from live mission numbers (POST /api/charts/data without a deck, as the chart builder's preview), fitted
// to the frame's size, so it grows and shrinks with its box on the board. The numbers are fetched again every few
// minutes and when the page comes back into view.
//
// The chart comes in the address after '#' (never sent to a server): the chart builder's board model
//   { v: 2, source: 'mission' | 'table', spec: {...query} | rows: ['Week, Friends', ...], option: {...ECharts} }
// as base64url-encoded JSON (encodeModel). A chart the older builder placed ({ v: 1, props: {...look}, spec | rows,
// option?: '...' }) is drawn the older way, exactly as on a slide. A new '#' redraws without reloading.
// ?theme=dark draws on dark.
//
// Who uses it: the page GET /whiteboard/chart (whiteboard-frames.mjs), which loads it from
// /_manager/chart/whiteboard-chart.mjs; the portal's Whiteboard (portal/whiteboard/) shows that page in a frame.
// How it fits: the helpers above startChartFrame have no DOM, so slidev/tests/whiteboard.test.mjs runs them in plain
// Node.
import { chartType } from './chart-core.mjs'
import { chartView as engineView, readOption, viewOption } from './chart-engine.mjs'
import { normalizeSpec, SpecError } from './chart-spec.mjs'
import { safeChartOption } from './safe-chart-option.mjs'

export const REFRESH_MS = 5 * 60 * 1000
export const RETRY_MS = 60 * 1000
export const MAX_MODEL_CHARS = 60000
const MAX_ROWS = 500
const MAX_ROW_CHARS = 4000
const MAX_OPTION_CHARS = 40000
const NOT_LOADED = 'The numbers could not load. Trying again in a minute.'
const LOADING = 'Loading mission numbers…'
const NO_SETTINGS = 'This chart has no settings. Edit it on the whiteboard.'

function toBase64Url(bytes) {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64Url(text) {
  const clean = String(text).replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(clean + '='.repeat((4 - clean.length % 4) % 4))
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

const plain = v => !!v && typeof v === 'object' && !Array.isArray(v)

/** The model as it goes after '#' (the same as portal/whiteboard/board-core.js encodeChartModel). */
export function encodeModel(model) {
  return toBase64Url(new TextEncoder().encode(JSON.stringify(model)))
}

/**
 * A model checked for drawing: { model, problem }. model is null when it cannot be drawn; problem is a sentence.
 * model = { props (what chart-engine's chartView takes), spec (the query, for loading its numbers) }. The query goes
 * through the same checks as a slide's (normalizeSpec); the server checks it again.
 */
export function checkModel(raw) {
  if (!plain(raw)) return { model: null, problem: NO_SETTINGS }
  let props
  if (plain(raw.props)) {
    // Placed by the older builder: drawn with the older settings, as on a slide.
    props = { ...raw.props, type: chartType(raw.props.type) }
    if (typeof raw.option === 'string' && raw.option.trim()) {
      if (raw.option.length > MAX_OPTION_CHARS) return { model: null, problem: 'The advanced settings of this chart are too long.' }
      props.option = raw.option
    }
  }
  else if (plain(raw.option)) {
    if (JSON.stringify(raw.option).length > MAX_OPTION_CHARS) return { model: null, problem: 'The settings of this chart are too long.' }
    const read = readOption(raw.option)
    if (!read.value) return { model: null, problem: read.problem || NO_SETTINGS }
    props = { option: read.value, chartId: 'whiteboard' }
  }
  else return { model: null, problem: NO_SETTINGS }
  const model = { props, spec: null }
  if (raw.spec !== undefined && raw.spec !== null) {
    try { model.spec = normalizeSpec(raw.spec) }
    catch (error) { return { model: null, problem: `The chart's settings have a mistake: ${error instanceof SpecError ? error.message : 'they cannot be read'}` } }
    props.query = model.spec
  }
  else if (Array.isArray(raw.rows) && raw.rows.length) {
    if (raw.rows.length > MAX_ROWS || raw.rows.some(r => typeof r !== 'string' || r.length > MAX_ROW_CHARS))
      return { model: null, problem: 'The table of this chart is too long.' }
    props.rows = raw.rows
  }
  else return { model: null, problem: 'This chart has no numbers. Edit it on the whiteboard.' }
  return { model, problem: '' }
}

/**
 * For the chart builder, before "Add to the whiteboard" (whiteboard-builder.mjs hands it to the builder as
 * target.check): '' when this frame will draw the model, else what to change, in the builder's words. The limits are
 * the ones decodeModel and checkModel apply, so a chart that previewed in the builder never arrives as an error box.
 */
export function boardLimitProblem(model) {
  const rows = Array.isArray(model?.rows) ? model.rows : null
  if (rows && rows.length > MAX_ROWS)
    return `A chart on the whiteboard can show a table of at most ${MAX_ROWS} rows, headings included; this one has ${rows.length}. Shorten the table, or use mission numbers.`
  if (rows && rows.some(r => typeof r !== 'string' || r.length > MAX_ROW_CHARS))
    return `A row of this table is longer than ${MAX_ROW_CHARS.toLocaleString('en')} characters. Shorten it to put the chart on the whiteboard.`
  if (plain(model?.option) && JSON.stringify(model.option).length > MAX_OPTION_CHARS)
    return 'The settings of this chart are too long for the whiteboard. Remove some on the All options tab.'
  if (encodeModel(model).length > MAX_MODEL_CHARS)
    return 'This chart is too large for the whiteboard. Shorten the table, or remove some settings on the All options tab.'
  return checkModel(model).problem
}

/** The model from the text after '#': { model, problem }. */
export function decodeModel(fragment) {
  const text = String(fragment || '').replace(/^#/, '')
  if (!text) return { model: null, problem: NO_SETTINGS }
  if (text.length > MAX_MODEL_CHARS) return { model: null, problem: 'The settings of this chart are too long.' }
  let raw
  try { raw = JSON.parse(new TextDecoder().decode(fromBase64Url(text))) }
  catch { return { model: null, problem: 'The settings of this chart cannot be read. Edit it on the whiteboard.' } }
  return checkModel(raw)
}

/**
 * What to draw ({ view (chart-engine's chartView), problem }): problem is what the frame says instead ('' when
 * there is a chart). answer: POST /api/charts/data's answer for a query (null while loading).
 */
export function chartView(model, answer) {
  const view = engineView(model.props, model.spec ? answer : null)
  return { view, problem: view.problem || '' }
}

/** Whether the chart is drawn again (not only resized) when its box changes size: key numbers and small multiples. */
export function sizeAware(model) {
  if (!model) return false
  const p = model.props
  if (p.type) return chartType(p.type) === 'tile' || p.multiples === true || p.multiples === 'true'
  return ['tile', 'multiples'].includes(p.option?.gfm?.kind)
}

/**
 * The ECharts option for a view (null when there is nothing to draw). This frame is on the manager address, and a
 * board's chart may come from a zone's slide, so nothing in it is drawn as HTML (safe-chart-option.mjs).
 */
export function frameOption(view, ctx) {
  return safeChartOption(viewOption(view, ctx))
}

/** "Live · 14:05" and its longer explanation, for the corner of a live chart. */
export function liveNote(at, lang) {
  let time = ''
  try { time = new Date(at).toLocaleTimeString(lang || undefined, { hour: '2-digit', minute: '2-digit' }) }
  catch { time = '' }
  return { short: time ? `Live · ${time}` : 'Live', long: `Live mission numbers${time ? `, updated at ${time}` : ''}. They update every few minutes.` }
}

// ---- the page ------------------------------------------------------------------

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.onload = () => resolve()
    script.onerror = () => { script.remove(); reject(new Error('The chart library could not be loaded.')) }
    document.head.appendChild(script)
  })
}

let libraries = null
function loadLibraries() {
  const g = globalThis
  libraries ||= Promise.all([g.echarts?.init ? null : loadScript('/_manager/chart/echarts.min.js'), g.ecStat?.regression ? null : loadScript('/_manager/chart/ecStat.min.js')])
    .then(() => ({ echarts: g.echarts, ecStat: g.ecStat }))
    .catch((error) => { libraries = null; throw error })
  return libraries
}

/** Starts the frame: reads the model, loads the numbers, draws, and keeps both up to date. */
export function startChartFrame() {
  const P = window.PresentationSession
  const plot = document.getElementById('plot')
  const message = document.getElementById('message')
  const note = document.getElementById('note')
  const dark = new URLSearchParams(location.search).get('theme') === 'dark'
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  const state = { model: null, problem: '', answer: null, loadedAt: 0, error: '', loading: false, request: 0, timer: 0 }
  let chart = null
  let lib = null
  let drawnAt = ''

  function say(text, busy = false) {
    message.hidden = !text
    message.textContent = text || ''
    message.classList.toggle('busy', busy)
  }

  function draw() {
    if (!state.model) { chart?.clear(); note.hidden = true; return say(state.problem) }
    const { view, problem: viewProblem } = chartView(state.model, state.answer)
    let problem = viewProblem
    if (state.model.spec && !state.answer) problem = state.error || LOADING
    if (!problem && !lib) problem = 'Loading chart…'
    const width = plot.clientWidth, height = plot.clientHeight
    if (!problem && (width < 20 || height < 20)) return
    if (!problem) {
      if (!chart) chart = lib.echarts.init(plot, null, { renderer: 'svg' })
      const style = getComputedStyle(document.body)
      let option = null
      try { option = frameOption(view, { dark, font: style.fontFamily || 'system-ui, sans-serif', animate: false, ecStat: lib.ecStat, width, height }) }
      catch (error) { problem = `This chart cannot be drawn with these settings (${error.message}).` }
      if (option) { chart.resize(); chart.setOption(option, { notMerge: true }); drawnAt = `${width}x${height}` }
      else if (!problem) problem = 'Add numbers to show this chart.'
    }
    if (problem) chart?.clear()
    say(problem, problem === LOADING || problem === 'Loading chart…')
    const live = !!state.model.spec && !!state.answer && !problem
    note.hidden = !live
    if (live) {
      const text = liveNote(state.loadedAt, document.documentElement.lang)
      note.textContent = text.short
      note.title = text.long
      if (state.error) note.title += ` ${state.error}`
    }
  }

  async function load() {
    if (!state.model?.spec) return
    const mine = ++state.request
    clearTimeout(state.timer)
    state.loading = true
    try {
      const answer = await P.api('/api/charts/data', { method: 'POST', body: JSON.stringify({ spec: state.model.spec }) })
      if (mine !== state.request) return
      state.answer = answer
      state.loadedAt = Date.now()
      state.error = ''
      state.timer = setTimeout(load, REFRESH_MS)
    }
    catch (error) {
      if (mine !== state.request) return
      // A refusal or a mistake in the settings is said as the server says it; anything else is tried again soon.
      state.error = (error.status === 400 || error.status === 403) && error.message ? error.message : NOT_LOADED
      if (error.status === 400 || error.status === 403) state.answer = null
      else state.timer = setTimeout(load, RETRY_MS)
    }
    finally { if (mine === state.request) state.loading = false }
    draw()
  }

  function readModel() {
    const { model, problem } = decodeModel(location.hash)
    const before = state.model?.spec ? JSON.stringify(state.model.spec) : ''
    state.model = model
    state.problem = problem
    if (!model?.spec) { state.answer = null; state.error = ''; clearTimeout(state.timer) }
    else if (JSON.stringify(model.spec) !== before) { state.answer = null; state.error = ''; load() }
    draw()
  }

  new ResizeObserver(() => {
    if (!chart) return draw()
    const size = `${plot.clientWidth}x${plot.clientHeight}`
    if (size === drawnAt) return
    if (sizeAware(state.model)) draw()
    else { chart.resize(); drawnAt = size }
  }).observe(plot)
  window.addEventListener('hashchange', readModel)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.model?.spec && !state.loading && Date.now() - state.loadedAt > REFRESH_MS) load()
  })
  loadLibraries().then(loaded => { lib = loaded; draw() }, error => { state.problem = error.message; say(error.message) })
  readModel()
}
