<script setup lang="ts">
defineProps<{
  kicker?: string
  footer?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-cover">
    <div class="gfm-cover__bar" />
    <div class="gfm-cover__main">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <slot />
    </div>
    <div v-if="footer" class="gfm-cover__footer">{{ footer }}</div>
  </div>
</template>

<style>
.gfm-cover { position: relative; justify-content: center; padding-left: 96px; }
.gfm-cover__bar { position: absolute; left: 0; top: 0; bottom: 0; width: 28px; background: var(--gfm-teal); }
.gfm-cover__main h1 { font-size: 60px; line-height: 1.08; margin-bottom: 14px; }
.gfm-cover__main p { font-size: 26px; color: var(--gfm-muted); margin: 0; }
.gfm-cover__footer { position: absolute; left: 96px; bottom: 34px; font-size: 16px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--gfm-muted); }
</style>

<studio>
description: "Opening slide. A big title (a # heading), a line under it, a small label above and a footer line."
props:
  kicker:
    label: Label above the title
  footer:
    label: Footer line (for example the mission or the date)
</studio>
