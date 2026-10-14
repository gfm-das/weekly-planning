<script setup lang="ts">
/**
 * MmmGauge - a half-circle gauge of the Monday Morning Meeting, zone conference and Stake decks: the arc, the number
 * in its middle, the change from the week before under it, a black tick for a target, "0" and the top value at its ends
 * and a title below. Drawn as plain SVG, so it prints and exports exactly as it looks.
 *
 * <MmmGauge x="735" y="325" w="362" h="250" tone="yellow" title="First Time First Week Attendance" :max="100"
 *   :query='{"measures":["first_time_sacrament.actual"],"weeks":4}' />
 *
 * `mode`: value (the latest week against `max`), ratio (the second number as a share of the first, with `target` as
 * the tick), year (how much of the year has passed) or manual (`value`, `change` typed in the slide; a rate that has
 * no source in the portal is typed here and carries a "Manual" tag while `placeholder` is on).
 */
import { computed } from 'vue'
import { gaugeModel, useMmmQuery } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  h?: number
  title?: string
  query?: Record<string, any> | string
  mode?: 'value' | 'ratio' | 'year' | 'manual'
  tone?: 'cyan' | 'green' | 'yellow'
  max?: number
  target?: number | string
  value?: number | string
  change?: number | string
  minLabel?: string
  maxLabel?: string
  tag?: string
  placeholder?: boolean
}>(), {
  x: 735, y: 325, w: 362, h: 250, title: '', mode: 'value', tone: 'cyan', max: 100, minLabel: '0', maxLabel: '', tag: 'Manual', placeholder: false,
})

const { answer, message, has } = useMmmQuery(() => props.query)
const model = computed<any>(() => gaugeModel(has.value ? answer.value : null, {
  mode: props.mode, max: props.max, target: props.target === '' ? null : (props.target as any), value: props.value as any, change: props.change as any,
}))

