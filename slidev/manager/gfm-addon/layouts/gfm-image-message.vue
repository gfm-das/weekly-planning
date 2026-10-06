<script setup lang="ts">
defineProps<{
  image?: string
  imageSide?: 'left' | 'right'
  kicker?: string
}>()
</script>

<template>
  <div class="gfm-layout gfm-image-message" :class="{ 'gfm-image-message--right': imageSide === 'right' }">
    <div class="gfm-image-message__image" :style="image ? { backgroundImage: `url('${image}')` } : {}">
      <div v-if="!image" class="gfm-image-message__empty">Add a picture</div>
    </div>
    <div class="gfm-image-message__text">
      <div v-if="kicker" class="gfm-kicker">{{ kicker }}</div>
      <slot />
    </div>
  </div>
</template>

<style>
.gfm-image-message { flex-direction: row; padding: 0; }
.gfm-image-message--right { flex-direction: row-reverse; }
.gfm-image-message__image { flex: 0 0 44%; background: var(--gfm-surface) center / cover no-repeat; display: flex; align-items: center; justify-content: center; }
.gfm-image-message__empty { color: var(--gfm-muted); font-size: 18px; }
.gfm-image-message__text { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; padding: 40px 48px; }
</style>

<studio>
description: A picture beside a message. The picture fills one side of the slide; the text sits on the other.
props:
  image:
    label: Picture (an address, or a file from the assets panel)
  imageSide:
    label: Side of the picture
    options:
      - left
      - right
  kicker:
    label: Label above the text
</studio>
