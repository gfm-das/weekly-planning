<script setup lang="ts">
// GFM Studio V2: slide list (left), slide canvas (centre, GrapesJS), properties (right). A normal prebuilt page:
// opening it starts nothing on the server, and saving is one PUT of JSON (no build).
import type { Component } from 'grapesjs';
import { nextTick, onMounted, reactive, ref, shallowRef } from 'vue';
import { ApiError, fetchCatalog, fetchDeck, pageInfo, saveDeck, uploadAsset } from '../shared/api';
import { mark } from '../shared/perf';
import { TRANSITIONS_LIST, type DataProps, type Deck, type PartType, type Slide } from '../shared/types';
import DataPanel from './DataPanel.vue';
import ViewersDialog from './ViewersDialog.vue';
import { createEditor, newId, PART_LABELS, type StudioEditor } from './grape';

const { slug } = pageInfo();
const canvas = ref<HTMLElement | null>(null);
const deck = ref<Deck>({ version: 1, name: 'New presentation', theme: 'gfm', slides: [] });
const current = ref(0);
const status = ref('Loading…');
const saving = ref(false);
const canEdit = ref(true);
const canManage = ref(false);
const exists = ref(false); // saved on the server at least once
const viewersOpen = ref(false);
const catalog = ref<any>(null);
const catalogError = ref('');
const studio = shallowRef<StudioEditor | null>(null);
const selected = shallowRef<Component | null>(null);
const sel = reactive<{ type: PartType | ''; props: Record<string, any> }>({ type: '', props: {} });
let loading = true;
let loadedOnce = false;
let dirty = false;

const BLOCKS: PartType[] = ['text', 'heading', 'image', 'shape', 'chart', 'kpi', 'table'];

function markDirty() {
  if (loading) return;
  dirty = true;
  status.value = 'Unsaved changes';
}

const blankSlide = (): Slide => ({ id: newId('slide'), transition: 'slide', autoAnimate: false, notes: '', components: [] });

// The selected slide's parts go back into the deck before the slide changes or the deck is saved.
function flush() {
  const s = studio.value;
  if (s && deck.value.slides[current.value]) deck.value.slides[current.value].components = s.read();
}

function show(i: number) {
  loading = true;
  studio.value!.load(deck.value.slides[i]);
  sel.type = ''; selected.value = null;
  // GrapesJS reports its own loading as changes for a moment: only changes after that are the person's.
  setTimeout(() => { loading = false; }, 500);
}

function go(i: number) {
  if (i === current.value) return;
  flush();
  current.value = i;
  show(i);
}

function addSlide() { flush(); deck.value.slides.splice(current.value + 1, 0, blankSlide()); current.value += 1; show(current.value); markDirty(); }
function duplicateSlide() {
  flush();
  const copy: Slide = JSON.parse(JSON.stringify(deck.value.slides[current.value]));
  copy.id = newId('slide');
  deck.value.slides.splice(current.value + 1, 0, copy); // part ids stay the same: Auto-Animate then matches them
  current.value += 1; show(current.value); markDirty();
}
function deleteSlide() {
  if (deck.value.slides.length < 2 || !confirm('Delete this slide?')) return;
  deck.value.slides.splice(current.value, 1);
  current.value = Math.min(current.value, deck.value.slides.length - 1);
  show(current.value); markDirty();
}
function moveSlide(d: number) {
  const j = current.value + d;
  if (j < 0 || j >= deck.value.slides.length) return;
  flush();
  const [s] = deck.value.slides.splice(current.value, 1);
  deck.value.slides.splice(j, 0, s);
  current.value = j; markDirty();
}

function onSelected(model: Component | null) {
  selected.value = model;
  if (!model) { sel.type = ''; return; }
  sel.type = model.get('gfmType');
  sel.props = JSON.parse(JSON.stringify(model.get('gfmProps') || {}));
}

function setProps(patch: Record<string, any>) {
  if (!selected.value) return;
  sel.props = { ...sel.props, ...patch };
  studio.value!.setPartProps(selected.value, JSON.parse(JSON.stringify(sel.props)));
  markDirty();
}
function setData(next: DataProps) { setProps(next as any); }

async function pickImage(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    setProps({ asset: await uploadAsset(slug, file), alt: sel.props.alt || file.name.replace(/\.[^.]+$/, '') });
  } catch (error) { status.value = (error as Error).message; }
}

