<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { onDomEvent } from '../composables/useDomEvent'
import { activePanel, dockWidth, studioOpen } from '../state'
// GFM: only the Element panel (the one open at start) is loaded with the editor; the others load when first opened.
const PanelAnimate = defineAsyncComponent(() => import('./panels/PanelAnimate.vue'))
const PanelAssets = defineAsyncComponent(() => import('./panels/PanelAssets.vue'))
const PanelComponents = defineAsyncComponent(() => import('./panels/PanelComponents.vue'))
import PanelInspect from './panels/PanelInspect.vue'
const PanelLayout = defineAsyncComponent(() => import('./panels/PanelLayout.vue'))
const PanelSlides = defineAsyncComponent(() => import('./panels/PanelSlides.vue'))
const PanelData = defineAsyncComponent(() => import('../../gfm/PanelData.vue'))
import StudioIcon from './parts/StudioIcon.vue'

const panels = {
  inspect: { title: 'Element', component: PanelInspect },
  components: { title: 'Components', component: PanelComponents },
  animate: { title: 'Animation', component: PanelAnimate },
  layout: { title: 'Slide layout', component: PanelLayout },
  slides: { title: 'Slides', component: PanelSlides },
  assets: { title: 'Assets', component: PanelAssets },
  data: { title: 'Data', component: PanelData },
} as const

const current = computed(() => panels[activePanel.value] ?? panels.inspect)

const resizing = ref(false)

onDomEvent<PointerEvent>(window, 'pointermove', (event) => {
  if (!resizing.value)
    return
  dockWidth.value = Math.min(560, Math.max(240, window.innerWidth - event.clientX))
})

onDomEvent(window, 'pointerup', () => (resizing.value = false))
</script>

<template>
  <aside class="studio-dock" :style="{ width: `${dockWidth}px` }">
    <div
      class="studio-dock__resizer"
      title="Drag to resize"
      @pointerdown.prevent="resizing = true"
    />
    <header class="studio-dock__header">
      <span class="studio-dock__title">{{ current.title }}</span>
      <button class="studio-icon-button" title="Close Studio (E)" @click="studioOpen = false">
        <StudioIcon name="close" />
      </button>
    </header>
    <div class="studio-dock__body">
      <component :is="current.component" />
    </div>
  </aside>
</template>
