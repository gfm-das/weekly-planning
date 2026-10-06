<script setup lang="ts">
// The data panel of a selected GFM chart / KPI / table: source, dimension, metrics, period, filter, sort, chart type,
// calculated fields, story scenes and the advanced ECharts JSON. It edits the part's props; the query it builds is
// checked by the same rules as the server's (chart-spec.mjs normalizeSpec).
import { computed, reactive, ref, watch } from 'vue';
import { normalizeSpec } from '../../../manager/gfm-addon/lib/chart-spec.mjs';
import { CHART_KIND_LABELS } from '../charts/presets';
import { fieldKey } from '../data/field-key';
import { checkFormula as checkFormulaInWorker } from '../data/worker-api';
import { queryChart } from '../shared/api';
import type { Calc, ChartKind, DataProps } from '../shared/types';

const props = defineProps<{ modelValue: DataProps; catalog: any; slug: string; kind: 'chart' | 'kpi' | 'table' }>();
const emit = defineEmits<{ 'update:modelValue': [DataProps] }>();

const DIMENSIONS = [
  { id: 'week', label: 'Week (mission total)', level: 'mission', by: 'week' },
  { id: 'mission', label: 'Mission', level: 'mission', by: 'unit' },
  { id: 'zone', label: 'Zone', level: 'zone', by: 'unit' },
  { id: 'district', label: 'District', level: 'district', by: 'unit' },
  { id: 'area', label: 'Area', level: 'area', by: 'unit' },
];
const PERIODS = [{ n: 1, label: 'Current week' }, { n: 4, label: 'Last 4 weeks' }, { n: 12, label: 'Last 12 weeks' }, { n: 26, label: 'Last 26 weeks' }, { n: 52, label: 'Last 52 weeks' }];

const q = computed(() => props.modelValue.query);
const dimension = computed(() => DIMENSIONS.find(d => d.level === q.value.level && d.by === q.value.by)?.id ?? 'zone');
const measures = computed<any[]>(() => props.catalog?.measures ?? []);
const zones = computed<any[]>(() => props.catalog?.zones ?? []);
const search = ref('');
const error = ref('');
const advancedText = ref(props.modelValue.advanced ? JSON.stringify(props.modelValue.advanced, null, 2) : '');
const advancedError = ref('');

const labelOf = (id: string) => measures.value.find(m => m.id === id)?.short || measures.value.find(m => m.id === id)?.label || id;
const groups = computed(() => (props.catalog?.groups ?? []).map((g: any) => ({
  ...g, items: measures.value.filter(m => m.group === g.id && (!search.value || `${m.label} ${m.id}`.toLowerCase().includes(search.value.toLowerCase()))),
})).filter((g: any) => g.items.length));

// Everything a chart can show: the measures chosen and the calculated fields.
const allFields = computed(() => [
  ...q.value.measures.map((m: string) => ({ key: fieldKey(m), label: labelOf(m) })),
  ...props.modelValue.calcs.map(c => ({ key: c.name, label: c.label })),
]);
const shown = computed(() => (props.modelValue.fields.length ? props.modelValue.fields : q.value.measures.map(fieldKey)));

// Two changes in one click (a metric and the fields shown) must build on each other, not on the parent's older copy.
let latest = props.modelValue;
watch(() => props.modelValue, v => { latest = v; });
function change(patch: Partial<DataProps>) {
  latest = { ...latest, ...patch };
  emit('update:modelValue', latest);
}

function setQuery(patch: Record<string, any>) {
  try {
    const next = normalizeSpec({ ...q.value, ...patch });
    error.value = '';
    change({ query: next });
    return true;
  } catch (e) {
    error.value = (e as Error).message;
    return false;
  }
}

function setDimension(id: string) {
  const d = DIMENSIONS.find(x => x.id === id)!;
  const keepFilter = d.level === 'zone' || d.level === 'district' || d.level === 'area' ? q.value.filter : {};
  setQuery({ level: d.level, by: d.by, filter: keepFilter, weeks: d.by === 'week' && q.value.weeks.last < 4 ? { last: 12 } : q.value.weeks });
}

function toggleMeasure(id: string) {
  const has = q.value.measures.includes(id);
  const list = has ? q.value.measures.filter((m: string) => m !== id) : [...q.value.measures, id];
  if (!list.length) return;
  const key = fieldKey(id);
  const fields = props.modelValue.fields.length ? props.modelValue.fields : q.value.measures.map(fieldKey);
  if (setQuery({ measures: list })) change({ fields: has ? fields.filter((f: string) => f !== key) : [...fields, key] });
}

function toggleField(key: string) {
  const fields = shown.value.includes(key) ? shown.value.filter((f: string) => f !== key) : [...shown.value, key];
  if (fields.length) change({ fields });
}

