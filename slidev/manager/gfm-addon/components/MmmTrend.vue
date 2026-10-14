<script setup lang="ts">
/**
 * MmmTrend - the "Last 90 Days" chart of the Monday Morning Meeting, zone conference and Stake decks: smooth lines with
 * a soft area under each, optional dashed trend lines, optional value labels, in a white framed panel with a title.
 * Live from the weekly plans, like <MissionChart :query>:
 *
 * <MmmTrend x="55" y="325" w="660" h="250" title="Last 90 Days" :labels="['Friends Found','Church Attendance']"
 *   :colors="['#4da580','#ffa90a']" :query='{"measures":["friends_found.actual","sacrament_attendance.actual"],"weeks":13}' />
 *
 * `labels` are the names in the legend (written in the slide's language: the numbers come from the portal under their
 * English names, so the slide names them itself). `cumulative` draws a running total with a label on each step (the
 * query then uses "transform": "cumulative").
 */
import { computed, ref, watch } from 'vue'
import { useMissionChart, weekLabels } from '../lib/charts'
import { listOf, readAnswer, useMmmQuery } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  h?: number
  title?: string
  query?: Record<string, any> | string
  labels?: string[] | string
  colors?: string[] | string
  trend?: boolean
  goal?: boolean
  values?: boolean
  legend?: boolean
  smooth?: boolean
  yMax?: number
}>(), {
  x: 55, y: 325, w: 660, h: 250, title: '', trend: false, goal: false, values: false, legend: true, smooth: true,
})

const el = ref<HTMLElement>()
const { answer, message, refresh, has } = useMmmQuery(() => props.query)
const PALETTE = ['#4da580', '#ffa90a', '#ffe600', '#d32f2f', '#2e7d32', '#1f6fd1']
const names = computed(() => listOf(props.labels))
const colors = computed(() => (listOf(props.colors).length ? listOf(props.colors) : PALETTE))
const table = computed(() => {
  if (!has.value || !answer.value) return null
  const read = readAnswer(answer.value)
  if (!read.labels.length || !read.actuals.length) return null
  // With `goal` the goal series are drawn too, after the actuals (the Stake pages show both lines).
  return { weeks: read.labels, series: props.goal ? [...read.actuals, ...read.goals] : read.actuals }
})
const empty = computed(() => !!table.value && !table.value.series.some(s => s.values.some(v => v !== null)))

// The straight line of least squares through a series' points (a dashed "trend").
function line(values: (number | null)[]) {
  const pts = values.map((v, i) => [i, v] as const).filter(([, v]) => v !== null) as [number, number][]
  if (pts.length < 3) return values.map(() => null)
  const n = pts.length, sx = pts.reduce((a, p) => a + p[0], 0), sy = pts.reduce((a, p) => a + p[1], 0)
  const sxy = pts.reduce((a, p) => a + p[0] * p[1], 0), sxx = pts.reduce((a, p) => a + p[0] * p[0], 0)
  const d = n * sxx - sx * sx
  if (!d) return values.map(() => null)
  const m = (n * sxy - sx * sy) / d, b = (sy - m * sx) / n
  return values.map((_, i) => Math.max(0, m * i + b))
}

