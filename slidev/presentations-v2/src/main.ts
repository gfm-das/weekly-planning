// One application, two pages: /p-v2/<deck> (the presentation, Reveal.js) and /studio-v2/<deck> (the editor, GrapesJS).
// Each loads only its own code (a presentation never loads the editor, and the editor starts without ECharts).
import { createApp } from 'vue';
import { pageInfo } from './shared/api';
import { mark } from './shared/perf';

mark('boot');
// Two separate imports (not one conditional): the bundler then keeps each page's scripts and styles apart.
if (pageInfo().mode === 'studio-v2') {
  const { default: Studio } = await import('./studio/Studio.vue');
  createApp(Studio).mount('#app');
  mark('studio shell');
} else if (pageInfo().mode === 'library-v2') {
  const { default: Library } = await import('./runtime/Library.vue');
  createApp(Library).mount('#app');
  mark('library shell');
} else {
  const { default: Player } = await import('./runtime/Player.vue');
  createApp(Player).mount('#app');
  mark('player shell');
}
