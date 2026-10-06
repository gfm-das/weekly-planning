// Builds src/entry.js into dist/ (build.sh then copies it to portal/whiteboard/vendor/): one ES module
// (gfm-excalidraw.js) that keeps its exports, its chunks (each of the 55 Excalidraw languages and the Mermaid diagram
// tools load only when used) and one stylesheet (gfm-excalidraw.css). An app build rather than a library build, so the
// code is fully minified.
import { defineConfig } from 'vite'

// Excalidraw asks esm.sh for a font it cannot find under window.EXCALIDRAW_ASSET_PATH. The page sets that path to its
// own vendor folder; this points the fallback there too, so the whiteboard never contacts another site.
const MARK = '"ASSETS_FALLBACK_URL",'
const END = '/dist/prod/`'
const LOCAL = '(typeof window<"u"&&typeof window.EXCALIDRAW_ASSET_PATH=="string"?window.EXCALIDRAW_ASSET_PATH:(typeof location<"u"?location.origin:"http://localhost")+"/whiteboard/vendor/")'
const localFontFallback = {
  name: 'gfm-local-font-fallback',
  transform(code, id) {
    if (!id.includes('@excalidraw') || !code.includes(MARK)) return null
    const from = code.indexOf(MARK) + MARK.length
    const end = code.indexOf(END, from)
    if (end < 0 || end - from > 200 || !code.slice(from, end).startsWith('`https://esm.sh/'))
      this.error('The esm.sh font fallback was not found where expected: check the Excalidraw version.')
    return { code: code.slice(0, from) + LOCAL + code.slice(end + END.length), map: null }
  },
}

export default defineConfig({
  plugins: [localFontFallback],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2020',
    sourcemap: false,
    minify: true,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 5000,
    modulePreload: false,
    rolldownOptions: {
      input: 'src/entry.js',
      preserveEntrySignatures: 'exports-only',
      output: {
        entryFileNames: 'gfm-excalidraw.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: info => (info.names || []).some(name => name.endsWith('.css')) ? 'gfm-excalidraw.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
})
