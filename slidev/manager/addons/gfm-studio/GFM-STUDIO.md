# GFM Studio (our copy of slidev-addon-studio)

This folder is the visual editor of the presentation system. It started as a copy of an open-source Slidev add-on, and
from now on **we own and change it**. The presentation engine is still Slidev; nothing here replaces it.

| | |
|---|---|
| Upstream | https://github.com/BobTheShoplifter/slidev-addon-studio |
| Copied from | the npm package `slidev-addon-studio` **0.3.1** (as published; the package carries no commit id) |
| Copied on | 5 Oct 2026, from the live Presentations container's `node_modules` |
| Licence | MIT, (c) 2026 Daniel Christensen (`LICENSE`, kept as it is) |
| Used by | `slidev/package.json` → `slidev.addons` (`/slidev/manager/addons/gfm-studio`), before `gfm-addon` |
| Why under `manager/` | that folder is already mounted into the container and is one of the folders every deck editor may read (`zone-decks.mjs` SHARED_FOLDERS), so no new mount or rule is needed |

## What we changed (patches)

Keep this list current: one line per change to an upstream file, so a newer upstream can be compared and merged.

| File | Change | Why |
|---|---|---|
| `package.json` | name `gfm-studio`, `private` | it is a folder of the repository now, not a published package |
| `client/composables/useDeckApi.ts`, `client/composables/useSlideSource.ts`, `client/ui/StudioRoot.vue`, `node/plugin.ts`, `styles/studio.css` | Paste Presentation: import/restore/check calls, a whole-deck undo step that survives the reload, the dialog mounted lazily, `node/deck-import.ts`, a notice toast | one undoable import (`gfm/ImportDialog.vue`) |
| `client/state.ts`, `client/ui/StudioToolbar.vue`, `client/ui/StudioDock.vue`, `client/ui/parts/StudioIcon.vue` | a Data tab and panel (`gfm/PanelData.vue`, loaded on first use), one icon | the GFM Data Inspector; the other changes are the hooks that load it |
| `client/ui/StudioDock.vue` | the five panels other than Element load with `defineAsyncComponent` | the editor starts with one panel; the rest load when first opened (measured: small, 7 files, but the rule for every later GFM panel) |

## Where our own code goes

Our additions live in clearly named places, so the upstream files stay recognisable:

- `gfm/` (exists): `PanelData.vue` (the Data Inspector: Data, Visual, Story, Style, Animation, Advanced) and `FormulaEditor.vue` (loaded only when a calculated field is opened). Later: everything GFM-specific (AI import,
  AI import, layout picker entries). Upstream files only get small hooks that load these modules.
- Startup measurement and the preview-first loading are **not** in this folder: they are in the editor page
  (`slidev/manager/studio.html`) and `editor-bridge.js`.

## Updating from upstream

1. `npm pack slidev-addon-studio@<version>` and unpack it next to this folder.
2. Compare file by file with `git diff --no-index`; reapply the patches in the table above.
3. Run the Studio tests and open a deck in the editor before deploying.
