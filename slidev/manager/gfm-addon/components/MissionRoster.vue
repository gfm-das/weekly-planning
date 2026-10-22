<script setup lang="ts">
/**
 * Roster counts only, never names of people. Round 28:
 *   view="units":  the number of church units with missionaries, missionaries and companionships, and a bar chart
 *                  of missionaries per unit (unit names; spec level "unit", rosterUnitSpec).
 *   view="gender": elders and sisters, as numbers and one bar split by share.
 * Current week, or the reporting Sunday on or before asOf="YYYY-MM-DD". Data: POST /api/charts/data
 * (dashboards.roster_area_week, migrations 059/060, aggregate only). Both queries are read from the slides' plain
 * attributes (componentSpecs), so a published deck may ask for them.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { fetchChartData } from '../lib/charts'
import { canonicalJson, deckOfPath, rosterSpec, rosterUnitSpec } from '../lib/chart-spec.mjs'

const props = withDefaults(defineProps<{ view?: 'units' | 'gender', asOf?: string, title?: string, height?: number }>(),
  { view: 'units', asOf: '', title: '', height: 240 })

const gender = computed(() => props.view === 'gender')
const spec = computed(() => rosterSpec({ view: props.view, asOf: props.asOf }))
const unitSpec = computed(() => gender.value ? null : rosterUnitSpec({ asOf: props.asOf }))
const values = ref<Record<string, number | null> | null>(null)
const week = ref('')
const failed = ref(false)

async function load() {
  failed.value = false
  if (!spec.value) { failed.value = true; return }
  try {
    const deck = typeof location === 'undefined' ? '' : deckOfPath(location.pathname)
    const answer = await fetchChartData(deck, spec.value, canonicalJson(spec.value))
    const out: Record<string, number | null> = {}
    spec.value.measures.forEach((m: string, i: number) => {
      const v = answer.table.series[i]?.values ?? []
      out[m] = v.length ? v[v.length - 1] : null
    })
    const weeks = answer.meta?.weeks ?? answer.table.labels
    week.value = weeks[weeks.length - 1] ?? ''
    values.value = out
  }
  catch { failed.value = true }
}
onMounted(load)
watch(() => spec.value && canonicalJson(spec.value), load)

const fmt = (v: number | null | undefined) => v == null ? '–' : v.toLocaleString(undefined, { maximumFractionDigits: 0 })
const tiles = computed(() => {
  const v = values.value ?? {}
  if (gender.value) {
    return [
      { label: 'Elders', value: fmt(v['roster.elders']) },
      { label: 'Sisters', value: fmt(v['roster.sisters']) },
    ]
  }
  return [
    { label: 'Units', value: fmt(v['roster.units']) },
    { label: 'Missionaries', value: fmt(v['roster.missionaries']) },
    { label: 'Companionships', value: fmt(v['roster.companionships']) },
  ]
})
// Elders and sisters as shares of one bar.
const split = computed(() => {
  const v = values.value ?? {}
  const e = Number(v['roster.elders'] ?? 0), s = Number(v['roster.sisters'] ?? 0)
  const all = e + s
  return all ? { elders: Math.round(e / all * 100), sisters: 100 - Math.round(e / all * 100) } : null
})
</script>

<template>
  <div class="gfm-roster">
    <div v-if="title" class="gfm-roster-title">{{ title }}</div>
    <div v-if="failed" class="gfm-roster-note">–</div>
    <template v-else>
      <div class="gfm-roster-tiles">
        <div v-for="t in tiles" :key="t.label" class="gfm-roster-tile">
          <div class="gfm-roster-value">{{ values ? t.value : '…' }}</div>
          <div class="gfm-roster-label">{{ t.label }}</div>
        </div>
      </div>
      <MissionChart v-if="unitSpec" class="gfm-roster-chart" :query="unitSpec" type="bar" title="Missionaries per unit"
        :height="height" :show-values="true" legend="none" />
      <div v-if="gender && split" class="gfm-roster-split" role="img" :aria-label="`Elders ${split.elders}%, Sisters ${split.sisters}%`">
        <div class="gfm-roster-split-e" :style="{ width: split.elders + '%' }">{{ split.elders }}%</div>
        <div class="gfm-roster-split-s" :style="{ width: split.sisters + '%' }">{{ split.sisters }}%</div>
      </div>
    </template>
    <div v-if="week" class="gfm-roster-note">{{ week }}</div>
  </div>
</template>

<style scoped>
.gfm-roster { width: 100%; min-width: 0; }
.gfm-roster-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: .75rem; }
.gfm-roster-tile { border: 1px solid #d0d7de; border-radius: .5rem; padding: .6rem; text-align: center; }
.gfm-roster-value { font-size: 2rem; font-weight: 600; color: #0f766e; line-height: 1.2; }
.gfm-roster-label { font-size: .85rem; opacity: .8; }
.gfm-roster-title { font-weight: 600; margin-bottom: .5rem; }
.gfm-roster-chart { margin-top: .75rem; }
.gfm-roster-split { display: flex; height: 2.2rem; margin-top: 1rem; border-radius: .5rem; overflow: hidden; font-weight: 600; color: #fff; }
.gfm-roster-split > div { display: flex; align-items: center; justify-content: center; min-width: 2.5rem; }
.gfm-roster-split-e { background: #0f766e; }
.gfm-roster-split-s { background: #b45309; }
.gfm-roster-note { font-size: .75rem; opacity: .6; margin-top: .5rem; }
</style>

<studio>
description: Roster counts of the mission, never names of people - the number of church units with missionaries and a bar chart of missionaries per unit, or elders and sisters. This week or as of a date.
category: GFM data
snippet: '<MissionRoster view="units" />'
preview: '<MissionRoster view="gender" />'
props:
  view:
    label: Counts
    options:
      - units
      - gender
  asOf:
    label: As of date (YYYY-MM-DD, empty = this week)
  title:
    label: Title
  height:
    label: Height of the chart (px)
</studio>
