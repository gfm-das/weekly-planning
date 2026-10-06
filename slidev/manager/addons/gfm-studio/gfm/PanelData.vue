<script setup lang="ts">
/**
 * GFM Studio: the Data panel (GFM Data Inspector). For a selected MissionChart:
 *   DATA       the numbers (read from the chart's query) and its calculated fields
 *   VISUAL     the chart kind (Trend, Goal vs actual, Ranked bar ...) and what each kind reads
 *   STORY      the steps the chart goes through, one click each
 *   STYLE      title and height
 *   ANIMATION  how the story moves (morph, fade, none), how long, the easing
 *   ADVANCED   the ECharts option and the `shape` as JSON
 * Everything is written back to the slide as attributes of the chart's tag (calc, preset, story ...): the slide stays
 * ordinary Slidev. The panel is loaded when the Data tab is first opened; the formula editor only when a calculated
 * field is opened (GFM-STUDIO.md).
 */
import type { PropMeta } from '../client/types'
import { computed, defineAsyncComponent, ref } from 'vue'
import { useStudio } from '../client/context'
import { readProp, writeProp } from '../client/md/props'
import { selection } from '../client/state'
import { PRESETS } from '../../../gfm-addon/lib/chart-presets.mjs'
import { EASINGS, TRANSITIONS } from '../../../gfm-addon/lib/chart-story.mjs'

const FormulaEditor = defineAsyncComponent(() => import('./FormulaEditor.vue'))

const studio = useStudio()
const TABS = ['Data', 'Visual', 'Story', 'Style', 'Animation', 'Advanced'] as const
const tab = ref<typeof TABS[number]>('Data')

const range = computed(() => selection.value?.range ?? null)
const isChart = computed(() => selection.value?.tag === 'MissionChart' && !!range.value)

// ---- reading and writing the chart's tag ----
const meta = (name: string, type = 'string') => ({ name, type }) as PropMeta
const decode = (s: string) => s.replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, '\'').replace(/&amp;/g, '&')
function raw(name: string, type = 'string') {
  const v = range.value ? readProp(studio.content(), range.value, meta(name, type)) : null
  return v === null || v === true ? '' : decode(String(v))
}
function json<T>(name: string): T | null {
  const text = raw(name, 'object[]').trim()
  if (!text) return null
  try { return JSON.parse(text) as T } catch { return null }
}
async function write(name: string, type: string, value: string | null) {
  if (!range.value) return
  const next = writeProp(studio.content(), range.value, meta(name, type), value)
  await studio.commit(next, `Set ${name}`)
}
const writeText = (name: string, value: string) => write(name, 'string', value.trim() ? value : null)
const writeNumber = (name: string, value: string) => write(name, 'number', value.trim() === '' ? null : String(Number(value)))
const writeJson = (name: string, value: unknown) => {
  const empty = value === null || value === undefined || (Array.isArray(value) && !value.length) || (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value as object).length)
  return write(name, 'object[]', empty ? null : JSON.stringify(value))
}

// The chart's numbers as it drew them (MissionChart keeps them on its element while the editor is open).
const chart = computed(() => {
  void studio.content()
  const el = selection.value?.el as HTMLElement | undefined
  return (el?.closest?.('.gfm-chart') as any)?.__gfmChart ?? (el?.querySelector?.('.gfm-chart') as any)?.__gfmChart ?? null
})
const table = computed(() => chart.value?.table ?? null)
const seriesNames = computed<string[]>(() => (table.value?.series ?? []).filter((s: any) => s.role !== 'goal').map((s: any) => s.name))

// ---- DATA ----
const query = computed(() => json<any>('query'))
const MEASURE_NAMES: Record<string, string> = { friends_found: 'New people being taught', baptisms_confirmations: 'Baptisms and confirmations', baptismal_dates: 'Baptismal dates', sacrament_attendance: 'Sacrament attendance', members_at_lessons: 'Members at lessons', new_member_sacrament: 'New member sacrament attendance' }
const measureLabel = (id: string) => `${MEASURE_NAMES[id.split('.')[0]] ?? id.split('.')[0].replace(/_/g, ' ')}${id.endsWith('.previous_goal') ? ' (goal)' : id.endsWith('.goal') ? ' (goal)' : ''}`
const calcs = computed(() => json<any[]>('calc') ?? [])
const openCalc = ref(-1)
async function saveCalc(index: number, value: any) {
  const list = [...calcs.value]
  list[index] = value
  await writeJson('calc', list)
}
async function addCalc() {
  const list = [...calcs.value, { name: `Field ${calcs.value.length + 1}`, formula: '', format: 'number' }]
  await writeJson('calc', list)
  openCalc.value = list.length - 1
}
async function removeCalc(index: number) {
  const list = calcs.value.filter((_, i) => i !== index)
  openCalc.value = -1
  await writeJson('calc', list)
}

