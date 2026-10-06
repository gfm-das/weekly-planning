# Presentations tests (`slidev/tests`)

These tests check the presentation manager (`slidev/manager`, see its [README](../manager/README.md)) and its
Slidev add-on. Almost all are plain Node tests (`node --test`): no browser, no database and no internet. A few
headless Edge checks (the `.ps1` files) open real pages in Microsoft Edge.

## Running them

The quick way, the same as the updater's quick tests (from the repository root, with Docker):

```
docker run --rm --network none -v <repo>:/repo -w /repo/slidev node:24-alpine node --test tests/*.test.mjs
```

A few tests need Slidev itself: its parser, the `slidev` program and its packages. They are skipped above. To run
them too, give the container the **live layout**: Slidev's `node_modules` at `/slidev/node_modules`, this
repository's manager at `/slidev/manager` and a writable `/slidev/decks`. Use a *copy* of the live `node_modules`
volume (a build writes into it), never the live volume and never live decks:

```
docker volume create gfm-test-<name>-nm
docker run --rm -v gfm-test-slides-nm:/from:ro -v gfm-test-<name>-nm:/to node:24-alpine cp -a /from/. /to/
docker run --rm --network none -v <repo>:/repo -v gfm-test-<name>-nm:/slidev/node_modules \
  -v <repo>/slidev/manager:/slidev/manager:ro -v <repo>/slidev/package.json:/slidev/package.json:ro \
  --tmpfs /slidev/decks -w /repo/slidev node:24-alpine node --test tests/*.test.mjs
```

On Windows without Docker, `node --test tests/` runs the plain tests; the ones that need a POSIX shell are skipped.

## What each file checks

### The manager's server

| File | What it checks |
|---|---|
| `web.test.mjs` | `web.mjs` (answers, packed pages and files, request bodies, cookies, file types) and `settings.mjs` (defaults and limits). |
| `deck-files.test.mjs` | Deck names, titles (only the title changes in `slides.md`), the decks folder, New / Duplicate / Rename / Delete. Live layout. |
| `delivery.test.mjs` | Compression (and a rebuild taking over unchanged packed copies), which editor answers are packed, cache headers, the add-on fingerprint, the build queue, the editor warm-up. |
| `packing.test.mjs` | What the manager address sends packed: the library, `portal-bridge.js` (and "not changed" for a browser that has it), Monaco (packed only for a GET that takes gzip; a HEAD or a browser without gzip gets the plain file). |
| `deck-origin.test.mjs` | The two addresses: what 3030 refuses, what 8089 accepts, deck passes; then the real manager's routes. |
| `zone-decks.test.mjs` | Zone presentations: who sees and changes which deck; a deck includes only its own files (also in a real build). |
| `protected-decks.test.mjs` | Protected decks cannot be renamed or deleted; the library shows why. |
| `chart-access.test.mjs` | Who may ask for a chart's numbers, pinning, shared answers, the builder's files. |
| `whiteboard.test.mjs` | The Whiteboard's chart frames: managers only, framed by the portal only, no HTML drawn. |
| `safe-chart-option.test.mjs` | Charts drawn on 3030 never draw HTML from a chart's settings. |
| `present.test.mjs` | Download PDF in published decks and screen mirroring in the presenter view. |

### Charts

| File | What it checks |
|---|---|
| `chart-engine.test.mjs` | The chart engine: every ECharts series type drawn with the real ECharts (server-side). |
| `chart-core.test.mjs` | Tables, number formats, trend lines and the older chart settings. |
| `chart-golden.test.mjs` | Charts written with the older settings draw exactly as before (fingerprints in `fixtures/chart-golden.json`). |
| `chart-builder.test.mjs`, `chart-edit.test.mjs` | The chart builder's non-visual part: reading and writing chart tags, chart-ids, the type picker. |
| `chart-spec.test.mjs` | Chart queries: the same canonical form and hash as portal-api (`fixtures/chart-spec-vectors.json`). |
| `transformers.test.mjs` | The ```` ```chart ```` block in a slide. |
| `mission-dashboard.test.mjs` | The Mission Dashboard showcase deck's charts. |
| `rename-friends-found.test.mjs` | The one-off script that renamed "Friends found" in existing decks. |

### Helpers (not tests themselves)

| File | What it is |
|---|---|
| `helpers/manager-harness.mjs` | Runs the **real** manager from a copy in a temporary folder, with small stand-ins for Slidev, its packages, Supabase and portal-api. Used by the route tests above. |
| `chart-cases.mjs`, `old-charts.mjs`, `make-chart-golden.mjs` | The golden chart cases, the old chart code loader, and the script that made the fingerprints. |
| `i18n-serve-library.mjs` | The real manager with made-up decks, to look at the library in another language in a browser. |

### Headless Edge checks (run by hand; each file says how)

| File | What it checks |
|---|---|
| `deck-origin/edge_deck_origin.ps1` | The real manager, real Slidev builds and the real editor with this branch's portal-api on a **throw-away** database copy: the two addresses, passes, zone decks, the chart builder under the page's security policy. Uses `deck-origin/serve-deck-origin.mjs`. |
| `edge_chart_builder.ps1` | The chart builder dialog in a computer and a phone width (`builder-harness/`: made-up numbers, no manager). |
| `present/edge_present.ps1` | Download PDF and screen mirroring on a really built deck (`present/serve-built-deck.mjs`). |
| `dashboard-deck/edge_dashboard_deck.ps1`, `dashboard-deck/chain-check.mjs` | The Mission Dashboard deck through the manager and portal-api on a throw-away database copy. |
| `speed/edge_speed.ps1` | Speed, not right or wrong: builds, the editor's start, the manager's routes, and the library, two decks, `/studio` (with Add chart and Source) and a Whiteboard chart frame at phone and computer width, on the local network and on a slowed "4G" line. Writes `report.json` and screenshots. Uses `speed/serve-speed.mjs` and a **throw-away** database copy; round 9's numbers are in `docs/handoff/round9/slidev.md`. |

Never point a test at the live system: the live containers, the live database or the live decks.

### GFM Studio

| File | What it checks |
|---|---|
| `studio-publish.test.mjs` | Editing only saves: no automatic publishing, a viewer opening a deck does not publish an open editor's draft, leaving the editor queues the publish. Live layout. |
| `studio-perf/` | Not a test run: the container and notes for measuring the editor's startup in a real browser (`studio-perf/README.md`). |
| `ai-import.test.mjs` | Paste Presentation: the check of pasted decks written like ChatGPT's and Claude's (`fixtures/ai-decks`), the safe fixes, replace/append/insert/undo of an import, the AI spec files being what `tools/make-ai-spec.mjs` makes. Parts need the live layout. |
| `source-upload.test.mjs` | Upload source: a deck's ZIP read back in (only slides.md and public/, no path leaves the deck, damaged and oversized ZIPs). |
| `formula.test.mjs`, `chart-presets.test.mjs`, `chart-story.test.mjs`, `gfm-components.test.mjs` | Calculated fields, chart kinds (every chart type), data stories, the GFM layouts and components. |
| `e2e/studio-e2e.js` | Not a test run: the browser checks of the Studio acceptance test, pasted into a real browser (instructions at the top of the file). |