async function save() {
  if (saving.value) return;
  saving.value = true;
  status.value = 'Saving…';
  try {
    flush();
    deck.value.name = deck.value.name.trim() || 'Untitled';
    await saveDeck(slug, deck.value);
    dirty = false;
    exists.value = true;
    status.value = 'Saved';
  } catch (error) {
    status.value = `Not saved: ${(error as Error).message}`;
  } finally { saving.value = false; }
}

const thumb = (s: Slide) => s.components.find(c => c.type === 'heading' || c.type === 'text')?.props.text || (s.components.some(c => c.type === 'chart') ? 'Chart' : 'Empty slide');

onMounted(async () => {
  document.title = 'Studio V2';
  mark('studio start');
  try {
    const loaded = await fetchDeck(slug);
    deck.value = loaded.deck;
    canEdit.value = loaded.can_edit;
    canManage.value = loaded.can_manage;
    exists.value = true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) { canManage.value = true; deck.value = { version: 1, name: slug.replace(/-/g, ' '), theme: 'gfm', slides: [blankSlide()] }; }
    else { status.value = (error as Error).message; return; }
  }
  if (!deck.value.slides.length) deck.value.slides.push(blankSlide());
  mark('deck loaded');
  studio.value = createEditor(canvas.value!, slug, { dirty: markDirty, selected: onSelected });
  (window as any).__gfmStudio = studio.value; // for the browser checks (tests/v2)
  mark('grapesjs init');
  studio.value.editor.on('load', () => { show(0); mark('first render'); setTimeout(() => { if (!dirty || !loadedOnce) { dirty = false; status.value = 'Saved'; } loadedOnce = true; }, 600); });
  fetchCatalog().then(c => { catalog.value = c; mark('catalog'); }).catch(e => { catalogError.value = (e as Error).message; });
  window.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); void save(); } });
  window.addEventListener('beforeunload', e => { if (dirty) e.preventDefault(); });
});
</script>

<template>
  <div class="studio">
    <header>
      <input v-model="deck.name" class="name" maxlength="120" @input="markDirty" aria-label="Presentation name" />
      <span class="status" data-test="status" :class="{ warn: status.startsWith('Not') || status.startsWith('Unsaved') }">{{ status }}</span>
      <a class="btn" href="/library-v2">Library</a>
      <button v-if="canManage" class="btn" data-test="viewers" :disabled="!exists" :title="exists ? '' : 'Save the presentation first'" @click="viewersOpen = true">Who can view</button>
      <a class="btn" :href="`/p-v2/${slug}`" target="_blank" rel="noopener">Present ▶</a>
      <a class="btn" :href="`/p-v2/${slug}?projector=1`" target="_blank" rel="noopener" title="Larger text, a black surround, a still screen">Projector ▶</a>
      <button class="btn primary" data-test="save" :disabled="saving || !canEdit" @click="save">Save</button>
    </header>

    <aside class="left">
      <h4>Slides</h4>
      <ol>
        <li v-for="(s, i) in deck.slides" :key="s.id" :class="{ on: i === current }" @click="go(i)">
          <span class="n">{{ i + 1 }}</span><span class="t">{{ thumb(s) }}</span>
        </li>
      </ol>
      <div class="row">
        <button class="btn" @click="addSlide">+ Slide</button>
        <button class="btn" @click="duplicateSlide">Copy</button>
        <button class="btn" @click="deleteSlide">Delete</button>
      </div>
      <div class="row"><button class="btn" @click="moveSlide(-1)">↑</button><button class="btn" @click="moveSlide(1)">↓</button></div>
      <h4>Add to slide</h4>
      <div class="blocks">
        <button v-for="b in BLOCKS" :key="b" class="btn block" :data-test="`add-${b}`" @click="studio?.addPart(b)">{{ PART_LABELS[b] }}</button>
      </div>
      <p class="hint">Click a part on the slide to move, resize or change it. Delete removes it. Ctrl+Z undoes.</p>
    </aside>

    <main ref="canvas" class="canvas"></main>

    <aside class="right">
      <template v-if="!sel.type">
        <h4>This slide</h4>
        <template v-if="deck.slides[current]">
          <label>Slide change
            <select v-model="deck.slides[current].transition" @change="markDirty"><option v-for="t in TRANSITIONS_LIST" :key="t" :value="t">{{ t }}</option></select>
          </label>
          <label class="check"><input type="checkbox" v-model="deck.slides[current].autoAnimate" @change="markDirty" /> Auto-Animate to the next slide</label>
          <label>Speaker notes <textarea v-model="deck.slides[current].notes" rows="6" maxlength="2000" @input="markDirty"></textarea></label>
        </template>
      </template>

      <template v-else>
        <h4>{{ PART_LABELS[sel.type] }}</h4>
        <template v-if="sel.type === 'text' || sel.type === 'heading'">
          <label>Text <textarea :value="sel.props.text" rows="4" data-test="text-input" @input="setProps({ text: ($event.target as HTMLTextAreaElement).value })"></textarea></label>
          <label>Size (px) <input type="number" min="8" max="100" :value="sel.props.size" @input="setProps({ size: Number(($event.target as HTMLInputElement).value) })" /></label>
          <label>Colour <input type="color" :value="sel.props.color" @input="setProps({ color: ($event.target as HTMLInputElement).value })" /></label>
        </template>
        <template v-else-if="sel.type === 'image'">
          <label>Picture <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-test="image-file" @change="pickImage" /></label>
          <label>Description <input :value="sel.props.alt" maxlength="200" @input="setProps({ alt: ($event.target as HTMLInputElement).value })" /></label>
        </template>
        <template v-else-if="sel.type === 'shape'">
          <label>Colour <input type="color" :value="sel.props.color" @input="setProps({ color: ($event.target as HTMLInputElement).value })" /></label>
          <label class="check"><input type="checkbox" :checked="sel.props.round" @change="setProps({ round: ($event.target as HTMLInputElement).checked })" /> Rounded</label>
        </template>
        <template v-else>
          <p v-if="catalogError" class="err">{{ catalogError }}</p>
          <p v-else-if="!catalog" class="hint">Loading the list of numbers…</p>
          <DataPanel v-else :model-value="(sel.props as DataProps)" :catalog="catalog" :slug="slug" :kind="(sel.type as any)" @update:model-value="setData" />
        </template>
      </template>
    </aside>
  <ViewersDialog v-if="viewersOpen" :slug="slug" @close="viewersOpen = false" />
  </div>
