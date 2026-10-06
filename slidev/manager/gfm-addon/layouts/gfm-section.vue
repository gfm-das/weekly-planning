<script setup lang="ts">
defineProps<{
  kicker?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-section">
    <div class="gfm-section__main">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <slot />
    </div>
  </div>
</template>

<style>
.gfm-section { justify-content: center; background: var(--gfm-teal); color: #fff; }
html.dark .gfm-section { background: #0b4f58; }
.gfm-section .gfm-kicker { color: rgba(255, 255, 255, 0.82); }
.gfm-section h1, .gfm-section h2 { color: #fff; font-size: 54px; line-height: 1.1; }
.gfm-section p { font-size: 24px; color: rgba(255, 255, 255, 0.9); }
</style>

<studio>
description: Starts a new part of the presentation. A big heading on a teal background, with an optional label such as "Part 2".
props:
  kicker:
    label: Label above the heading
</studio>