function build(ctx: any) {
  const t = table.value
  if (!t || empty.value) return null
  const frame = el.value?.closest('.mmm-frame') as HTMLElement | null
  const k = frame ? frame.clientWidth / 1152 : 0.85
  const fs = Math.max(8, Math.round(12.5 * k * 10) / 10)
  const ink = ctx.dark ? '#f1f3f5' : '#2d505e'
  const grid = ctx.dark ? '#4a4a4a' : '#d9dde2'
  const x = weekLabels(t.weeks)
  const series: any[] = []
  t.series.forEach((s, i) => {
    const color = colors.value[i % colors.value.length]
    const name = names.value[i] || s.name
    series.push({
      name, type: 'line', smooth: props.smooth, symbol: props.values ? 'circle' : 'none', symbolSize: 4 * k * 1.5, data: s.values,
      lineStyle: { color, width: 2 * k * 1.2 }, itemStyle: { color },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}55` }, { offset: 1, color: `${color}05` }] } },
      label: props.values ? { show: true, position: 'top', color, fontSize: fs, fontFamily: 'inherit' } : { show: false },
      connectNulls: true, animation: false, z: 3 + i,
    })
    if (props.trend) {
      series.push({ name: `${name} (trend)`, type: 'line', symbol: 'none', data: line(s.values), lineStyle: { color: ctx.dark ? '#ddd' : '#111', width: 1.2 * k * 1.2, type: [8 * k, 5 * k] }, silent: true, tooltip: { show: false }, animation: false, z: 2 })
    }
  })
  return {
    animation: false,
    textStyle: { fontFamily: ctx.font, color: ink, fontSize: fs },
    grid: { left: 36 * k, right: 12 * k, top: (props.legend ? 36 : 14) * k, bottom: 38 * k, containLabel: false },
    legend: props.legend ? { show: true, top: 4 * k, right: 10 * k, itemWidth: 22 * k, itemHeight: 2 * k, itemGap: 26 * k, textStyle: { color: ink, fontSize: fs * 0.95 }, data: series.filter(s => !String(s.name).endsWith('(trend)')).map(s => s.name) } : { show: false },
    xAxis: { type: 'category', data: x, boundaryGap: false, axisLine: { lineStyle: { color: grid } }, axisTick: { show: false }, axisLabel: { color: ink, fontSize: fs, interval: 'auto', hideOverlap: true } },
    yAxis: { type: 'value', min: 0, max: props.yMax || undefined, splitLine: { lineStyle: { color: grid } }, axisLabel: { color: ink, fontSize: fs } },
    series,
  }
}

const { render, failed, ready } = useMissionChart(el, build, refresh, () => true,
  () => { try { return JSON.stringify([table.value, names.value, colors.value, props.trend, props.goal, props.values, props.legend, props.smooth, props.yMax]) } catch { return `${Date.now()}` } })
watch([table, names, colors, () => props.trend, () => props.goal, () => props.values, () => props.legend, () => props.smooth, () => props.yMax], () => render(), { flush: 'post' })

const text = computed(() => (failed.value ? 'The chart could not be loaded. Reload the page to try again.' : message.value || (empty.value ? 'No numbers for these weeks yet.' : (has.value && !ready.value ? 'Loading mission numbers…' : ''))))
const place = computed(() => ({
  left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))`, height: `calc(${props.h} * var(--u))`,
}))
</script>

<template>
  <div class="mmm-box mmm-trend mmm-panel" :style="place" role="figure" :aria-label="title">
    <div v-if="title" class="mmm-trend__title">{{ title }}</div>
    <div ref="el" class="mmm-trend__plot" />
    <div v-if="text" class="mmm-message">{{ text }}</div>
  </div>
</template>

<style>
.mmm-trend { overflow: hidden; }
.mmm-trend__title { position: absolute; left: calc(5 * var(--u)); top: calc(5 * var(--u)); z-index: 2; font-weight: 700; font-size: calc(17 * var(--u)); }
.mmm-trend__plot { position: absolute; inset: calc(24 * var(--u)) calc(4 * var(--u)) calc(2 * var(--u)) calc(4 * var(--u)); }
</style>

<studio>
description: "The 'Last 90 Days' trend chart - smooth lines with a soft area, optional dashed trend lines and value labels. Live from the weekly plans."
category: GFM data
snippet: '<MmmTrend x="55" y="325" w="660" h="250" title="Last 90 Days" :labels="[''Friends Found'']" :query=''{"measures":["friends_found.actual"],"weeks":13}'' />'
props:
  title:
    label: Title
  trend:
    label: Dashed trend lines
  values:
    label: Numbers on the points
  legend:
    label: Show the legend
</studio>
