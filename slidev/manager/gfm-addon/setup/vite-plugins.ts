// Slidev's Vite hook of the GFM addon: what every deck's page code may load, the local tab icon, the presenter's
// Screen Mirror panel and Studio's <studio> blocks. Slidev loads this for every editor and every build.
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { deckFilesPlugin } from '../lib/deck-folder.mjs'
import { localFavicon } from '../lib/favicon.mjs'
import { isSlidevScreenMirror } from '../lib/screen-mirror.mjs'

const SCREEN_MIRROR = fileURLToPath(new URL('../presenter/ScreenMirror.vue', import.meta.url))

// The chart components describe their props for the visual editor in a
// `<studio>` block. slidev-addon-studio answers Vue's request for that block;
// this does the same, so decks still build if Studio is ever switched off.
const STUDIO_BLOCK = /[?&]vue&type=studio\b/

export default (options: { userRoot?: string, cliRoot?: string } = {}) => [
  // A deck's page code loads files only from its own folder, node_modules and
  // the manager's code (zone presentations, round 7; lib/deck-folder.mjs).
  deckFilesPlugin(options),
  {
    name: 'gfm-addon:studio-block',
    enforce: 'pre' as const,
    load(id: string) {
      return STUDIO_BLOCK.test(id) ? 'export default {}' : null
    },
  },
  // One Vite dependency cache per deck. Slidev runs "installed globally" here
  // (/slidev/node_modules is above every deck), so it puts one cache for all
  // decks in @slidev/cli/node_modules/.vite. Vite's cache key includes the deck
  // folder, so opening another deck threw that cache away, re-ran the
  // optimiser and made the editor reload itself, and two open editors
  // rewrote each other's files. A `post` config hook runs after Slidev's own
  // and wins. The cache (about 23 MB) lives in the deck's node_modules, which
  // Download and Duplicate leave out and Rename deletes.
  {
    name: 'gfm-addon:deck-cache',
    enforce: 'post' as const,
    apply: 'serve' as const,
    config(config: { root?: string }) {
      const root = config.root || options.userRoot
      return root ? { cacheDir: join(root, 'node_modules/.vite') } : undefined
    },
  },
  // The presenter view's "Screen Mirror" panel: the addon's copy, which says
  // why mirroring cannot start (plain http on the office network, a frame
  // without display-capture) instead of a button that does nothing.
  {
    name: 'gfm-addon:screen-mirror',
    enforce: 'pre' as const,
    resolveId(source: string, importer?: string) {
      return isSlidevScreenMirror(source, importer) ? SCREEN_MIRROR : null
    },
  },
  // Built decks get a local tab icon instead of Slidev's default from
  // cdn.jsdelivr.net (the manager does the same for the editor page).
  {
    name: 'gfm-addon:local-favicon',
    transformIndexHtml(html: string) {
      return localFavicon(html)
    },
  },
]
