<script setup lang="ts">
/**
 * GFM Studio: Paste Presentation. A person pastes the Slidev Markdown an AI (or another person) wrote; it is checked, shown
 * as an outline and only then brought in: replacing the presentation, added after the last slide, or inserted after the
 * current slide. The whole import is one undoable step (Studio's Undo and Ctrl+Z write the earlier file back).
 *
 * Loaded when first opened (it brings the check with it, import-analyze.mjs). Nothing is changed until Import is pressed.
 */
import { useNav } from '@slidev/client'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { importApi, assetApi } from '../client/composables/useDeckApi'
import { pushDeckHistory } from '../client/composables/useSlideSource'
import { importOpen, importPrefill } from '../client/state'
import spec from '../../../gfm-addon/ai/gfm-spec.json'
import aiPrompt from '../../../gfm-addon/ai/gfm-ai-prompt.txt?raw'
import { analyzeDeck, autoFix, FIXES } from './import-analyze.mjs'
import { useCatalog } from '../client/composables/useCatalog'

type Mode = 'replace' | 'append' | 'insert'

const nav = useNav()
const { components } = useCatalog()
const text = ref(importPrefill.value || '')
const mode = ref<Mode>('append')
const stage = ref<'edit' | 'checked'>('edit')
const checking = ref(false)
const importing = ref(false)
const result = ref<any>(null)
const slidevCheck = ref<any>(null)
const override = ref(false)
const message = ref('')
const copied = ref(false)
const area = ref<HTMLTextAreaElement>()
const fileInput = ref<HTMLInputElement>()
const current = computed(() => nav.currentSlideNo.value)

onMounted(() => { importPrefill.value = ''; area.value?.focus() })
function close() { importOpen.value = false }
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
// Editing the text starts the check again.
watch(text, () => { stage.value = 'edit'; result.value = null; message.value = '' })

async function assetSet() {
  const got = await assetApi.list()
  return got ? new Set(got.assets.map(a => a.url)) : null
}

/** Checks the text: Slidev's own reading first, then the GFM checks. */
async function validate() {
  checking.value = true
  message.value = ''
  try {
    slidevCheck.value = await importApi.check(text.value)
    result.value = analyzeDeck(text.value, { spec: spec as any, known: components.map(c => c.name), assets: await assetSet(), parsed: slidevCheck.value })
    override.value = false
    stage.value = 'checked'
  }
  finally { checking.value = false }
}

const blocked = computed(() => result.value?.issues.filter((i: any) => i.severity === 'blocked') ?? [])
const errors = computed(() => result.value?.issues.filter((i: any) => i.severity === 'error') ?? [])
const warnings = computed(() => result.value?.issues.filter((i: any) => i.severity === 'warning' || i.severity === 'info') ?? [])
/** Slidev can load it even if parts of it are unknown (so "Import anyway" is honest); a blocked one never imports. */
const loadable = computed(() => !!slidevCheck.value?.ok && (slidevCheck.value?.slides ?? 0) > 0)
const canImport = computed(() => !!result.value && !blocked.value.length && !importing.value && (result.value.valid || (override.value && loadable.value)))
const fixes = computed<string[]>(() => result.value?.fixable ?? [])

async function applyFixes() {
  const fixed = autoFix(text.value, fixes.value)
  text.value = fixed.markdown
  message.value = fixed.applied.length ? `Fixed: ${fixed.applied.join(' ')}` : ''
  await validate()
}

const modeText = computed(() => ({ replace: 'Replace the presentation', append: 'Add after the last slide', insert: `Insert after slide ${current.value}` })[mode.value])

async function doImport() {
  if (!canImport.value) return
  importing.value = true
  try {
    const done = await importApi.import(mode.value, text.value, mode.value === 'insert' ? current.value : undefined)
    if (!done) { message.value = 'The import did not work. Nothing was changed.'; return }
    const label = `Imported ${done.count} slide${done.count === 1 ? '' : 's'}`
    pushDeckHistory(label, done.before, done.after)
    try { sessionStorage.setItem('gfm-studio:notice', `${label}. Ctrl+Z undoes the whole import.`) } catch {}
    // The deck reloads by itself (the server asks for it); the toast above is shown then.
    importOpen.value = false
  }
  finally { importing.value = false }
}

async function copyInstructions() {
  try { await navigator.clipboard.writeText(aiPrompt); copied.value = true; setTimeout(() => (copied.value = false), 2500) }
  catch { message.value = 'The browser did not allow copying. Select the instructions in the editor page menu instead.' }
}

async function openFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 1_500_000) { message.value = 'That file is too large to import (over 1.5 MB).'; return }
  text.value = await file.text()
  ;(event.target as HTMLInputElement).value = ''
}

const dot = (s: string) => ({ green: '#127a4a', yellow: '#b7791f', red: '#b42318' })[s]
const word = (s: string) => ({ green: 'Fully editable', yellow: 'Partly editable', red: 'Source-first' })[s]
const sevWord = (s: string) => ({ blocked: 'Not allowed', error: 'Problem', warning: 'Check', info: 'Note' })[s] ?? s
const bySlide = computed(() => {
  const map = new Map<number, any[]>()
  for (const i of [...blocked.value, ...errors.value, ...warnings.value]) map.set(i.slide, [...(map.get(i.slide) ?? []), i])
  return [...map.entries()].sort((a, b) => a[0] - b[0])
})
</script>

