# Presentation library

The library is served at `http://localhost:3030/` and is embedded in the mission portal. Existing decks remain in the external `j5iyrpjbsssqlilqhw9axugx_slidev-data` volume.

Since round 8, published decks and the deck editor run on a second address, `http://<computer>:8089` ("the deck address"; container port 3041), where the Presentations sign-in is never accepted: a deck is page code, and Zone Leaders write decks too. The library and the editor page lead there with a deck pass for that one deck. See "The deck address" below and `docs/handoff/round8/deckorigin.md`.

Two things come from this repository and are mounted read-only over the volume:

- the whole `manager/` folder at `/slidev/manager` (`server.mjs` and the files it loads, the editor page `studio.html`, the shared browser script `portal-bridge.js`, and the `gfm-addon` Slidev addon; `manager/README.md` is a map of every file, `tests/README.md` of the tests);
- `package.json` at `/slidev/package.json`. Every dependency is pinned to the exact version installed in the volume, and `slidev.addons` turns on `slidev-addon-studio` and `/slidev/manager/gfm-addon` for every deck. The container still runs `npm install` on start; with pinned versions that match the lock file it changes nothing. To upgrade Slidev, change the versions here on purpose and recreate the service.

Apply `migrations/012_presentation_access.sql` to the Beta database, and provide the same `PORTAL_SERVICE_KEY` used by the portal API in `slidev/.env` before recreating the service. The service joins `gfm-network` through `local-override.yml`.

The manager validates the incoming Supabase user token and creates a server session that expires no later than the verified token. Every list, deck request, editing route, and management action is authorized by `http://portal-api:8091/internal/presentations/check`. The API resolves current roles and stewardship from the database. An unavailable ACL API denies access until it recovers. A positive "can manage" answer is remembered for 15 seconds per user, because the editor loads hundreds of files through that check.

APs, the President, and DAs manage decks and access. DLs, ZLs, and STLs view assigned decks. **Manage access** in a deck's actions controls eligible roles, zones, districts, and individuals. Unconfigured decks are visible to managers only. Access follows a deck when it is renamed or duplicated, and deleting a deck asks portal-api to delete its rule (`operation: 'delete'`; an older portal-api that answers 4xx is only logged).

Deploy from this directory with:

```powershell
docker compose -f slidev-compose.yml -f local-override.yml up -d --no-deps slidev
```

A plain `docker restart` is enough after changing files in `manager/`; changing mounts needs the command above.

Deploy order matters:

1. The `manager/gfm-addon` folder must exist before this `package.json` (which lists it in `slidev.addons`) is used. Without it every editor start stops at once; the editor page then says so and shows Slidev's last lines.
2. Deploy this manager (with the CORS-enabled `/api/session`) **before** the portal. A new portal shell against an old manager cannot sign the Presentations frame in.
3. When `portal/portal-enhancements.js` changes, bump its `?v=` in `portal/index.template.html`, otherwise browsers can keep running the cached old script, which no longer matches the new `index.html`.

The pre-ACL manager is preserved inside the volume at `/slidev/backups/presentation-acl-20260917/server.mjs`. Older local copies of `server.mjs` are in `backups/slidev-manager/` at the repository root (not mounted).

# Editing: Studio inside the editor page

