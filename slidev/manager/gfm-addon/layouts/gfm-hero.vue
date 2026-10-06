<script setup lang="ts">
defineProps<{
  kicker?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-hero">
    <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
    <slot />
  </div>
</template>

<style>
.gfm-hero { justify-content: center; align-items: center; text-align: center; padding-left: 80px; padding-right: 80px; }
.gfm-hero h1, .gfm-hero h2 { font-size: 52px; line-height: 1.15; max-width: 760px; }
.gfm-hero p { font-size: 26px; color: var(--gfm-muted); max-width: 720px; }
</style>

<studio>
description: One message, large and centred - a statement, a big number or a question for the whole group.
props:
  kicker:
    label: Label above the message
</studio>
