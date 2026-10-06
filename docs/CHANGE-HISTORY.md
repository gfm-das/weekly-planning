# Change history (rounds 2 to 12)

One line per piece of work, newest last. The full notes of each round (design reasons, deploy logs, rollbacks) are in
the git history: commit **`4f18bab`** is the last one that still has all of them. Read one with, for example:

```
git show 4f18bab:docs/handoff/round2/roles.md
git ls-tree -r --name-only 4f18bab docs/handoff | grep round
```

The notes that code and pages still point to are kept in `docs/handoff/` (marked **kept** below). What is true today:
`docs/README-start-here.md` and `CLAUDE.md`. Where an old note disagrees with the code, the code is right.

| Round | What changed | Migrations | Notes |
|---|---|---|---|
| 2 | Staff accounts and importer fixes; Call-ins like the old Beta pages; people in Weekly Planning (New Member form); Weekly Planning built from the database, questions managed in DA Management; several roles per person; faster Presentations and chart engine; the known-issues list | 021 to 027 | `round2/*` (history) |
| 3 | "New People Being Taught" wording; database clean-up of test data and unused parts; New Member history; small fixes from the round-2 reviews | 028 to 030 | `round3/*` (history) |
| 4 | Dashboards as a Slidev deck (later replaced) | | `round4/dashboard-deck.md` (history) |
| 5 | Whiteboard, portal one Weekly Planning and one Call-ins | 031 | in git history |
| 6 | Appsmith, Grafana and Superset retired; Dashboards is DataEase; stewardship everywhere (ZL only their zone); the 14-language interface; Presentations screen mirroring and PDF; the Whiteboard tab; nightly backups | 031, 032 | **kept:** `round6/dataease.md`, `i18n.md`, `ops.md`, `portalx.md`, `present.md`, `whiteboard2.md` |
| 7 | APs have full rights in DA Management; Archetypal Health; Weekly Planning section bar; the Update button (updates from GitHub); data uploads; zone presentations | 033 to 035 | **kept:** `round7/updater.md`, `archetypes.md` |
| 8 | DA Management wording after Appsmith; DataEase in 14 languages; zone presentations for managers (the deck address) | 036 | **kept:** `round8/deckorigin.md` |
| 9 | Tidy-up of portal-api, DA Management, the portal pages and Presentations; speed and declutter; faster access checks | 037 | **kept:** `round9/dam.md`, `portal-a.md`, `slidev.md` |
| 10 | The portal, Dashboards and everything else on the public address (Cloudflare tunnel); permission fixes for announcements, calendar and Archetypal Health | | **kept:** `round10/public-dashboards.md`, `public-domain.md`, `public-everything.md` |
| 11 | Facebook, social media and FindeChristus archived | 038 | in git history |
| 12 | Uploads fill in people automatically (Historical CSV and the new People upload); Overview week list; Glimpse shows open zones and weeks with data; DA Management > Places (close and reopen zones, districts, areas); faster Dashboards page; clean-up and simplify | 039, 040 | `round12/*` (current) |
| 13 | GFM Presentations V2 (alpha, runs beside Slidev): a prebuilt editor (GrapesJS) and Reveal.js player with live ECharts charts, calculated fields and chart morphs, no build per deck | | `slidev/presentations-v2/README.md` |

Decisions that still hold (they were in `12_DECISIONS_AND_CONVENTIONS.md`, now in `CLAUDE.md`): the database is the one
source of truth; Sunday is the reporting-week key and reports are area, unit and week scoped; the six key indicators come
first; submitting is explicit and locked work needs a scoped unlock; rights combine role and stewardship (hiding a button is
not security); managers are AP, President and Data Analyst; every import is one batch that can be undone.

- **GFM Studio step 1 (5 Oct 2026):** the editor add-on is our own copy (`slidev/manager/addons/gfm-studio`); the editor page shows the published deck first and fades to the editor; editing only saves (publish = Publish now, on leaving, or when an idle editor stops); startup timings in the log and `window.GFM_PERF`; Node compile cache and library-menu pre-start shorten the start; fixed a manager crash when an editor stopped under an open live connection.

- **GFM Studio steps 2 to 4 (5 Oct 2026):** 11 GFM layouts and 8 components; calculated fields, 41 chart kinds (every chart type), data stories and a Data tab in Studio; Paste Presentation with a check, outline and one-step undo, the AI authoring spec and Copy AI instructions, Upload/Download source, a manager performance view (`?debug`).
