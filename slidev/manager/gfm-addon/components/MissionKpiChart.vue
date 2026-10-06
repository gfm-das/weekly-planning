<script setup lang="ts">
/**
 * MissionKpiChart — live mission numbers for one key indicator, week by week, with the goal and a trend line.
 *
 * <MissionKpiChart kpi="New people being taught" :weeks="12" chart="bar" trend="linear" />
 *
 * `kpi` is the indicator's name (New people being taught, Baptisms and
 * confirmations, Baptismal dates, Sacrament attendance, Members at lessons,
 * New member sacrament attendance) or its id (friends_found, …). Decks
 * written before the rename keep working with kpi="Friends found".
 * The numbers are the mission totals reported in Call-ins, loaded when the
 * slide is shown (so a published deck always shows the latest weeks).
 * The goal for a week is the goal set the week before, as in Call-ins.
 * `weeks` is 1–104; `chart` is bar, line, area or tile (a key number with a
 * small line of the weeks); `trend` is worked out by echarts-stat; `height`
 * is in slide pixels (a slide is 980 wide). The props are listed simple ones
 * first, because Studio's Element panel shows them in this order.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { buildOption, fetchMissionKpis, KPI_NAMES, kpiChart, kpiId, kpiWeekCount, useMissionChart } from '../lib/charts'
import type { KpiWeek } from '../lib/charts'

const props = withDefaults(defineProps<{
  kpi?: string // a name from KPI_NAMES ('New people being taught', or the old 'Friends found') or its id ('friends_found')
  weeks?: number
  chart?: 'bar' | 'line' | 'area' | 'tile'
  showGoal?: boolean
  trend?: 'linear' | 'polynomial' | 'exponential' | 'logarithmic' | 'moving-average' | 'none'
  degree?: number
  trendColor?: string
  colors?: string[]
  goalColor?: string
  title?: string
  height?: number
  showValues?: boolean
  trendStyle?: 'dashed' | 'dotted' | 'solid'
  trendWidth?: number
  trendLabel?: string
  window?: number
  forecast?: number
  target?: number
  targetLabel?: string
  targetColor?: string
  average?: boolean
  averageColor?: string
  legend?: 'auto' | 'top' | 'bottom' | 'right' | 'none'
  yMin?: number
  yMax?: number
  smooth?: boolean
  valuePosition?: 'auto' | 'top' | 'inside' | 'bottom'
  dataZoom?: boolean
  option?: Record<string, any> | string
  chartId?: string
}>(), {
  kpi: 'friends_found',
  weeks: 12,
  chart: 'bar',
  showGoal: true,
  trend: 'linear',
  degree: 2,
  trendColor: '',
  goalColor: '',
  title: '',
  height: 360,
  showValues: false,
  trendStyle: 'dashed',
  trendWidth: 2,
  trendLabel: '',
  window: 3,
  forecast: 0,
  targetLabel: 'Target',
  targetColor: '',
  average: false,
  averageColor: '',
  legend: 'auto',
  smooth: false,
  valuePosition: 'auto',
  dataZoom: false,
  chartId: '',
})

const el = ref<HTMLElement>()
const rows = ref<KpiWeek[] | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const weekCount = computed(() => kpiWeekCount(props.weeks))
const kpiKey = computed(() => kpiId(props.kpi))
const heading = computed(() => String(props.title || '').trim() || KPI_NAMES[kpiKey.value])
const box = computed(() => ({ height: `${Math.max(120, Math.min(2000, Number(props.height) || 360))}px` }))

// The table (weeks, actual and goal) and the settings handed to the chart.
const view = computed(() => kpiChart(rows.value, props, heading.value))
const table = computed(() => view.value.table)

// Coming back to the slide tries again after a failure and refreshes numbers
// older than ten minutes (a deck can stay open through a whole meeting).
const STALE_MS = 10 * 60 * 1000
let loadedAt = 0

const { render, failed, ready } = useMissionChart(el, ctx => buildOption(table.value, view.value.settings, ctx), () => {
  if (state.value === 'error' || (state.value === 'ready' && Date.now() - loadedAt > STALE_MS)) load()
}, () => props.chart === 'tile')

let request = 0
async function load() {
  const mine = ++request
  // A refresh keeps showing the numbers it already has.
  if (!rows.value) state.value = 'loading'
  try {
    const list = await fetchMissionKpis(weekCount.value)
    if (mine !== request) return
    rows.value = list
    loadedAt = Date.now()
    state.value = 'ready'
  }
  catch {
    if (mine !== request) return
    if (!rows.value) state.value = 'error'
  }
}

onMounted(load)
watch(weekCount, () => { rows.value = null; load() })
watch(view, () => render(), { deep: true, flush: 'post' })

const loading = computed(() => !failed.value && (state.value === 'loading' || (state.value === 'ready' && !!table.value && !ready.value)))
const message = computed(() => {
  if (failed.value) return 'The chart could not be loaded. Reload the page to try again.'
  if (loading.value) return 'Loading mission numbers…'
  if (state.value === 'error') return 'The numbers could not load. Try again in a minute.'
  return table.value ? '' : 'No numbers for these weeks yet.'
})
</script>

<template>
  <div class="gfm-chart" :style="box" role="figure" :aria-label="heading" :data-chart-id="chartId || undefined">
    <!-- ECharts writes the chart's spoken description on this element. -->
    <div ref="el" class="gfm-chart__plot" :role="message ? undefined : 'img'" />
    <div v-if="message" class="gfm-chart__message" :class="{ 'gfm-chart__message--loading': loading }">
      <strong>{{ heading }}</strong>
      <span>{{ message }}</span>
    </div>
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
/* Shown only if loading takes a while, so a quick chart does not flash it. */
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
description: Live mission numbers for one key indicator, week by week, with the goal and a trend line. The first settings are the everyday ones; the ones marked More fine-tune the chart.
category: Charts
snippet: '<MissionKpiChart kpi="New people being taught" :weeks="12" chart="bar" trend="linear" />'
preview: '<MissionKpiChart kpi="New people being taught" :weeks="8" :height="150" />'
props:
  kpi:
    label: Key indicator
    options:
      - New people being taught
      - Baptisms and confirmations
      - Baptismal dates
      - Sacrament attendance
      - Members at lessons
      - New member sacrament attendance
  weeks:
    label: Weeks (1–104)
  chart:
    label: Chart type (tile = one big number)
  showGoal:
    label: Show the goal
  trend:
    label: Trend line
  degree:
    label: Trend degree (polynomial, 2–6)
  trendColor:
    label: Trend line colour (empty = the bar or line colour)
    control: color
  colors:
    label: Colours
    control: color[]
  goalColor:
    label: Goal line colour
    control: color
  title:
    label: Title (default is the indicator's name)
  height:
    label: Height (slide pixels)
  showValues:
    label: Show values
  trendStyle:
    label: More · Trend line style
  trendWidth:
    label: More · Trend line width (1–8)
  trendLabel:
    label: More · Trend name in the legend
  window:
    label: More · Moving average over how many weeks (2–52)
  forecast:
    label: More · Forecast weeks (needs a trend line)
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
  yMin:
    label: More · Lowest number on the axis
  yMax:
    label: More · Highest number on the axis
  smooth:
    label: More · Smooth line
  valuePosition:
    label: More · Where the values go
  dataZoom:
    label: More · Zoom slider
  chartId:
    hidden: true
  option:
    hidden: true
</studio>
