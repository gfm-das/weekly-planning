<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue';
import { fetchDeck, pageInfo } from '../shared/api';
import { mark } from '../shared/perf';

const host = ref<HTMLElement | null>(null);
const message = ref('Loading the presentation…');

onMounted(async () => {
  const { slug } = pageInfo();
  try {
    const { deck } = await fetchDeck(slug);
    document.title = deck.name;
    mark('deck loaded');
    const { startPresentation } = await import('../runtime/present');
    message.value = '';
    await nextTick();
    await startPresentation(host.value!, deck, slug);
  } catch (error) {
    message.value = (error as Error).message || 'The presentation could not be opened.';
  }
});
</script>

<template>
  <div v-if="message" class="gfm-message">{{ message }}</div>
  <div ref="host" class="reveal" :hidden="!!message"></div>
</template>

<style>
@import '../runtime/present.css';
</style>
