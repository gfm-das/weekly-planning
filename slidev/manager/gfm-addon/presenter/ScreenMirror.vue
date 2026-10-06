<script setup lang="ts">
// The presenter view's "Screen Mirror" panel, in place of Slidev 52's
// internals/ScreenCaptureMirror.vue (swapped in by setup/vite-plugins.ts).
// Same capture as Slidev's, but it says why mirroring cannot start (plain
// http on the office network, a frame without display-capture, a phone)
// and what to do instead, reports a refused or cancelled capture, and stops
// the capture when the panel closes. See lib/screen-mirror.mjs.
import { onBeforeUnmount, shallowRef, useTemplateRef } from 'vue'
import { mirrorFailure, mirrorProblem } from '../lib/screen-mirror.mjs'

const video = useTemplateRef<HTMLVideoElement>('video')
const stream = shallowRef<MediaStream | null>(null)
const started = shallowRef(false)
const failure = shallowRef('')
const problem = typeof window === 'undefined' ? null : mirrorProblem(window)

function stopped() {
  if (video.value) video.value.srcObject = null
  stream.value = null
  started.value = false
}

async function startCapture() {
  failure.value = ''
  let capture: MediaStream
  try {
    capture = await navigator.mediaDevices.getDisplayMedia({
      video: { cursor: 'always' },
      audio: false,
      selfBrowserSurface: 'include',
      preferCurrentTab: false,
    } as any)
  }
  catch (error) {
    failure.value = mirrorFailure(error)
    return
  }
  stream.value = capture
  capture.addEventListener('inactive', stopped)
  if (video.value) {
    video.value.srcObject = capture
    video.value.play().catch(() => {})
  }
  started.value = true
}

onBeforeUnmount(() => {
  for (const track of stream.value?.getTracks() || []) track.stop()
})
</script>

<template>
  <div class="gfm-mirror">
    <video v-show="started" ref="video" class="gfm-mirror__video" muted playsinline />
    <div v-if="!started" class="gfm-mirror__panel">
      <div v-if="problem" class="gfm-mirror__note" role="note" :data-problem="problem.kind">
        <strong>{{ problem.title }}</strong>
        <p v-for="(line, i) in problem.lines" :key="i">
          {{ line }}
        </p>
        <a v-if="problem.link" class="slidev-form-button" :href="problem.link.href" target="_blank" rel="noopener">{{ problem.link.text }}</a>
      </div>
      <template v-else>
        <div class="gfm-mirror__hint">
          Use screen capturing to mirror your main screen back to presenter view.<br>
          Click the button below and <b>select your other monitor or window</b>.
        </div>
        <button class="slidev-form-button" type="button" @click="startCapture">
          Start Screen Mirroring
        </button>
        <p v-if="failure" class="gfm-mirror__failure" role="alert">
          {{ failure }}
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.gfm-mirror {
  width: 100%;
  height: 100%;
}
.gfm-mirror__video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.gfm-mirror__panel {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  box-sizing: border-box;
  overflow: auto;
}
.gfm-mirror__hint {
  opacity: 0.5;
}
.gfm-mirror__note {
  max-width: 36rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
  padding: 1rem 1.25rem;
  border: 1px solid rgba(217, 107, 43, 0.6);
  border-radius: 0.5rem;
  background: rgba(217, 107, 43, 0.08);
  line-height: 1.45;
  user-select: text;
}
.gfm-mirror__note p,
.gfm-mirror__failure {
  margin: 0;
}
.gfm-mirror__failure {
  max-width: 36rem;
  color: #c2410c;
}
</style>
