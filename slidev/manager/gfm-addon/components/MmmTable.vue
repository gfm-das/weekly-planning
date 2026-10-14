<script setup lang="ts">
/**
 * MmmTable - the table of the Monday Morning Meeting, zone conference and Stake decks: one row per zone (or per area /
 * companionship in a zone's deck), one column for each number of the query and, with `ratio`, a last column with the
 * share of the second number in the first. Largest first, cut to `top` rows. Live from the weekly plans (counts only,
 * never names; the portal hides counts below 3 per area):
 *
 * <MmmTable x="38" y="325" w="520" h="250" :headers="['Zone','Total','At Church','At Church %']" ratio
 *   :query='{"measures":["new_members.total","new_members.at_church"],"level":"zone","by":"unit","weeks":1}' />
 *
 * `headers` are the heading of the name column, then of each number, then of the share. In a zone's deck the portal
 * gives only that zone's numbers, so a table "by area" lists the zone's own areas.
 */
import { computed } from 'vue'
import { listOf, numberText, percentText, readAnswer, unitRows, useMmmQuery } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  h?: number
  query?: Record<string, any> | string
  headers?: string[] | string
  top?: number
  ratio?: boolean
  dense?: boolean
}>(), { x: 38, y: 325, w: 520, h: 250, top: 6, ratio: true, dense: false })

const { answer, message } = useMmmQuery(() => props.query)
const locale = typeof document === 'undefined' ? undefined : document.documentElement.lang || undefined
const heads = computed(() => listOf(props.headers))
const count = computed(() => (answer.value ? Math.min(8, readAnswer(answer.value).actuals.length) : Math.max(0, heads.value.length - 1 - (props.ratio ? 1 : 0))))
const rows = computed(() => (answer.value ? unitRows(answer.value, { columns: Array.from({ length: count.value }, (_, i) => i), ratioOf: [0, 1], top: props.top }) : []))
const showRatio = computed(() => props.ratio && count.value >= 2)
const columns = computed(() => `2.3fr repeat(${Math.max(1, count.value)}, 1fr)${showRatio.value ? ' 1fr' : ''}`)
const place = computed(() => ({
  left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))`, height: `calc(${props.h} * var(--u))`,
  '--mmm-cols': columns.value,
}))
const text = computed(() => message.value || (answer.value && !rows.value.length ? 'No numbers yet.' : ''))
</script>

<template>
  <div class="mmm-box mmm-table mmm-panel" :class="{ 'is-dense': dense }" :style="place" role="table">
    <div class="mmm-table__head" role="row">
      <span v-for="(head, i) in heads.slice(0, 1 + count + (showRatio ? 1 : 0))" :key="i" role="columnheader">{{ head }} <i v-if="i === 1">▼</i></span>
    </div>
    <div v-for="(row, i) in rows" :key="row.name" class="mmm-table__row" :class="{ 'is-odd': i % 2 === 0 }" role="row">
      <span role="cell" class="mmm-table__name">{{ row.name }}</span>
      <span v-for="(cell, c) in row.cells" :key="c" role="cell">{{ numberText(cell, locale) }}</span>
      <span v-if="showRatio" role="cell">{{ row.ratio === null ? '–' : percentText(row.ratio, 0) }}</span>
    </div>
    <div v-if="text" class="mmm-message">{{ text }}</div>
  </div>
</template>

<style>
.mmm-table { overflow: hidden; padding: calc(6 * var(--u)) calc(8 * var(--u)); }
.mmm-table__head, .mmm-table__row { display: grid; grid-template-columns: var(--mmm-cols); align-items: center; text-align: center; }
.mmm-table__head { background: #e8f0fb; font-weight: 700; font-size: calc(17 * var(--u)); height: calc(32 * var(--u)); border-radius: calc(3 * var(--u)); white-space: nowrap; }
.mmm-dark .mmm-table__head { background: #3e4650; }
.mmm-table__head i { font-style: normal; font-size: calc(10 * var(--u)); }
.mmm-table__row { height: calc(34 * var(--u)); font-size: calc(22 * var(--u)); font-weight: 300; }
.mmm-table__row.is-odd { background: #f3f4f6; }
.mmm-dark .mmm-table__row.is-odd { background: #3a3a3a; }
.mmm-table__name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 calc(4 * var(--u)); }
.mmm-table.is-dense .mmm-table__head { font-size: calc(12 * var(--u)); height: calc(36 * var(--u)); white-space: normal; line-height: 1.05; }
.mmm-table.is-dense .mmm-table__row { height: calc(21 * var(--u)); font-size: calc(14 * var(--u)); }
</style>

<studio>
description: "A live table by zone (or by area in a zone's deck): one column for each number and, optionally, the share of the second number in the first, largest first."
category: GFM data
snippet: '<MmmTable x="38" y="325" w="520" h="250" :headers="[''Zone'',''Total'',''At Church'',''At Church %'']" ratio :query=''{"measures":["new_members.total","new_members.at_church"],"level":"zone","by":"unit","weeks":1}'' />'
props:
  top:
    label: How many rows
  ratio:
    label: Show the percent column
  dense:
    label: Small rows (long lists)
</studio>
