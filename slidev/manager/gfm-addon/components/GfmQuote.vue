<script setup lang="ts">
/**
 * GfmQuote - a quotation or a scripture, with who said it or where it is from.
 *
 * <GfmQuote author="Alma 37:6">By small and simple things are great things brought to pass.</GfmQuote>
 */
withDefaults(defineProps<{
  author?: string
}>(), {
  author: '',
})
</script>

<template>
  <figure class="gfm-quote">
    <blockquote class="gfm-quote__text"><slot /></blockquote>
    <figcaption v-if="author" class="gfm-quote__author">{{ author }}</figcaption>
  </figure>
</template>

<style>
.gfm-quote { margin: 12px 0; padding: 0 0 0 28px; border-left: 5px solid var(--gfm-teal); }
.gfm-quote__text { margin: 0; font-size: 32px; line-height: 1.35; font-style: italic; color: var(--gfm-navy); }
.gfm-quote__text > :last-child { margin-bottom: 0; }
.gfm-quote__author { margin-top: 12px; font-size: 18px; font-weight: 650; letter-spacing: 0.06em; text-transform: uppercase; color: var(--gfm-teal); }
</style>

<studio>
description: A quotation or scripture, large, with the source underneath.
category: GFM content
snippet: |-
  <GfmQuote author="Alma 37:6">
  By small and simple things are great things brought to pass.
  </GfmQuote>
preview: '<GfmQuote author="Alma 37:6">By small and simple things are great things brought to pass.</GfmQuote>'
props:
  author:
    label: Who said it, or the reference
</studio>
