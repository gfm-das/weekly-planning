<script setup lang="ts">
/**
 * GfmKpiGrid - several key indicators as a tidy grid of tiles.
 *
 * <GfmKpiGrid metrics="friends_found,baptismal_dates,sacrament_attendance" />
 *
 * `metrics` is a comma list of key indicator names or ids; empty = all six, in the order of the Preach My Gospel
 * indicators. The first tile is outlined (`highlightFirst`).
 */
import { computed } from 'vue'

const ALL = 'friends_found,baptisms_confirmations,baptismal_dates,sacrament_attendance,members_at_lessons,new_member_sacrament'

const props = withDefaults(defineProps<{
  metrics?: string
  weeks?: number
  columns?: number
  highlightFirst?: boolean
}>(), {
  metrics: ALL,
  weeks: 12,
  columns: 0,
  highlightFirst: true,
})

const list = computed(() => String(props.metrics || ALL).split(',').map(s => s.trim()).filter(Boolean).slice(0, 12))
// 0 = automatic: up to 3 across (a number needs room to be read on a call), 2 for four tiles.
const across = computed(() => props.columns > 0 ? props.columns : list.value.length === 4 ? 2 : Math.min(3, list.value.length || 1))
const height = computed(() => (list.value.length > across.value ? 150 : 200))
</script>

<template>
  <div class="gfm-kpi-grid" :style="{ gridTemplateColumns: `repeat(${across}, minmax(0, 1fr))` }">
    <GfmKpi
      v-for="(metric, i) in list"
      :key="metric + i"
      :metric="metric"
      :weeks="weeks"
      :height="height"
      :highlight="highlightFirst && i === 0"
    />
  </div>
</template>

<style>
.gfm-kpi-grid { display: grid; gap: 14px; width: 100%; }
</style>

<studio>
description: Key indicators of the mission as a grid of tiles, live from the weekly plans. Choose which ones, how many weeks the small lines show, and whether the first is outlined.
category: GFM data
snippet: '<GfmKpiGrid metrics="friends_found,baptismal_dates,sacrament_attendance" />'
preview: '<GfmKpiGrid metrics="friends_found,baptismal_dates" :weeks="8" />'
props:
  metrics:
    label: Key indicators, separated by commas (empty = all six)
  weeks:
    label: Weeks in each small line (1-104)
  columns:
    label: Tiles across (0 = automatic)
  highlightFirst:
    label: Outline the first tile
</studio>
