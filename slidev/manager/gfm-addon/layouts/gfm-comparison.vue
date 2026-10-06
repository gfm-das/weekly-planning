<script setup lang="ts">
defineProps<{
  heading?: string
  frontmatter?: Record<string, any>
  kicker?: string
  leftTitle?: string
  rightTitle?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-comparison-layout">
    <div class="gfm-head">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <h1 v-if="heading || frontmatter?.title">{{ heading || frontmatter?.title }}</h1>
    </div>
    <div class="gfm-body">
      <div class="gfm-grid gfm-comparison-layout__grid">
        <div class="gfm-col">
          <div v-if="leftTitle" class="gfm-comparison-layout__title">{{ leftTitle }}</div>
          <slot />
        </div>
        <div class="gfm-comparison-layout__vs">vs</div>
        <div class="gfm-col">
          <div v-if="rightTitle" class="gfm-comparison-layout__title gfm-comparison-layout__title--right">{{ rightTitle }}</div>
          <slot name="right" />
        </div>
      </div>
    </div>
  </div>
</template>

<style>
.gfm-comparison-layout__grid { grid-template-columns: 1fr auto 1fr; align-items: center; }
.gfm-comparison-layout__title { font-size: 15px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--gfm-muted); margin-bottom: 10px; }
.gfm-comparison-layout__title--right { color: var(--gfm-teal); }
.gfm-comparison-layout__vs { align-self: center; width: 52px; height: 52px; line-height: 52px; text-align: center; border-radius: 50%; border: 2px solid var(--gfm-line); color: var(--gfm-muted); font-weight: 650; }
</style>

<studio>
description: "Two things side by side, such as this week and last week, or two zones. Put the first, then a line with ::right:: and the second."
props:
  heading:
    label: Slide title
  kicker:
    label: Label above the title
  leftTitle:
    label: Heading of the left side
  rightTitle:
    label: Heading of the right side
</studio>
