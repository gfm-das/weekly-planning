<script setup lang="ts">
/**
 * GfmComparison - two numbers side by side with the change between them (this week and last week, two zones ...).
 *
 * <GfmComparison leftLabel="Last week" :leftValue="41" rightLabel="This week" :rightValue="47" />
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  leftLabel?: string
  leftValue?: number
  rightLabel?: string
  rightValue?: number
  unit?: string
}>(), {
  leftLabel: 'Before',
  leftValue: 0,
  rightLabel: 'Now',
  rightValue: 0,
  unit: '',
})

const diff = computed(() => props.rightValue - props.leftValue)
const percent = computed(() => (props.leftValue ? Math.round((diff.value / Math.abs(props.leftValue)) * 100) : null))
const tone = computed(() => (diff.value > 0 ? 'good' : diff.value < 0 ? 'bad' : 'neutral'))
const text = computed(() => `${diff.value > 0 ? '+' : ''}${diff.value}${props.unit}${percent.value === null ? '' : ` (${diff.value > 0 ? '+' : ''}${percent.value}%)`}`)
</script>

<template>
  <div class="gfm-compare">
    <div class="gfm-compare__side">
      <div class="gfm-label">{{ leftLabel }}</div>
      <div class="gfm-compare__value gfm-compare__value--before">{{ leftValue }}{{ unit }}</div>
    </div>
    <div class="gfm-compare__change" :class="`gfm-tone-${tone}`">{{ diff > 0 ? '▲' : diff < 0 ? '▼' : '=' }}<span>{{ text }}</span></div>
    <div class="gfm-compare__side">
      <div class="gfm-label">{{ rightLabel }}</div>
      <div class="gfm-compare__value">{{ rightValue }}{{ unit }}</div>
    </div>
  </div>
</template>

<style>
.gfm-compare { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 10px 0; }
.gfm-compare__side { min-width: 0; }
.gfm-compare__value { font-size: 64px; line-height: 1.05; font-weight: 750; letter-spacing: -0.02em; color: var(--gfm-navy); }
.gfm-compare__value--before { color: var(--gfm-muted); }
.gfm-compare__change { display: flex; flex-direction: column; align-items: center; font-size: 28px; font-weight: 700; line-height: 1.2; }
.gfm-compare__change span { font-size: 20px; }
</style>

<studio>
description: Two numbers side by side with the change between them - this week and last week, or two zones.
category: GFM content
snippet: '<GfmComparison leftLabel="Last week" :leftValue="41" rightLabel="This week" :rightValue="47" />'
preview: '<GfmComparison leftLabel="Last week" :leftValue="41" rightLabel="This week" :rightValue="47" />'
props:
  leftLabel:
    label: Left label
  leftValue:
    label: Left number
  rightLabel:
    label: Right label
  rightValue:
    label: Right number
  unit:
    label: Unit after the numbers (for example %)
</studio>
