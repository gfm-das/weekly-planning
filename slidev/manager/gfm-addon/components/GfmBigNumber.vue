<script setup lang="ts">
/**
 * GfmBigNumber - one number, large, with its label, the change and a short note.
 *
 * <GfmBigNumber value="47" label="New people being taught" change="+6 from last week" tone="good" />
 */
withDefaults(defineProps<{
  value?: string
  label?: string
  change?: string
  tone?: 'good' | 'warn' | 'bad' | 'neutral'
  note?: string
}>(), {
  value: '0',
  label: '',
  change: '',
  tone: 'neutral',
  note: '',
})
</script>

<template>
  <div class="gfm-bignumber gfm-card">
    <div v-if="label" class="gfm-label">{{ label }}</div>
    <div class="gfm-bignumber__value">{{ value }}</div>
    <div v-if="change" class="gfm-bignumber__change" :class="`gfm-tone-${tone}`">{{ change }}</div>
    <div v-if="note" class="gfm-bignumber__note">{{ note }}</div>
  </div>
</template>

<style>
.gfm-bignumber { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.gfm-bignumber__value { font-size: 68px; line-height: 1; font-weight: 750; letter-spacing: -0.02em; color: var(--gfm-navy); }
.gfm-bignumber__change { font-size: 20px; font-weight: 650; }
.gfm-bignumber__note { font-size: 16px; color: var(--gfm-muted); }
</style>

<studio>
description: One number shown large, with its label, the change from before and a short note.
category: GFM content
snippet: '<GfmBigNumber value="47" label="New people being taught" change="+6 from last week" tone="good" />'
preview: '<GfmBigNumber value="47" label="New people being taught" change="+6 from last week" tone="good" />'
props:
  value:
    label: The number
  label:
    label: What it counts
  change:
    label: Change (for example +6 from last week)
  tone:
    label: Colour of the change
    options:
      - good
      - warn
      - bad
      - neutral
  note:
    label: Note under the number
</studio>