<template>
  <div class="gfm-imp" role="dialog" aria-modal="true" aria-label="Paste Presentation" @mousedown.self="close">
    <div class="gfm-imp__box">
      <header class="gfm-imp__head">
        <h2>Paste Presentation</h2>
        <button class="gfm-imp__x" title="Close (Esc)" @click="close">
          ×
        </button>
      </header>

      <p class="gfm-imp__lead">
        Paste a complete Slidev presentation, for example one written by ChatGPT or Claude. It is checked first; nothing changes until you press Import.
      </p>

      <div class="gfm-imp__row">
        <button class="gfm-btn" @click="copyInstructions">
          {{ copied ? 'Copied' : 'Copy AI instructions' }}
        </button>
        <button class="gfm-btn" @click="fileInput?.click()">
          Open a file…
        </button>
        <input ref="fileInput" type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden @change="openFile">
        <span class="gfm-imp__hint">Give the instructions to the AI first, then paste what it writes.</span>
      </div>

      <textarea ref="area" v-model="text" class="gfm-imp__text" spellcheck="false" placeholder="---&#10;theme: default&#10;title: My presentation&#10;---&#10;&#10;# First slide" />

      <fieldset class="gfm-imp__modes">
        <legend>Bring it in</legend>
        <label><input v-model="mode" type="radio" value="append"> Add after the last slide</label>
        <label><input v-model="mode" type="radio" value="insert"> Insert after slide {{ current }}</label>
        <label><input v-model="mode" type="radio" value="replace"> Replace the presentation <span class="gfm-imp__hint">(keeps its title)</span></label>
      </fieldset>

      <div class="gfm-imp__row">
        <button class="gfm-btn" :disabled="!text.trim() || checking" @click="validate">
          {{ checking ? 'Checking…' : 'Validate' }}
        </button>
        <button class="gfm-btn gfm-btn--go" :disabled="!canImport" @click="doImport">
          {{ importing ? 'Importing…' : 'Import' }}
        </button>
        <button class="gfm-btn" @click="close">
          Cancel
        </button>
        <span v-if="result" class="gfm-imp__hint">{{ modeText }}</span>
      </div>
      <p v-if="message" class="gfm-imp__msg">
        {{ message }}
      </p>

      <section v-if="result" class="gfm-imp__result">
        <h3>
          {{ result.slides.length }} slide{{ result.slides.length === 1 ? '' : 's' }}:
          <span :style="{ color: dot('green') }">{{ result.counts.green }} fully editable</span>,
          <span :style="{ color: dot('yellow') }">{{ result.counts.yellow }} partly</span>,
          <span :style="{ color: dot('red') }">{{ result.counts.red }} source-first</span>
        </h3>
        <p v-if="result.counts.red || result.counts.yellow" class="gfm-imp__hint">
          Slides that are not green use advanced Slidev features. Some parts can be edited visually; use Source for full control. Nothing is refused for that.
        </p>

        <div v-if="blocked.length || errors.length" class="gfm-imp__summary gfm-imp__summary--bad">
          <b>{{ blocked.length + errors.length }} issue{{ blocked.length + errors.length === 1 ? '' : 's' }} found</b>
          <span v-if="blocked.length">— some code is not allowed in a presentation, so this cannot be imported until it is removed.</span>
        </div>
        <div v-else-if="warnings.length" class="gfm-imp__summary">
          Nothing is wrong, but {{ warnings.length }} thing{{ warnings.length === 1 ? '' : 's' }} to look at.
        </div>
        <div v-else class="gfm-imp__summary gfm-imp__summary--ok">
          No problems found.
        </div>

        <ul v-if="bySlide.length" class="gfm-imp__issues">
          <li v-for="[no, list] in bySlide" :key="no">
            <b>{{ no ? `Slide ${no}` : 'The whole text' }}</b>
            <div v-for="(i, k) in list" :key="k" :class="`gfm-sev gfm-sev--${i.severity}`">
              <span>{{ sevWord(i.severity) }}</span> {{ i.message }}
            </div>
          </li>
        </ul>

        <div v-if="fixes.length" class="gfm-imp__fix">
          <button class="gfm-btn" @click="applyFixes">
            Auto-fix safe issues ({{ fixes.length }})
          </button>
          <span class="gfm-imp__hint">{{ fixes.map(f => (FIXES as any)[f]).join(' ') }} Nothing else is changed.</span>
        </div>
        <label v-if="(errors.length) && !blocked.length && loadable" class="gfm-imp__any">
          <input v-model="override" type="checkbox"> Import anyway. Slidev can load it; the slides marked red may show errors until you fix them in Source.
        </label>
        <p v-else-if="errors.length && !blocked.length && !loadable" class="gfm-imp__hint">
          Slidev cannot read this text yet, so it cannot be imported. Fix the problems above in the text box.
        </p>

        <h3>Preview</h3>
        <ol class="gfm-imp__outline">
          <li v-for="s in result.slides" :key="s.no">
            <span class="gfm-imp__dot" :style="{ background: dot(s.status) }" :title="word(s.status)" />
            <span class="gfm-imp__no">{{ s.no }}</span>
            <span class="gfm-imp__layout">{{ s.layout }}</span>
            <span class="gfm-imp__title">{{ s.heading || '(no heading)' }}</span>
            <span v-if="s.components.length" class="gfm-imp__comps">{{ s.components.join(', ') }}</span>
            <span v-for="n in s.notes" :key="n" class="gfm-imp__note">{{ n }}</span>
          </li>
        </ol>
        <p class="gfm-imp__hint">
          After the import you will see the real slides; Ctrl+Z puts everything back.
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.gfm-imp { position: fixed; inset: 0; z-index: 200; background: rgba(10, 20, 26, 0.55); display: flex; align-items: center; justify-content: center; padding: 18px; font-family: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif; }
.gfm-imp__box { background: #fff; color: #193746; width: min(880px, 100%); max-height: 100%; overflow: auto; border-radius: 16px; padding: 20px 24px 22px; box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35); }
html.dark .gfm-imp__box { background: #18262f; color: #edf7f8; }
.gfm-imp__head { display: flex; justify-content: space-between; align-items: center; }
.gfm-imp__head h2 { margin: 0; font-size: 22px; }
.gfm-imp__x { border: 0; background: transparent; color: inherit; font-size: 26px; cursor: pointer; line-height: 1; }
.gfm-imp__lead { margin: 6px 0 12px; opacity: 0.8; font-size: 14px; }
.gfm-imp__row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 10px 0; }
.gfm-imp__hint { font-size: 12.5px; opacity: 0.7; }
.gfm-imp__text { width: 100%; box-sizing: border-box; height: 240px; font-family: ui-monospace, Consolas, monospace; font-size: 12.5px; line-height: 1.45; padding: 10px; border-radius: 10px; border: 1px solid rgba(128, 128, 128, 0.45); background: transparent; color: inherit; resize: vertical; }
.gfm-imp__modes { border: 1px solid rgba(128, 128, 128, 0.35); border-radius: 10px; margin: 10px 0; display: flex; gap: 6px 18px; flex-wrap: wrap; font-size: 14px; }
.gfm-imp__modes legend { font-size: 12px; opacity: 0.7; padding: 0 6px; }
.gfm-btn { border: 1px solid rgba(128, 128, 128, 0.5); background: transparent; color: inherit; border-radius: 10px; padding: 8px 14px; font-size: 14px; cursor: pointer; }
.gfm-btn:hover:not(:disabled) { border-color: #087f8c; color: #087f8c; }
.gfm-btn:disabled { opacity: 0.45; cursor: default; }
.gfm-btn--go { background: #087f8c; border-color: #087f8c; color: #fff; font-weight: 650; }
.gfm-btn--go:hover:not(:disabled) { background: #066a75; color: #fff; }
.gfm-imp__msg { color: #b42318; font-size: 13px; }
.gfm-imp__result h3 { margin: 14px 0 6px; font-size: 16px; }
.gfm-imp__summary { padding: 8px 12px; border-radius: 10px; background: rgba(183, 121, 31, 0.12); font-size: 14px; }
.gfm-imp__summary--bad { background: rgba(180, 35, 24, 0.12); }
.gfm-imp__summary--ok { background: rgba(18, 122, 74, 0.12); }
.gfm-imp__issues { list-style: none; padding: 0; margin: 10px 0; display: grid; gap: 8px; }
.gfm-imp__issues li > b { font-size: 13px; }
.gfm-sev { font-size: 13.5px; margin: 3px 0 0 4px; padding-left: 8px; border-left: 3px solid #b7791f; }
.gfm-sev span { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 6px; }
.gfm-sev--error { border-color: #b42318; }
.gfm-sev--blocked { border-color: #7a1810; background: rgba(180, 35, 24, 0.08); }
.gfm-sev--info { border-color: #087f8c; }
.gfm-imp__fix { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 10px 0; }
.gfm-imp__any { display: block; font-size: 13.5px; margin: 8px 0; }
.gfm-imp__outline { list-style: none; padding: 0; margin: 6px 0; display: grid; gap: 4px; font-size: 13.5px; }
.gfm-imp__outline li { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; padding: 4px 6px; border-radius: 8px; background: rgba(128, 128, 128, 0.08); }
.gfm-imp__dot { width: 10px; height: 10px; border-radius: 50%; align-self: center; flex: none; }
.gfm-imp__no { font-weight: 700; min-width: 20px; }
.gfm-imp__layout { font-family: ui-monospace, Consolas, monospace; font-size: 12px; opacity: 0.75; }
.gfm-imp__title { font-weight: 600; }
.gfm-imp__comps { font-size: 12px; opacity: 0.7; }
.gfm-imp__note { flex-basis: 100%; font-size: 12.5px; opacity: 0.75; padding-left: 36px; }
</style>
