<script setup lang="ts">
/**
 * MissionChart — a chart from your own numbers or from mission numbers, drawn with ECharts.
 *
 * A chart is its numbers plus an ECharts option (what Add chart and Edit chart write):
 * <MissionChart chart-id="c4k2m9" :rows="['Week, New people being taught', 'Aug 3, 12', 'Aug 10, 15']" :option='{"series":[{"type":"bar"}]}' />
 *
 * The numbers: `rows` (one table row per entry; Studio edits this as a list),
 * `csv` (a pasted table: tabs, commas or semicolons between columns, or `;`
 * between rows on one line), `data` (an object) or `query` (mission numbers
 * from the database, loaded when the slide is shown; leaders see a query only
 * when it is written in the deck exactly like this, as plain JSON). The first
 * row holds the headings, the first column the labels and every other
 * column one series.
 * The option: any ECharts 6 option (every series type except map, datasets
 * and transforms, dataZoom, visualMap, markLine/markArea/markPoint, toolbox,
 * brush, timeline, calendar, polar, singleAxis, parallel, graphic, aria, rich
 * labels, animations and universal transitions, several grids). The table is
 * bound to its series and the mission look laid under it; see
 * lib/chart-engine.mjs and slidev/README.md "Charts in slides".
 * `chart-id` names the chart for the editor (Edit chart always changes the
 * chart with that id). `height` is in slide pixels (a slide is 980 wide).
 *
 * Charts written with the older settings (`type`, `trend`, `goal` …) are
 * drawn exactly as before (chart-core's buildOption); Studio's Element panel
 * lists those settings, simple ones first.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useSlideContext } from '@slidev/client'
import type { ChartAnswer } from '../lib/charts'
import { ChartDataError, chartType, chartView, fetchChartData, isOptionChart, peekChartData, readOverride, useMissionChart, viewOption } from '../lib/charts'
import { canonicalJson, deckOfPath, normalizeSpec } from '../lib/chart-spec.mjs'
import { parseStory, stepSettings, storyMotion } from '../lib/chart-story.mjs'

const props = withDefaults(defineProps<{
  type?: 'line' | 'bar' | 'area' | 'scatter' | 'pie' | 'donut' | 'gauge' | 'tile' | 'heatmap' | 'radar' | 'funnel' | 'treemap' | 'sunburst' | 'boxplot' | 'waterfall'
  title?: string
  rows?: string[]
  csv?: string
  data?: Record<string, any> | Record<string, any>[]
  trend?: 'none' | 'linear' | 'polynomial' | 'exponential' | 'logarithmic' | 'moving-average'
  degree?: number
  trendColor?: string
  colors?: string[]
  showValues?: boolean
  height?: number
  max?: number
  trendStyle?: 'dashed' | 'dotted' | 'solid'
  trendWidth?: number
  trendLabel?: string
  window?: number
  forecast?: number
  goal?: string
  goalColor?: string
  target?: number
  targetLabel?: string
  targetColor?: string
  average?: boolean
  averageColor?: string
  legend?: 'auto' | 'top' | 'bottom' | 'right' | 'none'
  xTitle?: string
  yTitle?: string
  yMin?: number
  yMax?: number
  labelRotate?: number
  format?: 'auto' | 'plain' | 'percent' | 'compact' | 'decimals'
  decimals?: number
  prefix?: string
  suffix?: string
  valuePosition?: 'auto' | 'top' | 'inside' | 'bottom'
  stack?: boolean
  horizontal?: boolean
  smooth?: boolean
  seriesTypes?: string[]
  multiples?: boolean
  dataZoom?: boolean
  option?: Record<string, any> | string
  query?: Record<string, any> | string
  chartId?: string
  // GFM Studio: calculated fields (formula.mjs), a chart kind (chart-presets.mjs) and the few settings a kind reads.
  calc?: Record<string, any>[] | string
  preset?: string
  presetTop?: number
  presetAggregate?: 'last' | 'sum'
  presetTarget?: number
  shape?: Record<string, any>
  story?: Record<string, any>[] | string
  storyTransition?: 'morph' | 'fade' | 'none'
  storyDuration?: number
  storyEasing?: string
}>(), {
  // No default for `type`: a chart written without one is a line chart the
  // older way, unless its option names its series types (see isOptionChart).
  title: '',
  rows: () => [],
  csv: '',
  trend: 'none',
  degree: 2,
  trendColor: '',
  showValues: false,
  height: 360,
  trendStyle: 'dashed',
  trendWidth: 2,
  trendLabel: '',
  window: 3,
  forecast: 0,
  goal: '',
  goalColor: '',
  targetLabel: 'Target',
  targetColor: '',
  average: false,
  averageColor: '',
  legend: 'auto',
  xTitle: '',
  yTitle: '',
  labelRotate: 0,
  format: 'auto',
  prefix: '',
  suffix: '',
  valuePosition: 'auto',
  stack: false,
  horizontal: false,
  smooth: false,
  seriesTypes: () => [],
  multiples: false,
  dataZoom: false,
  chartId: '',
})

const TYPE_NAMES = {
  line: 'Line chart', bar: 'Bar chart', area: 'Area chart', scatter: 'Scatter chart', pie: 'Pie chart', donut: 'Donut chart', gauge: 'Gauge',
  tile: 'Key number', heatmap: 'Heat map', radar: 'Radar chart', funnel: 'Funnel chart', treemap: 'Tree map', sunburst: 'Sunburst chart', boxplot: 'Box plot', waterfall: 'Waterfall chart',
}

const el = ref<HTMLElement>()
const root = ref<HTMLElement>()
const box = computed(() => ({ height: `${Math.max(120, Math.min(2000, Number(props.height) || 360))}px` }))

// ---- a data story (`story`): the chart changes step by step, one Slidev click per step (lib/chart-story.mjs) ----
const story = computed(() => parseStory(props.story))
const clicks: any = (() => { try { return (useSlideContext() as any)?.$clicksContext ?? null } catch { return null } })()
const storyId = `gfm-story-${Math.random().toString(36).slice(2)}`
const storyStart = ref(0)
onMounted(() => {
  const n = story.value.steps.length
  if (n > 1 && clicks) {
    // Like Slidev's own click gap: this chart reserves n - 1 clicks, counted from where it is on the slide.
    storyStart.value = clicks.currentOffset
    clicks.register(storyId, { max: clicks.currentOffset + n - 1, delta: n - 1 })
  }
})
onUnmounted(() => { try { clicks?.unregister?.(storyId) } catch {} })
const stepIndex = computed(() => {
  const n = story.value.steps.length
  if (n < 2 || !clicks) return 0
  return Math.max(0, Math.min(n - 1, Math.round(Number(clicks.current) - storyStart.value)))
})
// What the chart is at the current step: its own settings with the step on top.
const effective = computed<Record<string, any>>(() => (story.value.steps.length ? stepSettings(props, story.value.steps, stepIndex.value) : props))
const optionMode = computed(() => isOptionChart(effective.value))

// The settings the engine reads. A chart drawn from its option still takes
// Studio's Title and Colours when the option has none of its own, and a
// type chosen in Studio's panel does not turn it back into an older chart.
const settings = computed(() => {
  const now = effective.value
  const all: Record<string, any> = { ...now }
  if (!optionMode.value) return all
  const option = readOverride(now.option, 5000).value ?? {}
  const extra: Record<string, any> = {}
  if (String(now.title || '').trim() && option.title === undefined) extra.title = { text: String(now.title).trim() }
  if (Array.isArray(now.colors) && now.colors.length && option.color === undefined) extra.color = now.colors
  return { ...all, type: undefined, option: Object.keys(extra).length ? { ...option, ...extra } : option }
})
const label = computed(() => {
  if (optionMode.value) {
    const title = settings.value.option?.title
    return String((Array.isArray(title) ? title[0]?.text : title?.text) || '').trim() || 'Chart'
  }
  return String(props.title || '').trim() || TYPE_NAMES[chartType(props.type)]
})

// ---- numbers from the database (`query`) ----
const hasQuery = computed(() => props.query !== undefined && props.query !== null && props.query !== '')
const spec = computed(() => {
  if (!hasQuery.value) return { value: null, key: '', problem: '' }
  try {
    const value = normalizeSpec(props.query)
    return { value, key: canonicalJson(value), problem: '' }
  }
  catch (error: any) {
    return { value: null, key: '', problem: `The chart's settings have a mistake: ${error?.message || error}` }
  }
})
const deck = typeof location === 'undefined' ? '' : deckOfPath(location.pathname)
const editing = typeof location !== 'undefined' && location.pathname.startsWith('/edit/')
// The last numbers for this query: a slide rebuilt in the editor shows them at once.
const answer = ref<ChartAnswer | null>(spec.value.key ? peekChartData(deck, spec.value.key) : null)
const state = ref<'loading' | 'ready' | 'error'>(answer.value ? 'ready' : 'loading')
const loadError = ref('')

// Coming back to the slide tries again after a failure and refreshes numbers
// older than ten minutes (a deck can stay open through a whole meeting).
const STALE_MS = 10 * 60 * 1000
let loadedAt = 0
let request = 0
async function load() {
  const { value, key } = spec.value
  if (!value) return
  const mine = ++request
  if (!answer.value) state.value = 'loading'
  try {
    const got = await fetchChartData(deck, value, key)
    if (mine !== request) return
    answer.value = got
    loadedAt = Date.now()
    state.value = 'ready'
    if (editing && got.meta?.pinned === false)
      console.warn(`[gfm-addon] MissionChart "${label.value}": leaders who view this deck cannot see it, because its query is not written in the slides as plain JSON (use Add chart or Edit chart to write it).`)
  }
  catch (error) {
    if (mine !== request) return
    loadError.value = error instanceof ChartDataError ? error.message : 'The numbers could not load. Try again in a minute.'
    if (!answer.value || error instanceof ChartDataError) {
      answer.value = null
      state.value = 'error'
    }
  }
}
onMounted(() => { if (hasQuery.value) load() })
watch(() => spec.value.key, (now, before) => {
  if (now === before) return
  answer.value = now ? peekChartData(deck, now) : null
  if (now) load()
})

// What to draw: the older settings (drawn exactly as before) or the option.
const view = computed(() => chartView(settings.value, hasQuery.value ? answer.value : null))
const suppressed = computed(() => !!(hasQuery.value && answer.value?.meta?.suppressed))
// Everything the drawing depends on: a render that would draw the same chart draws nothing.
function signature() {
  const v = view.value
  try { return JSON.stringify([v.mode, v.table, v.mode === 'legacy' ? v.settings : v.option]) }
  catch { return `${Date.now()}` }
}
const chartKey = () => (props.chartId ? `${deck}#${props.chartId}` : '')
function sizeAware() {
  const v = view.value
  if (v.mode === 'legacy') return chartType(props.type) === 'tile' || !!props.multiples
  return ['tile', 'multiples'].includes(v.option?.gfm?.kind) || !!v.table?.byUnit
}

const { render, failed, ready } = useMissionChart(el, ctx => viewOption(view.value, ctx), () => {
  if (!hasQuery.value) return
  if (state.value === 'error' || (state.value === 'ready' && Date.now() - loadedAt > STALE_MS)) load()
}, sizeAware, signature, chartKey, () => (story.value.steps.length > 1 ? storyMotion(props) : null))
watch(view, () => render(), { flush: 'post' })

// A mistake in the advanced settings of an older chart is reported once; the chart is drawn without them.
watch(() => props.option, (option) => {
  if (optionMode.value) return
  const { problem } = readOverride(option)
  if (problem) console.warn(`[gfm-addon] MissionChart "${label.value}": ${problem} The chart is shown without them.`)
}, { immediate: true })

const problem = computed(() => {
  if (!hasQuery.value) return view.value.problem
  if (spec.value.problem) return spec.value.problem
  if (state.value === 'error') return loadError.value
  if (state.value !== 'ready') return ''
  return view.value.problem
})
const loading = computed(() => !failed.value && !problem.value && (!ready.value || (hasQuery.value && state.value === 'loading')))
const message = computed(() => failed.value
  ? 'The chart could not be loaded. Reload the page to try again.'
  : problem.value || (loading.value ? (hasQuery.value ? 'Loading mission numbers…' : 'Loading chart…') : ''))

// A mistake in a calculated field: the chart is drawn without that field, and the editor says why (a published deck
// stays quiet: viewers cannot fix it).
const calcNote = computed(() => {
  const first = (view.value as any).calc?.problems?.[0]
  return first ? `Calculated field${first.name ? ` “${first.name}”` : ''}: ${first.message}` : ''
})

// While the editor is open, the chart's numbers (with its calculated fields) are kept on its element, so GFM Studio's
// Data panel can list the fields and preview a formula. Nothing is kept in a published deck.
function keepForEditor() {
  if (!editing || !root.value) return
  const v = view.value as any
  ;(root.value as any).__gfmChart = { table: v.source ?? v.table ?? null, shown: v.table ?? null, calc: v.calc ?? null, problem: problem.value || '' }
}
watch([view, () => problem.value], keepForEditor, { flush: 'post' })
onMounted(keepForEditor)
</script>

<template>
  <div ref="root" class="gfm-chart" :style="box" role="figure" :aria-label="label" :data-chart-id="chartId || undefined">
    <!-- ECharts writes the chart's spoken description on this element. -->
    <div ref="el" class="gfm-chart__plot" :class="{ 'gfm-chart__plot--noted': suppressed && !message }" :role="message ? undefined : 'img'" />
    <div v-if="message" class="gfm-chart__message" :class="{ 'gfm-chart__message--loading': loading }">
      <strong v-if="optionMode ? label !== 'Chart' : title">{{ optionMode ? label : title }}</strong>
      <span>{{ message }}</span>
    </div>
    <div v-else-if="suppressed" class="gfm-chart__note">Numbers below 3 are hidden to protect privacy.</div>
    <div v-if="editing && calcNote" class="gfm-chart__calc">{{ calcNote }}</div>
  </div>
</template>

<style scoped>
.gfm-chart {
  position: relative;
  width: 100%;
}
.gfm-chart__plot {
  position: absolute;
  inset: 0;
}
.gfm-chart__plot--noted {
  bottom: 20px;
}
.gfm-chart__note {
  position: absolute;
  right: 0;
  bottom: 0;
  font-size: 12px;
  line-height: 16px;
  opacity: 0.7;
}
.gfm-chart__calc {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  font-size: 12px;
  line-height: 16px;
  color: #b42318;
  background: rgba(255, 255, 255, 0.85);
  padding: 2px 6px;
}
.gfm-chart__message {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 16px;
  text-align: center;
  font-size: 15px;
  line-height: 1.4;
  opacity: 0.75;
  border: 1px dashed currentColor;
  border-radius: 10px;
}
.gfm-chart__message strong {
  font-size: 17px;
  font-weight: 600;
}
/* Shown only if drawing takes a while, so a quick chart does not flash it. */
.gfm-chart__message--loading {
  border-color: transparent;
  animation: gfm-chart-appear 0.2s ease-out 0.4s both;
}
@keyframes gfm-chart-appear {
  from { opacity: 0; }
  to { opacity: 0.75; }
}
</style>

