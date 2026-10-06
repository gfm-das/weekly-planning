<script setup lang="ts">
// Mission Dashboard: the slide number, small, in the top corner of every slide (not when printing).
// The portal theme is followed in setup/main.ts.
import { useNav } from '@slidev/client'

const { currentPage, total, isPrintMode } = useNav()
</script>

<template>
  <div v-if="!isPrintMode" class="absolute top-2.5 right-5 text-[11px] leading-4 tabular-nums opacity-50 pointer-events-none">
    {{ currentPage }} / {{ total }}
  </div>
</template>