// ---- VISUAL ----
const preset = computed(() => raw('preset'))
const presetList = Object.entries(PRESETS as Record<string, { label: string, description: string, needs: string, group: string }>)
const keptKinds = presetList.filter(([, p]) => p.group === 'kind')
const typeKinds = presetList.filter(([, p]) => p.group === 'type')
const kindNeeds = computed(() => (PRESETS as any)[preset.value]?.needs ?? '')
const legacy = computed(() => !!raw('type') && !raw('chartId'))

// ---- STORY ----
const steps = computed(() => json<any[]>('story') ?? [])
async function saveSteps(list: any[]) { await writeJson('story', list) }
async function addStep() {
  const only = seriesNames.value.slice(0, Math.min(seriesNames.value.length, steps.value.length + 1))
  await saveSteps([...steps.value, { label: `Step ${steps.value.length + 1}`, ...(only.length ? { shape: { only } } : {}) }])
}
async function stepsFromSeries() {
  await saveSteps(seriesNames.value.map((name, i) => ({ label: name, shape: { only: seriesNames.value.slice(0, i + 1) } })))
}
async function patchStep(index: number, patch: Record<string, any>) {
  await saveSteps(steps.value.map((s, i) => (i === index ? { ...s, ...patch } : s)))
}
async function toggleOnly(index: number, name: string) {
  const step = steps.value[index] ?? {}
  const current: string[] = step.shape?.only ?? seriesNames.value
  const next = current.includes(name) ? current.filter(n => n !== name) : seriesNames.value.filter(n => current.includes(n) || n === name)
  await patchStep(index, { shape: { ...(step.shape ?? {}), only: next.length === seriesNames.value.length ? undefined : next } })
}
async function moveStep(index: number, by: number) {
  const list = [...steps.value]
  const to = index + by
  if (to < 0 || to >= list.length) return
  ;[list[index], list[to]] = [list[to], list[index]]
  await saveSteps(list)
}
const removeStep = (index: number) => saveSteps(steps.value.filter((_, i) => i !== index))

// ---- ADVANCED ----
const optionText = ref<string | null>(null)
const optionShown = computed(() => optionText.value ?? raw('option', 'object[]'))
const optionProblem = ref('')
async function applyOption() {
  const text = (optionText.value ?? '').trim()
  if (!text) { optionProblem.value = ''; return writeJson('option', null) }
  try { JSON.parse(text) } catch (error: any) { optionProblem.value = `Not valid JSON: ${error.message}`; return }
  optionProblem.value = ''
  await write('option', 'object[]', JSON.stringify(JSON.parse(text)))
  optionText.value = null
}
</script>

