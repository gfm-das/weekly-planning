<script setup lang="ts">
// "Who can view": the viewing permission of one presentation (managers). Managers always see every presentation; the
// choices below let more leaders view this one. portal-api checks and keeps them (the same rule table as Slidev's).
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchViewers, saveViewers } from '../shared/api';

const props = defineProps<{ slug: string }>();
const emit = defineEmits<{ close: [] }>();

const loading = ref(true);
const error = ref('');
const saved = ref(false);
const options = reactive<{ roles: string[]; zones: any[]; districts: any[]; users: any[] }>({ roles: [], zones: [], districts: [], users: [] });
const rule = reactive<{ everyone: boolean; roles: string[]; zone_ids: number[]; district_ids: number[]; user_ids: string[] }>({ everyone: false, roles: [], zone_ids: [], district_ids: [], user_ids: [] });
const search = ref('');

const ROLE_WORDS: Record<string, string> = { DL: 'District Leaders', ZL: 'Zone Leaders', STL: 'Sister Training Leaders' };
const users = computed(() => options.users.filter(u => !search.value || String(u.name).toLowerCase().includes(search.value.toLowerCase())).slice(0, 60));
const nobody = computed(() => !rule.everyone && !rule.roles.length && !rule.zone_ids.length && !rule.district_ids.length && !rule.user_ids.length);

onMounted(async () => {
  try {
    const { access, options: choices } = await fetchViewers(props.slug);
    Object.assign(options, { roles: choices.roles ?? [], zones: choices.zones ?? [], districts: choices.districts ?? [], users: choices.users ?? [] });
    rule.everyone = !!access.everyone;
    rule.roles = [...(access.roles ?? [])];
    rule.zone_ids = [...(access.zone_ids ?? [])];
    rule.district_ids = [...(access.district_ids ?? [])];
    rule.user_ids = (access.user_ids ?? []).map(String);
  } catch (e) {
    error.value = (e as Error).message;
  } finally { loading.value = false; }
});

function toggle<T>(list: T[], value: T) {
  const i = list.indexOf(value);
  if (i >= 0) list.splice(i, 1); else list.push(value);
  saved.value = false;
}

async function save() {
  error.value = '';
  try {
    await saveViewers(props.slug, { everyone: rule.everyone, roles: rule.roles, zone_ids: rule.zone_ids, district_ids: rule.district_ids, user_ids: rule.user_ids });
    saved.value = true;
  } catch (e) { error.value = (e as Error).message; }
}
</script>

<template>
  <div class="veil" @click.self="emit('close')">
    <div class="box" role="dialog" aria-label="Who can view">
      <h3>Who can view this presentation</h3>
      <p class="hint">Managers can always view and change it. Choose who else may <b>view</b> it. Viewers cannot change it. With nothing chosen, only managers can view it.</p>
      <p v-if="loading">Loading…</p>
      <template v-else>
        <label class="check"><input type="checkbox" v-model="rule.everyone" @change="saved = false" /> <b>Everyone</b> with Presentations access (District, Zone and Sister Training Leaders)</label>
        <fieldset :disabled="rule.everyone">
          <legend>Or only these roles</legend>
          <label v-for="r in options.roles" :key="r" class="check"><input type="checkbox" :checked="rule.roles.includes(r)" @change="toggle(rule.roles, r)" /> {{ ROLE_WORDS[r] ?? r }}</label>
          <legend>…in these zones <small>(none chosen: the whole mission)</small></legend>
          <div class="list"><label v-for="z in options.zones" :key="z.id" class="check"><input type="checkbox" :checked="rule.zone_ids.includes(z.id)" @change="toggle(rule.zone_ids, z.id)" /> {{ z.name }}</label></div>
          <legend>…in these districts</legend>
          <div class="list"><label v-for="d in options.districts" :key="d.id" class="check"><input type="checkbox" :checked="rule.district_ids.includes(d.id)" @change="toggle(rule.district_ids, d.id)" /> {{ d.name }}</label></div>
        </fieldset>
        <fieldset>
          <legend>Also these people</legend>
          <input v-model="search" placeholder="Search by name…" />
          <div class="list"><label v-for="u in users" :key="u.user_id" class="check"><input type="checkbox" :checked="rule.user_ids.includes(String(u.user_id))" @change="toggle(rule.user_ids, String(u.user_id))" /> {{ u.name }}</label></div>
        </fieldset>
        <p v-if="nobody" class="hint">Only managers can view this presentation.</p>
      </template>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="saved" class="ok">Saved. Changes reach viewers within 15 seconds.</p>
      <div class="row"><button class="btn" @click="emit('close')">Close</button><button class="btn primary" data-test="viewers-save" :disabled="loading" @click="save">Save</button></div>
    </div>
  </div>
</template>

<style scoped>
.veil { position: fixed; inset: 0; background: rgba(10,25,35,.45); display: flex; align-items: center; justify-content: center; z-index: 100; }
.box { background: #fff; border-radius: 14px; padding: 18px 20px; width: 520px; max-width: calc(100vw - 32px); max-height: calc(100vh - 40px); overflow: auto; box-shadow: 0 14px 38px rgba(20,30,40,.3); display: grid; gap: 8px; }
h3 { margin: 0; } .hint { color: #6b828d; font-size: 13px; margin: 0; } .err { color: #b42318; font-size: 13px; margin: 0; } .ok { color: #127a4a; font-size: 13px; margin: 0; }
fieldset { border: 1px solid #d9e5e8; border-radius: 10px; padding: 6px 10px 10px; margin: 0; } legend { font-size: 12px; font-weight: 700; color: #556d7a; padding: 0 4px; }
.check { display: flex; gap: 8px; align-items: center; font-size: 14px; padding: 2px 0; }
.list { max-height: 120px; overflow: auto; border: 1px solid #e3eaee; border-radius: 8px; padding: 2px 8px; margin-bottom: 4px; }
input:not([type=checkbox]) { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #d9e5e8; border-radius: 8px; font: inherit; margin-bottom: 4px; }
.row { display: flex; justify-content: flex-end; gap: 8px; }
.btn { border: 1px solid #d9e5e8; background: #fff; border-radius: 9px; padding: 8px 14px; cursor: pointer; font: 600 14px inherit; color: #17394b; } .btn.primary { background: #087f8c; border-color: #087f8c; color: #fff; } .btn:disabled { opacity: .55; }
</style>
