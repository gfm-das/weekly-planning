# GFM Presentations V2: audit (before building)

Worktree `..\gfm-worktrees\presentations-v2`, branch `feat/presentations-v2`. Nothing changed yet except this file.

## What exists today

| Question | Answer |
|---|---|
| Manager entry point | `slidev/manager/server.mjs`: two listeners, **manager address** (3040 inside, browsers 3030: library, `/studio/`, `/api/`) and **deck address** (3041 / 8089: published decks, which run deck code). |
| Routes | `manager-routes.mjs`: `routeManagerRequest` (pages) and `API_ROUTES` (a list of `[method, regex, handler]`). Adding `/studio-v2/`, `/p-v2/` and `/api/presentations-v2/...` means adding lines there. |
| Sign-in | `authenticatedContext(req)` (session cookie from the portal bridge, 12 h) gives `{user_id, mission_id}`. |
| Access checks | `access.mjs`, which asks portal-api `/internal/presentations/check`: `presentationAccess(ctx, slug)` (may open), `assertDeckEditor` (may change), `assertDeckCreator`, `assertPresentationManager`. Rules: managers all; ZL/STL their zone's decks; DL only decks shared with them. |
| Chart data API | `POST /api/charts/data {deck, spec}` -> `numbers.mjs chartData` -> `chart-access.mjs chartRequest` -> portal-api `/internal/presentations/chart-data` (`portal-api/charts.py`). |
| Query schema | `gfm-addon/lib/chart-spec.mjs normalizeSpec`: `{v, measures:['friends_found.actual'], level: mission/zone/district/area, by: week/unit, filter, weeks:{last}, transform, sort, top, audience}`. Python twin in `charts.py`. |
| Answer shape | `{table:{labels, series:[...]}, meta:{level, weeks, units, suppressed, stewardship, ...}}`. |
| Stewardship + suppression | **Server side, in portal-api** (`charts.py deck_units`, `leader_units`; people counts under 3 per area are hidden, migration 025). The browser's scope is never trusted. |
| Pinning | A non-manager gets numbers only for a query written in the deck (`PinIndex` reads `slides.md`). A V2 deck has no `slides.md`, so V2 needs its own pin set read from `deck.json`. |
| ECharts safety | `safe-chart-option.mjs safeChartOption()`: tooltips as plain text, no data view, no links. Needed on the manager address, where the sign-in lives. |
| Where decks live | `/slidev/decks/<slug>/` in the Docker volume `slidev-data` (`DECKS_DIR` in `settings.mjs`). Manager code is mounted read-only from `slidev/manager`. |
| Container | `node:24-alpine`, runs `npm install` then `npm start`. Only `manager/` and `package.json` come from the repo. |

## Assumptions that failed or need a decision

1. **ASSUMPTION FAILED: referral data.** No referral measures exist in the chart API. `charts.py MEASURES` has the six key indicators (+ goals), plan counts (started/submitted), and people counts (new members, baptismal-date friends, high potentials). Referrals are only in roster-importer uploads.
   *Smallest change:* build the demo on the existing measures (e.g. `friends_found.actual`, `baptismal_dates.actual`, `sacrament_attendance.actual`), and compute the calculated field from them (e.g. Date rate = baptismal_dates / friends_found). A referral source would be a separate, database-reviewed step.
2. **Trust boundary.** Slidev decks run on the separate deck address because their code is not trusted. A V2 deck is data (JSON), not code, so the V2 pages can be served by the manager address if the runtime never inserts deck text as HTML (text via `textContent`, images only from the deck's own assets, CSP with scripts from self only, charts through `safeChartOption`). GrapesJS stores HTML, so the saved format must be the structured component JSON from the sprint prompt, not raw HTML.
3. **Where V2 code is built.** The container has no build step for the SPA. Plan: build the Vite app once on the host (or in a throw-away node container), commit the built `dist/` under `slidev/presentations-v2/dist`, and mount it read-only like `manager/`. No per-deck build, no Monaco.
4. **Storage.** `decks-v2/<slug>/deck.json` inside the same Docker volume, next to `decks/`. V2 slugs share the access table (`portal.presentation_access`) with Slidev slugs, so an existing slug cannot be reused for a V2 deck; I would use a `v2-` prefix or a separate check. A V2 deck needs an access rule created through the existing `access` operation `create`.

## Proposed build order (small, each testable)

1. Server: V2 routes + `deck.json` storage (atomic write, `.bak`) + `/api/presentations-v2/:deck` GET/PUT + `/query` reusing `chartData` with a V2 pin set. Tests with plain Node.
2. SPA: Vite + Vue 3 + TS; Reveal runtime at `/p-v2/:deck` with `GfmChart` (ECharts 6 core, Arquero, math.js).
3. Studio: GrapesJS Core, blocks, data panel, calculated-field dialog, save/load.
4. Chart morph (scenes inside one slide first, then cross-slide) and the demo deck.
5. Deploy only after your go: mount + restart of the slidev container, then `health.ps1`.
