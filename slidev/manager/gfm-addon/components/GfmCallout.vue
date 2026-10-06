<script setup lang="ts">
/**
 * GfmCallout - a box that points something out: an invitation, a reminder, a warning.
 *
 * <GfmCallout title="Invitation" tone="info">Invite one friend this week.</GfmCallout>
 */
withDefaults(defineProps<{
  title?: string
  tone?: 'info' | 'good' | 'warn' | 'bad'
}>(), {
  title: '',
  tone: 'info',
})
</script>

<template>
  <div class="gfm-callout" :class="`gfm-callout--${tone}`">
    <div v-if="title" class="gfm-callout__title">{{ title }}</div>
    <div class="gfm-callout__body"><slot /></div>
  </div>
</template>

<style>
.gfm-callout { box-sizing: border-box; border-radius: var(--gfm-radius); border: 1px solid var(--gfm-line); border-left: 6px solid var(--gfm-teal); background: var(--gfm-surface); padding: 16px 22px; margin: 8px 0; }
.gfm-callout--good { border-left-color: var(--gfm-good); }
.gfm-callout--warn { border-left-color: var(--gfm-warn); }
.gfm-callout--bad { border-left-color: var(--gfm-bad); }
.gfm-callout__title { font-size: 15px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--gfm-teal); margin-bottom: 4px; }
.gfm-callout--good .gfm-callout__title { color: var(--gfm-good); }
.gfm-callout--warn .gfm-callout__title { color: var(--gfm-warn); }
.gfm-callout--bad .gfm-callout__title { color: var(--gfm-bad); }
.gfm-callout__body { font-size: 21px; line-height: 1.4; }
.gfm-callout__body > :last-child { margin-bottom: 0; }
</style>

<studio>
description: A box that points something out - an invitation, a reminder or a warning - with a small heading.
category: GFM content
snippet: |-
  <GfmCallout title="Invitation" tone="info">
  Invite one friend this week.
  </GfmCallout>
preview: '<GfmCallout title="Invitation" tone="info">Invite one friend this week.</GfmCallout>'
props:
  title:
    label: Heading
  tone:
    label: Kind
    options:
      - info
      - good
      - warn
      - bad
</studio>