function toggleZone(id: number) {
  const zs: number[] = q.value.filter?.zones ?? [];
  const next = zs.includes(id) ? zs.filter(z => z !== id) : [...zs, id];
  setQuery({ filter: next.length ? { zones: next } : {} });
}

// ---- value filter and sort ----
const vf = computed(() => props.modelValue.filter ?? { field: '', op: '>' as const, value: 0 });
function setValueFilter(patch: Record<string, any>) {
  const next = { ...vf.value, ...patch };
  change({ filter: next.field ? { field: next.field, op: next.op, value: Number(next.value) || 0 } : null });
}

// ---- calculated fields ----
const dialog = reactive({ open: false, editing: '', name: '', label: '', formula: '', format: 'number' as Calc['format'], problem: '', preview: [] as string[] });
const knownFields = computed(() => allFields.value.filter(f => f.key !== dialog.editing).map(f => f.key));

function openCalc(calc?: Calc) {
  Object.assign(dialog, { open: true, editing: calc?.name ?? '', name: calc?.name ?? '', label: calc?.label ?? '', formula: calc?.formula ?? '', format: calc?.format ?? 'number', problem: '', preview: [] });
  void checkFormula();
}

let checking = 0;
async function checkFormula() {
  const mine = ++checking;
  dialog.problem = ''; dialog.preview = [];
  if (!dialog.formula.trim()) return;
  try {
    const answer = await queryChart(props.slug, props.modelValue.query);
    const keys = props.modelValue.query.measures.map(fieldKey);
    const rows = await checkFormulaInWorker(dialog.formula, knownFields.value, answer, keys);
    if (mine !== checking) return;
    dialog.preview = rows.map(r => `${r.label}: ${r.value == null ? '–' : dialog.format === 'percent' ? `${(r.value * 100).toFixed(1)}%` : String(Math.round(r.value * 100) / 100)}`);
  } catch (e) {
    if (mine === checking) dialog.problem = (e as Error).message;
  }
}

function saveCalc() {
  if (!/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(dialog.name)) { dialog.problem = 'The name uses letters, digits and _ and starts with a letter (for example contact_rate).'; return; }
  if (dialog.problem) return;
  const calc: Calc = { name: dialog.name, label: dialog.label.trim() || dialog.name, formula: dialog.formula, format: dialog.format };
  const others = props.modelValue.calcs.filter(c => c.name !== dialog.editing);
  if (others.some(c => c.name === calc.name) || q.value.measures.map(fieldKey).includes(calc.name)) { dialog.problem = 'That name is already a field.'; return; }
  const calcs = dialog.editing ? props.modelValue.calcs.map(c => (c.name === dialog.editing ? calc : c)) : [...props.modelValue.calcs, calc];
  const fields = shown.value.includes(calc.name) || dialog.editing ? shown.value : [...shown.value, calc.name];
  change({ calcs, fields });
  dialog.open = false;
}
function removeCalc(name: string) {
  change({ calcs: props.modelValue.calcs.filter(c => c.name !== name), fields: shown.value.filter((f: string) => f !== name), sortBy: props.modelValue.sortBy === name ? '' : props.modelValue.sortBy });
}

// ---- story scenes ----
function addScene() { change({ scenes: [...props.modelValue.scenes, { name: `Scene ${props.modelValue.scenes.length + 1}`, fields: [...shown.value] }] }); }
function buildUp() { change({ scenes: shown.value.map((_: string, i: number) => ({ name: labelOfField(shown.value[i]), fields: shown.value.slice(0, i + 1) })) }); }
const labelOfField = (key: string) => allFields.value.find(f => f.key === key)?.label ?? key;
function toggleSceneField(si: number, key: string) {
  const scenes = props.modelValue.scenes.map((s, i) => (i === si ? { ...s, fields: s.fields.includes(key) ? s.fields.filter((f: string) => f !== key) : [...s.fields, key] } : s));
  change({ scenes });
}

