# The presentation manager (`slidev/manager`)

**Presentations** in the mission portal are slide decks. This folder is the program behind them. It:

- keeps the decks (one folder per deck, with a `slides.md` file written in Markdown);
- shows the **library** (a card per deck) and the **editor page** (`/studio/<deck>`);
- starts the visual editor (Slidev with Studio) for a deck someone edits;
- **publishes** decks: it turns `slides.md` into web pages that anyone allowed can open;
- gives charts in slides their **mission numbers**;
- checks, for every request, **who is asking** and what they may do.

The slide tool itself is [Slidev](https://sli.dev), installed from npm (the versions are pinned in
`slidev/package.json`). Its code is never changed: `gfm-addon/` is the small Slidev add-on that brings the mission's
charts, and a few fixes, into every deck.

Everything else about Presentations (how to write charts, the showcase decks, how it is deployed) is in
[`slidev/README.md`](../README.md). How the tests work is in [`slidev/tests/README.md`](../tests/README.md).

## The big picture

```
   Mission portal (port 8070)
   └─ Presentations frame ─────────────────────────────────────────────┐
                                                                        │
   the manager address (browsers: port 3030)      the deck address (browsers: port 8089)
   manager-routes.mjs                             deck-routes.mjs
     /             the library                      /p/<deck>/      a published deck
     /studio/<d>   the editor page                  /edit/<deck>/   the deck's editor (in a frame of /studio)
     /api/...      what the pages ask for           /api/...        numbers for that deck's own charts
     /whiteboard/  the Whiteboard's chart frames
            │                                                │
            └──────────────┬─────────────────────────────────┘
                           │ asks "who may do what?" and "which numbers?"
                           ▼
                  portal-api (/internal/presentations/*) ──► the mission database
                           │
            Slidev: `slidev build` (publishing) and one editor per deck being edited
```

### Why two addresses?

A deck is page code: its slides can run JavaScript in the browser of whoever opens it, and Zone Leaders write decks
too. If a deck ran on the same address as the library, its code could use the manager's sign-in. So published decks
and the editor run on a second address (port 8089), where the manager's sign-in is never accepted. A deck page gets
a **deck pass** instead: good for one deck, for a short time. `deck-origin.mjs` explains every rule.

## The files

Every file starts with a few lines saying **what it is**, **who uses it** and **how it fits**.

### Starting

| File | What it does |
|---|---|
| `server.mjs` | Starts the two listeners (manager address and deck address) and two jobs after the start. Start here. |
| `settings.mjs` | Every setting in one place (ports, folders, how many editors may run …), read from the environment. |

### Answering requests

| File | What it does |
|---|---|
| `manager-routes.mjs` | Every address on port 3030: the library, `/studio`, the `/api/` table (`API_ROUTES`), the Whiteboard frames. |
| `deck-routes.mjs` | Every address on port 8089: published decks, the editor, and the numbers of a deck's own charts. |
| `web.mjs` | Small helpers: send JSON, a page or a file kept in memory (packed with gzip), read a request's body and cookies, file types. |
| `pages.mjs` | The pages the manager makes itself: message pages, the "Open this presentation?" page, the ✎ button on a deck. |
| `library.html` | The library page (the cards). |
| `studio.html` | The editor page: the bar at the top, the visual editor in a frame, the Source pane. |

### Who is asking

| File | What it does |
|---|---|
| `sign-in.mjs` | The Presentations sign-in (a cookie the portal keeps alive) and the deck passes. |
| `access.mjs` | Asks portal-api who may open, change or make a deck; remembers a "yes" for 15 seconds. |
| `deck-origin.mjs` | The rules of the two addresses: what 3030 refuses, what 8089 accepts, how deck passes work. |
| `zone-decks.mjs` | Zone presentations: reads portal-api's answer (managers, ZL and STL, DL); keeps secrets away from Slidev. |
| `protected-decks.mjs` | Decks another page opens by name cannot be renamed or deleted (the list is empty today). |

### Decks

| File | What it does |
|---|---|
| `deck-files.mjs` | Where a deck's files are, its name ("slug") and its title (read with Slidev's own parser). |
| `deck-actions.mjs` | New, Duplicate, Rename and Delete; the editor page's status line. |
| `builds.mjs` | Publishing (`slidev build`): one build at a time, a new copy swapped in only when it worked, publishing by itself. |
| `source-upload.mjs` | Upload source: reads a deck's .zip (slides.md and public/ only, safe paths) and writes it into the deck. |
| `editors.mjs` | The visual editors: start one per deck, warm it up, pack its files on the way to the browser, stop it when nobody used it for 40 minutes (10 when it was only started ahead of time). |
| `delivery.mjs` | Faster decks: compressed copies (a rebuild reuses the unchanged ones), which editor answers are packed, cache headers, the build queue, the chart add-on's fingerprint. |

