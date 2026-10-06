# Dashboards (DataEase)

The portal's **Dashboards** button opens DataEase v2 Community Edition (free, GPLv3, https://github.com/dataease/dataease)
inside the portal. It shows three dashboards made from the mission's numbers: **Key indicators**, **Zones & districts**
and **Covenant path**, in the viewer's language (14 languages). Only the APs, the President and the Data Analysts
can open it, and only through the portal. They can also change the dashboards ("All dashboards and Edit").

It runs as the compose project `gfm-dataease` on port **8088** of the server. Deploy history, tests and rollback of
round 6: `docs/handoff/round6/dataease.md`; the 14 languages: `i18n/README.md` and `docs/handoff/round8/dataease-i18n.md`.

## The six containers

| Container | What it does | Networks |
|---|---|---|
| `gfm-dataease` | DataEase itself (Java, heap 900 MB, limit 1600 MB) | `gfm-dataease-internal` only: no internet, no other services |
| `gfm-dataease-mysql` | DataEase's own notebook: dashboards, charts, datasets, the data source (MySQL 8.4, limit 512 MB) | internal |
| `gfm-dataease-web` | nginx, the only open door (port 8088). Every request needs the portal's Dashboards sign-in | internal + `gfm-dataease-edge` |
| `gfm-dataease-gate` | checks that sign-in for nginx and holds DataEase's own sign-in (Node, no packages) | internal |
| `gfm-dataease-dbproxy` | a pipe to the Beta database's port 5432, and nothing else | internal + `gfm-network` |
| `gfm-dataease-backup` | every night at 02:15 DataEase's notebook and files into `backups\nightly` (limit 128 MB) | internal |

## How a visit works

```
 portal (8070)  --POST /api/dataease/session-->  portal-api: "is this an AP, the President or a Data Analyst?"
                <-- cookie gfm_dataease (signed, 15 minutes, renewed while Dashboards is open)
 portal frame   --GET :8088/gfm-start?gfmLang=de-->  gfm-dataease-web (nginx)
                                                       asks the gate: is the cookie good?  (gate/gate.mjs /check)
                                                       yes: adds DataEase's own sign-in (never sent to the browser)
                                                   --> gfm-dataease (DataEase) --> dbproxy --> Beta database,
                                                       as gfm_dashboard_reader: the "dashboards" views only
 browser        <-- "Key indicators" in German (the gate picks the German copy; i18n/gfm-i18n.js translates the page)
```

- **From anywhere.** https://dashboards.example.org is a Cloudflare tunnel route to 8088; the portal
  on https://example.org opens it in its frame. There portal-api sets the cookie for the whole domain
  (Secure), and `/gfm-signout` clears that one too (`docs/handoff/round10/public-dashboards.md`).
- **Sign-in.** The free edition has one account ("admin") and no single sign-on, so nobody signs in to DataEase: the
  portal's signed cookie and the gate stand in. DataEase's own sign-in page, password change and "Log out" are
  switched off in nginx. The gate logs who (portal user id) opened Dashboards and every change:
  `docker logs gfm-dataease-gate`.
- **What people see.** A slim bar on top (`web/gfm/boot.js`) switches between the three dashboards and leads to "All
  dashboards and Edit". Phones get DataEase's phone page.
- **Data.** One data source, "GFM mission data (read-only)": the login `gfm_dashboard_reader` can read only the
  `dashboards` views (migrations 018 and 025: numbers per area, district, zone and week; no names of people).
  `seed-dashboards.ps1 -ReaderCheck` proves it.
- **Languages.** DataEase itself is always told "English" (it would otherwise start in Chinese after a restart).
  `i18n/gfm-i18n.js` then shows its words in the viewer's language. Chart words that DataEase draws as pictures (axes,
  legends, table headers) come from **copies of the three dashboards per language** (the folders Deutsch, Español ...
  inside "Mission"), made by `translate-dashboards.ps1`. The gate opens the copy in the viewer's language by a fixed
  id rule (`lib/languages.mjs`), so no list needs updating.
- **Charts.** nginx changes one default of DataEase's chart library so the x axis always keeps its first and last
  label (the latest complete week); see `web/default.conf`.
- **Speed.** nginx compresses text on the way (the chart library: 4.4 MB becomes about 1.5 MB; one dashboard's
  answer: about 250 kB becomes about 25 kB), and the browser keeps the chart library and asks only "changed?" on the
  next visit. A second visit downloads a few kB instead of about 4 MB (round 9, `docs/handoff/round9/ops.md`).

## The files