<template>
  <div v-if="!isChart" class="studio-empty">
    <p>Select a chart on the slide to work with its numbers, calculated fields, kind and story.</p>
    <p class="studio-hint">
      Charts are made with <b>Add chart</b> at the top of the editor.
    </p>
  </div>

  <template v-else>
    <div class="gfm-tabs" role="tablist">
      <button v-for="t in TABS" :key="t" class="gfm-tab" role="tab" :aria-selected="tab === t" @click="tab = t">
        {{ t }}
      </button>
    </div>

    <!-- DATA -->
    <template v-if="tab === 'Data'">
      <section class="studio-section">
        <h3 class="studio-section__title">
          Numbers
        </h3>
        <template v-if="query">
          <p class="studio-hint">
            Mission numbers, {{ query.level === 'mission' ? 'the whole mission' : `by ${query.level}` }}{{ query.by === 'week' ? ', week by week' : '' }}, the last {{ query.weeks?.last ?? '?' }} weeks.
          </p>
          <ul class="gfm-list">
            <li v-for="m in query.measures" :key="m">
              {{ measureLabel(m) }}
            </li>
          </ul>
        </template>
        <p v-else class="studio-hint">
          This chart has its own table of numbers.
        </p>
        <p class="studio-hint">
          To choose other numbers, a zone or a period, use <b>Edit chart</b> at the top of the editor.
        </p>
      </section>

      <section class="studio-section">
        <h3 class="studio-section__title">
          Calculated fields
        </h3>
        <div v-for="(c, i) in calcs" :key="i" class="gfm-row">
          <template v-if="openCalc !== i">
            <div class="gfm-row__main">
              <b>{{ c.name }}</b>
              <code class="gfm-code">{{ c.formula || '(no formula yet)' }}</code>
            </div>
            <button class="studio-button" @click="openCalc = i">
              Edit
            </button>
            <button class="studio-button studio-button--danger" title="Remove" @click="removeCalc(i)">
              ×
            </button>
          </template>
          <FormulaEditor v-else :model-value="c" :table="table" @update:model-value="saveCalc(i, $event)" @done="openCalc = -1" />
        </div>
        <div class="studio-button-row">
          <button class="studio-button" @click="addCalc">
            + Calculated field
          </button>
        </div>
        <p v-if="chart?.calc?.problems?.length" class="gfm-bad">
          {{ chart.calc.problems[0].name ? `“${chart.calc.problems[0].name}”: ` : '' }}{{ chart.calc.problems[0].message }}
        </p>
        <p class="studio-hint">
          A formula uses the chart's numbers, for example <code>[Successfully Contacted] / [Referrals Received]</code>.
        </p>
      </section>
    </template>

    <!-- VISUAL -->
    <template v-else-if="tab === 'Visual'">
      <section class="studio-section">
        <h3 class="studio-section__title">
          Chart kind
        </h3>
        <p v-if="legacy" class="gfm-bad">
          This chart was made the older way. Open <b>Edit chart</b> and save it once; then a kind can be chosen here.
        </p>
        <div class="gfm-kinds">
          <button class="gfm-kind" :aria-pressed="!preset" @click="writeText('preset', '')">
            <b>As built</b><span>Keep the chart as it is</span>
          </button>
          <button v-for="[id, p] in keptKinds" :key="id" class="gfm-kind" :aria-pressed="preset === id" :title="p.description" @click="writeText('preset', id)">
            <b>{{ p.label }}</b><span>{{ p.description }}</span>
          </button>
        </div>
        <h3 class="studio-section__title" style="margin-top: 14px">
          Every chart type
        </h3>
        <div class="gfm-kinds">
          <button v-for="[id, p] in typeKinds" :key="id" class="gfm-kind" :aria-pressed="preset === id" :title="`${p.label}: needs ${p.needs}`" @click="writeText('preset', id)">
            <b>{{ p.label }}</b><span>{{ p.needs }}</span>
          </button>
        </div>
        <p v-if="kindNeeds" class="studio-hint">
          Needs: {{ kindNeeds }}.
        </p>
        <p v-if="chart?.problem" class="gfm-bad">
          {{ chart.problem }}
        </p>
      </section>
      <section v-if="['ranked-bar', 'leaderboard', 'progress'].includes(preset)" class="studio-section">
        <label class="studio-field">
          <span class="studio-field__label">Show the top</span>
          <span class="studio-field__control"><input type="number" min="0" :value="raw('presetTop', 'number')" placeholder="12" @change="writeNumber('presetTop', ($event.target as HTMLInputElement).value)"></span>
        </label>
        <p class="studio-hint">
          0 shows every row.
        </p>
      </section>
      <section v-if="['funnel', 'conversion-funnel'].includes(preset)" class="studio-section">
        <label class="studio-field">
          <span class="studio-field__label">Step values</span>
          <span class="studio-field__control">
            <select :value="raw('presetAggregate') || 'last'" @change="writeText('presetAggregate', ($event.target as HTMLSelectElement).value)">
              <option value="last">Latest week</option>
              <option value="sum">All weeks added</option>
            </select>
          </span>
        </label>
      </section>
      <section v-if="preset === 'big-number'" class="studio-section">
        <label class="studio-field">
          <span class="studio-field__label">Goal</span>
          <span class="studio-field__control"><input type="number" :value="raw('presetTarget', 'number')" @change="writeNumber('presetTarget', ($event.target as HTMLInputElement).value)"></span>
        </label>
      </section>
    </template>

    <!-- STORY -->
    <template v-else-if="tab === 'Story'">
      <section class="studio-section">
        <h3 class="studio-section__title">
          Steps
        </h3>
        <p class="studio-hint">
          One click on the slide moves the chart to the next step. The chart stays the same chart and changes in place.
        </p>
        <div v-for="(s, i) in steps" :key="i" class="gfm-step">
          <div class="gfm-step__head">
            <span class="gfm-step__n">{{ i + 1 }}</span>
            <input type="text" :value="s.label" placeholder="Step name" @change="patchStep(i, { label: ($event.target as HTMLInputElement).value })">
            <button class="studio-button" title="Move up" :disabled="i === 0" @click="moveStep(i, -1)">
              ↑
            </button>
            <button class="studio-button" title="Move down" :disabled="i === steps.length - 1" @click="moveStep(i, 1)">
              ↓
            </button>
            <button class="studio-button studio-button--danger" title="Remove" @click="removeStep(i)">
              ×
            </button>
          </div>
          <div v-if="seriesNames.length" class="gfm-step__body">
            <span class="studio-hint">Show:</span>
            <label v-for="n in seriesNames" :key="n" class="gfm-check">
              <input type="checkbox" :checked="!s.shape?.only || s.shape.only.includes(n)" @change="toggleOnly(i, n)"> {{ n }}
            </label>
          </div>
          <label class="studio-field">
            <span class="studio-field__label">Kind</span>
            <span class="studio-field__control">
              <select :value="s.preset || ''" @change="patchStep(i, { preset: ($event.target as HTMLSelectElement).value || undefined })">
                <option value="">Same as the chart</option>
                <option v-for="[id, p] in presetList" :key="id" :value="id">{{ p.label }}</option>
              </select>
            </span>
          </label>
          <label class="studio-field">
            <span class="studio-field__label">Order</span>
            <span class="studio-field__control">
              <select :value="s.shape?.sort || ''" @change="patchStep(i, { shape: { ...(s.shape ?? {}), sort: ($event.target as HTMLSelectElement).value || undefined } })">
                <option value="">As they are</option>
                <option value="desc">Highest first</option>
                <option value="asc">Lowest first</option>
              </select>
            </span>
          </label>
        </div>
        <div class="studio-button-row">
          <button class="studio-button" @click="addStep">
            + Step
          </button>
          <button v-if="seriesNames.length > 1" class="studio-button" title="One step for each number, adding one more each time" @click="stepsFromSeries">
            A step per number
          </button>
          <button v-if="steps.length" class="studio-button studio-button--danger" @click="saveSteps([])">
            No story
          </button>
        </div>
      </section>
    </template>

    <!-- STYLE -->
    <template v-else-if="tab === 'Style'">
      <section class="studio-section">
        <label class="studio-field">
          <span class="studio-field__label">Title</span>
          <span class="studio-field__control"><input type="text" :value="raw('title')" @change="writeText('title', ($event.target as HTMLInputElement).value)"></span>
        </label>
        <label class="studio-field">
          <span class="studio-field__label">Height</span>
          <span class="studio-field__control"><input type="number" min="120" max="2000" :value="raw('height', 'number')" placeholder="360" @change="writeNumber('height', ($event.target as HTMLInputElement).value)"></span>
        </label>
        <p class="studio-hint">
          The look (colours, type, spacing) comes with the chart kind and is the same in every chart. For colours and more, use <b>Edit chart</b>.
        </p>
      </section>
    </template>

    <!-- ANIMATION -->
    <template v-else-if="tab === 'Animation'">
      <section class="studio-section">
        <h3 class="studio-section__title">
          Story motion
        </h3>
        <label class="studio-field">
          <span class="studio-field__label">Data transition</span>
          <span class="studio-field__control">
            <select :value="raw('storyTransition') || 'morph'" @change="writeText('storyTransition', ($event.target as HTMLSelectElement).value === 'morph' ? '' : ($event.target as HTMLSelectElement).value)">
              <option v-for="t in TRANSITIONS" :key="t" :value="t">{{ { morph: 'Morph (move into place)', fade: 'Fade', none: 'None' }[t] }}</option>
            </select>
          </span>
        </label>
        <label class="studio-field">
          <span class="studio-field__label">Duration (ms)</span>
          <span class="studio-field__control"><input type="number" min="0" max="3000" step="50" :value="raw('storyDuration', 'number')" placeholder="700" @change="writeNumber('storyDuration', ($event.target as HTMLInputElement).value)"></span>
        </label>
        <label class="studio-field">
          <span class="studio-field__label">Easing</span>
          <span class="studio-field__control">
            <select :value="raw('storyEasing') || 'cubicInOut'" @change="writeText('storyEasing', ($event.target as HTMLSelectElement).value === 'cubicInOut' ? '' : ($event.target as HTMLSelectElement).value)">
              <option v-for="e in EASINGS" :key="e" :value="e">{{ e }}</option>
            </select>
          </span>
        </label>
        <p class="studio-hint">
          Each story step comes with one click. The slide's entrance animation is under <b>Animate</b>.
        </p>
      </section>
    </template>

    <!-- ADVANCED -->
    <template v-else>
      <section class="studio-section">
        <h3 class="studio-section__title">
          ECharts option
        </h3>
        <textarea :value="optionShown" rows="10" spellcheck="false" class="gfm-code-area" @input="optionText = ($event.target as HTMLTextAreaElement).value" />
        <p v-if="optionProblem" class="gfm-bad">
          {{ optionProblem }}
        </p>
        <div class="studio-button-row" style="margin-top: 6px">
          <button class="studio-button" :disabled="optionText === null" @click="applyOption">
            Apply
          </button>
          <button class="studio-button" :disabled="optionText === null" @click="optionText = null; optionProblem = ''">
            Revert
          </button>
        </div>
        <p class="studio-hint">
          Any ECharts 6 option, written over the chart kind. The same one <b>Edit chart</b> shows under All options.
        </p>
      </section>
      <section class="studio-section">
        <h3 class="studio-section__title">
          Source of this chart
        </h3>
        <p class="studio-hint">
          Everything here is written to the chart's tag in the slide. Open <b>Source</b> at the top to see and edit it as text.
        </p>
      </section>
    </template>
  </template>
