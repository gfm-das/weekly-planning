<script setup lang="ts">
defineProps<{
  heading?: string
  frontmatter?: Record<string, any>
  kicker?: string
  caption?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-full-chart">
    <div class="gfm-head">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <h1 v-if="heading || frontmatter?.title">{{ heading || frontmatter?.title }}</h1>
    </div>
    <div class="gfm-body gfm-chart-slot">
      <slot />
    </div>
    <div v-if="caption" class="gfm-caption">{{ caption }}</div>
  </div>
</template>

<style>
.gfm-chart-slot { justify-content: flex-start !important; }
.gfm-chart-slot > * { width: 100%; }
.gfm-caption { flex: none; margin-top: 10px; font-size: 16px; color: var(--gfm-muted); }
</style>

<studio>
description: One chart, as large as the slide allows, with a title and an optional source line. Put a chart (height about 360) in the slide.
props:
  heading:
    label: Slide title
  kicker:
    label: Label above the title
  caption:
    label: Line under the chart (for example the source or the weeks shown)
</studio>
