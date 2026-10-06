<script setup lang="ts">
// The V2 library: the presentations this person may view (portal-api decides per deck). Managers also make new ones.
import { onMounted, ref } from 'vue';
import { listDecks, type DeckListItem } from '../shared/api';
import { mark } from '../shared/perf';

const decks = ref<DeckListItem[]>([]);
const canManage = ref(false);
const message = ref('Loading…');
const title = ref('');

onMounted(async () => {
  document.title = 'Presentations V2';
  try {
    const answer = await listDecks();
    decks.value = answer.decks;
    canManage.value = answer.can_manage;
    message.value = answer.decks.length ? '' : 'No presentations are available to you yet. A manager chooses who can view each one.';
    mark('library loaded');
  } catch (error) {
    message.value = (error as Error).message;
  }
});

const slugOf = (text: string) => text.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
function create() {
  const slug = slugOf(title.value);
  if (!slug) return;
  location.href = `/studio-v2/${slug}`;
}
const when = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
</script>

<template>
  <div class="lib">
    <header>
      <h1>Presentations V2 <a class="back" href="/">Classic presentations</a></h1>
      <form v-if="canManage" @submit.prevent="create">
        <input v-model="title" placeholder="Name of a new presentation" maxlength="60" aria-label="Name of a new presentation" />
        <button class="btn primary" :disabled="!title.trim()">New presentation</button>
      </form>
    </header>
    <p v-if="message" class="msg">{{ message }}</p>
    <ul>
      <li v-for="d in decks" :key="d.slug">
        <div class="name">{{ d.name }}</div>
        <div class="meta">{{ d.slides }} slides · changed {{ when(d.updated_at) }}</div>
        <div class="row">
          <a class="btn primary" :href="`/p-v2/${d.slug}`">Present</a>
          <a class="btn" :href="`/p-v2/${d.slug}?projector=1`" title="Larger text, a black surround and a still screen">Projector</a>
          <a v-if="d.can_edit" class="btn" :href="`/studio-v2/${d.slug}`">Edit</a>
        </div>
      </li>
    </ul>
  </div>
</template>

<style>
html, body { margin: 0; font-family: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif; color: #193746; background: #eef4f5; }
.lib { max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }
.lib header { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }
.lib h1 { margin: 0; font-size: 26px; color: #17394b; }
.lib .back { font-size: 14px; font-weight: 600; margin-left: 12px; color: #087f8c; }
.lib form { display: flex; gap: 8px; }
.lib input { padding: 8px 10px; border: 1px solid #d9e5e8; border-radius: 9px; font: inherit; min-width: 220px; }
.lib ul { list-style: none; padding: 0; margin: 20px 0 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.lib li { background: #fff; border: 1px solid #d9e5e8; border-radius: 14px; padding: 16px; display: grid; gap: 6px; }
.lib .name { font-weight: 700; font-size: 18px; color: #17394b; }
.lib .meta { color: #6b828d; font-size: 13px; }
.lib .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.lib .btn { display: inline-flex; align-items: center; border: 1px solid #d9e5e8; background: #fff; border-radius: 9px; padding: 8px 14px; cursor: pointer; font: 600 14px inherit; color: #17394b; text-decoration: none; }
.lib .btn:hover { background: #e8f1f2; } .lib .btn.primary { background: #087f8c; border-color: #087f8c; color: #fff; } .lib .btn:disabled { opacity: .55; cursor: default; }
.lib .msg { color: #556d7a; }
</style>
