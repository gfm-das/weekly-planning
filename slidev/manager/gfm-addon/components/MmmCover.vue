<script setup lang="ts">
/**
 * MmmCover - the title slide of the Monday Morning Meeting, zone conference and Stake decks: the whole slide in the deep
 * blue-green, the name of the mission (or zone) in big white italic letters, a thin line and the name of the meeting
 * under it. With `picture` the left part holds a picture (the zone conference has one); `picture-slot` shows an empty
 * dashed place for it instead, so the picture is easy to add.
 *
 * <MmmCover line-1="Deutschland" line-2="Frankfurt Mission" below="Monday Morning Meeting" />
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  line1?: string
  line2?: string
  below?: string
  below2?: string
  picture?: string
  pictureSlot?: boolean
  pictureText?: string
  tag?: string
}>(), { line1: '', line2: '', below: '', below2: '', picture: '', pictureSlot: false, pictureText: 'Put a picture here', tag: 'Manual' })

const hasPicture = computed(() => !!props.picture || props.pictureSlot)
</script>

<template>
  <div class="mmm-frame mmm-cover" :class="{ 'has-picture': hasPicture }">
    <div v-if="hasPicture" class="mmm-cover__picture" :class="{ 'is-empty': !picture }">
      <img v-if="picture" :src="picture" alt="" />
      <span v-else>{{ pictureText }}</span>
      <span v-if="!picture" class="mmm-manual-tag">{{ tag }}</span>
    </div>
    <div class="mmm-cover__text">
      <div v-if="line1" class="mmm-cover__big">{{ line1 }}</div>
      <div v-if="line2" class="mmm-cover__big">{{ line2 }}</div>
      <hr />
      <div v-if="below" class="mmm-cover__big">{{ below }}</div>
      <div v-if="below2" class="mmm-cover__big">{{ below2 }}</div>
    </div>
  </div>
</template>

<style>
.mmm-frame.mmm-cover { background: #2d505e; color: #fff; border: 0; display: flex; align-items: center; justify-content: center; }
.mmm-cover__text { text-align: center; padding: 0 calc(60 * var(--u)); width: 100%; }
.mmm-cover.has-picture .mmm-cover__text { width: 60.5%; margin-left: auto; padding: 0 calc(30 * var(--u)); }
.mmm-cover__big { font-size: calc(62 * var(--u)); font-weight: 700; font-style: italic; line-height: 1.12; }
.mmm-cover.has-picture .mmm-cover__big { font-size: calc(56 * var(--u)); }
.mmm-cover hr { border: 0; border-top: calc(2 * var(--u)) solid #fff; margin: calc(22 * var(--u)) auto; width: 100%; opacity: 1; }
.mmm-cover__picture { position: absolute; left: 0; top: 0; bottom: 0; width: 39.5%; background: #1d3640; overflow: hidden; display: flex; align-items: center; justify-content: center; }
.mmm-cover__picture img { width: 100%; height: 100%; object-fit: cover; }
.mmm-cover__picture.is-empty { border: calc(2 * var(--u)) dashed #8fb0bd; font-size: calc(22 * var(--u)); color: #b9ccd4; text-align: center; padding: calc(20 * var(--u)); }
</style>

<studio>
description: "The title slide - the whole slide in deep blue-green with the name big and white, a thin line and the meeting's name under it. Optionally a picture on the left."
category: GFM content
snippet: '<MmmCover line-1="Deutschland" line-2="Frankfurt Mission" below="Monday Morning Meeting" />'
props:
  line1:
    label: First line
  line2:
    label: Second line
  below:
    label: Under the line
  picture:
    label: Picture on the left (address or file)
</studio>