<studio>
description: A chart from your own numbers or from mission numbers, drawn with ECharts. Use Add chart at the top of the editor to make one, and Edit chart to change the selected chart (every chart type, the numbers, and every setting). The settings below are for charts written the older way.
category: Charts
snippet: >-
  <MissionChart :rows="['Label, Value', 'A, 3', 'B, 5', 'C, 4']" :option='{"series":[{"type":"bar"}]}' />
preview: '<MissionChart type="bar" :height="150" csv="Label,Value; A,3; B,5; C,4" />'
props:
  type:
    label: Chart type
  title:
    label: Title
  rows:
    label: Data, one row per box (first row = headings; for mission numbers use Add chart)
  csv:
    hidden: true
  data:
    hidden: true
  trend:
    label: Trend line
  degree:
    label: Trend degree (polynomial, 2–6)
  trendColor:
    label: Trend line colour (empty = the series colour)
    control: color
  colors:
    label: Series colours
    control: color[]
  showValues:
    label: Show values
  height:
    label: Height (slide pixels)
  max:
    label: Maximum (gauge and radar)
  trendStyle:
    label: More · Trend line style
  trendWidth:
    label: More · Trend line width (1–8)
  trendLabel:
    label: More · Trend name in the legend
  window:
    label: More · Moving average over how many points (2–52)
  forecast:
    label: More · Forecast periods (needs a trend line)
  goal:
    label: More · Goal column (its heading)
  goalColor:
    label: More · Goal line colour
    control: color
  target:
    label: More · A line at this number
  targetLabel:
    label: More · That line's name (for example Goal)
  targetColor:
    label: More · That line's colour
    control: color
  average:
    label: More · Average line
  averageColor:
    label: More · Average line colour
    control: color
  legend:
    label: More · Legend
  xTitle:
    label: More · Title under the chart (x axis)
  yTitle:
    label: More · Title beside the numbers (y axis)
  yMin:
    label: More · Lowest number on the axis
  yMax:
    label: More · Highest number on the axis
  labelRotate:
    label: More · Turn the labels (degrees)
  format:
    label: More · Number format
  decimals:
    label: More · Decimal places
  prefix:
    label: More · Before each number (e.g. €)
  suffix:
    label: More · After each number (e.g. people)
  valuePosition:
    label: More · Where the values go
  stack:
    label: More · Stack the series
  horizontal:
    label: More · Horizontal bars
  smooth:
    label: More · Smooth lines
  seriesTypes:
    label: More · Type per series (line, bar, area or scatter)
  multiples:
    label: More · One small chart per series
  dataZoom:
    label: More · Zoom slider
  option:
    hidden: true
  chartId:
    hidden: true
  query:
    hidden: true
  calc:
    hidden: true
  preset:
    hidden: true
  presetTop:
    hidden: true
  presetAggregate:
    hidden: true
  presetTarget:
    hidden: true
  shape:
    hidden: true
  story:
    hidden: true
  storyTransition:
    hidden: true
  storyDuration:
    hidden: true
  storyEasing:
    hidden: true
</studio>
