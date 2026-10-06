# GFM Presentations V2 (alpha, beside Slidev)

One prebuilt web app for two pages. Slidev is untouched and keeps `/studio/<deck>` and `/p/<deck>`.

| Page | What |
|---|---|
| `/studio-v2/<deck>` | The editor: slide list, canvas (GrapesJS Core), properties. Save is one PUT of JSON: no build, no Slidev, no per-deck process. |
| `/library-v2` | The library: the V2 presentations this person may view (Present, Projector, and Edit where allowed). Managers make new ones here. |
| `/p-v2/<deck>` | The presentation (Reveal.js): arrows, F fullscreen, N notes, steps, Auto-Animate, transitions. |

Both are served by the presentation manager (`slidev/manager/v2-routes.mjs`, routes in `manager-routes.mjs`) on the manager
address (port 3030). A deck is `decks-v2/<deck>/deck.json` in the Slidev Docker volume (the previous save is kept as
`deck.json.bak`), pictures are in `decks-v2/<deck>/assets/`.

## Who can view (the viewing permission)

Each presentation has a viewing rule, set in the editor with **Who can view** (managers; save the deck once first): everyone with
Presentations access (DL, ZL, STL), or only some roles, in some zones or districts, plus named people. Viewers can only view;
they never change a presentation. Managers always see and change everything; with nothing chosen only managers see it. The rule
lives in portal-api's `portal.presentation_access` under the key `v2-<deck>` (the same table, checks and caching as Slidev
sharing), and the library, the player, the pictures and the numbers all follow it.

## On a projector

`/p-v2/<deck>?projector=1`, the **Projector** button, the P key, or fullscreen (F) switch on projector mode: text and chart
labels 30% larger (text that then does not fit is made smaller again), thicker lines, darker greys, a black surround with the slide
using the whole screen. After 3 seconds without the mouse or a key the cursor, toolbar, arrows and progress bar fade away. The
screen is kept awake while presenting (after the first click or key). Clickers work (PageDown/PageUp, Space), B blacks the
screen, N shows the speaker notes, ? lists the keys, Esc shows all slides.

## How it fits together

```
GrapesJS (editor) -> deck.json -> Reveal.js (player)
                         |
parts.ts draws every part (the same code in both)
chart: portal-api (through the manager) -> data worker (Arquero + math.js) -> preset -> ECharts 6
```

- **Access** is the Slidev access (V2 decks have their own sharing key `v2-<deck>`, so a Slidev deck of the same name never opens a V2 deck; new Slidev decks can no longer be named `v2-...`): `access.mjs` (portal-api decides). Open = may open the deck; edit = may change it; a new V2
  deck is made by a manager only. Numbers go through the same `chartData` as Slidev charts, so portal-api still decides
  stewardship (a leader sees their own zone, district or area) and hides small counts. A viewer who is not a manager gets
  numbers only for the queries saved in the deck ("pinned"; `v2-deck.mjs deckPinKeys`).
- **A deck is data, not code.** Text is set as text, pictures are the deck's own uploaded files (png, jpg, gif, webp, checked by
  their first bytes), the server checks and cleans every save (`v2-deck.mjs validateDeck`), charts pass `safeChartOption`. That is
  why these pages may run on the manager address.
- **No `unsafe-eval` in the pages.** Arquero and math.js build functions from text, so they run in a web worker
  (`src/data/data-worker.ts`) that the manager serves with its own policy: it may do that, but it has no network, no page, no
  cookies. The pages' policy stays `script-src 'self' 'nonce-…'`.
- **Chart morph.** Charts on different slides with the same *transition id* are one ECharts instance above the slides: it moves
  to the next chart's place while ECharts' `universalTransition` morphs the data. Story mode: a chart with scenes gets one
  Reveal step per extra scene (one story chart per slide). A slide with a shared chart always uses the fade transition.
- **Calculated fields** are math.js formulas over the chart's fields (`friends_found_actual`, other calculated fields) with
  `+ - * / ^`, brackets, numbers and `safeDivide abs round floor ceil min max sqrt pow log`. Nothing else parses; a missing
  number or a division by zero gives an empty value.

## Build and test (from `slidev/presentations-v2`)

```
docker run --rm -v "${PWD}\..:/s" -w /s/presentations-v2 node:24-alpine sh -c "npm install && npm run build"
docker run --rm --network none -v "${PWD}\..\..:/r" -w /r/slidev node:24-alpine node --test tests/v2-deck.test.mjs tests/v2-routes.test.mjs
```

`dist/` is committed (the container has no build step; `slidev-compose.yml` mounts it read-only). Rebuild and commit it with
every change to `src/`. To look at the pages without portal-api: `slidev/tests/v2/serve-v2.mjs` (a real manager with made-up
numbers; the file explains how to sign in).

## Demo deck

`demo/referral-demo.deck.json`: six slides on the key indicators (referrals are not in the chart API): title, a shared chart that
morphs between two numbers, a funnel, a leaderboard with the calculated field "Date rate", and a story-mode chart.
Put it on the server with `docker cp` into `decks-v2/referral-demo/deck.json` of the Slidev volume, or open
`/studio-v2/referral-demo` as a manager and Save.

## Known limits (alpha)

- Interface texts are English only (language support comes later).
- Slides are 960 x 540 (16:9) only. Text is plain (no bold or links). One story chart per slide.
- Referral numbers are not available through the chart API: V2 charts show the key indicators, plans and people counts.