| File | What it does |
|---|---|
| `compose.yml` | The six containers. `.env.example` lists the settings; `init-env.ps1` writes the real `dataease/.env` (secret, not in Git). |
| `gate/gate.mjs` | The gate: checks the portal's cookie, holds DataEase's sign-in, sends `/gfm-start` to the right dashboard. |
| `web/default.conf` | nginx in front of DataEase (the rules above). |
| `web/gfm/` | `boot.js` (the dashboards bar, English, no DataEase sign-in page) and the small pages shown instead of DataEase's sign-in ("Please open Dashboards from the mission portal", "Dashboards are starting"). Their words come from `i18n/` like every other DataEase page, and the portal's own translator (`i18n.js` from port 8070) is loaded there too: it picks the language from the portal's `gfm_lang` cookie when the address has no `?gfmLang=`, and it translates the portal's messages shown there ("Dashboards are not available right now." …). Keep both. |
| `lib/dataease-client.mjs` | Talks to DataEase's web API: sign-in, password change, the tree of dashboards. |
| `lib/dashboard-store.mjs` | Reads, saves and publishes dashboards through that API (used by the two scripts below). |
| `lib/build.mjs` | Turns a short dashboard description (`dashboards/*.json`) into what DataEase saves (a 1280 x 800 canvas). |
| `lib/languages.mjs` | The 14 languages and the id rule of the copies (`115 LL DD GG PPPP 000000`). |
| `lib/copies.mjs` | Makes the translated copy of one dashboard. |
| `seed-dashboards.mjs` / `.ps1` | Sets DataEase up: data source, datasets, the three dashboards; `-Check`, `-Reset`, `-Export`, `-ReaderCheck`. |
| `translate-dashboards.mjs` / `.ps1` | Makes the copies in the 13 other languages; `-Check`, `-Only de,ar`, `-Remove`. |
| `dashboards/` | The three dashboards as short descriptions, their datasets (`datasets.json`, SQL in `sql/`), DataEase's own style defaults (`base/`), and `export/` (the dashboards exactly as DataEase stores them). |
| `backup/nightly.sh` | The nightly backup container's program. |
| `backup-dataease.ps1` | A backup now into `backups/`; `-RestoreFrom` puts one back (also the nightly files). |
| `init-env.ps1`, `set-reader-password.ps1` | Write `dataease/.env` with generated values; set the reader login's password. |
| `i18n/` | The 14 languages (kept by the languages stream; see `i18n/README.md`). |
| `tests/` | See "Test" below. |

## Change the dashboards

People change them in DataEase ("All dashboards and Edit", then Edit); DataEase keeps that in its own database,
which is backed up every night. Then run `translate-dashboards.ps1`, so the other 13 languages follow (never edit a
copy: it is replaced the next time).

To make a change repeatable from the repository, edit the description in `dashboards/` and run
`seed-dashboards.ps1 -Reset` (this replaces changes made in DataEase to the three dashboards; back up first with
`backup-dataease.ps1`), or keep DataEase's version in Git with `seed-dashboards.ps1 -Export`. Ids in the descriptions
stay fixed and far apart (see `fieldId` in `lib/build.mjs` for why).

A change of the SQL in `dashboards/sql/` only (the same columns): back up with `backup-dataease.ps1`, then run
`seed-dashboards.ps1` without a switch. It updates the six datasets in place (same ids, so every chart and every
language copy keeps working), leaves the dashboards alone and checks every chart at the end.

## Everyday checks

- `health.ps1`: the rows "Dashboards (DataEase)" (DataEase answers and the gate is signed in) and "DataEase Sign-in
  Boundary" (without the portal's cookie DataEase answers 401).
- `powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1 -Check`: every chart answers.
- Never `docker compose ... down -v`: `-v` deletes the volumes, and with them every dashboard people built.

## Test

No DataEase is needed for these; they run in the plain Node image without network:

```powershell
docker run --rm --network none -v "${PWD}\dataease:/d" -w /d node:24-alpine node --test tests/*.test.mjs
```

| Test | What it checks |
|---|---|
| `tests/gate.test.mjs` | The cookie (the same example portal-api signs), DataEase's sign-in kept and renewed, the first-start password change, `/start` and the languages, the change log. |
| `tests/build.test.mjs` | The dashboard descriptions and what `lib/build.mjs` makes of them: ids, colours, phone layout, filters, SQL. |
| `tests/copies.test.mjs` | The id rule and the language copies, on the three dashboards exactly as DataEase stored them. |
| `tests/store.test.mjs` | The shared helpers: the tree walk, the password change, saving and publishing, the dataset fields. |
| `tests/reader-check.mjs` | Against a running DataEase (`seed-dashboards.ps1 -ReaderCheck`): what the data source may read. |
| `tests/edge_dataease.ps1` | Against a running DataEase, in headless Edge, with screenshots. |
| `ops-tests/test-dataease-backup.ps1` | `backup-dataease.ps1` with a stand-in for docker: the backup, and the restore's order (backup first, stop, load, start again, also after a failure). |

`ops-tests\run-all.ps1` runs the Node tests and the backup test with all other operations tests.
