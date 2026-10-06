// The Vue side of <MissionChart> and <MissionKpiChart>: loading the chart
// libraries, drawing into an element and fetching live mission numbers.
// Everything else (tables, trends, the ECharts option) is in chart-core.mjs
// (the older settings) and chart-engine.mjs (a table plus an ECharts option),
// which have no Vue or Slidev imports and are re-exported here.
//
// ECharts 6.0.0 and echarts-stat 1.2.0 are the vendored UMD builds in
// slidev/manager/vendor. Importing them with `?url` lets Vite serve them in the
// editor (/edit/<slug>/@fs/...) and copy them into a build's assets
// (/p/<slug>/assets/...), so the same code works under both base paths. They
// are loaded once as classic scripts and set globalThis.echarts / ecStat.
import type { Ref } from 'vue'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDarkMode, useNav } from '@slidev/client'
import echartsUrl from '../../vendor/echarts.min.js?url'
import ecStatUrl from '../../vendor/ecStat.min.js?url'
import { KPI_FETCH_WEEKS } from './chart-core.mjs'
import { deckOfPath } from './chart-spec.mjs'
import { REPLACE_MERGE, stabilize } from './chart-story.mjs'

export * from './chart-core.mjs'
export * from './chart-engine.mjs'

export type ChartType = 'line' | 'bar' | 'area' | 'scatter' | 'pie' | 'donut' | 'gauge' | 'tile' | 'heatmap' | 'radar' | 'funnel' | 'treemap' | 'sunburst' | 'boxplot' | 'waterfall'
export interface ChartSeries { name: string, values: (number | null)[], role?: 'goal' }
/** `problem` is set (and the lists are empty) when the table cannot be read. */
export interface ChartTable { labels: string[], series: ChartSeries[], problem?: string }
export interface ChartContext { dark: boolean, font: string, animate: boolean, ecStat: any, width?: number, height?: number }
export interface StoryMotion { kind: 'morph' | 'fade' | 'none', duration: number, easing: string }
export interface KpiWeek { week: string, [kpi: string]: any }

let libraries: Promise<{ echarts: any, ecStat: any }> | null = null

function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.async = false
    script.onload = () => resolve()
    script.onerror = () => { script.remove(); reject(new Error(`Could not load ${src}`)) }
    document.head.appendChild(script)
  })
}

/**
 * echarts-stat's dataset transforms (`ecStat:regression`, `ecStat:histogram`,
 * `ecStat:clustering`), registered once, so an option can use them.
 */
function registerTransforms(g: any) {
  if (g.__gfmTransforms || !g.echarts?.registerTransform || !g.ecStat?.transform) return
  for (const transform of Object.values(g.ecStat.transform)) {
    try { g.echarts.registerTransform(transform) }
    catch {}
  }
  g.__gfmTransforms = true
}

export function loadChartLibraries() {
  const g = globalThis as any
  const ready = () => g.echarts?.init && g.ecStat?.regression
  if (ready()) {
    registerTransforms(g)
    return Promise.resolve({ echarts: g.echarts, ecStat: g.ecStat })
  }
  libraries ||= Promise.all([g.echarts?.init ? null : loadScript(echartsUrl), g.ecStat?.regression ? null : loadScript(ecStatUrl)])
    .then(() => {
      if (!ready()) throw new Error('The chart libraries did not start.')
      registerTransforms(g)
      return { echarts: g.echarts, ecStat: g.ecStat }
    })
    .catch((error) => { libraries = null; throw error })
  return libraries
}

function isLightInk(color: string) {
  const m = color.match(/[\d.]+/g)
  if (!m || m.length < 3) return false
  const [r, g, b] = m.slice(0, 3).map(Number)
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.6
}

// The last option each chart drew, by its key (chart-id, or its settings).
// When the editor rebuilds a slide, the chart is made again: it starts from
// what it showed and moves to the new drawing instead of flashing and
// growing in from nothing.
const lastDrawn = new Map<string, { option: any, at: number }>()
const KEEP_MS = 30 * 60 * 1000

/** How long a burst of changes (typing in Studio's panel, a slide rebuilt twice) is waited for. */
const SETTLE_MS = 70

/**
 * Draws `build(ctx)` into `el` once the element has a size. Slides that are
 * not showing are 0x0, so the chart starts (and resizes) from a
 * ResizeObserver; it follows dark mode, never animates in print mode and is
 * disposed with the component. `onShow` runs each time the chart comes into
 * view again (its slide is shown). `sizeAware` charts (key numbers, small
 * multiples) are drawn again when their size changes, because their layout
 * depends on it. `signature` says what the drawing depends on: a render
 * whose signature (and size and colours) did not change draws nothing, and
 * renders asked for in quick succession draw once. `key` names the chart
 * across a rebuild of its slide (see lastDrawn).
 */
