<script setup lang="ts">
/**
 * MmmChips - a short list of names in light-blue rounded labels, as on the "1st Time Temple Attendance" and
 * "Baptisms Last Week" page. The names are typed by hand (the portal shows no names in a chart); while `placeholder`
 * is on the list carries a "Manual" tag on screen.
 *
 * <MmmChips x="760" y="360" w="240" items="Name 1|Name 2" placeholder />
 */
import { computed } from 'vue'
import { listOf } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  items?: string[] | string
  align?: 'start' | 'center'
  tag?: string
  placeholder?: boolean
}>(), { x: 40, y: 120, w: 240, align: 'center', tag: 'Manual', placeholder: false })

const names = computed(() => listOf(props.items).filter(Boolean))
const place = computed(() => ({ left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))` }))
</script>

<template>
  <div class="mmm-box mmm-chips" :style="place">
    <span v-if="placeholder" class="mmm-manual-tag" style="right: 0; top: calc(-22 * var(--u))">{{ tag }}</span>
    <div v-for="(name, i) in names" :key="i" class="mmm-chip" :class="{ 'is-start': align === 'start' }">{{ name }}</div>
  </div>
</template>

<style>
.mmm-chip { background: var(--mmm-cyan-tint); border: calc(2 * var(--u)) solid #000; border-radius: calc(7 * var(--u)); padding: calc(5 * var(--u)) calc(10 * var(--u)); margin-bottom: calc(10 * var(--u)); text-align: center; font-weight: 700; font-size: calc(15 * var(--u)); color: #2d505e; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mmm-chip.is-start { text-align: start; }
</style>

<studio>
description: "A short list of names in light-blue rounded labels (temple visits, baptisms of last week). Typed by hand and marked Manual."
category: GFM content
snippet: '<MmmChips x="760" y="360" w="240" items="Name 1|Name 2" placeholder />'
props:
  items:
    label: Names (separated by |)
  placeholder:
    label: Mark as typed by hand (Manual tag)
</studio>
