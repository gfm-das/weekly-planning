<script setup lang="ts">
/**
 * MmmSlot - a place for a video or a picture in the Media presentation: a framed box with a caption. Give it `src`:
 * a picture (png, jpg, gif, webp, svg), a video file (mp4, webm, ogg) or a YouTube / Vimeo address; the files of the
 * deck's own `public` folder (Studio's Assets panel) work too, written as `/my-video.mp4`. Without `src` the slot shows
 * a dashed box that says what to put there, and a "Manual" tag on screen. A video starts with its Play button (or
 * `autoplay`, muted); in the PDF a video is printed as its first picture.
 *
 * <MmmSlot x="40" y="90" w="540" h="420" kind="video" src="/welcome.mp4" caption="Welcome video" />
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  h?: number
  kind?: 'video' | 'image'
  src?: string
  caption?: string
  empty?: string
  tag?: string
  autoplay?: boolean
  fit?: 'contain' | 'cover'
}>(), { x: 40, y: 90, w: 540, h: 420, kind: 'image', src: '', caption: '', empty: 'Put a video or a picture here', tag: 'Manual', autoplay: false, fit: 'contain' })

const clean = computed(() => String(props.src || '').trim())
// What the address is: a video service (shown in a frame), a video file or a picture.
const embed = computed(() => {
  const s = clean.value
  const yt = /^https?:\/\/(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{6,20})/i.exec(s)
  if (yt) return `https://www.youtube-nocookie.com/embed/${yt[1]}`
  const vm = /^https?:\/\/(?:www\.)?vimeo\.com\/(\d{5,12})/i.exec(s)
  if (vm) return `https://player.vimeo.com/video/${vm[1]}`
  return ''
})
const isVideoFile = computed(() => /\.(mp4|webm|ogv|ogg|mov)(\?|#|$)/i.test(clean.value) || (!embed.value && props.kind === 'video' && !/\.(png|jpe?g|gif|webp|svg|avif)(\?|#|$)/i.test(clean.value)))
const place = computed(() => ({
  left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))`, height: `calc(${props.h} * var(--u))`,
}))
</script>

<template>
  <figure class="mmm-box mmm-slot" :class="{ 'is-empty': !clean }" :style="place">
    <div class="mmm-slot__frame mmm-panel">
      <iframe v-if="embed" :src="embed" :title="caption || 'Video'" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen loading="lazy" />
      <video v-else-if="clean && isVideoFile" :src="clean" controls playsinline preload="metadata" :autoplay="autoplay" :muted="autoplay" :style="{ objectFit: fit }" />
      <img v-else-if="clean" :src="clean" :alt="caption" :style="{ objectFit: fit }" />
      <div v-else class="mmm-slot__empty">
        <svg viewBox="0 0 48 48" aria-hidden="true"><rect x="5" y="9" width="38" height="30" rx="4" /><path v-if="kind === 'video'" d="M20 18v12l10-6z" /><path v-else d="M9 35l10-11 7 8 5-6 8 9" /></svg>
        <span>{{ empty }}</span>
      </div>
      <span v-if="!clean" class="mmm-manual-tag">{{ tag }}</span>
    </div>
    <figcaption v-if="caption" class="mmm-slot__caption">{{ caption }}</figcaption>
  </figure>
</template>

<style>
.mmm-slot { margin: 0; }
.mmm-slot__frame { position: absolute; inset: 0; overflow: hidden; background: #000; display: flex; align-items: center; justify-content: center; }
.mmm-slot.is-empty .mmm-slot__frame { background: var(--mmm-card); border-style: dashed; border-color: var(--mmm-muted); }
.mmm-slot__frame iframe, .mmm-slot__frame video, .mmm-slot__frame img { width: 100%; height: 100%; border: 0; display: block; }
.mmm-slot__empty { display: flex; flex-direction: column; align-items: center; gap: calc(10 * var(--u)); color: var(--mmm-muted); font-size: calc(18 * var(--u)); text-align: center; padding: calc(16 * var(--u)); }
.mmm-slot__empty svg { width: calc(56 * var(--u)); height: calc(56 * var(--u)); fill: none; stroke: currentColor; stroke-width: 2; stroke-linejoin: round; }
.mmm-slot__empty svg path { fill: currentColor; }
.mmm-slot__caption { position: absolute; left: 0; right: 0; top: 100%; margin-top: calc(6 * var(--u)); text-align: center; font-weight: 700; font-size: calc(18 * var(--u)); }
</style>

<studio>
description: "A framed place for a video (a file or a YouTube / Vimeo address) or a picture, with a caption. Empty, it shows a dashed box that says what to put there."
category: GFM content
snippet: '<MmmSlot x="40" y="90" w="540" h="420" kind="video" caption="Video" />'
props:
  kind:
    label: What goes here
    options:
      - video
      - image
  src:
    label: Address or file of the video or picture
  caption:
    label: Caption
  fit:
    label: Fit
    options:
      - contain
      - cover
</studio>