export function useMissionChart(el: Ref<HTMLElement | undefined>, build: (ctx: ChartContext) => any, onShow?: () => void, sizeAware?: () => boolean, signature?: () => string, key?: () => string, motion?: () => StoryMotion | null) {
  const { isDark } = useDarkMode()
  const { isPrintMode } = useNav()
  const failed = ref(false)
  // True once the chart has been drawn the first time (the libraries are
  // about 1.1 MB, so this can take a moment on a slow connection).
  const ready = ref(false)
  let lib: { echarts: any, ecStat: any } | null = null
  let chart: any = null
  let observer: ResizeObserver | null = null
  let gone = false
  let shown = false
  let drawnAt = ''
  let drawnSig = ''
  let timer: ReturnType<typeof setTimeout> | null = null
  let first = true

  const sized = (node?: HTMLElement) => !!node && node.clientWidth > 0 && node.clientHeight > 0

  function draw() {
    timer = null
    const node = el.value
    if (!chart || !node || !lib || gone) return
    const style = getComputedStyle(node)
    // A dark slide (dark mode, or a dark layout with light text) gets the dark palette.
    const dark = !!isDark.value || isLightInk(style.color)
    const size = `${node.clientWidth}x${node.clientHeight}`
    const sig = signature ? `${signature()}|${dark}|${isPrintMode.value}|${sizeAware?.() ? size : ''}` : ''
    if (sig && sig === drawnSig) return
    drawnAt = size
    try {
      const option = build({ dark, font: style.fontFamily || 'system-ui, sans-serif', animate: !isPrintMode.value, ecStat: lib.ecStat, width: node.clientWidth, height: node.clientHeight })
      const name = key?.() || ''
      if (option) {
        const before = first && name ? lastDrawn.get(name) : null
        if (before && Date.now() - before.at < KEEP_MS && !isPrintMode.value) {
          // Start from what this chart showed before its slide was rebuilt.
          chart.setOption({ ...before.option, animation: false }, { notMerge: true })
        }
        const drawStart = performance.now()
        const story = motion?.()
        if (story && !first && !isPrintMode.value) {
          // A step of a data story: the same chart instance moves to the next state (stable series ids, ECharts'
          // universal transition for a series that changes kind) instead of being drawn from nothing.
          chart.setOption(stabilize(option, story), { notMerge: false, replaceMerge: REPLACE_MERGE })
        }
        else chart.setOption(story ? stabilize(option, story) : option, { notMerge: true })
        notePerf('draws', performance.now() - drawStart)
        if (name) {
          lastDrawn.set(name, { option, at: Date.now() })
          if (lastDrawn.size > 200) lastDrawn.delete(lastDrawn.keys().next().value!)
        }
      }
      else chart.clear()
      first = false
      drawnSig = sig
    }
    catch (error) {
      console.error('[gfm-addon] chart could not be drawn', error)
      chart.clear()
      drawnSig = ''
    }
  }

  /** Draws soon: changes that come together (a slide rebuilt, a setting typed) are drawn once. */
  function render(now = false) {
    if (timer) clearTimeout(timer)
    if (now) draw()
    else timer = setTimeout(draw, SETTLE_MS)
  }

  function start() {
    const node = el.value
    if (gone || chart || !lib || !sized(node)) return
    chart = lib.echarts.init(node, null, { renderer: 'svg' })
    draw()
    ready.value = true
  }

  onMounted(() => {
    loadChartLibraries().then((loaded) => {
      if (gone) return
      lib = loaded
      observer = new ResizeObserver(() => {
        const now = sized(el.value)
        if (now && !shown) onShow?.()
        shown = now
        if (!now) return
        if (!chart) return start()
        chart.resize()
        if (sizeAware?.() && drawnAt !== `${el.value!.clientWidth}x${el.value!.clientHeight}`) render()
      })
      if (el.value) observer.observe(el.value)
      start()
    }, () => { failed.value = true })
  })

  watch([isDark, isPrintMode], () => render(true), { flush: 'post' })

  onBeforeUnmount(() => {
    gone = true
    if (timer) clearTimeout(timer)
    observer?.disconnect()
    chart?.dispose()
    chart = null
  })

  return { render, failed, ready }
}

// ---- live mission numbers ------------------------------------------------------

let kpiRequest: { until: number, promise: Promise<KpiWeek[]> } | null = null

