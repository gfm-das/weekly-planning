import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// One application for the V2 editor (/studio-v2/<deck>) and the V2 presentation (/p-v2/<deck>).
// The manager serves the built files under /_v2/ (manager/v2-routes.mjs), so every file name starts with that.
export default defineConfig({
  base: '/_v2/',
  plugins: [vue()],
  // The data worker (Arquero, math.js) is served with its own policy by the manager: file name data-worker-<hash>.js.
  worker: { format: 'es' },
  build: {
    target: 'es2022', // top-level await in main.ts
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
    rollupOptions: { output: { manualChunks: { echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers', 'echarts/features'] } } },
  },
  server: { fs: { allow: ['..'] } },
});
