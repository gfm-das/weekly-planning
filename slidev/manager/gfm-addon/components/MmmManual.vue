<script setup lang="ts">
/**
 * MmmManual - a table typed by hand, in the look of the "Coming This Week" and "On Date" pages: one white framed
 * column for each heading. The portal shows people's names only to the leaders who plan them and never in a chart, so
 * the names of the friends with a baptismal date, the temple visits and the baptisms of last week are typed here
 * (or pasted from the Call-ins list) before the meeting. While `placeholder` is on the table carries a "Manual" tag
 * on screen; delete the attribute once the real rows are in.
 *
 * <MmmManual headers="Friend|Baptismal Date|Companionship|Unit" rows="Name 1|Oct 15, 2026|Companionship A|Unit A;Name 2|Oct 17, 2026|Companionship B|Unit B" placeholder />
 *
 * `rows`: one row per `;`, cells split by `|` (or an array of arrays). `sorted` puts the small arrow under that heading.
 */
import { computed } from 'vue'
import { listOf, manualRows } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  h?: number
  headers?: string[] | string
  rows?: string[][] | string
  sorted?: number
  goal?: string
  goalLabel?: string
  tag?: string
  placeholder?: boolean
}>(), { x: 28, y: 90, w: 1096, h: 485, sorted: 1, goal: '', goalLabel: 'Goal', tag: 'Manual', placeholder: false })

const heads = computed(() => listOf(props.headers))
const body = computed(() => manualRows(props.rows))
const widths = computed(() => (heads.value.length === 4 ? '260fr 268fr 268fr 260fr' : `repeat(${Math.max(1, heads.value.length)}, 1fr)`))
const place = computed(() => ({
  left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))`, height: `calc(${props.h} * var(--u))`,
  gridTemplateColumns: widths.value,
}))
</script>

<template>
  <div class="mmm-box mmm-manual" :style="place" role="table">
    <div v-for="(head, c) in heads" :key="c" class="mmm-manual__col mmm-panel" role="rowgroup">
      <div class="mmm-manual__head" role="columnheader">{{ head }} <i v-if="c === sorted">▲</i></div>
      <div v-for="(row, r) in body" :key="r" class="mmm-manual__cell" role="cell">{{ row[c] }}</div>
    </div>
    <span v-if="placeholder" class="mmm-manual-tag" :style="{ right: goal ? 'calc(90 * var(--u))' : 'calc(40 * var(--u))', top: 'calc(-16 * var(--u))' }">{{ tag }}</span>
    <div v-if="goal" class="mmm-badge mmm-badge--goal mmm-badge--top mmm-manual__goal" style="--t: var(--mmm-red-tint)"><b>{{ goalLabel }}</b><span>{{ goal }}</span></div>
  </div>
</template>

<style>
.mmm-manual { display: grid; gap: calc(10 * var(--u)); }
.mmm-manual__col { min-width: 0; overflow: hidden; text-align: center; }
.mmm-manual__head { font-weight: 700; font-size: calc(17 * var(--u)); min-height: calc(26 * var(--u)); padding: calc(4 * var(--u)) calc(4 * var(--u)) 0; line-height: 1.15; }
.mmm-manual__head i { font-style: normal; font-size: calc(8 * var(--u)); vertical-align: middle; }
.mmm-manual__cell { font-size: calc(26 * var(--u)); font-weight: 300; height: calc(40.5 * var(--u)); padding: calc(4 * var(--u)) calc(4 * var(--u)) 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mmm-manual__goal { right: calc(-6 * var(--u)); top: calc(-24 * var(--u)); }
</style>

<studio>
description: "A table typed by hand - white framed columns for the friends with a baptismal date, temple visits or baptisms. Marked Manual until the real names are in."
category: GFM data
snippet: '<MmmManual headers="Friend|Baptismal Date|Companionship|Unit" rows="Name 1|Oct 15, 2026|Companionship A|Unit A" placeholder />'
props:
  headers:
    label: Headings (separated by |)
  rows:
    label: Rows (cells by |, rows by ;)
  placeholder:
    label: Mark as typed by hand (Manual tag)
</studio>