// The arc: centre (170, 176), outer radius 160, inner radius 122, from the left (180 degrees) over the top to the right.
const CX = 170, CY = 176, RO = 160, RI = 122
const at = (r: number, ratio: number) => { const a = Math.PI * (1 - ratio); return [CX + r * Math.cos(a), CY - r * Math.sin(a)] }
const band = (from: number, to: number) => {
  to = Math.min(to, 0.9995)
  if (to - from <= 0.0005) return ''
  const [ox1, oy1] = at(RO, from), [ox2, oy2] = at(RO, to), [ix2, iy2] = at(RI, to), [ix1, iy1] = at(RI, from)
  const large = 0 // the arc never spans more than 180 degrees
  return `M${ox1.toFixed(2)} ${oy1.toFixed(2)}A${RO} ${RO} 0 ${large} 1 ${ox2.toFixed(2)} ${oy2.toFixed(2)}L${ix2.toFixed(2)} ${iy2.toFixed(2)}A${RI} ${RI} 0 ${large} 0 ${ix1.toFixed(2)} ${iy1.toFixed(2)}Z`
}
const ratio = computed(() => (model.value.ready ? model.value.ratio : 0))
const fillPath = computed(() => band(0, ratio.value))
const restPath = computed(() => band(ratio.value, 1))
const tick = computed(() => {
  const t = model.value.tick
  if (t === null || t === undefined || !model.value.ready) return null
  const r = model.value.max > 1 ? t / model.value.max : t
  const [x1, y1] = at(RI - 4, Math.max(0, Math.min(1, r))), [x2, y2] = at(RO + 4, Math.max(0, Math.min(1, r)))
  return { x1, y1, x2, y2 }
})
const changeText = computed(() => {
  const c = model.value.change
  if (c === null || c === undefined || !Number.isFinite(c)) return ''
  const body = model.value.changeIsPoints ? `${Math.abs(c).toFixed(2)}%` : String(Math.abs(Math.round(c * 100) / 100))
  return c < 0 ? `-${body}` : body
})
const place = computed(() => ({
  left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))`, height: `calc(${props.h} * var(--u))`,
}))
const top = computed(() => props.maxLabel || (model.value.ready ? (model.value.percent ? '1' : String(model.value.max)) : (props.mode === 'manual' || Number(props.max) <= 1 ? '1' : String(props.max))))
</script>

<template>
  <div class="mmm-box mmm-gauge mmm-panel" :class="`mmm-gauge--${tone}`" :style="place" role="img" :aria-label="`${title}: ${model.display || ''}`">
    <span v-if="placeholder" class="mmm-manual-tag">{{ tag }}</span>
    <svg class="mmm-gauge__svg" viewBox="0 0 340 200" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <path v-if="restPath" :d="restPath" class="mmm-gauge__rest" />
      <path v-if="fillPath" :d="fillPath" class="mmm-gauge__fill" />
      <line v-if="tick" :x1="tick.x1" :y1="tick.y1" :x2="tick.x2" :y2="tick.y2" class="mmm-gauge__tick" />
    </svg>
    <div class="mmm-gauge__num">{{ model.ready ? model.display : '–' }}</div>
    <div v-if="changeText" class="mmm-gauge__change" :class="changeText.startsWith('-') ? 'is-down' : 'is-up'">{{ changeText }}</div>
    <div class="mmm-gauge__end mmm-gauge__end--min">{{ minLabel }}</div>
    <div class="mmm-gauge__end mmm-gauge__end--max">{{ top }}</div>
    <div class="mmm-gauge__title">{{ title }}</div>
    <div v-if="message" class="mmm-message">{{ message }}</div>
  </div>
</template>

<style>
.mmm-gauge { --g: var(--mmm-cyan); --gt: var(--mmm-cyan-tint); }
.mmm-gauge--green { --g: var(--mmm-green); --gt: #c8e6d3; }
.mmm-gauge--yellow { --g: var(--mmm-yellow); --gt: #fff7d1; }
.mmm-gauge__svg { position: absolute; left: 4%; right: 4%; top: 6%; width: 92%; height: 76%; }
.mmm-gauge__fill { fill: var(--g); }
.mmm-gauge__rest { fill: var(--gt); }
.mmm-gauge__tick { stroke: #000; stroke-width: 5; stroke-linecap: butt; }
.mmm-dark .mmm-gauge__tick { stroke: #fff; }
.mmm-gauge__num { position: absolute; left: 0; right: 0; top: 47%; text-align: center; font-size: calc(46 * var(--u)); font-weight: 300; line-height: 1; }
.mmm-gauge__change { position: absolute; left: 0; right: 0; top: 66%; text-align: center; font-size: calc(21 * var(--u)); font-weight: 400; }
.mmm-gauge__change.is-up { color: var(--mmm-green); }
.mmm-gauge__change.is-down { color: #f26d6d; }
.mmm-gauge__end { position: absolute; top: 79%; font-size: calc(13 * var(--u)); font-weight: 400; }
.mmm-gauge__end--min { left: 6%; }
.mmm-gauge__end--max { right: 6%; }
.mmm-gauge__title { position: absolute; left: 0; right: 0; bottom: calc(10 * var(--u)); text-align: center; font-weight: 700; font-size: calc(18 * var(--u)); }
</style>

<studio>
description: "A half-circle gauge with the number in the middle, the change from the week before and an optional target tick. Live from the weekly plans, or typed and marked Manual."
category: GFM data
snippet: '<MmmGauge x="735" y="325" w="362" h="250" tone="yellow" title="First Time First Week Attendance" :max="100" :query=''{"measures":["first_time_sacrament.actual"],"weeks":4}'' />'
props:
  title:
    label: Title
  tone:
    label: Colour
    options:
      - cyan
      - green
      - yellow
  mode:
    label: What it shows
    options:
      - value
      - ratio
      - year
      - manual
  placeholder:
    label: Mark as typed by hand (Manual tag)
</studio>
