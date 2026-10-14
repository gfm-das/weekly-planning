<script setup lang="ts">
/**
 * MmmPair - the two coloured boxes beside a chart on the Stake coordination pages: the blue "Actual" and the red
 * "Goal". Live from the weekly plans (the sum of the last `weeks` weeks of the first number and of its goal), or typed
 * in the slide (`actual`, `goal`) for a number the portal does not hold yet; typed boxes carry a "Manual" tag while
 * `placeholder` is on.
 *
 * <MmmPair x="940" y="60" labels="Actual|Goal" :weeks="4"
 *   :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":4}' />
 */
import { computed } from 'vue'
import { listOf, numberText, pairSums, useMmmQuery } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  query?: Record<string, any> | string
  labels?: string[] | string
  weeks?: number
  actual?: number | string
  goal?: number | string
  tag?: string
  placeholder?: boolean
}>(), { x: 900, y: 60, w: 110, weeks: 4, tag: 'Manual', placeholder: false })

const { answer, message, has } = useMmmQuery(() => props.query)
const locale = typeof document === 'undefined' ? undefined : document.documentElement.lang || undefined
const names = computed(() => listOf(props.labels))
const typed = (v: any) => (v === undefined || v === null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v))
const sums = computed(() => (has.value && answer.value ? pairSums(answer.value, { weeks: props.weeks }) : { ready: true, actual: typed(props.actual), goal: typed(props.goal) }))
const place = computed(() => ({ left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))` }))
</script>

<template>
  <div class="mmm-box mmm-pair" :style="place">
    <span v-if="placeholder" class="mmm-manual-tag" style="right: 0; top: calc(-18 * var(--u))">{{ tag }}</span>
    <div class="mmm-pair__label">{{ names[0] }}</div>
    <div class="mmm-pair__box mmm-pair__box--actual">{{ numberText((sums as any).actual, locale) || '–' }}</div>
    <div class="mmm-pair__label">{{ names[1] }}</div>
    <div class="mmm-pair__box mmm-pair__box--goal">{{ numberText((sums as any).goal, locale) || '–' }}</div>
    <div v-if="message" class="mmm-pair__note">{{ message }}</div>
  </div>
</template>

<style>
.mmm-pair__label { text-align: center; font-size: calc(13 * var(--u)); font-weight: 700; margin-bottom: calc(3 * var(--u)); }
.mmm-pair__box { text-align: center; font-size: calc(36 * var(--u)); font-weight: 700; line-height: 1; color: #fff; padding: calc(9 * var(--u)) 0; border-radius: calc(8 * var(--u)); border: calc(2 * var(--u)) solid #fff; margin-bottom: calc(14 * var(--u)); }
.mmm-pair__box--actual { background: #1f78d8; }
.mmm-pair__box--goal { background: #c4171f; }
.mmm-pair__note { font-size: calc(10 * var(--u)); color: var(--mmm-muted); }
</style>

<studio>
description: "The blue Actual box and red Goal box beside a Stake chart - summed from the weekly plans, or typed and marked Manual."
category: GFM data
snippet: '<MmmPair x="900" y="60" labels="Actual|Goal" actual="3" goal="3" placeholder />'
props:
  labels:
    label: Names of the two boxes (separated by |)
  actual:
    label: Typed actual (when there is no query)
  goal:
    label: Typed goal
  placeholder:
    label: Mark as typed by hand (Manual tag)
</studio>