</template>

<style scoped>
.gfm-tabs { display: flex; flex-wrap: wrap; gap: 2px; padding: 6px 8px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.3); }
.gfm-tab { border: 0; border-bottom: 2px solid transparent; background: transparent; color: inherit; padding: 6px 8px; font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; cursor: pointer; opacity: 0.7; }
.gfm-tab[aria-selected='true'] { border-bottom-color: #087f8c; opacity: 1; color: #087f8c; }
.gfm-list { margin: 4px 0 8px; padding-left: 18px; font-size: 13px; }
.gfm-row { display: flex; gap: 6px; align-items: center; margin: 6px 0; flex-wrap: wrap; }
.gfm-row > :only-child { flex: 1 1 100%; }
.gfm-row__main { flex: 1; min-width: 0; display: flex; flex-direction: column; font-size: 13px; }
.gfm-code { font-size: 12px; opacity: 0.8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gfm-bad { color: #b42318; font-size: 12.5px; margin: 6px 0; }
.gfm-kinds { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.gfm-kind { text-align: left; border: 1px solid rgba(128, 128, 128, 0.4); border-radius: 10px; background: transparent; color: inherit; padding: 8px 9px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.gfm-kind b { font-size: 13px; }
.gfm-kind span { font-size: 11px; opacity: 0.7; line-height: 1.3; }
.gfm-kind[aria-pressed='true'] { border-color: #087f8c; box-shadow: inset 0 0 0 1px #087f8c; }
.gfm-step { border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 10px; padding: 8px; margin: 8px 0; }
.gfm-step__head { display: flex; gap: 4px; align-items: center; margin-bottom: 6px; }
.gfm-step__head input { flex: 1; min-width: 0; }
.gfm-step__n { width: 20px; height: 20px; border-radius: 50%; background: #087f8c; color: #fff; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.gfm-step__body { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-bottom: 4px; }
.gfm-check { font-size: 12.5px; display: inline-flex; gap: 4px; align-items: center; }
.gfm-code-area { width: 100%; box-sizing: border-box; font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
</style>
