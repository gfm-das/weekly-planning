<script setup lang="ts">
/**
 * GFM Studio: the calculated field editor (loaded only when a calculated field is opened - it brings the formula
 * language with it, see GFM-STUDIO.md "lazy loading").
 *
 * Name, formula, format; the chart's fields and the functions as buttons that put the right text into the formula
 * (that is the autocomplete: clicking, or typing the first letters of a name shows what matches); the result for the
 * chart's own numbers as you type, with the friendly error and where it is.
 */
import { computed, ref, watch } from 'vue'
import { FORMATS, FUNCTIONS, fieldNames, formatValue, parseFormula, previewFormula } from '../../../gfm-addon/lib/formula.mjs'

interface Calc { name: string, formula: string, format?: string, decimals?: number | string, hide?: boolean }

const props = defineProps<{ modelValue: Calc, table: any | null, others?: string[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: Calc): void, (e: 'done'): void }>()

const draft = ref<Calc>({ format: 'number', ...props.modelValue })
watch(() => props.modelValue, v => (draft.value = { format: 'number', ...v }))

// The fields a formula may use: the chart's own numbers, and the calculated fields before this one.
const fields = computed(() => [...fieldNames(props.table), ...(props.others ?? [])])
const area = ref<HTMLTextAreaElement>()

const preview = computed(() => {
  const table = props.table ?? { labels: [], series: [] }
  // The calculated fields before this one are part of the table the formula sees (they are in the chart's table).
  return previewFormula(table, draft.value.formula ?? '', draft.value.format ?? 'number', draft.value.decimals ?? null)
})
const syntax = computed(() => {
  try { parseFormula(draft.value.formula ?? ''); return '' } catch (error: any) { return error.message }
})

function insert(text: string, caretBack = 0) {
  const el = area.value
  const value = draft.value.formula ?? ''
  const start = el?.selectionStart ?? value.length
  const end = el?.selectionEnd ?? value.length
  // A word being typed is replaced by the suggestion.
  const before = value.slice(0, start).replace(/[A-Za-z_]*$/, (word) => (text.toUpperCase().startsWith(word.toUpperCase()) || text.startsWith('[') ? '' : word))
  draft.value = { ...draft.value, formula: before + text + value.slice(end) }
  const caret = before.length + text.length - caretBack
  requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(caret, caret) })
  push()
}