Slidev stays the engine. The visual editor is the third-party addon [slidev-addon-studio](https://github.com/BobTheShoplifter/slidev-addon-studio) (Slides, Layout, Components, Animate and Assets panels, on-canvas drag and resize, double-click text editing). It runs inside each deck's Slidev dev server, which the manager starts on demand and proxies at `/edit/<slug>/`.

`GET /studio/<slug>` (managers only) is the editor page around it:

- **← Library** goes back to `/`. Clicking the deck title renames it.
- The status line shows whether everything is saved (Studio and Slidev's side editor write `slides.md` directly) and whether viewers see the latest version.
- **Source** opens the whole `slides.md` in Monaco (served from Slidev's own `monaco-editor` at `/vendor/monaco/vs/`, packed with gzip), and closes it again. Ctrl+S saves. Saving uses `GET/PUT /api/presentations/<slug>/source` with the `version` from GET, which is required; if it is missing, or Studio changed the file in the meantime, the save is refused with 409 and nothing is overwritten. The text stays read-only until the slides have loaded.
- **View** opens `/p/<slug>/`, publishing what is saved first when the build is older than the source (Source text the user chose not to save is not published).
- **Publish now** runs `POST /api/presentations/<slug>/publish`. A failed build returns 422 with the last lines of Slidev's output; the previous build stays live.

There are no private drafts: saved changes go live on their own. Saving never waits for a build, but while a deck is open in the editor a watcher on its folder publishes in the background once the slides have not changed for 10 seconds (`SLIDEV_BUILD_DEBOUNCE_MS`), leaving the editor publishes at once (the page sends `POST /api/presentations/<slug>/editor/leave` as it closes), and opening `/p/<slug>/` rebuilds in the background when the source is newer. **Publish now** is for publishing straight away and seeing any build problem. Builds run with `nice -n 10`, so an open editor stays quick while one runs, and one at a time for the whole manager (a build needs about 0.5 GB; `SLIDEV_BUILD_CONCURRENCY=2` allows two): builds someone waits for (a change, **Publish now**, leaving the editor, a first view) go before rebuilds after an addon change. `GET /health` shows `builds_running` and `builds_waiting`, and the log says `waiting for another presentation's build to finish`. The status line says "Publishing when you pause" while the 10 seconds run.

If the deck's Slidev dev server stops while starting (a broken add-on, theme or headmatter), `POST /api/presentations/<slug>/editor` answers 503 at once with Slidev's last output instead of waiting for the start-up timeout.

The ✎ button in published decks opens `/studio/<slug>` (the old addresses `/?edit=<slug>` and `/edit/<slug>/` on the manager address were removed in round 9).

## Opening the editor quickly

- **One Vite cache per deck.** Slidev runs "installed globally" here, so on its own it keeps one dependency cache for all decks in `@slidev/cli/node_modules/.vite`. Vite's cache key includes the deck folder, so every time a different deck was opened the cache was thrown away and rebuilt, and the editor reloaded itself halfway through loading; two open editors overwrote each other's cache. The addon's `gfm-addon:deck-cache` Vite plugin (`setup/vite-plugins.ts`, a `post` config hook that runs after Slidev's) moves the cache to `decks/<slug>/node_modules/.vite` (about 25 MB per deck). Download and Duplicate leave `node_modules` out; Rename deletes it, so the cache is rebuilt once.
- **Warm-up before "ready".** After Slidev answers, the manager loads the editor page's modules once itself (`delivery.mjs` `warmModuleGraph`: static imports and the `import()` calls the editor runs, 6 at a time, a second pass if Vite re-bundled dependencies meanwhile, never more than 60 s). Vite then has every module compiled and every dependency bundled before the browser asks, so the browser's first load is fast and does not reload itself. The cold-start safety net in the editor HTML (a single reload when UnoCSS's styles are missing) now waits 6 s instead of 15 s.
- **The loading message names the step:** "Step 1 of 3: starting the slide tools", "Step 2 of 3: getting every slide and chart ready", "Step 3 of 3: almost there". The page reads the step from `GET /api/presentations/<slug>/editor` (`{stage: 'stopped'|'starting'|'preparing'|'ready', seconds}`).
- **Started ahead of time.** When the manager starts, and when a manager opens the library, the editor of the most recently changed deck is started in the background, if fewer than two editors run (at most once a minute; `SLIDEV_PRESTART=0` turns it off).
- **Idle editors stop.** An editor nobody has used for 40 minutes (`SLIDEV_IDLE_MINUTES`) is stopped (each uses about 540 MB) and its saved changes are published. The editor page keeps its own editor in use while it is open and visible, and starts it again if it was stopped while the page was in the background.
- **Logged:** `[<slug>:edit] starting Slidev on port N (why)`, `[slidev-ready] … answering after N s`, `prepared N files (N MB) in N s`, `ready N s after start`, `stopping: not used for N min`, and for builds `built in N s; compressed …`.

## The deck address (round 8, `manager/deck-origin.mjs`)

- **Two addresses, one process.** `server.mjs` listens on 3040 (published 3030: the library, `/studio`, the API, the Whiteboard frames) and on 3041 (published 8089: `/p/<slug>/…`, `/edit/<slug>/…`, and `POST /api/charts/data` and `GET /api/mission-kpis?deck=` for a deck's own charts). Settings: `PRESENTATION_DECK_SERVER_PORT` (3041; 0 = any free port, for tests), `PRESENTATIONS_DECK_PORT` (8089) and `PRESENTATIONS_PUBLIC_PORT` (3030).
- **Deck pass.** `GET /p/<slug>/…` on 3030 checks access, sets a cookie `gfm_view_<slug>` and sends the browser on to the same path on 8089. The editor page's `POST /api/presentations/<slug>/editor` sets `gfm_edit_<slug>` and frames `http://<computer>:8089/edit/<slug>/1`. A pass is good for one deck and one mode, and short-lived (round 8 review): a view pass ends 30 minutes after its last use (an open deck page uses it every 5 minutes, `GET /api/deck-pass`, from a small script the server adds to the page); an edit pass ends 15 minutes after its last use (the `/studio` status question renews it), at once when `/studio` is left (`POST …/editor/leave` with the page's own id), and when the editor stops. Every pass ends with the sign-in (at most 12 hours). 8089 never reads `presentation_session` or a Bearer token, and never starts an editor (only `/studio` does).
- **Numbers on 8089 (round 8 review).** A deck page gets numbers only for the deck of the page that asks (its Referer; a request naming another deck is refused), with that deck's pass, and only for charts written in that deck's `slides.md` (for everyone, managers too; `chart-access.mjs` `pinnedOnly`). Key numbers only for a deck with a `<MissionKpiChart>`. The chart builder's preview asks 3030, which keeps the manager's rules.
- **Chart settings drawn on 3030 (round 8 review).** The chart builder of `/studio` and the Whiteboard frames draw charts a ZL may have written, so `manager/safe-chart-option.mjs` changes them first: tooltips are drawn as text (`renderMode: 'richText'`, tags taken out of their text, no `extraCssText`), links (`title.link/sublink`, treemap/sunburst `nodeClick: 'link'`) and the toolbox's data view are left out. These pages also carry a Content-Security-Policy with a nonce (`whiteboard-frames.mjs chartPageCsp`): only their own scripts run, never an inline handler.
- **3030 refuses deck pages.** Data routes need `X-GFM-Request` (added by `portal-bridge.js`) or a Bearer token; `Origin` on the deck port is refused everywhere; `Sec-Fetch-Site: same-site/cross-site` is refused on data routes; `/p/`, `/edit/` and `/studio/` started by another page show a confirm page instead of giving a pass. 3030's pages carry `frame-ancestors` for the portal only.
- **8089** answers changes (POST) and the editor's websocket only from its own pages, and may be framed by the portal and by 3030.
- **The editor inside `/studio`** talks to `/studio` by messages (`manager/editor-bridge.js`). `/studio` still reads and writes slides for the chart builder through 3030 (`/__slidev/slides/<n>.json`, `/@studio/deck`, named by the Referer).
- **Numbers of a zone's deck** are that zone's for everyone (portal-api `charts.deck_units`); answers are kept per deck.

## Published decks (`/p/<slug>/`)

- **Access is asked once per deck.** A deck is about 60 files; a positive access answer is remembered for 15 seconds per person and deck, so opening a deck asks portal-api once instead of about 60 times. Revoking access applies within 15 seconds.
- **Compressed.** Each build writes `.br` and `.gz` copies of its text files (only when they are smaller). The manager sends the best one the browser accepts with `Content-Encoding` and `Vary: Accept-Encoding`; the page itself (which differs per person because of the editor button) is compressed on the fly. A rebuild takes the packed copies of files that did not change from the last build (most of Slidev's own code), which saves about 3 s per build. A failed compression only costs speed. The manager's own pages, `portal-bridge.js`, Monaco and the files of the editor (Vite sends them as they are) go packed with gzip too.
- **Cached.** Files under `assets/` have a content hash in their names and are sent with `private, max-age=31536000, immutable`; everything else with `private, no-cache`.
- **No request to the internet.** Built decks, the editor, the library and the manager's pages use a small local tab icon instead of Slidev's default from `cdn.jsdelivr.net`.

## Download PDF and screen mirroring (round 6)

- **Download PDF.** Published decks include Slidev's browser exporter, `/p/<slug>/export`. Slidev's default (`browserExporter: 'dev'`) left it out of builds, so downloading worked only in the editor. The addon's preparser (`manager/gfm-addon/setup/preparser.ts`, `lib/published-deck.mjs`) turns it on in `slidev build` only, unless the deck sets `browserExporter` itself (`browserExporter: false` leaves a deck without it).
  - **Where:** the library's ⋮ **Download PDF** (everyone who sees the deck), and the PDF icon in the slide controls.
  - **How:** **PDF** opens the browser's print dialog ("Save as PDF", Background graphics on); one page per slide.
  - **Access:** the same as opening the deck, because it is a page of the deck.
  - **Not used:** `download: true` / `slidev build --download` would need playwright-chromium, which is not installed.
  - **On the office network:** the PPTX and PNG buttons on that page need screen capture, which needs a secure address; the PDF works on any address.
- **Screen mirroring** (presenter view → Screen Mirror) uses the browser's screen capture. That needs:
  - a secure address: https, or `http://localhost`;
  - `display-capture` on every frame around the deck: the portal's `#appFrame` and the editor frame in `studio.html` both allow it.
- **On plain http** (the office LAN address), the addon's panel `manager/gfm-addon/presenter/ScreenMirror.vue` says why mirroring is not available and what to do. It replaces Slidev's panel by the Vite plugin `gfm-addon:screen-mirror`, and its logic is in `lib/screen-mirror.mjs`.
- **The owner's options** (present from `http://localhost:8070` on the server computer, an Edge/Chrome policy for the two LAN addresses, or local HTTPS): `docs/handoff/round6/present.md`.

# Staying signed in

The portal never puts its token in the frame URL and never sends it by `postMessage` (deck scripts ran on this origin before round 8; they run on the deck address now, and the rule stays). Instead the portal shell (`portal/portal-enhancements.js`) calls `POST /api/session` itself with `credentials: 'include'` and `Authorization: Bearer <portal token>`:

- before it opens the Presentations frame, then every 4 minutes (sooner if the session ends earlier), when the tab becomes visible again, and whenever the frame asks with `postMessage({type: 'presentations-session-request'})`;
- it answers `{type: 'presentations-session-refreshed', expires_at}` or `{type: 'presentations-session-error', message}` to this origin only.

`/api/session` allows CORS with credentials (and answers the `OPTIONS` preflight) for:

- every origin listed in `PRESENTATIONS_PORTAL_ORIGINS`, and
- the portal on the same machine: an origin whose hostname is the one the browser used for this server and whose scheme and port appear in that list (for example `http://<any-address>:8070`). A new LAN address or a hostname therefore keeps working. A portal reached through a different hostname (a proxy) must be listed.

A refused origin is logged once (`[session] refused a sign-in from ...`), and the portal tells the user that Presentations is not set up for that portal address. When the browser already has a session cookie for the same user, the session is extended in place, so open pages and the editor's websockets keep working. A sign-in that fails with 401/403, or that belongs to a different user than the cookie, ends the cookie's session, so a shared computer never falls back to an earlier user's session; a passing outage keeps the same user's session. If the portal's sign-in before opening the frame fails, the portal also calls `/api/logout` before it opens the frame. `GET /api/session` reports the current session (`{ok, role, expires_at}`) or 401.

Pages served here load `/_manager/portal-bridge.js`: on a 401 from the API it asks the portal for a refresh, waits up to 10 seconds, and retries once; it also asks a few minutes before `expires_at`. A signed-out page navigation (for example `/studio/<slug>` or `/p/<slug>/`) gets a small page that renews the session through the portal and reloads.

# Portal sign-out

`POST /api/logout` clears the presentation server session and expires its cookie. The portal may call it with credentials and `mode: 'no-cors'` after removing its iframe. Requests must come from a portal origin accepted by `/api/session`, this server's origin, or a loopback CLI request. Logout does not require a valid session and is safe to repeat. On sign-out the portal stops its keep-alive timer and cancels a renewal that is still on its way; the server also refuses, for ten minutes, a renewal that carries a cookie ended by logout, so a late renewal cannot sign the browser back in.

# Charts in slides

The `manager/gfm-addon` Slidev addon adds two chart components to every deck: `<MissionChart>` draws a table you give it or, with `query`, numbers from the database (made with **Add chart** in the editor; see "Charts from mission numbers" below); `<MissionKpiChart>` draws one live key indicator. They use the ECharts 6.0.0 and echarts-stat 1.2.0 files kept in `manager/vendor/`; nothing is installed from npm. Both components are in Studio's **Components** panel under **Charts**. Click one to add it, then change its settings in the **Element** panel.

- **Size.** A chart fills the width it is given and is `height` slide pixels tall (360 by default; a slide is 980 wide and about 550 tall). Put it in a `two-cols` layout or a grid to place it beside text.
- **When charts draw.** A chart draws when its slide is shown. It follows dark mode and does not animate in print or PDF export (`?print`).
- **Number and date format.** Numbers and dates follow the deck's language, which is English unless the headmatter sets `htmlAttrs: { lang: de }`.
- **Trend lines.** `trend="linear"`, `polynomial` (with `degree`, 2–6), `exponential`, `logarithmic` or `moving-average` (with `window`, 2–52 points) adds a trend line for each series, worked out by echarts-stat (the moving average is a plain trailing mean). The legend names it, for example "Trend (linear)" or "Zone North trend (polynomial, degree 2)", unless `trend-label` gives it a name. It is dashed and in the series colour unless `trend-color`, `trend-style` (`solid`, `dashed`, `dotted`) or `trend-width` (0.5–8) say otherwise. `forecast="3"` carries the trend on for 3 more periods, in a shaded "Forecast" band. Trend lines apply to line, bar, area and scatter charts; a stacked chart gets one trend line through its totals. Exponential needs numbers above 0; a trend that cannot be worked out is left out.
- **Messages.** Instead of a chart, the chart area says what is missing: "Add data to show this chart.", "Add numbers above 0 to show this chart." for a pie or donut, or which row of a table has more values than headings. While the chart files load on a slow connection, it says "Loading chart…".
- **Screen readers.** Each chart is a figure named by its title (or "Bar chart" and so on), and ECharts adds a spoken description of its series and values.
- **After changing the addon.** Every build records a fingerprint of `manager/gfm-addon`, `manager/vendor` and `package.json` in `dist/.gfm-build.json` (never served). A minute after the manager starts, it rebuilds, one at a time and at low priority, every published deck built with another fingerprint, and opening an outdated deck queues its rebuild as well (behind any build someone waits for; never a second build of a deck that is already building or waiting). So after deploying a change to the addon, published decks get the new chart code on their own within a few minutes. `GET /health` shows the current fingerprint (`chart_addon`); `SLIDEV_ADDON_REBUILD=0` turns the start-up rebuild off. A deck whose rebuild fails keeps its old build and is not retried until its slides change or someone chooses **Publish now**.
- **Chart engine.** `lib/chart-engine.mjs` (round 6) draws a chart from its numbers plus an ECharts option (see "Charts as ECharts options" below); `lib/chart-core.mjs` holds the tables, numbers and trends and draws charts written with the older settings exactly as before (`buildOption`). Neither has Vue or Slidev imports, so they run in plain Node (`tests/chart-engine.test.mjs` draws every series type with the vendored ECharts in server-side mode) and in other pages. `lib/charts.ts` is the Vue side (loading the libraries, drawing, live numbers) and re-exports both.
- **Editing without flicker.** A chart draws again only when what it shows changes (its numbers, option, size, colours), a burst of changes is drawn once (70 ms), and when the editor rebuilds a slide the chart starts from what it showed and moves to the new drawing (by its `chart-id`), with the last mission numbers shown at once while newer ones load.

## Charts as ECharts options (round 6)

**Add chart** and **Edit chart** write a chart as its numbers plus an [ECharts 6 option](https://echarts.apache.org/en/option.html):

```md
<MissionChart chart-id="c4k2m9x" :query='{"audience":"deck", … ,"weeks":{"last":12}}' :option='{"title":{"text":"New people being taught"},"series":[{"type":"bar","gfm":{"trend":{"method":"linear"}}}]}' />
<MissionChart chart-id="c7p0q2a" :height="300" :rows="['From\tTo\tPeople', 'Finding\tTaught\t40', 'Taught\tBaptismal date\t12']" :option='{"series":[{"type":"sankey"}]}' />
```

- **`chart-id`** names the chart for the editor: **Edit chart** finds and changes the chart with that id, wherever the lines have moved, and never the chart beside it. A chart copied in Source keeps the id; the builder gives the one it saves a new id. Charts written before round 6 have none; they get one the first time they are saved with the builder.
- **The numbers** (`rows`, `csv`, `data` or `query`) become dataset 0; the first column holds the labels, every other column is one series. A series without `data` takes the next column, and the last one repeats for the columns after it, so `"series":[{"type":"line"}]` draws every column (also when a query brings one line per zone). Goal columns of mission numbers (and a pasted column named in `gfm.goal.column`) are drawn as the goal line. Series that need their own shape of data get it from the table: pie and funnel (the column's rows, above 0), gauge (the last value; its maximum is the next column), radar (one shape per column), heat map (rows across, columns down; on `"coordinateSystem":"calendar"` the labels are dates, on `"matrix"` names), tree, tree map and sunburst (labels with levels, `North / Frankfurt 1`), box plot (one box per column, 1.5 box lengths, unusual values as dots), candlestick (four columns: open, close, lowest, highest), sankey, chord and graph (three columns: from, to and a number), theme river, parallel (one line per row), lines (four columns: from x, from y, to x, to y) and custom (`"renderItem"` is `"waterfall"`, `"range"` or `"errorbar"`, since JSON cannot hold a function). A series with `encode` naming its columns (`{"x":"Week","y":"Goal"}`) reads just those.
- **Everything else is plain ECharts** and is passed through: every series type (line, bar, scatter, effectScatter, pictorialBar, pie, funnel, gauge, radar, heatmap, tree, treemap, sunburst, boxplot, candlestick, graph, sankey, chord, themeRiver, parallel, lines, custom), datasets and transforms (`filter`, `sort`, `boxplot`, and echarts-stat's `ecStat:regression`, `ecStat:histogram`, `ecStat:clustering`; the chart's table is dataset 0, the option's own datasets follow), dataZoom, visualMap, markLine / markArea / markPoint, toolbox, brush, timeline (with no `options`, one step per row of the table), calendar, polar, singleAxis, parallel axes, graphic, aria, the ECharts 6 matrix, thumbnail and axis breaks, rich labels, animations and universal transitions (on by default, so a change of type or numbers morphs), several grids. **Maps are not available:** they need a map file, and none is installed.
- **The mission look is laid under the option:** the mission colours (dark ones on dark slides), fonts, axes, spacing for the title, legend, zoom slider, colour scale and timeline, number formats in the deck's language, and a spoken description for screen readers. Anything the option sets wins.
- **The few GFM words** (for what JSON cannot say): `gfm.format` `{"style": "auto" | "plain" | "percent" | "compact" | "decimals", "decimals", "prefix", "suffix"}`; `gfm.kind` `"tile"` (a key number: the latest value with the change and the share of `gfm.target`) or `"multiples"` (one small chart per column on one scale); `gfm.goal` (how goal columns are drawn, and `column` for a pasted goal column); `series[i].gfm.trend` `{"method": "linear" | "polynomial" | "exponential" | "logarithmic" | "moving-average", "degree", "window", "forecast", "color", "width", "style", "label"}` (a trend line through that series and every series it is repeated for, with a shaded "Forecast" band). They never reach ECharts.
- **Older charts** (written with `type`, `trend`, `goal` and the other settings below) are drawn exactly as before: a chart is drawn from its option only when it has no `type` (or has a `chart-id`) and its option's series name their types. When the builder opens an older chart it turns its settings into the same chart as an option (`legacyToOption`) and saves it that way.
- **Studio's Element panel** lists the older settings; for a chart drawn from its option only **Title**, **Series colours** and **Height** apply (when the option has none of its own). Use **Edit chart** for everything else.

## Chart kinds, calculated fields and stories (GFM Studio)

Three attributes of `<MissionChart>` that GFM Studio's **Data** tab writes (and that anyone, or an AI, can write by hand).
They sit on top of an ordinary chart: its numbers (`rows` or `query`) and its `option` stay as they are.

**`preset`: a chart kind.** `trend`, `goal-vs-actual`, `ranked-bar`, `comparison`, `big-number`, `progress`,
`cumulative-goal`, `funnel`, `conversion-funnel`, `leaderboard`, `small-multiples` (`lib/chart-presets.mjs`), and every chart type
as a plain kind `type-<name>` (line, area, stacked-area, bar, stacked-bar, horizontal-bar, scatter, effect-scatter,
pictorial-bar, pie, donut, gauge, radar, heatmap, matrix-heatmap, calendar-heatmap, treemap, sunburst, boxplot,
candlestick, waterfall, range, errorbar, tree, graph, sankey, chord, theme-river, parallel, polar-bar). A kind
chooses the orientation, the order, the labels and the number of things shown, so the chart looks right without
settings; any ECharts `option` written in the chart is merged over it. Settings a kind reads: `presetTop` (ranked kinds,
default 12, 0 = all), `presetAggregate` (`last` or `sum`, funnels), `presetTarget` (big number). A kind that does not suit
the numbers says so in the chart instead of drawing something misleading.

**`calc`: calculated fields.** A list of `{ "name", "formula", "format", "hide" }`:

```
<MissionChart preset="ranked-bar" :rows="[…]"
  :calc='[{"name":"Successful Contact Rate","formula":"[Successfully Contacted] / [Referrals Received]","format":"percent"}]'
  :shape='{"only":["Successful Contact Rate"]}' />
```

Formulas use a field's name in `[ ]`, `+ - * / % ^`, comparisons, `AND OR NOT`, and `SUM AVG MIN MAX COUNT IF SAFE_DIVIDE
DIFFERENCE PERCENT_CHANGE CUMULATIVE_SUM MOVING_AVG LAG ROUND ABS` (`lib/formula.mjs`, which also holds the help the
editor shows). Dividing by 0 gives no number (a gap) and the editor says how many rows. A formula can only use the
numbers of its own chart, so it never shows anyone a number the chart's query did not already give them, and nothing a
writer types is run as JavaScript (it is read by a small parser and worked out by that file alone). Formats: `number`,
`percent` (a fraction shown as a percentage), `integer`, `compact`, `decimals`. A mistake in one field leaves that field
out; the chart is still drawn and the editor shows the sentence.

**`shape`: which numbers are shown.** `{ "only": [names], "hide": [names], "sort": "desc"|"asc", "top": n }`.

**`story`, `storyTransition`, `storyDuration`, `storyEasing`: a data story.** A list of steps, each a small change to the
chart (`preset`, `shape`, `calc`, `title`, `colors`, `option`, and a `label`). Step 1 is the chart with the first step on
it and every Slidev click goes to the next; the chart reserves one click per step after the first. It is one ECharts
instance for the whole story: each step is applied with `setOption`, series keep stable ids and a series that changes
kind morphs (universal transition). `storyTransition` is `morph` (default), `fade` or `none`; `storyDuration` 0 to 3000
ms (default 700); `storyEasing` one of `cubicInOut`, `cubicOut`, `linear`, `elasticOut`, `backOut` (`lib/chart-story.mjs`).
A step can never change the chart's `query`, so what a viewer is allowed to see does not change with the story.

`calc`, `preset`, `shape` and `story` are kept as they are when **Edit chart** saves the chart; Edit chart's own preview
does not draw them.

## Paste Presentation and the AI authoring spec (GFM Studio)

**The workflow.** *More ▸ Copy AI instructions* → ask ChatGPT or Claude for a presentation → copy what it writes → **Paste
presentation** (or Studio's toolbar) → **Validate** → read the outline → **Import** → keep editing visually. A whole import is
one undoable step (Ctrl+Z, or Undo in Studio's toolbar; Redo brings it back).

**What the check says** (`addons/gfm-studio/gfm/import-analyze.mjs`, with Slidev's own parser behind it: `/@studio/check`):
every slide is **green** (known GFM layouts and components, standard Markdown: fully editable in Studio), **yellow** (custom
HTML or CSS, settings Studio does not know: partly editable) or **red** (unknown components, `<script setup>`, anything it
cannot show visually: edit it in Source). Nothing is refused for being advanced. Problems are listed by slide: a tag never
closed, an unknown component or layout (with "Did you mean …?"), a chart's `option`, `calc`, `story` or `preset` that is wrong,
a picture that is not in Assets or comes from another website, a theme that is not installed. **Blocked** code (`<script>` that
loads or runs outside code, `onclick=` and other handlers, `v-html`, `javascript:` links, `<meta>`, `<base>`) is never imported.
**Auto-fix** does only the safe things and says what it did: take the text out of a code box (``` … ```), use the installed
theme, straight quotes in slide settings. **Import anyway** is offered when Slidev can load the text but something unknown
remains.

**Bringing it in** (`addons/gfm-studio/node/deck-import.ts`): *Add after the last slide*, *Insert after slide N* or *Replace the
presentation*. Only a replace takes the pasted deck's own settings (theme, fonts …); the deck keeps its title and any
deck-wide setting the paste leaves out. An added slide keeps its own settings (layout, class, background …) and drops the
deck-wide ones.

**The spec.** `manager/gfm-addon/ai/gfm-ai-spec-v1.md` (the full text), `gfm-ai-prompt.txt` (the short instructions the
button copies) and `gfm-spec.json` (what the check reads) are **made from the layouts and components themselves**:
`tools/make-ai-spec.mjs`, run after changing a layout, component, chart kind or formula function (a test fails until it is
run). The version number is in the generator (`SPEC_VERSION`).

**More ▸** Download slides.md, Download source (.zip), **Upload source…**: a `.md` goes through the same check as a paste; a
`.zip` (what Download source makes) puts its `slides.md` and `public/` pictures into the deck (`manager/source-upload.mjs`: no
code, no paths outside the deck; the old slides.md is kept as `slides.md.before-upload`).

**Performance view (managers).** Open the editor page with `?debug`: cold or warm editor, process id, memory, start-up time of
each step, cache state, the lazy Studio modules the browser loaded, chart query and draw times, the last publish of each deck
(`GET /api/presentations-diagnostics`).

**Browser checks:** `tests/e2e/studio-e2e.js` (how to run it is at its top).

## `<MissionChart>`: a chart from your own numbers

| Setting | Values | Default |
|---|---|---|
| `type` | `line`, `bar`, `area`, `scatter`, `pie`, `donut`, `gauge`, `tile` (a key number), `heatmap`, `radar`, `funnel`, `treemap`, `sunburst`, `boxplot`, `waterfall` | `line` |
| `title` | text above the chart | none |
| `rows` | the table, one row per entry (see below) | none |
| `csv` | the table as text (see below) | none |
| `data` | the same table as an object (see below) | none |
| `trend` | `none`, `linear`, `polynomial`, `exponential`, `logarithmic`, `moving-average` | `none` |
| `degree` | 2–6, for `polynomial` | 2 |
| `trend-color` | the trend line's colour | the series colour |
| `colors` | series colours, e.g. `:colors="['#00869e', '#d96b2b']"` | mission palette |
| `show-values` | write the numbers on the chart | off |
| `height` | slide pixels | 360 |
| `max` | gauge maximum; radar maximum for every spoke | gauge: the table's second column, otherwise 100; radar: a round number above the highest value |

**More settings.** Studio lists these after the everyday ones, marked "More". All are off or empty by default, so a chart without them looks exactly as before.

| Setting | What it does |
|---|---|
| `trend-style`, `trend-width`, `trend-label` | the trend line's pattern (`dashed`, `dotted`, `solid`; default dashed), width (0.5–8; default 2) and name in the legend |
| `window` | points in a moving average (2–52; default 3) |
| `forecast` | periods to carry the trend on (0–52; needs a trend). Numbers and dates in the first column continue with the same step; other labels become +1, +2 … |
| `goal`, `goal-color` | the heading of a column to draw as the goal line (as in live charts), and its colour |
| `target`, `target-label`, `target-color` | a straight line at a number (for example a goal of 30), its name ("Target" when none is written; the builder writes "Goal") and colour; the axis grows to show it |
| `average`, `average-color` | an average line for each series, and its colour |
| `legend` | `auto` (when there is more than one entry), `top`, `bottom`, `right`, `none` |
| `x-title`, `y-title` | axis titles |
| `y-min`, `y-max` | the value axis's lowest and highest number |
| `label-rotate` | turn the labels under the chart (−90 to 90 degrees) |
| `format`, `decimals`, `prefix`, `suffix` | numbers as `auto` (as before), `plain`, `percent` (the table holds 45 for 45 %), `compact` (1.2K) or `decimals`; how many decimals (0–4); text before (`€`) or after (` people`) every number |
| `value-position` | where `show-values` writes the numbers: `auto`, `top`, `inside`, `bottom` |
| `stack` | stack the bars or areas (one trend line through the totals) |
| `horizontal` | horizontal bars |
| `smooth` | smooth lines |
| `series-types` | one type per column for combined charts, e.g. `:series-types="['bar', 'line']"` |
| `multiples` | one small chart per column, side by side on the same scale |
| `data-zoom` | a zoom slider under the chart (not in print) |
| `option` | advanced: ECharts settings as an object or JSON text, merged over the chart last. Not shown in Studio; use Source. Objects merge key by key, a list of objects merges item by item (`series: [{ "smooth": true }]` changes the first series), `null` removes a setting. `__proto__`, `constructor` and `prototype` keys are dropped; at most 12 levels and 2000 entries. If it cannot be read, the chart is drawn without it and the browser console says why. |

**The new chart types** read the same table:

- `tile`: the latest value of the first column, large, with the change from the row before, the share of the goal (the second column or `target`) and a small line of every row underneath.
- `heatmap`: one row of cells per column, one column of cells per row of the table; darker is more.
- `radar`: one spoke per row, one shape per column.
- `funnel`: the rows from top to bottom in the table's order, first column only.
- `treemap`, `sunburst`: the first column's labels with levels, `Zone / District` (also `>` or `›`); a level's size is the sum below it.
- `boxplot`: one box per column, the spread of its rows (quartiles as spreadsheets' QUARTILE.INC; points beyond 1.5 box lengths are drawn as unusual values).
- `waterfall`: the first row is where it starts (for example last month's number), every other row a change (+ or −) from the running total; a last "Total" bar shows where it ends. Rises use the first colour, falls the second, the start and the total the third.

`slidev/showcase/chart-gallery` shows every type and most settings with sample figures (see "Chart gallery deck" below).

**The table.** The first row holds the headings, the first column holds the labels (x axis, or slices), and every other column is one series. There are three ways to give it:

- **`csv`, in Source.** Copy the cells from a spreadsheet and paste them over several lines. Columns may be separated by tabs, commas or semicolons, or by two or more spaces when you type the table yourself. On one line, put `;` between rows.
- **`rows`, in Studio.** Charts added from Studio's Components panel keep one table row per entry, `:rows="['Week, Friends', 'Aug 3, 12']"`. The **Data** setting shows one box per row: type a row with commas, or paste one spreadsheet row into each box. **Add** makes a new row. When a chart has both, `rows` is used once it holds a heading row and one data row.
- **`data`,** an object (see the example below).

Studio's settings show `rows` but not `csv`, because a one-line box would join the lines of a pasted table. To change a `csv` table, use **Source** or the **Markdown** box at the bottom of the Element panel.

**Numbers.** Write `12.5`, `1234`, or `45%`. Empty cells leave a gap.

- **Commas.** In a table with commas between columns, a decimal comma or thousands comma starts a new cell. Write `12.5` and `1234`, or put the number in quotes (`"12,5"`). Otherwise the chart says which row has too many values.
- **Tabs or semicolons.** In a table with tabs or semicolons between columns, `12,5`, `1.234,5` and `1,234.5` also work.
- **`1.234` and `1,234`.** A dot or comma followed by exactly three digits is read the way the deck's language writes numbers. In English, `1,234` is one thousand two hundred thirty-four and `1.234` is one point two three four. In German (`htmlAttrs: { lang: de }`) it is the other way round. If another number in the same column shows the decimal mark (`12.5` or `12,5`), that wins.

A line chart with a linear trend, on one line:

```md
<MissionChart type="line" title="New people being taught" trend="linear" csv="Week,New people being taught; Aug 3,12; Aug 10,15; Aug 17,14; Aug 24,19; Aug 31,22" />
```

The same chart as Studio writes it, with one row per entry:

```md
<MissionChart type="line" title="New people being taught" trend="linear" :rows="['Week, New people being taught', 'Aug 3, 12', 'Aug 10, 15', 'Aug 17, 14', 'Aug 24, 19', 'Aug 31, 22']" />
```

A bar chart with two series pasted from a spreadsheet, a polynomial trend and the values shown:

```md
<MissionChart type="bar" title="Baptismal dates" trend="polynomial" :degree="2" show-values csv="
Week	Zone North	Zone South
Jul 6	4	3
Jul 13	6	4
Jul 20	5	6
Jul 27	8	5
Aug 3	9	7
" />
```

A pie or donut uses the first series and draws only numbers above 0. With `show-values`, each slice also shows its number and share:

```md
<MissionChart type="pie" title="New people being taught, by source" csv="Source,Friends; Members,18; Online,9; Finding,12; Service,5" />
<MissionChart type="donut" title="Baptisms by zone" show-values csv="Zone,Baptisms; North,7; South,5; East,9" />
```

A gauge shows the last row's first value. Its maximum is `max`, or the row's second value (a goal), or 100:

```md
<MissionChart type="gauge" title="Sacrament attendance" :height="300" csv="Measure,Actual,Goal; This week,412,450" />
```

A scatter chart with numbers in the first column gets a numeric x axis:

```md
<MissionChart type="scatter" title="Lessons and baptismal dates" trend="linear" csv="Lessons,Baptismal dates; 20,2; 35,4; 28,3; 50,7; 44,5; 61,8" />
```

The same table can be given as an object instead of `csv`:

```md
<MissionChart type="bar" title="By quarter" :data="{ labels: ['Q1', 'Q2', 'Q3'], series: { North: [4, 6, 9], South: [3, 5, 4] } }" />
```

**As a code block.** A fenced block whose language is `chart` becomes a `<MissionChart>`. The words after `chart` are its settings, and the lines inside are the table:

````md
```chart type=area trend=polynomial degree=3 title="Members at lessons"
Week,Members at lessons
Jul 19,81
Jul 26,86
Aug 2,84
Aug 9,90
Aug 16,97
```
````

The block understands every setting above, written with dashes or in camelCase (`trend-color=#d96b2b` or `trendColor=#d96b2b`). Switches (`show-values`, `stack`, `horizontal`, `smooth`, `average`, `multiples`, `data-zoom`) are on when written alone or as `=true`. Lists have commas between the entries (`colors=#00869e,#d96b2b`, `series-types=bar,line`). `option` is JSON in single quotes: `option='{"yAxis":{"min":0}}'`. A number setting that is not a number is left out. Values containing spaces need quotes. Studio shows the block as one chart that can be moved and resized. To change the numbers, use **Source**, or the raw Markdown in the Element panel.

## Charts from mission numbers (the database)

A `<MissionChart>` can take its numbers straight from the database instead of a table: the key indicators, lessons and plans of Call-ins, and counts of the people on the weekly plans (new members, friends with a baptismal date, high-potential friends), for the mission or per zone, district or area, week by week. The numbers load when the slide is shown, so a published deck always has the latest weeks. Every look setting above works the same.

**Make one with the chart builder** (managers, in the editor `/studio/<deck>`): **Add chart** in the top bar adds a new chart; **Edit chart** appears when a chart is selected on the slide and changes it. The dialog has two panes: the live preview on the left (drawn by the same chart engine as the slides, with "Charts show totals only, never names or notes." under it) and the settings on the right, in four tabs. On a phone it fills the screen, with the preview on top and the tabs below. There are no ready-made charts: a new chart starts as New people being taught, week by week, with the goal set the week before, and everything is changed from there. **Undo** and **Redo** (the arrows in the header, or Ctrl+Z and Ctrl+Y) go back and forth through every change made in the dialog. **Close** (or Esc) on a chart with changes asks once before throwing them away.

- **Numbers**: *What would you like to show?* **Mission numbers**, **Paste a table** (cells copied from a spreadsheet, shown as a grid) or **Type the numbers** (a grid of boxes, with Add a row / Add a column). For mission numbers: **Which key indicator?** (the six; **Other numbers** opens every number: lessons, plans, and counts of new members, friends with a baptismal date and high-potential friends), **Compare with** (only the goals the chosen numbers have: goal set the week before, next week's goal, or nothing), **For** (the mission, each zone, district or area) and **Which** zones, districts or areas, **Show** (week by week or one bar per unit, with **Order** and **How many**), **As** (the numbers, % of goal, a running total, an average of 4 weeks, per area), **Weeks** (chips or any number up to 104, the current week on or off) and **Who sees what** (everyone who can open the presentation sees the same numbers, or each leader sees only their own stewardship; district and area charts default to stewardship). The title follows these choices until you type your own.
- **Chart type**: 34 kinds covering every ECharts series type, in four groups: *Everyday* (bars, line, area, pie, donut, key number, gauge), *Compare* (stacked bars, sideways bars, bars and a line, picture bars, round bars, rose, radar, funnel, small charts), *Spread and time* (dots, pulsing dots, heat map, calendar, theme river, box plot, candlestick, ranges, waterfall, play through) and *Parts and flows* (tree map, sunburst, tree, flow, chord, network, parallel lines, lines between points). A hint says what a kind needs from the table (for example "Three columns: from, to and a number."). Changing the type keeps the title, colours, legend, tools and animation, and for charts on axes the axes, labels, reference lines and trend line.
- **Settings**, in groups that open and close: **Title** (and a line under it); **Series** (how each column is drawn: bars, line, area, dots or picture bars; smooth lines, stacking, dots on lines, steps, line width, bar width, a track behind bars, bars sorted as they change; for other kinds their own choices, such as rose slices, the funnel's order, the network's layout, the tree's direction or the timeline's play settings); **Axes** (titles, lowest and highest number, turned labels, how many lines, a logarithmic scale, grid lines, upside down, always the last label); **Labels** (numbers on the chart, where, size, counting up, the name at the end of a line); **Legend** (automatic, top, bottom, right, left, none); **Tooltip** (on or off, for one point or every series, the pointer, the order); **Colours** (mission, warm, cool or calm, a colour for each series, patterns for colour-blind readers); **Trend line** (off, straight, curved, growing, levelling off, moving average; how curved, the window, carried on as a forecast, width, colour, dashes, its name); **Reference lines** (the goal line's colour, **A line at this number** named "Goal" unless you name it, an average line, the highest and lowest marked, a shaded band); **Zoom and tools** (a zoom slider, zoom with the wheel, buttons to save a picture, show the numbers as a table, switch between lines and bars, go back to the start, and a box to pick out points); **Colour by value** (a smooth scale or steps, its colours and range); **Animation** (on or off, how long, its style, changes, morphing between chart types); **Numbers** (automatic, whole, percent, short, fixed decimals, text before and after); **Size** (the height).
- **All options**: the whole chart as ECharts JSON in a code editor that offers ECharts' names as you type (Ctrl+Space lists them, with a note for each) and underlines what ECharts does not know. Mistakes are listed under it and the preview keeps the last good chart; a chart with a mistake cannot be saved. **Tidy the layout**, **Copy the slide tag**, and the exact tag the slide gets. The form and the JSON are the same chart: a change in one shows in the other.

**Insert chart** puts it on the current slide (after the selected element) or on a new slide after it (the choice beside the button). **Update chart** reads the slide again, finds the chart by its `chart-id` (older charts without one: by their lines and Studio's fingerprint of the tag, as before, refusing when the lines changed) and replaces only that chart's tag, keeping everything around it. After saving, the editor selects that chart again on the slide. The builder writes through the same slide API Studio uses, so the slide redraws at once and the change is saved to `slides.md` like any Studio edit. A `<MissionKpiChart>` or an older `<MissionChart>` opened with **Edit chart** is saved as the same chart written as an option. When numbers cannot load it says "The numbers could not load. Try again in a minute."; weeks without plans say "No numbers for these weeks yet."

**The editor keeps a chart selected.** When the slide is rebuilt after a change, Studio re-finds its selection by picking the nearest element of the same kind, which can be the other chart on the slide. When the selection moves off a chart that way, without a click or key from you, the editor selects your chart again (by its `chart-id`).

**What the builder writes** (the query and the option are plain JSON in single quotes; keep them that way when editing by hand, so leaders who view the deck see the chart):

```md
<MissionChart chart-id="c4k2m9x" :query='{"audience":"deck","by":"week","filter":{},"includeCurrent":true,"level":"mission","measures":["friends_found.actual","friends_found.previous_goal"],"sort":"none","top":0,"transform":"none","v":1,"weeks":{"last":12}}' :option='{"title":{"text":"New people being taught"},"series":[{"type":"bar","gfm":{"trend":{"method":"linear"}}}]}' />
```

A shorter query works too; missing settings take their defaults: `:query='{"measures":["sacrament_attendance.actual"],"level":"zone","by":"unit","weeks":4}'`. In a chart block write `query='{…}'`.

| Query setting | Values | Default |
|---|---|---|
| `measures` | 1–8 numbers, e.g. `friends_found.actual` (new people being taught), `friends_found.previous_goal` (the goal set the week before), `friends_found.goal` (next week's goal, set on the same plan). The six key indicators (`friends_found` = New people being taught, `baptisms_confirmations`, `baptismal_dates`, `sacrament_attendance`, `members_at_lessons`, `new_member_sacrament`); `first_time_sacrament.actual`, `lessons_with_friends.actual`/`.goal`, `follow_up_lessons.actual`/`.goal`; `plans.started`, `plans.submitted`; `new_members.total`, `.at_church`, `.temple_recommend`, `.calling`, `.aaronic_priesthood`, `.melchizedek_priesthood`, `.ministering`, `.with_minister`, `.visited_temple`, `.reading`, `.praying`, `.member_involvement`, `.discussed_in_gemiko`; `baptismal_date_friends.total`, `.next_4_weeks`, `.at_church`, `.reading`, `.praying`, `.keeping_commandments`, `.member_involvement`; `high_potentials.total`, `.at_church` | – |
| `level` | `mission`, `zone`, `district`, `area` | `mission` |
| `filter` | `{"zones": [ids], "districts": [ids], "areas": [ids]}` (levels at or above the chart's) | everything |
| `weeks` | `{"last": 1–104}` (or just a number) | 12 |
| `includeCurrent` | include the current reporting week, whose plans may still change | `true` |
| `by` | `week` (one line per unit and number; at most 40 lines) or `unit` (one bar per unit, the weeks added up) | `week` |
| `transform` | `none`, `pct_of_goal` (each number against its goal, with a goal line at 100 %; only weeks that had a goal count, also when the weeks are added up per unit), `cumulative`, `rolling4` (these two by week only), `per_area` (divided by the areas with a plan that week) | `none` |
| `sort`, `top` | `none`, `desc` or `asc`, and 0–50 (by unit only) | `none`, 0 |
| `audience` | `deck`: everyone sees the same numbers; `stewardship`: each leader sees only their own zone, district or areas | `deck` for mission and zone, `stewardship` for district and area |

**Who sees what.**
- Managers (AP, President, Data Analyst, also as an additional role) may ask for any chart; the builder's preview uses the same route.
- DLs, ZLs and STLs see a database chart only in a deck they may open, and only when its query is written in that deck's `slides.md` ("pinned"). The manager compares the query's canonical form (sorted keys, defaults filled in, SHA-256) with every `query` in the file, which it reads again whenever the file changes. Removing a chart from the slides ends it at once. A query written as a JavaScript expression with variables cannot be pinned; in the editor such a chart warns in the browser console.
- With `audience: stewardship` a DL sees their district and its areas, and a ZL or STL their zone. A chart whose level is wider than someone's stewardship shows their own units one level down (a zone chart shows a DL their district, never part of a zone under the zone's name). Managers see the whole mission.
- People numbers are counts only, never names or notes. Per area, a count below 3 is hidden, and so is a yes-count unless at least 3 answered yes and at least 3 did not; the chart then says "Numbers below 3 are hidden to protect privacy." District, zone and mission totals are not hidden.

**Data route.** `POST /api/charts/data` `{deck, spec}` at the server root (like `/api/mission-kpis`) answers `{table: {labels, series: [{name, values, role?}]}, meta: {level, by, audience, unit, weeks, suppressed, stewardship, pinned, hash, generated_at}}`. The page and the manager share each answer for a minute (per mission and query; per person for `stewardship`) and never remember a failure. `GET /api/charts/catalog` (managers, five minutes) lists the numbers, zones, districts, areas and weeks for the builder. Both call portal-api (`/internal/presentations/chart-data` and `/internal/presentations/chart-catalog`, in `portal-api/charts.py`), which builds the SQL from a whitelist and runs it read-only as `gfm_dashboard_reader` over the `dashboards` views of migrations 018 and 025. Messages: "Loading mission numbers…", "The numbers could not load. Try again in a minute.", "No numbers for these weeks yet.", "This chart is not part of the presentation, so its numbers are not shown.", "There are no numbers for your stewardship in this chart.", and a sentence for a mistake in the query.

**Builder files.** `manager/chart-builder.mjs` (the dialog), `gfm-addon/lib/chart-builder-core.mjs` (reading and writing chart tags, chart-ids, the chart types), `gfm-addon/lib/chart-engine.mjs` (drawing), `gfm-addon/lib/chart-schema.mjs` (the ECharts option schema for All options), `gfm-addon/lib/chart-spec.mjs` (the query's rules, the same as in `charts.py`; shared test vectors in `tests/fixtures/chart-spec-vectors.json`) and `manager/chart-access.mjs` (pinning, shared answers). The manager serves the builder, the chart engine, the schema and the chart libraries at `/_manager/chart/` (code only, gzipped, checked again with an ETag).

## `<MissionKpiChart>`: live mission numbers

This chart shows one of the six key indicators, week by week, as mission totals from Call-ins. The numbers load when the slide is shown, so a published deck always has the latest weeks. Each week's goal is the goal set the week before, as in Call-ins.

| Setting | Values | Default |
|---|---|---|
| `kpi` | `New people being taught`, `Baptisms and confirmations`, `Baptismal dates`, `Sacrament attendance`, `Members at lessons`, `New member sacrament attendance` (or the ids `friends_found`, `baptisms_confirmations`, `baptismal_dates`, `sacrament_attendance`, `members_at_lessons`, `new_member_sacrament`). Decks written before the rename keep working with `Friends found`. | `New people being taught` |
| `weeks` | 1–104 | 12 |
| `chart` | `bar`, `line`, `area`, `tile` (the latest week as one big number, with the change from the week before, the share of the goal and a small line of the weeks) | `bar` |
| `show-goal` | show the goal line (`:show-goal="false"` hides it) | on |
| `trend` | `linear`, `polynomial`, `exponential`, `logarithmic`, `moving-average`, `none` | `linear` |
| `degree` | 2–6, for `polynomial` | 2 |
| `trend-color` | the trend line's colour | the bar or line colour |
| `colors` | the bar or line colour (the first entry; a second entry colours the goal line) | mission palette |
| `goal-color` | the goal line's colour | the palette's second colour |
| `title` | text above the chart | the indicator's name |
| `height` | slide pixels | 360 |
| `show-values` | write the numbers on the chart | off |

The "More" settings of `<MissionChart>` work here too: `trend-style`, `trend-width`, `trend-label`, `window`, `forecast` (labelled with the Sundays that follow), `target`, `target-label`, `target-color`, `average`, `average-color`, `legend`, `y-min`, `y-max`, `smooth`, `value-position`, `data-zoom` and `option`.

```md
<MissionKpiChart kpi="New people being taught" :weeks="12" />
<MissionKpiChart kpi="Sacrament attendance" :weeks="26" chart="line" trend="polynomial" :degree="3" trend-color="#d96b2b" :forecast="4" />
<MissionKpiChart kpi="Baptismal dates" chart="tile" :height="220" />
```

The most recent week is the current reporting week, as in Call-ins. Its numbers may still grow while reports come in.

While the numbers load, the chart area says "Loading mission numbers…". If they cannot be loaded (signed out, portal-api down), it says "The numbers could not load. Try again in a minute." If no weeks have been reported yet, it says "No numbers for these weeks yet."

**Data route.** The charts call `GET /api/mission-kpis?weeks=N&deck=<slug>` (N from 1 to 104, 12 by default) at the server root, not under `/edit/<slug>/` or `/p/<slug>/`, so the editor's Referer routing never sends it to a Slidev instance. Since round 8 decks run on the deck address, where the route needs that deck's pass (older builds name the deck only in the Referer), and a zone's deck gets that zone's totals. The manager address (3030) no longer has this route (round 9: no page there used it). It calls portal-api's `POST /internal/presentations/kpis` with the service key and answers `{"weeks": [...]}`, oldest week first:

```json
{"weeks": [{"week": "2026-09-20", "friends_found": {"actual": 42, "goal": 45}, "baptisms_confirmations": {"actual": 6, "goal": 7}, "...": "all six indicators"}]}
```

`goal` is `null` when the week before has no row. The mission totals count a goal nobody set as `0`, so the chart leaves weeks with a goal of `0` out of the goal line. Every live chart in a page asks once for 104 weeks (the most any chart shows) and keeps the most recent `weeks` of the answer, so a deck with charts of 12, 16 and 26 weeks makes one request instead of three; the page keeps the answer for a minute. The manager shares answers for 60 seconds per mission and week count, and a failure is not remembered. Errors: 400 for a bad `weeks`, 401 without a session, 403 for other roles and for leaders with no deck, and 503 with "The numbers could not load. Try again in a minute." when portal-api fails. A deck downloaded and opened elsewhere shows that message instead of numbers.

# Showcase deck

`showcase/mission-charts/` is a finished 17-slide deck, "Mission charts", that shows what the chart components can do. It is meant for the President, the APs and the data office, and doubles as a template.

- **Slides:** a cover, the six key indicators at a glance, one live slide each for sacrament attendance, new people being taught, baptismal dates, members at lessons and new members at sacrament meeting, a part-two divider, a pasted-table chart, a donut and a gauge, a part-three divider "Straight from our plans", four slides of charts from the database (zones side by side with % of goal; a heat map of every zone and week and a key number; new members and friends with a baptismal date with a three-week average; new people being taught per area for each leader's own stewardship), "Make your own chart" with Add chart, and a closing slide. Every slide has speaker notes; the presenter view (`/p/mission-charts/presenter/1`, or the presenter button in the slide controls) shows them.
- **Live and sample numbers:** slides 2–7 use `<MissionKpiChart>`, so they need migration 018 and portal-api's `/internal/presentations/kpis` (otherwise they say "The numbers could not load. Try again in a minute."). Slides 12–15 use `<MissionChart :query>`, so they need migration 025 and portal-api's `charts.py`. Slides 9–10 use made-up figures and say "sample figures" on the slide.
- **Files:** `slides.md` and `public/cover.svg`. The deck uses Slidev's own layouts, UnoCSS classes and system fonts (`fonts.provider: none`), so it loads nothing from the internet. It follows light and dark mode.

The repository copy is not mounted. Install it once into the decks volume; after that it is an ordinary deck, and changes made in Studio are not copied back to the repository.

**Install (PowerShell, from the repository root):**

1. Check that the name is free. `mission-charts` must not be listed:
   ```powershell
   docker exec slidev-j5iyrpjbsssqlilqhw9axugx ls /slidev/decks
   ```
   If it is listed, stop: `docker cp` would put the copy inside the existing folder.
2. Copy the folder. The folder name is the deck's address, `/p/mission-charts/`:
   ```powershell
   docker cp slidev/showcase/mission-charts slidev-j5iyrpjbsssqlilqhw9axugx:/slidev/decks/mission-charts
   ```
3. Publish it through the manager, signed in to the portal as an AP, the President or a Data Admin. Either open **Presentations** and click **Mission charts** (the first visit builds it and waits about 20 seconds), or choose **⋮ → Edit → Publish now**. Both build into a temporary folder and only then replace `dist/`. **Publish now** also shows Slidev's messages if the build fails.
4. Only if the manager cannot be used, build it the same way from the command line:
   ```powershell
   docker exec slidev-j5iyrpjbsssqlilqhw9axugx sh -ec 'cd /slidev; d=/slidev/decks/mission-charts; rm -rf $d/.dist-building-manual; node_modules/.bin/slidev build $d/slides.md --out $d/.dist-building-manual --base /p/mission-charts/; if [ -d $d/dist ]; then mv $d/dist $d/.dist-old-manual; fi; mv $d/.dist-building-manual $d/dist; rm -rf $d/.dist-old-manual'
   ```
5. Check: `docker exec slidev-j5iyrpjbsssqlilqhw9axugx ls /slidev/decks/mission-charts/dist` lists `index.html`, and the deck opens in Presentations.

**Who sees it:** a deck copied in this way has no access rule, so it is visible to managers only (AP, President, Data Analyst). To show it to DLs, ZLs or STLs, use **⋮ → Manage access**. Anyone who may open it sees the live mission-wide totals on slides 2–7 and 12–14; slide 15 shows each leader only their own stewardship.

**Updating it from the repository later** overwrites changes made in Studio. Copy the folder's contents (note the `/.`), then choose **Publish now**. `docker cp` keeps the files' modification times from Windows, so the manager may not notice the change on its own:
```powershell
docker cp slidev/showcase/mission-charts/. slidev-j5iyrpjbsssqlilqhw9axugx:/slidev/decks/mission-charts/
```

**Removing it:** **⋮ → Delete** in the library (asks first and removes the folder), or `docker exec slidev-j5iyrpjbsssqlilqhw9axugx rm -rf /slidev/decks/mission-charts`.

## Chart gallery deck

`showcase/chart-gallery/` is an 11-slide deck, "Chart gallery", with sample figures only (no live numbers, so it works without portal-api): trend colour, style, name and forecast with a target line; stacked and horizontal bars; bars and a line together with the goal and average lines; three key numbers; heat map and radar; funnel and waterfall; tree map and sunburst; box plot and small charts; percentages, axis titles, a zoom slider and a moving average; and the chart block in Source. Each slide names the settings it uses, so it doubles as a copy-and-paste reference.

Install it like the showcase deck, under its own name (`chart-gallery` must not be listed first):

```powershell
docker exec slidev-j5iyrpjbsssqlilqhw9axugx ls /slidev/decks
docker cp slidev/showcase/chart-gallery slidev-j5iyrpjbsssqlilqhw9axugx:/slidev/decks/chart-gallery
```

Then open it in Presentations (the first visit builds it). It is visible to managers only until **⋮ → Manage access** says otherwise.

## Mission Dashboard deck (the portal's Dashboards button)

`showcase/mission-dashboard/` is the deck the portal's **Dashboards** button opens (round 4; it replaced Grafana there). It is installed once as the live deck folder `mission-dashboard`, so its address is `/p/mission-dashboard/`, and the portal shows it inside the Dashboards tab after signing the frame in to Presentations, like the Presentations page. Every chart is a `<MissionChart :query>` (charts from the database) and loads the latest numbers when its slide is shown.

- **Slides (13):** this week at a glance (six key number tiles with a line of 12 weeks, New people being taught first, each against the goal set the week before); one slide per key indicator (26 weeks, the goal line, a straight or curved trend and one sentence of what to look at); zones against their own goals (last week, % of goal) and a heat map of zones by week; new members on the covenant path and friends preparing for baptism (count-only tiles); districts to help first (the 8 lowest by % of goal over 4 weeks, each leader sees only their own stewardship); and how to change the dashboard.
- **Finished weeks only** (`"includeCurrent": false`): the week still being reported would pull every trend line down at the start of the week. "This week" on the first slide is the last finished week.
- **Files:** `slides.md`; `style.css` (tiles, the calm colour around the slide, and on a phone held upright a note: tap full screen, then turn the phone sideways, or on an iPhone, which cannot go full screen, use a computer or tablet); `global-bottom.vue` (the slide number); `setup/main.ts` (inside the portal it follows the portal's light or dark theme: the shell sends `portal-theme` when the frame loads and when the theme changes, and answers `portal-theme-request`).
- **Who sees it:** managers only (AP, President, Data Analyst), because it has **no access rule**. Leave it that way: do not use **Manage access** on it. The Dashboards button is shown to managers only as well. It keeps its name too: the button opens the folder `mission-dashboard` by name, so the manager refuses **Rename** and **Delete** for it (`manager/protected-decks.mjs`; the library shows why in the ⋮ menu). Use **Duplicate** to experiment.
- **Editing:** like any deck (`/studio/mission-dashboard`, or **E** / ✎ in the deck). Click a chart and choose **Edit chart**; the charts are written so the builder opens them with nothing lost (`tests/mission-dashboard.test.mjs`). The repository copy is not mounted: changes made in Studio stay in the live deck.
- **Checks:** `tests/mission-dashboard.test.mjs` and `tests/protected-decks.test.mjs` (node), `portal-api/tests/dashboard_deck_db.py` (every chart through `charts.py` on a database copy: answers for an AP, refused for DL/ZL/STL), `tests/dashboard-deck/chain-check.mjs` (the same through a throw-away manager and portal-api) and `tests/dashboard-deck/edge_dashboard_deck.ps1` (headless Edge, every slide at 1366×768 and 390×844, light and dark).

**Install (PowerShell, from the repository root):** check that `mission-dashboard` is not listed and has no access rule, copy the folder, then publish it:
```powershell
docker exec slidev-j5iyrpjbsssqlilqhw9axugx ls /slidev/decks
docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -At -c "BEGIN READ ONLY; SELECT count(*) FROM portal.presentation_access WHERE deck_slug='mission-dashboard'; ROLLBACK;"
docker cp slidev/showcase/mission-dashboard slidev-j5iyrpjbsssqlilqhw9axugx:/slidev/decks/mission-dashboard
```
Publish it as a manager: open **Presentations** and click **Mission Dashboard** (the first view builds it, about 15 seconds), or **⋮ → Edit → Publish now**. Updating it from the repository later works like the showcase deck (`docker cp slidev/showcase/mission-dashboard/. …:/slidev/decks/mission-dashboard/`, then **Publish now**) and overwrites changes made in Studio.
