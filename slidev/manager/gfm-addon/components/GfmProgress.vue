<script setup lang="ts">
/**
 * GfmProgress - how far along a goal is: a bar, the numbers and the percentage.
 *
 * <GfmProgress label="Baptismal dates" :value="31" :goal="40" />
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  label?: string
  value?: number
  goal?: number
  unit?: string
}>(), {
  label: '',
  value: 0,
  goal: 100,
  unit: '',
})

const percent = computed(() => (props.goal > 0 ? Math.round((props.value / props.goal) * 100) : 0))
const width = computed(() => `${Math.max(0, Math.min(100, percent.value))}%`)
const tone = computed(() => (percent.value >= 100 ? 'good' : percent.value >= 70 ? 'neutral' : 'warn'))
</script>

<template>
  <div class="gfm-progress">
    <div class="gfm-progress__top">
      <span class="gfm-progress__label">{{ label }}</span>
      <span class="gfm-progress__numbers">{{ value }}{{ unit }} of {{ goal }}{{ unit }} · <b :class="`gfm-tone-${tone}`">{{ percent }}%</b></span>
    </div>
    <div class="gfm-progress__track"><div class="gfm-progress__fill" :style="{ width }" /></div>
  </div>
</template>

<style>
.gfm-progress { margin: 10px 0; }
.gfm-progress__top { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; margin-bottom: 8px; }
.gfm-progress__label { font-size: 22px; font-weight: 650; color: var(--gfm-navy); }
.gfm-progress__numbers { font-size: 19px; color: var(--gfm-muted); white-space: nowrap; }
.gfm-progress__track { height: 18px; border-radius: 9px; background: var(--gfm-teal-soft); overflow: hidden; }
.gfm-progress__fill { height: 100%; border-radius: 9px; background: var(--gfm-teal); transition: width 0.7s ease; }
</style>

<studio>
description: "How far along a goal is: a bar with the numbers and the percentage."
category: GFM content
snippet: '<GfmProgress label="Baptismal dates" :value="31" :goal="40" />'
preview: '<GfmProgress label="Baptismal dates" :value="31" :goal="40" />'
props:
  label:
    label: What is measured
  value:
    label: Reached so far
  goal:
    label: Goal
  unit:
    label: Unit after the numbers (for example %)
</studio>