/**
 * GET /api/mission-kpis at the server root (the deck address). Every chart in a
 * deck shares one request for the longest period (104 weeks) for a minute and
 * keeps the weeks it shows (`weeks`, the most recent ones), so a deck with
 * charts of 12, 16 and 26 weeks asks once instead of three times.
 */
export function fetchMissionKpis(weeks: number): Promise<KpiWeek[]> {
  const count = Math.min(KPI_FETCH_WEEKS, Math.max(1, Math.round(Number(weeks) || 12)))
  if (!kpiRequest || kpiRequest.until <= Date.now()) {
    // deck (round 8): which deck this page is, so the deck address knows which deck pass to use (and a zone's
    // deck shows only that zone's totals).
    const deck = typeof location === 'undefined' ? '' : deckOfPath(location.pathname)
    const promise = fetch(`/api/mission-kpis?weeks=${KPI_FETCH_WEEKS}${deck ? `&deck=${deck}` : ''}`, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Mission numbers answered ${response.status}.`)
        const body = await response.json()
        const list = Array.isArray(body) ? body : body?.weeks
        if (!Array.isArray(list)) throw new Error('Mission numbers came back in an unexpected shape.')
        return list as KpiWeek[]
      })
    const entry = { until: Date.now() + 60000, promise }
    kpiRequest = entry
    // A failure is not remembered: the next chart asks again.
    promise.catch(() => { if (kpiRequest === entry) kpiRequest = null })
  }
  return kpiRequest.promise.then(list => list.slice(-count))
}

// ---- charts from the database --------------------------------------------------

/** What POST /api/charts/data answers: the chart's table and what it shows. */
export interface ChartAnswer {
  table: { labels: string[], series: { name: string, values: (number | null)[], role?: 'goal' }[] }
  meta: { level?: string, by?: 'week' | 'unit', unit?: 'count' | 'percent' | 'per_area', weeks?: string[], suppressed?: boolean, stewardship?: boolean, units?: number, pinned?: boolean, [key: string]: any }
}

/** A refusal or a mistake in the chart's settings, with the server's own sentence (400 and 403 answers). */
export class ChartDataError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const chartRequests = new Map<string, { until: number, promise: Promise<ChartAnswer> }>()
// The last answer for each deck and query, kept while the page is open: a
// chart made again (its slide rebuilt in the editor) shows it at once while
// newer numbers load, instead of "Loading mission numbers…".
const lastAnswers = new Map<string, ChartAnswer>()

/** The last answer this page had for a deck and query, or null. */
export function peekChartData(deck: string, key: string): ChartAnswer | null {
  return lastAnswers.get(`${deck}:${key}`) ?? null
}

/**
 * POST /api/charts/data at the server root (the deck address) for a normalised
 * spec (`key` is its canonical JSON). Charts with the same query in a deck
 * share one request for a minute; a failure is not remembered. `deck` is the
 * deck's slug from the page address: viewers only get queries written in
 * that deck.
 */
/** The last few query and draw times of charts (ms), for the editor's diagnostics (window.__gfmChartPerf). */
function notePerf(kind: 'queries' | 'draws', ms: number) {
  try {
    const perf = ((globalThis as any).__gfmChartPerf ||= { queries: [], draws: [] })
    perf[kind].push(Math.round(ms))
    if (perf[kind].length > 30) perf[kind].shift()
  }
  catch {}
}

export function fetchChartData(deck: string, spec: Record<string, any>, key: string): Promise<ChartAnswer> {
  const id = `${deck}:${key}`
  const now = Date.now()
  let entry = chartRequests.get(id)
  if (!entry || entry.until <= now) {
    const asked = typeof performance !== 'undefined' ? performance.now() : 0
    const promise = fetch('/api/charts/data', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ deck, spec }),
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}))
      if (response.status === 400 || response.status === 403) throw new ChartDataError(String(body?.error || 'This chart is not available.'), response.status)
      if (!response.ok) throw new Error(`Mission numbers answered ${response.status}.`)
      if (!body?.table || !Array.isArray(body.table.series)) throw new Error('Mission numbers came back in an unexpected shape.')
      notePerf('queries', performance.now() - asked)
      lastAnswers.set(id, body as ChartAnswer)
      if (lastAnswers.size > 100) lastAnswers.delete(lastAnswers.keys().next().value!)
      return body as ChartAnswer
    })
    const mine = { until: now + 60000, promise }
    chartRequests.set(id, mine)
    promise.catch(() => { if (chartRequests.get(id) === mine) chartRequests.delete(id) })
    entry = mine
  }
  return entry.promise
}
