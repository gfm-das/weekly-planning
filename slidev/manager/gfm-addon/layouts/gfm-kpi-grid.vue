<script setup lang="ts">
defineProps<{
  heading?: string
  frontmatter?: Record<string, any>
  kicker?: string
  note?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-kpi-grid-layout">
    <div class="gfm-head">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <h1 v-if="heading || frontmatter?.title">{{ heading || frontmatter?.title }}</h1>
    </div>
    <div class="gfm-body"><slot /></div>
    <div v-if="note" class="gfm-caption">{{ note }}</div>
  </div>
</template>

<studio>
description: A set of key numbers. Put a GfmKpiGrid (the mission's key indicators) or several GfmBigNumber in the slide.
props:
  heading:
    label: Slide title
  kicker:
    label: Label above the title
  note:
    label: Line under the numbers
</studio>