</template>

<style>
html, body { margin: 0; height: 100%; font-family: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif; color: #193746; background: #eef4f5; }
#app { height: 100%; }
.studio { display: grid; grid-template-columns: 230px 1fr 340px; grid-template-rows: 52px 1fr; height: 100vh; }
.studio header { grid-column: 1 / -1; display: flex; gap: 10px; align-items: center; padding: 0 14px; background: #fff; border-bottom: 1px solid #d9e5e8; }
.studio .name { flex: 1; font: 700 17px inherit; border: 1px solid transparent; border-radius: 8px; padding: 6px 8px; color: #17394b; }
.studio .name:hover, .studio .name:focus { border-color: #d9e5e8; }
.studio .status { font-size: 13px; color: #127a4a; } .studio .status.warn { color: #8a5a00; }
.studio .btn { display: inline-flex; align-items: center; border: 1px solid #d9e5e8; background: #fff; border-radius: 9px; padding: 7px 12px; cursor: pointer; font: 600 14px inherit; color: #17394b; text-decoration: none; }
.studio .btn:hover { background: #e8f1f2; } .studio .btn.primary { background: #087f8c; border-color: #087f8c; color: #fff; } .studio .btn:disabled { opacity: .55; cursor: default; }
.studio aside { background: #f7fafb; padding: 10px 12px; overflow: auto; } .studio .left { border-right: 1px solid #d9e5e8; } .studio .right { border-left: 1px solid #d9e5e8; }
.studio h4 { margin: 12px 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #556d7a; }
.studio ol { list-style: none; margin: 0; padding: 0; } .studio li { display: flex; gap: 8px; padding: 7px 8px; border-radius: 8px; cursor: pointer; font-size: 13px; }
.studio li.on { background: #dcecee; font-weight: 600; } .studio li .n { color: #6b828d; width: 18px; } .studio li .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.studio .row { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; } .studio .blocks { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.studio .block { justify-content: center; } .studio .hint { font-size: 12px; color: #6b828d; } .studio .err { color: #b42318; font-size: 13px; }
.studio .canvas { min-width: 0; min-height: 0; position: relative; } .studio .canvas .gjs-editor { height: 100%; } .studio .canvas .gjs-cv-canvas { width: 100%; height: 100%; top: 0; }
.studio .right label { display: grid; gap: 3px; font-size: 13px; font-weight: 600; margin-top: 8px; } .studio .right label.check { display: flex; gap: 6px; align-items: center; font-weight: 400; }
.studio .right select, .studio .right textarea, .studio .right input:not([type=checkbox]):not([type=color]):not([type=file]) { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #d9e5e8; border-radius: 8px; font: inherit; }
@media (max-width: 900px) { .studio { grid-template-columns: 1fr; grid-template-rows: 52px 220px 1fr auto; } }
</style>
