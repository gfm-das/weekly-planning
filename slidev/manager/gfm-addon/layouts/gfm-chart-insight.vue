<script setup lang="ts">
defineProps<{
  heading?: string
  frontmatter?: Record<string, any>
  kicker?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-chart-insight">
    <div class="gfm-head">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <h1 v-if="heading || frontmatter?.title">{{ heading || frontmatter?.title }}</h1>
    </div>
    <div class="gfm-body">
      <div class="gfm-grid gfm-chart-insight__grid">
        <div class="gfm-col gfm-chart-slot"><slot /></div>
        <div class="gfm-col gfm-chart-insight__side"><slot name="right" /></div>
      </div>
    </div>
  </div>
</template>

<style>
.gfm-chart-insight__grid { grid-template-columns: 3fr 2fr; align-items: center; }
.gfm-chart-insight__side { border-left: 4px solid var(--gfm-teal); padding-left: 24px; }
.gfm-chart-insight__side p, .gfm-chart-insight__side li { font-size: 22px; }
</style>

<studio>
description: "A chart on the left and what it means on the right. Put the chart first, then a line with ::right:: and the message."
props:
  heading:
    label: Slide title
  kicker:
    label: Label above the title
</studio>
