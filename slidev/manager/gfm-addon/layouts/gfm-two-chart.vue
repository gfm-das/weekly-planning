<script setup lang="ts">
defineProps<{
  heading?: string
  frontmatter?: Record<string, any>
  kicker?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-two-chart">
    <div class="gfm-head">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <h1 v-if="heading || frontmatter?.title">{{ heading || frontmatter?.title }}</h1>
    </div>
    <div class="gfm-body">
      <div class="gfm-grid gfm-two-chart__grid">
        <div class="gfm-col gfm-chart-slot"><slot /></div>
        <div class="gfm-col gfm-chart-slot"><slot name="right" /></div>
      </div>
    </div>
  </div>
</template>

<style>
.gfm-two-chart__grid { grid-template-columns: 1fr 1fr; align-items: center; }
</style>

<studio>
description: "Two charts side by side (height about 300 each). Put the first chart, then a line with ::right:: and the second."
props:
  heading:
    label: Slide title
  kicker:
    label: Label above the title
</studio>
