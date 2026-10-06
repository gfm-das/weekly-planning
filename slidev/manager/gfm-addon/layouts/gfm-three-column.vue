<script setup lang="ts">
defineProps<{
  heading?: string
  frontmatter?: Record<string, any>
  kicker?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-three-column">
    <div class="gfm-head">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <h1 v-if="heading || frontmatter?.title">{{ heading || frontmatter?.title }}</h1>
    </div>
    <div class="gfm-body">
      <div class="gfm-grid gfm-three-column__grid">
        <div class="gfm-col gfm-card"><slot /></div>
        <div class="gfm-col gfm-card"><slot name="middle" /></div>
        <div class="gfm-col gfm-card"><slot name="right" /></div>
      </div>
    </div>
  </div>
</template>

<style>
.gfm-three-column__grid { grid-template-columns: 1fr 1fr 1fr; align-items: stretch; }
.gfm-three-column__grid .gfm-card { justify-content: flex-start; padding: 22px 24px; }
.gfm-three-column__grid h2 { font-size: 24px; color: var(--gfm-teal); }
.gfm-three-column__grid p, .gfm-three-column__grid li { font-size: 19px; }
</style>

<studio>
description: "Three equal cards, each with a heading and a few lines. Separate the cards with ::middle:: and ::right::."
props:
  heading:
    label: Slide title
  kicker:
    label: Label above the title
</studio>
