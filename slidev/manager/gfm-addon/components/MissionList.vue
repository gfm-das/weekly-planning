<script setup lang="ts">
/**
 * MissionList — a list (a table of rows) from the slide itself or from live mission numbers.
 *
 * <MissionList :rows="['Name, Zone, Date', 'Elder Sample, Mainz, 3 May']" group-by="Zone" reveal />
 * <MissionList :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit","weeks":{"last":4},"includeCurrent":false}'
 *   sort="New people being taught:desc" :limit="10" :sample="['Zone, New people being taught', 'Frankfurt, 31']" />
 *
 * `rows` (or `csv`): typed rows, the first one the headings. `query`: live mission numbers through the same safe path
 * as a live chart (a row per unit or week, a column per number; leaders see it only when it is written in the deck
 * like this, and only their own stewardship). `sample`: shown, with a note, when the live numbers cannot load.
 * `columns` picks and orders columns, `sort` is "Column" or "Column:desc", `limit` keeps the first rows, `group-by`
 * groups by a column. Long lists: `page-size` rows per page, turned with clicks (`paging="click"`, the default) or
 * every `auto-seconds` (`paging="auto"`). `reveal` brings the rows in one click at a time. See lib/list-core.mjs.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useNav, useSlideContext } from '@slidev/client'
import { answerTable, ChartDataError, fetchChartData, peekChartData } from '../lib/charts'
import type { ChartAnswer } from '../lib/charts'
import { canonicalJson, deckOfPath, normalizeSpec } from '../lib/chart-spec.mjs'
import { cellText, isNumberish, listClicks, listFromRows, listFromTable, listView, pageOf } from '../lib/list-core.mjs'
import { pageLanguage, word } from '../lib/deck-words.mjs'

const props = withDefaults(defineProps<{
  title?: string
  rows?: string[] | string
  csv?: string
  query?: Record<string, any> | string
  sample?: string[] | string
  columns?: string[] | string
  sort?: string
  limit?: number
  groupBy?: string
  pageSize?: number
  paging?: 'click' | 'auto'
  autoSeconds?: number
  reveal?: boolean
  height?: number
  numbered?: boolean
}>(), { title: '', csv: '', sort: '', limit: 0, groupBy: '', pageSize: 0, paging: 'click', autoSeconds: 6, reveal: false, height: 0, numbered: false })

const lang = pageLanguage()
const t = (key: string, vars: Record<string, any> = {}) => word(lang, key, vars)
const { isPrintMode } = useNav()

// ---- the rows ----
const hasQuery = computed(() => props.query !== undefined && props.query !== null && props.query !== '')
const spec = computed(() => {
  if (!hasQuery.value) return { value: null as any, key: '', problem: '' }
  try {
    const value = normalizeSpec(props.query)
    return { value, key: canonicalJson(value), problem: '' }
  }
  catch (error: any) { return { value: null, key: '', problem: `The list's query has a mistake: ${error?.message || error}` } }
})
const deck = typeof location === 'undefined' ? '' : deckOfPath(location.pathname)
const answer = ref<ChartAnswer | null>(spec.value.key ? peekChartData(deck, spec.value.key) : null)
const state = ref<'loading' | 'ready' | 'error'>(answer.value ? 'ready' : 'loading')
const loadError = ref('')
let request = 0
async function load() {
  const { value, key } = spec.value
  if (!value) return
  const mine = ++request
  try {
    const got = await fetchChartData(deck, value, key)
    if (mine !== request) return
    answer.value = got
    state.value = 'ready'
  }
  catch (error) {
    if (mine !== request) return
    loadError.value = error instanceof ChartDataError ? error.message : t('sample')
    answer.value = null
    state.value = 'error'
  }
}
onMounted(() => { if (hasQuery.value) load() })
watch(() => spec.value.key, (now) => { if (now) load() })

const hasSample = computed(() => (Array.isArray(props.sample) ? props.sample.length > 0 : !!String(props.sample ?? '').trim()))
const usingSample = computed(() => hasQuery.value && (state.value === 'error' || !!spec.value.problem) && hasSample.value)
const list = computed(() => {
  if (usingSample.value) return listFromRows(props.sample)
  if (hasQuery.value) return answer.value ? listFromTable(answerTable(answer.value)) : { columns: [], rows: [], problem: '' }
  return listFromRows(props.rows ?? props.csv)
})
const problem = computed(() => {
  if (usingSample.value) return ''
  if (spec.value.problem) return spec.value.problem
  if (hasQuery.value && state.value === 'error') return loadError.value
  return list.value.problem
})
const loading = computed(() => hasQuery.value && state.value === 'loading' && !usingSample.value)
const view = computed(() => listView(list.value, { columns: props.columns, sort: props.sort, limit: props.limit, groupBy: props.groupBy, pageSize: isPrintMode.value ? 0 : props.pageSize }))

// ---- clicks: one per row (reveal) or one per further page (paging="click"), counted like Slidev's own ----
const clicks: any = (() => { try { return (useSlideContext() as any)?.$clicksContext ?? null } catch { return null } })()
const clickId = `gfm-list-${Math.random().toString(36).slice(2)}`
const start = ref(0)
const wanted = computed(() => (isPrintMode.value ? 0 : listClicks(view.value, { reveal: props.reveal, paging: props.paging })))
let registered = -1
function register() {
  if (!clicks) return
  const n = wanted.value
  if (n === registered) return
  if (registered < 0) start.value = clicks.currentOffset
  try { clicks.unregister?.(clickId) } catch {}
  if (n > 0) clicks.register(clickId, { max: start.value + n, delta: n })
  registered = n
}
onMounted(register)
watch(wanted, register)
onUnmounted(() => { try { clicks?.unregister?.(clickId) } catch {} })
const done = computed(() => (clicks ? Math.max(0, Math.round(Number(clicks.current) - start.value)) : Number.POSITIVE_INFINITY))

// ---- pages ----
const autoPage = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
function startTimer() {
  if (timer) clearInterval(timer)
  timer = null
  if (props.paging !== 'auto' || props.reveal || view.value.pages < 2 || isPrintMode.value) return
  const ms = Math.max(2, Math.min(60, Number(props.autoSeconds) || 6)) * 1000
  timer = setInterval(() => { autoPage.value = (autoPage.value + 1) % view.value.pages }, ms)
}
onMounted(startTimer)
watch(() => [view.value.pages, props.paging, props.autoSeconds], startTimer)
onUnmounted(() => { if (timer) clearInterval(timer) })
const page = computed(() => {
  if (view.value.pages < 2) return 0
  if (props.paging === 'auto') return autoPage.value % view.value.pages
  if (props.reveal) return 0
  return Math.min(view.value.pages - 1, done.value)
})
const groups = computed(() => (props.reveal ? view.value.groups : pageOf(view.value, page.value)))
const shownRow = (n: number) => !props.reveal || isPrintMode.value || n < done.value
const numeric = (v: unknown) => isNumberish(v)
const box = computed(() => (props.height ? { maxHeight: `${Math.max(80, Math.min(2000, Number(props.height)))}px`, overflow: 'hidden' } : {}))
const hiddenCount = computed(() => Math.max(0, view.value.total - view.value.shown))
</script>

<template>
  <div class="gfm-list" :style="box" role="table" :aria-label="title || undefined">
    <div v-if="title" class="gfm-list__title">{{ title }}</div>
    <div v-if="loading" class="gfm-list__message">{{ t('loading') }}</div>
    <div v-else-if="problem" class="gfm-list__message">{{ problem }}</div>
    <div v-else-if="!view.shown" class="gfm-list__message">{{ t('empty') }}</div>
    <table v-else>
      <thead>
        <tr role="row">
          <th v-if="numbered" class="gfm-list__n" />
          <th v-for="(c, i) in view.columns" :key="i" role="columnheader">{{ c }}</th>
        </tr>
      </thead>
      <tbody v-for="g in groups" :key="g.name">
        <tr v-if="view.grouped" class="gfm-list__group" :class="{ 'gfm-list__row--hidden': !g.rows.some(r => shownRow(r.n)) }"><td :colspan="view.columns.length + (numbered ? 1 : 0)">{{ g.name }}</td></tr>
        <tr v-for="r in g.rows" :key="r.n" role="row" class="gfm-list__row" :class="{ 'gfm-list__row--hidden': !shownRow(r.n) }">
          <td v-if="numbered" class="gfm-list__n">{{ r.n + 1 }}</td>
          <td v-for="(c, i) in r.cells" :key="i" role="cell" :class="{ 'gfm-list__num': numeric(c) }">{{ cellText(c, lang) }}</td>
        </tr>
      </tbody>
    </table>
    <div class="gfm-list__foot">
      <span v-if="usingSample" class="gfm-list__sample">{{ t('sample') }}</span>
      <span v-if="view.pages > 1 && !reveal">{{ t('page', { n: page + 1, m: view.pages }) }}</span>
      <span v-if="hiddenCount">{{ t('more', { n: hiddenCount }) }}</span>
    </div>
  </div>
</template>

<style scoped>
.gfm-list { width: 100%; font-size: 15px; line-height: 1.35; }
.gfm-list__title { font-weight: 600; font-size: 17px; margin-bottom: 6px; }
.gfm-list table { width: 100%; border-collapse: collapse; }
.gfm-list th { text-align: start; font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: .03em; opacity: .7; padding: 4px 8px; border-bottom: 2px solid color-mix(in srgb, currentColor 25%, transparent); }
.gfm-list td { padding: 5px 8px; border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
.gfm-list__num { text-align: end; font-variant-numeric: tabular-nums; }
.gfm-list__n { width: 2.2em; opacity: .55; text-align: end; }
.gfm-list__group td { font-weight: 700; padding-top: 10px; border-bottom: none; color: var(--gfm-accent, #1f6feb); }
.gfm-list__row { transition: opacity .35s ease, transform .35s ease; }
.gfm-list__row--hidden { opacity: 0; transform: translateY(6px); }
.gfm-list__row--hidden td { border-color: transparent; }
.gfm-list__message { padding: 18px; text-align: center; opacity: .75; border: 1px dashed currentColor; border-radius: 10px; }
.gfm-list__foot { display: flex; gap: 14px; justify-content: flex-end; font-size: 12px; opacity: .7; margin-top: 4px; }
.gfm-list__sample { margin-inline-end: auto; }
</style>

<studio>
description: A list (a table of rows) typed into the slide or from live mission numbers, with sort, limit, groups, pages and rows that appear one click at a time.
category: Charts
snippet: >-
  <MissionList :rows="['Name, Zone', 'Elder Sample, Mainz', 'Sister Example, Wiesbaden']" sort="Name" />
preview: '<MissionList :rows="[''Name, Zone'', ''Elder Sample, Mainz'', ''Sister Example, Wiesbaden'']" />'
props:
  title:
    label: Title
  rows:
    label: Rows, one per box (first row = headings)
  csv:
    hidden: true
  query:
    hidden: true
  sample:
    label: Sample rows shown when the live numbers cannot load
  columns:
    label: Columns to show (their headings, in order)
  sort:
    label: Sort by (a heading, add :desc for largest first)
  limit:
    label: Show at most this many rows (0 = all)
  groupBy:
    label: Group by (a heading)
  pageSize:
    label: Rows per page (0 = one page)
  paging:
    label: Turn pages with clicks or automatically
  autoSeconds:
    label: Seconds per page (automatic pages)
  reveal:
    label: One row per click
  height:
    label: Highest it may grow (slide pixels, 0 = no limit)
  numbered:
    label: Number the rows
</studio>