// What the person is typing now: the last word (a field in [ ] or the start of a function).
const typing = computed(() => {
  const value = draft.value.formula ?? ''
  const open = value.lastIndexOf('[')
  if (open > value.lastIndexOf(']')) return { kind: 'field', word: value.slice(open + 1).toLowerCase() }
  const m = /([A-Za-z_]+)$/.exec(value)
  return m ? { kind: 'function', word: m[1].toLowerCase() } : { kind: '', word: '' }
})
const suggestions = computed(() => {
  const { kind, word } = typing.value
  if (kind === 'field') return fields.value.filter(f => f.toLowerCase().includes(word)).slice(0, 6).map(f => ({ label: `[${f}]`, text: `[${f}]`, help: 'field' }))
  if (kind === 'function' && word.length >= 1) return Object.entries(FUNCTIONS).filter(([n]) => n.toLowerCase().startsWith(word)).slice(0, 6).map(([n, f]) => ({ label: f.signature, text: `${n}()`, help: f.help, back: 1 }))
  return []
})
const help = computed(() => {
  const m = /([A-Z_]+)\([^()]*$/.exec((draft.value.formula ?? '').toUpperCase())
  const fn = m ? (FUNCTIONS as any)[m[1]] : null
  return fn ? { signature: fn.signature, help: fn.help, example: fn.example } : null
})

function push() { emit('update:modelValue', { ...draft.value }) }
function setFormat(format: string) { draft.value = { ...draft.value, format }; push() }
const sample = computed(() => preview.value.ok && preview.value.sample !== null ? preview.value.sample : null)
const notes = computed(() => (preview.value.notes?.divisionByZero ? `Divided by 0 in ${preview.value.notes.divisionByZero} ${preview.value.notes.divisionByZero === 1 ? 'row' : 'rows'}: those rows have no number.` : ''))
void formatValue
</script>

<template>
  <div class="gfm-formula">
    <label class="studio-field">
      <span class="studio-field__label">Name</span>
      <span class="studio-field__control">
        <input type="text" :value="draft.name" placeholder="Successful Contact Rate" @input="draft = { ...draft, name: ($event.target as HTMLInputElement).value }; push()">
      </span>
    </label>

    <div class="gfm-formula__label">Formula</div>
    <textarea
      ref="area"
      class="gfm-formula__text"
      rows="3"
      spellcheck="false"
      placeholder="[Successfully Contacted] / [Referrals Received]"
      :value="draft.formula"
      @input="draft = { ...draft, formula: ($event.target as HTMLTextAreaElement).value }; push()"
    />

    <div v-if="suggestions.length" class="gfm-formula__suggest">
      <button v-for="s in suggestions" :key="s.label" class="gfm-chip" :title="s.help" @mousedown.prevent="insert(s.text, (s as any).back || 0)">
        {{ s.label }}
      </button>
    </div>

    <div class="gfm-formula__result" :class="{ 'gfm-formula__result--bad': !preview.ok }">
      <template v-if="preview.ok">
        <span class="gfm-formula__label">Preview</span>
        <strong>{{ sample ?? '–' }}</strong>
        <span v-if="notes" class="studio-hint">{{ notes }}</span>
      </template>
      <template v-else>
        {{ syntax || preview.problem }}
      </template>
    </div>
    <p v-if="help" class="studio-hint">
      <code>{{ help.signature }}</code> — {{ help.help }} Example: <code>{{ help.example }}</code>
    </p>

    <label class="studio-field">
      <span class="studio-field__label">Format</span>
      <span class="studio-field__control">
        <select :value="draft.format" @change="setFormat(($event.target as HTMLSelectElement).value)">
          <option v-for="f in FORMATS" :key="f" :value="f">{{ { number: 'Number', percent: 'Percentage', integer: 'Whole number', compact: 'Compact (12K)', decimals: 'One decimal' }[f] }}</option>
        </select>
      </span>
    </label>
    <label class="studio-field">
      <span class="studio-field__label">Only a helper</span>
      <span class="studio-field__control">
        <input type="checkbox" :checked="!!draft.hide" @change="draft = { ...draft, hide: ($event.target as HTMLInputElement).checked }; push()">
        <span class="studio-hint">Not drawn; other fields can use it.</span>
      </span>
    </label>

    <div class="gfm-formula__label">Fields</div>
    <div class="gfm-formula__chips">
      <button v-for="f in fields" :key="f" class="gfm-chip" @click="insert(`[${f}]`)">
        [{{ f }}]
      </button>
      <span v-if="!fields.length" class="studio-hint">The chart's numbers appear here when the chart has loaded.</span>
    </div>
    <div class="gfm-formula__label">Functions</div>
    <div class="gfm-formula__chips">
      <button v-for="(f, name) in FUNCTIONS" :key="name" class="gfm-chip" :title="`${f.signature} — ${f.help}`" @click="insert(`${name}()`, 1)">
        {{ name }}
      </button>
    </div>
    <div class="studio-button-row" style="margin-top: 8px">
      <button class="studio-button" @click="emit('done')">
        Done
      </button>
    </div>
  </div>
</template>

<style scoped>
.gfm-formula__label { font-size: 11px; font-weight: 650; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.7; margin: 10px 0 4px; }
.gfm-formula__text { width: 100%; box-sizing: border-box; font-family: ui-monospace, Consolas, monospace; font-size: 13px; line-height: 1.4; resize: vertical; }
.gfm-formula__result { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin: 8px 0; padding: 8px 10px; border-radius: 8px; background: rgba(8, 127, 140, 0.1); }
.gfm-formula__result strong { font-size: 18px; }
.gfm-formula__result--bad { background: rgba(180, 35, 24, 0.12); color: #b42318; font-size: 13px; }
.gfm-formula__suggest, .gfm-formula__chips { display: flex; flex-wrap: wrap; gap: 4px; }
.gfm-chip { border: 1px solid rgba(128, 128, 128, 0.4); border-radius: 999px; background: transparent; color: inherit; padding: 2px 9px; font-size: 12px; cursor: pointer; }
.gfm-chip:hover { border-color: #087f8c; color: #087f8c; }
</style>
