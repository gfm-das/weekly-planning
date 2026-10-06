<script setup lang="ts">
/**
 * GfmKpi - one of the mission's six key indicators as a tile: the last finished week, the change from the week
 * before, the goal set the week before, and a small line of the weeks. Live from the weekly plans.
 *
 * <GfmKpi metric="New people being taught" />
 *
 * It draws a MissionKpiChart, so a published deck asks for the same key numbers (chart-access.mjs lets a deck that
 * holds a GfmKpi or GfmKpiGrid ask for them).
 */
withDefaults(defineProps<{
  metric?: string // a name ('New people being taught') or an id ('friends_found')
  weeks?: number
  height?: number
  highlight?: boolean
}>(), {
  metric: 'friends_found',
  weeks: 12,
  height: 168,
  highlight: false,
})
</script>

<template>
  <div class="gfm-kpi" :class="{ 'gfm-kpi--highlight': highlight }">
    <MissionKpiChart :kpi="metric" chart="tile" :weeks="weeks" :height="height" />
  </div>
</template>

<style>
.gfm-kpi { position: relative; box-sizing: border-box; border: 1px solid var(--gfm-line); border-radius: 14px; background: var(--gfm-surface); padding: 10px 10px 4px 12px; min-width: 0; }
.gfm-kpi--highlight { border-color: var(--gfm-teal); }
/* A key number's texts and its last dot may reach into the tile's padding instead of being cut off. */
.gfm-kpi .gfm-chart__plot, .gfm-kpi .gfm-chart__plot * { overflow: visible !important; }
</style>

<studio>
description: One key indicator of the mission as a tile - the last finished week against the goal set the week before, with a small line of the weeks. Live from the weekly plans.
category: GFM data
snippet: '<GfmKpi metric="New people being taught" />'
preview: '<GfmKpi metric="New people being taught" :height="120" />'
props:
  metric:
    label: Key indicator
    options:
      - New people being taught
      - Baptisms and confirmations
      - Baptismal dates
      - Sacrament attendance
      - Members at lessons
      - New member sacrament attendance
  weeks:
    label: Weeks in the small line (1-104)
  height:
    label: Height (slide pixels)
  highlight:
    label: Outline in teal (the first, most important number)
</studio>
