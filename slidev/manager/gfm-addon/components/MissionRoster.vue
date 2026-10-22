<script setup lang="ts">
/**
 * Round 27: roster counts only, never names. view="units": church units with missionaries, missionaries,
 * missionaries per unit and companionships. view="gender": elders and sisters. Current week, or the reporting
 * Sunday on or before asOf="YYYY-MM-DD". Data: POST /api/charts/data (dashboards.roster_area_week, aggregate only).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { fetchChartData } from '../lib/charts'
import { canonicalJson, deckOfPath, rosterSpec } from '../lib/chart-spec.mjs'

const props = withDefaults(defineProps<{ view?: 'units' | 'gender', asOf?: string, title?: string }>(), { view: 'units', asOf: '', title: '' })

const spec = computed(() => rosterSpec({ view: props.view, asOf: props.asOf }))
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

const fmt = (v: number | null | undefined, digits = 0) => v == null ? '–' : v.toLocaleString(undefined, { maximumFractionDigits: digits })
const tiles = computed(() => {
  const v = values.value ?? {}
  if (props.view === 'gender') {
    return [
      { label: 'Elders', value: fmt(v['roster.elders']) },
      { label: 'Sisters', value: fmt(v['roster.sisters']) },
      { label: 'Missionaries', value: fmt(v['roster.missionaries']) },
    ]
  }
  const units = v['roster.units'], people = v['roster.missionaries']
  return [
    { label: 'Units', value: fmt(units) },
    { label: 'Missionaries', value: fmt(people) },
    { label: 'Missionaries per unit', value: units ? fmt((people ?? 0) / units, 1) : '–' },
    { label: 'Companionships', value: fmt(v['roster.companionships']) },
  ]
})
</script>

<template>
  <div class="gfm-roster">
    <div v-if="title" class="gfm-roster-title">{{ title }}</div>
    <div v-if="failed" class="gfm-roster-note">–</div>
    <div v-else class="gfm-roster-tiles">
      <div v-for="t in tiles" :key="t.label" class="gfm-roster-tile">
        <div class="gfm-roster-value">{{ values ? t.value : '…' }}</div>
        <div class="gfm-roster-label">{{ t.label }}</div>
      </div>
    </div>
    <div v-if="week" class="gfm-roster-note">{{ week }}</div>
  </div>
</template>

<style scoped>
.gfm-roster-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 1rem; }
.gfm-roster-tile { border: 1px solid #d0d7de; border-radius: .5rem; padding: 1rem; text-align: center; }
.gfm-roster-value { font-size: 2.2rem; font-weight: 600; color: #0f766e; }
.gfm-roster-label { font-size: .9rem; opacity: .8; }
.gfm-roster-title { font-weight: 600; margin-bottom: .5rem; }
.gfm-roster-note { font-size: .75rem; opacity: .6; margin-top: .5rem; }
</style>

<studio>
description: Roster counts of the mission, never names - church units with missionaries, missionaries per unit and companionships, or elders and sisters. This week or as of a date.
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
</studio>