### Numbers and charts

| File | What it does |
|---|---|
| `numbers.mjs` | Key numbers and database charts: asks portal-api, shares answers for a minute. |
| `chart-access.mjs` | Who may ask for which chart ("pinning": only charts written in the deck). |
| `chart-builder.mjs` | The chart builder dialog of `/studio` (Add chart, Edit chart). |
| `safe-chart-option.mjs` | Makes a chart's settings safe to draw on 3030 (never HTML). |
| `vendor/` | ECharts 6.0.0 and echarts-stat 1.2.0, the chart libraries (not changed by us). |

### Scripts that run in the browser

| File | What it does |
|---|---|
| `portal-bridge.js` | Loaded by every page on 3030: the sign-in link to the portal, the colour theme, the language. |
| `editor-bridge.js` | Put into the editor page on 8089: tells `/studio` what the editor shows and does. |

### The portal's Whiteboard

| File | What it does |
|---|---|
| `whiteboard-frames.mjs` | The two Whiteboard pages (a live chart, the chart builder) and the framing rules of every page. |
| `whiteboard-chart.mjs` | The live chart frame. |
| `whiteboard-builder.mjs` | The chart builder, placing its chart on a board. |

### `gfm-addon/`: the Slidev add-on in every deck

| File | What it does |
|---|---|
| `components/MissionChart.vue` | `<MissionChart>`: a chart from your own numbers or from mission numbers. |
| `components/MissionKpiChart.vue` | `<MissionKpiChart>`: one key indicator, week by week. |
| `presenter/ScreenMirror.vue` | The presenter view's Screen Mirror panel (says why mirroring cannot start on plain http). |
| `lib/chart-engine.mjs` | Draws a chart from its numbers plus an ECharts option (one binder and one look per series type). |
| `lib/chart-core.mjs` | Tables, number formats and trend lines; draws charts written with the older settings exactly as before. |
| `lib/chart-builder-core.mjs` | Reads and writes chart tags in a slide (the builder's non-visual part). |
| `lib/chart-spec.mjs` | The query of a database chart: checking it and its canonical form (the same as portal-api's `charts.py`). |
| `lib/chart-schema.mjs` | The ECharts option's names for the builder's "All options" pane. |
| `lib/charts.ts` | The Vue side of the charts: loading ECharts, drawing, fetching live numbers. |
| `lib/deck-folder.mjs` | A deck may include files only from its own folder. |
| `lib/published-deck.mjs` | Published decks get Slidev's Download PDF page. |
| `lib/screen-mirror.mjs` | Why screen mirroring can or cannot start. |
| `lib/favicon.mjs` | The tab icon, written into the page (nothing is fetched from the internet). |
| `setup/*.ts` | Slidev's hooks: the ```` ```chart ```` block, the preparser and the Vite plugins. |

## How a request travels

**Opening the library.** The portal shows `http://<computer>:3030/` in its frame. `manager-routes.mjs` sends
`library.html`. Its script (with `portal-bridge.js`) asks the portal for a sign-in, then asks `GET /api/presentations`.
`access.mjs` asks portal-api which decks this person may open; the library shows only those.

**Opening a deck.** A card links to `/p/<deck>/` on 3030. The manager checks the person may open the deck, gives the
browser a **view pass** for that deck and sends it to the same address on 8089. There `deck-routes.mjs` checks the
pass and sends the published copy (`builds.mjs` builds it first if it was never published). A small script in the
page keeps the pass alive while the deck is open.

**Editing.** `/studio/<deck>` is the editor page. It asks `POST /api/presentations/<deck>/editor`: `editors.mjs` starts
Slidev for that deck (or reuses it) and the page gets an **edit pass**. The editor itself runs in a frame on 8089.
GFM Studio (our copy of the editor add-on: `addons/gfm-studio/`, see its `GFM-STUDIO.md`) saves `slides.md` after every change
but does not publish: a deck is published by **Publish now**, when the editor page is left (a queued publish) or when an idle
editor is stopped. While the editor page opens, it shows the published deck at once (`POST …/preview`) and fades to the
editor when it is editable. The library menu starts the editor ahead of time (`POST …/prestart`, `prestartDeck`). Startup
timings: `[GFM STUDIO STARTUP/OPEN/CLIENT]` in the log, `window.GFM_PERF` in the page (`tests/studio-perf/README.md`).
(`SLIDEV_AUTO_PUBLISH=1` brings back the old build 10 seconds after the
slides stop changing.)

**A chart's numbers.** A chart on a published deck asks `POST /api/charts/data` on 8089. The request needs that deck's
pass, and the chart must be written in the deck's slides (`chart-access.mjs`). `numbers.mjs` asks portal-api, which
shows every leader only their own stewardship, and shares the answer for a minute.

## Rules the code keeps

- A deck's code never gets the manager's sign-in (`deck-origin.mjs`).
- Leaders see only their own stewardship's numbers; portal-api decides. People numbers are counts, never names.
- Only the numbers of charts written in a deck are given to its pages ("pinning", `chart-access.mjs`).
- Slidev never gets the service keys (`zone-decks.mjs slidevEnv`).
- A deck includes files only from its own folder (`gfm-addon/lib/deck-folder.mjs`).
- A failed build never takes a deck away: viewers keep the last good copy (`builds.mjs`).
- Every text a person sees is written in English here and translated by the portal's `i18n.js` from
  `portal/i18n/<language>.json` (14 languages). Deck content is never translated.

## Settings

The container's environment (`slidev-compose.yml`) sets them; each has a default (`settings.mjs`).

| Setting | Default | What it is |
|---|---|---|
| `PRESENTATION_MANAGER_PORT` | 3040 | The manager address inside the container (browsers: 3030). |
| `PRESENTATION_DECK_SERVER_PORT` | 3041 | The deck address inside the container (browsers: 8089); 0 = any free port (tests). |
| `PRESENTATIONS_DECK_PORT`, `PRESENTATIONS_PUBLIC_PORT` | 8089, 3030 | The ports browsers use. |
| `PRESENTATIONS_PORTAL_ORIGINS` | the portal on 8070 | The portal's addresses (only they may sign in and frame the pages). |
| `PRESENTATION_ACL_API_URL`, `PORTAL_SERVICE_KEY` | `http://portal-api:8091` | portal-api and the key that proves it is the manager. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | | Supabase, which checks a portal sign-in. |
| `SLIDEV_MAX_RUNNING`, `SLIDEV_IDLE_MINUTES` | 10, 40 | How many editors may run; when an unused one stops. |
| `SLIDEV_PRESTART`, `SLIDEV_ADDON_REBUILD` | on, on | `0` turns off starting an editor ahead of time / rebuilding decks after a new chart add-on. |
| `SLIDEV_BUILD_DEBOUNCE_MS`, `SLIDEV_BUILD_CONCURRENCY` | 10000, 1 | The quiet time before publishing; builds at once (at most 2). |
| `PRESENTATION_SLIDEV_HOME`, `PRESENTATION_BIND_ADDRESS` | `/slidev`, `0.0.0.0` | For the tests only: a temporary Slidev folder, and 127.0.0.1. |

## Testing

From the repository root, with Docker (the same as the updater's quick tests):

```
docker run --rm --network none -v <repo>:/repo -w /repo/slidev node:24-alpine node --test tests/*.test.mjs
```

A few tests need Slidev itself (its parser, a real `slidev build`) and are skipped there. With a copy of the live
`node_modules` volume they all run; see [`slidev/tests/README.md`](../tests/README.md). After changing a text people
see, also run the portal's checks (`node portal/tests/i18n-check.cjs`).

## Changing something

- **A route:** find it in `manager-routes.mjs` (`API_ROUTES`) or `deck-routes.mjs`. Check who is asking first
  (`access.mjs`), then do one thing.
- **A text:** write it in English, and add it to all 14 catalogs in `portal/i18n/` (German and Spanish speak
  informally: du, tú). Code-only strings go into `portal/tests/i18n-ignore.json`.
- **A chart:** `gfm-addon/lib/chart-engine.mjs`; the tests draw every series type with ECharts.
- **Deploying:** this folder is mounted read-only into the Slidev container; restart the container. A change in
  `gfm-addon/` or `vendor/` changes the add-on's fingerprint, so published decks are rebuilt by themselves (one at
  a time, a minute after the start).

Style: server files end lines with semicolons; browser files and the add-on follow Slidev's style without them.
Comments say why, not what.