function applyAdvanced() {
  advancedError.value = '';
  if (!advancedText.value.trim()) return change({ advanced: null });
  try {
    const parsed = JSON.parse(advancedText.value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Write the settings as { }.');
    change({ advanced: parsed });
  } catch (e) { advancedError.value = (e as Error).message; }
}

watch(() => props.modelValue.advanced, v => { if (!v && advancedText.value && !advancedError.value) advancedText.value = ''; });
</script>

<template>
  <div class="data">
    <h4>Data source</h4>
    <select disabled><option>Mission key numbers (weekly)</option></select>

    <h4>Dimension</h4>
    <select :value="dimension" @change="setDimension(($event.target as HTMLSelectElement).value)">
      <option v-for="d in DIMENSIONS" :key="d.id" :value="d.id">{{ d.label }}</option>
    </select>

    <h4>Metrics <small>({{ q.measures.length }}/8)</small></h4>
    <input v-model="search" placeholder="Search numbers…" />
    <div class="list">
      <template v-for="g in groups" :key="g.id">
        <div class="group">{{ g.label }}</div>
        <label v-for="m in g.items" :key="m.id" class="check"><input type="checkbox" :checked="q.measures.includes(m.id)" @change="toggleMeasure(m.id)" /> {{ m.label }}</label>
      </template>
    </div>

    <h4>Date / period</h4>
    <select :value="q.weeks.last" @change="setQuery({ weeks: { last: Number(($event.target as HTMLSelectElement).value) } })">
      <option v-for="p in PERIODS" :key="p.n" :value="p.n">{{ p.label }}</option>
    </select>

    <h4>Filter</h4>
    <div v-if="q.level !== 'mission'" class="list small">
      <label v-for="z in zones" :key="z.id" class="check"><input type="checkbox" :checked="(q.filter?.zones ?? []).includes(z.id)" @change="toggleZone(z.id)" /> {{ z.name }}</label>
      <em v-if="!zones.length">No zones.</em>
    </div>
    <div class="row">
      <select :value="vf.field" @change="setValueFilter({ field: ($event.target as HTMLSelectElement).value })">
        <option value="">No value filter</option>
        <option v-for="f in allFields" :key="f.key" :value="f.key">{{ f.label }}</option>
      </select>
      <select :value="vf.op" @change="setValueFilter({ op: ($event.target as HTMLSelectElement).value })"><option>&gt;</option><option>&gt;=</option><option>&lt;</option><option>&lt;=</option></select>
      <input type="number" step="any" :value="vf.value" @change="setValueFilter({ value: ($event.target as HTMLInputElement).value })" style="width:70px" />
    </div>

    <h4>Sort</h4>
    <div class="row">
      <select :value="modelValue.sortBy" @change="change({ sortBy: ($event.target as HTMLSelectElement).value })">
        <option value="">—</option>
        <option v-for="f in allFields" :key="f.key" :value="f.key">{{ f.label }}</option>
      </select>
      <select :value="modelValue.sortDir" @change="change({ sortDir: ($event.target as HTMLSelectElement).value as any })">
        <option value="none">None</option><option value="desc">Descending</option><option value="asc">Ascending</option>
      </select>
    </div>

    <template v-if="kind === 'chart'">
      <h4>Chart type</h4>
      <select :value="modelValue.chartType" @change="change({ chartType: ($event.target as HTMLSelectElement).value as ChartKind })">
        <option v-for="(label, k) in CHART_KIND_LABELS" :key="k" :value="k">{{ label }}</option>
      </select>
    </template>

    <h4>Title</h4>
    <input :value="modelValue.title" maxlength="200" @input="change({ title: ($event.target as HTMLInputElement).value })" />

    <h4>Fields shown</h4>
    <div class="list small">
      <label v-for="f in allFields" :key="f.key" class="check"><input type="checkbox" :checked="shown.includes(f.key)" @change="toggleField(f.key)" /> {{ f.label }} <code>{{ f.key }}</code></label>
    </div>

    <h4>Calculated fields</h4>
    <div v-for="c in modelValue.calcs" :key="c.name" class="calc">
      <div><b>{{ c.label }}</b> <small>{{ c.format }}</small><br /><code>{{ c.formula }}</code></div>
      <div><button class="mini" @click="openCalc(c)">Edit</button> <button class="mini" @click="removeCalc(c.name)">Remove</button></div>
    </div>
    <button class="btn" data-test="add-calc" @click="openCalc()">+ Calculated Field</button>

    <template v-if="kind === 'chart'">
      <h4>Story mode (scenes)</h4>
      <div v-for="(s, i) in modelValue.scenes" :key="i" class="scene">
        <input :value="s.name" @input="change({ scenes: modelValue.scenes.map((x, k) => (k === i ? { ...x, name: ($event.target as HTMLInputElement).value } : x)) })" />
        <label v-for="f in allFields" :key="f.key" class="check"><input type="checkbox" :checked="s.fields.includes(f.key)" @change="toggleSceneField(i, f.key)" /> {{ f.label }}</label>
        <button class="mini" @click="change({ scenes: modelValue.scenes.filter((_, k) => k !== i) })">Remove scene</button>
      </div>
      <div class="row"><button class="btn" @click="addScene">+ Scene</button><button class="btn" @click="buildUp">Build up from fields</button></div>
      <small>Each scene after the first is one step in the presentation (press next).</small>

      <h4>Shared chart (smooth move between slides)</h4>
      <input :value="modelValue.transitionId" maxlength="60" placeholder="transition id, e.g. referrals-main" @input="change({ transitionId: ($event.target as HTMLInputElement).value.trim() })" />
      <small>Charts on different slides with the same id are one chart that morphs.</small>

      <details>
        <summary>Advanced ECharts JSON</summary>
        <textarea v-model="advancedText" rows="8" spellcheck="false" placeholder='{ "legend": { "show": false } }' @blur="applyAdvanced"></textarea>
        <div v-if="advancedError" class="err">{{ advancedError }}</div>
      </details>
    </template>

    <div v-if="error" class="err">{{ error }}</div>

    <div v-if="dialog.open" class="modal" @click.self="dialog.open = false">
      <div class="dialog">
        <h3>{{ dialog.editing ? 'Edit' : 'New' }} calculated field</h3>
        <label>Name <small>(used in formulas)</small><input v-model="dialog.name" data-test="calc-name" placeholder="contact_rate" /></label>
        <label>Label <small>(shown on the chart)</small><input v-model="dialog.label" data-test="calc-label" placeholder="Contact Rate" /></label>
        <label>Formula
          <input v-model="dialog.formula" data-test="calc-formula" placeholder="friends_found_actual / plans_submitted" @input="checkFormula" />
        </label>
        <div class="chips">Fields: <button v-for="k in knownFields" :key="k" class="mini" @click="dialog.formula += (dialog.formula && !dialog.formula.endsWith(' ') ? ' ' : '') + k; checkFormula()">{{ k }}</button></div>
        <small>Use + - * / ^ ( ), numbers and: safeDivide, abs, round, min, max, sqrt. Dividing by zero gives an empty value.</small>
        <label>Format
          <select v-model="dialog.format" @change="checkFormula"><option value="number">Number</option><option value="percent">Percentage</option></select>
        </label>
        <div v-if="dialog.problem" class="err">{{ dialog.problem }}</div>
        <div v-else-if="dialog.preview.length" class="preview"><b>Preview</b><div v-for="p in dialog.preview" :key="p">{{ p }}</div></div>
        <div class="row end"><button class="btn" @click="dialog.open = false">Cancel</button><button class="btn primary" data-test="calc-save" @click="saveCalc">Save field</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.data h4 { margin: 14px 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #556d7a; }
.data select, .data input:not([type=checkbox]), .data textarea { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #d9e5e8; border-radius: 8px; font: inherit; background: #fff; }
.list { max-height: 170px; overflow: auto; border: 1px solid #d9e5e8; border-radius: 8px; padding: 4px 8px; margin-top: 4px; background: #fff; }
.list.small { max-height: 110px; }
.group { font-size: 11px; font-weight: 700; color: #087f8c; margin-top: 6px; }
.check { display: flex; gap: 6px; align-items: center; font-size: 13px; padding: 1px 0; }
.check code { color: #6b828d; font-size: 11px; }
.row { display: flex; gap: 6px; margin-top: 4px; } .row.end { justify-content: flex-end; margin-top: 12px; }
.calc { display: flex; justify-content: space-between; gap: 6px; padding: 6px 8px; border: 1px solid #d9e5e8; border-radius: 8px; margin-bottom: 4px; font-size: 13px; background: #fff; }
.scene { border: 1px solid #d9e5e8; border-radius: 8px; padding: 6px 8px; margin-bottom: 6px; background: #fff; }
.btn { border: 1px solid #d9e5e8; background: #fff; border-radius: 8px; padding: 6px 10px; cursor: pointer; font: inherit; font-weight: 600; color: #17394b; }
.btn.primary { background: #087f8c; border-color: #087f8c; color: #fff; }
.mini { border: 1px solid #d9e5e8; background: #fff; border-radius: 6px; padding: 1px 7px; cursor: pointer; font-size: 12px; }
.err { color: #b42318; font-size: 13px; margin-top: 6px; }
small { color: #6b828d; }
.modal { position: fixed; inset: 0; background: rgba(10,25,35,.45); display: flex; align-items: center; justify-content: center; z-index: 100; }
.dialog { background: #fff; border-radius: 14px; padding: 18px 20px; width: 440px; max-width: calc(100vw - 32px); box-shadow: 0 14px 38px rgba(20,30,40,.3); display: grid; gap: 8px; }
.dialog h3 { margin: 0 0 4px; } .dialog label { display: grid; gap: 3px; font-size: 13px; font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; font-size: 12px; }
.preview { background: #e8f1f2; border-radius: 8px; padding: 8px 10px; font-size: 13px; }
</style>
