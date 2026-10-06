<script setup lang="ts">
/**
 * GfmInsight - what the numbers mean, in one or two sentences, set apart from the rest of the slide.
 *
 * <GfmInsight>Most zones taught more people than last week.</GfmInsight>
 */
withDefaults(defineProps<{
  label?: string
}>(), {
  label: 'What this shows',
})
</script>

<template>
  <div class="gfm-insight">
    <div class="gfm-insight__label">{{ label }}</div>
    <div class="gfm-insight__body"><slot /></div>
  </div>
</template>

<style>
.gfm-insight { box-sizing: border-box; border-left: 5px solid var(--gfm-teal); padding: 4px 0 4px 22px; margin: 8px 0; }
.gfm-insight__label { font-size: 15px; font-weight: 650; letter-spacing: 0.1em; text-transform: uppercase; color: var(--gfm-teal); margin-bottom: 6px; }
.gfm-insight__body { font-size: 26px; line-height: 1.35; font-weight: 550; color: var(--gfm-navy); }
.gfm-insight__body > :last-child { margin-bottom: 0; }
</style>

<studio>
description: What the numbers mean, in one or two sentences, set apart with a teal bar.
category: GFM content
snippet: |-
  <GfmInsight>
  Most zones taught more people than last week.
  </GfmInsight>
preview: '<GfmInsight>Most zones taught more people than last week.</GfmInsight>'
props:
  label:
    label: Small heading
</studio>
