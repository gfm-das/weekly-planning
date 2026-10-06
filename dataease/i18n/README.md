# DataEase in the mission's 14 languages

DataEase v2.10.27 Community Edition offers only English and Chinese, and the nginx front `gfm-dataease-web` keeps it
in English (`../web/default.conf`, `../web/gfm/boot.js`). Two things put Dashboards in the portal's languages
(en de es fr pt uk ru it tr fa ro sv da ar; fa and ar right to left):

1. **The page script** (this folder): `gfm-i18n.js` replaces the English words on every DataEase page in the browser:
   DataEase's own words, the dashboards bar, the sign-in pages, and the dashboards' titles, chart titles, filter
   labels, notes and text boxes.
2. **Copies of the three dashboards per language** (`../translate-dashboards.ps1`): the words DataEase draws on a
   canvas (chart axes, legends, table headers, tooltips) cannot be reached in the page, so each language has its
   own copy of Key indicators, Zones & districts and Covenant path with those words in it. The portal opens the
   copy in the viewer's language.

| File | What it is |
|---|---|
| `gfm-i18n.js` | The script nginx adds to DataEase's pages (and the sign-in pages load). |
| `<lang>.json` (14) | `messages`: DataEase's English texts (in `en.json`) and their translations, under DataEase's own keys. `gfm`: our own words (bar, sign-in pages, the three dashboards). `pmg`: key indicator names and Church terms in the official Preach My Gospel wording. `_meta`: language, direction, source, PMG gaps. |
| `web-i18n.conf` | The nginx piece `../web/default.conf` includes: serves `/gfm-i18n/` (the script and the 14 files). |
| `tests/` | `node --test` checks (no packages) and `edge_i18n.ps1` (headless Edge, German and Arabic, screenshots). |

## How a viewer gets their language

1. The portal opens Dashboards as `http://<host>:8088/gfm-start?gfmLang=<code>` (the portal language in
   sessionStorage `mission_language`, English when none; `portal/portal-enhancements.js`). Changing the language
   in the portal opens Dashboards again in the new language.
2. nginx passes `?gfmLang=` on to the gate. The gate (`../gate/gate.mjs`) opens the viewer's language copy of "Key
   indicators" when it exists (else the English one) and keeps the language in the address:
   `/?gfmLang=de#/preview?dvId=1150101000000000000`.
3. `gfm-i18n.js` reads `?gfmLang=` and remembers it in DataEase's localStorage (`gfm.dataease.language`), so pages
   DataEase opens later (the bar, "All dashboards and Edit", a reload) stay in that language. English, an unknown
   code or no language: the script does nothing.
4. The dashboards bar (`../web/gfm/boot.js`) lists the dashboards of the same folder as the open one: the German
   copies for a German viewer, the English dashboards for an English one.

## The copies and their ids (the "mapping")

`../lib/languages.mjs` gives every dashboard, folder and chart the scripts make a fixed id `115 LL DD GG PPPP 000000`:
LL = language (00 English, 01 de, 02 es, 03 fr, 04 pt, 05 uk, 06 ru, 07 it, 08 tr, 09 fa, 10 ro, 11 sv, 12 da, 13 ar),
DD = dashboard (01 Key indicators, 02 Zones & districts, 03 Covenant path; 00 = the folder), GG = generation (DataEase
keeps deleted rows, so a deleted id is never used again; the next free generation is taken), PPPP = the chart.
So the German copy of Key indicators is `1150101000000000000`, in the folder "Deutsch" `1150100000000000000` inside
"Mission" (`1150000000000000000`). Nobody needs to keep a list: the gate finds the copy from the English id.

- **Made by** `powershell -NoProfile -ExecutionPolicy Bypass -File dataease/translate-dashboards.ps1` (about 15
  seconds for 39 copies; `-Check` only looks, `-Only de,ar` limits the languages). It reads the English dashboards
  from DataEase (so it copies what editors changed there), translates with the same files as the page script
  (`../lib/copies.mjs`), saves each copy under its fixed id in its language folder and publishes it. The copies read
  the same datasets, so the numbers are always the same as in English.
- **An editor changed an English dashboard** (in DataEase, "All dashboards and Edit", then Edit): run
  `translate-dashboards.ps1` again. Every copy is replaced. **Never edit a copy**: the next run replaces it.
- **New words** (a new chart title or note in English): the script lists them per language as "no translation yet"
  and they stay English in the copies and on the page. Add them to the `gfm` part of `en.json` and of the 13 other
  files under a new key (same key in all 14), then run `translate-dashboards.ps1` again. `tests/gfm-words.test.mjs`
  checks that every word of `../dashboards/*.json` has a translation.
- A dashboard made by hand in DataEase (not by `seed-dashboards.ps1`) has no fixed id and stays English only (the
  page script still translates the words it knows).
- DataEase refuses names over 100 characters; such a title keeps English and is reported (the tests check ours).

## How the page script works

- **Translation**: it loads `/gfm-i18n/en.json` and `/gfm-i18n/<lang>.json` (checked with a 304 on each page,
  gzip) and replaces a text node, or a `placeholder`, `title` or `aria-label` attribute, whose trimmed text is
  exactly one of the English texts. Later parts win for the same English text: `gfm` over DataEase's `messages`,
  `pmg` over both. Also: texts with values (`Total 42`, `Select {0}`, `%s`), plural forms, texts split by `<br>`, a
  trailing colon (`Week before:`), a leading middle dot (`· Calling:` in "At church: 3 · Calling: 1") and a leading
  bracket (DataEase's chart error line). Key indicator names also match in any letter case and under the English
  names the portal and older dashboards use (`New people being taught`, `Sacrament attendance`...).
- **Never touched**: input and textarea values (only their placeholder/title/aria-label), `contenteditable`,
  `code`, `pre`, Monaco, CodeMirror, Ace and TinyMCE editing areas, `canvas`, `svg`, `translate="no"` and
  `.gfm-no-i18n`.
- **Cost**: one full pass when the dictionary arrives, then one MutationObserver whose records are handled once
  per animation frame; each node is looked at only when it is added or changed. Test: 30 000 text nodes with the
  real German file in well under a second.
- **Right to left (fa, ar)**: `<html lang>` is set (and put back when DataEase sets its own), and text direction
  only: `unicode-bidi: plaintext`, so each paragraph takes its direction from its own text. DataEase's layout is
  not mirrored.
- If a file cannot be loaded, DataEase stays in English (a console warning, nothing else).

## Preach My Gospel wording

`pmg` in each file comes from `pmg-terms.json` (official PMG 2023 wording): the six key indicators (label, and the
short form where there is one), their other English names (`@portal`, `@grafana`, `@old`), and key indicators,
goals, people you are teaching, new members, baptismal date, sacrament meeting, covenant path, ward, branch, district
council, lessons. Our own titles that name a key indicator use its PMG label (tested); the three sacrament titles of
Zones & districts use PMG's "sacrament meeting" (as the English uses the short "Sacrament attendance"), so they fit
DataEase's 100-character limit. **Gaps**: Persian PMG has only chapter 3, so `fa.json` uses our own Persian for the
six indicators and some terms (listed in `fa.json` `_meta.pmgGaps`; replace when official wording exists).

## What is translated (DataEase's own words)

Source: the local image only (DataEase's frontend locale `en`, the Element Plus `en` locale and the server's
`core_en_US.properties`). **2 043 texts in 13 languages** (1 037 seen when viewing: dashboard view, toolbar, filters,
dates, messages, sign-in, menus; 1 006 in the chart, dataset and data source editors), plus 68 of our own words
(`gfm`) and 31 PMG entries. **Stays English: 1 907 texts** used only on admin or Enterprise screens (system settings,
users, roles, sync tasks, reports...) or not used by the Community Edition at all.

## Limits

- Chart words drawn on a canvas stay English on an **English** dashboard (the page script cannot reach them); the
  language copies have them translated. Numbers and dates keep DataEase's formats. The browser tab title is left.
- Messages DataEase glues together from several texts in one node (for example `Creator:Mission`) stay English.
- A few DataEase words are fixed in its code, not in its language files; the week range's "To" is in `gfm`.
- After a DataEase update, texts that changed stay English until the files are regenerated from the new image the
  same way (`tests/` then shows any missing key).

## Tests

No packages; Node 20+ (here the local `node:24-alpine` image), from the repository root:

```
docker run --rm --network none -v "/path/to/weekly-planning:/repo:ro" -v "/path/to\gfm-worktrees\pmg-terms.json:/pmg-terms.json:ro" -e GFM_PMG_TERMS=/pmg-terms.json -w /repo node:24-alpine node --test "dataease/i18n/tests/*.test.mjs"
docker run --rm --network none -v "/path/to/weekly-planning:/repo:ro" -w /repo/dataease node:24-alpine node --test "tests/*.test.mjs"
```

- `i18n-files.test.mjs`: the 14 files are valid JSON with `messages`, `gfm` and `pmg`; every key of `en.json` in
  every file, nothing more, no empty value; placeholders kept; no Chinese; every PMG entry equals `pmg-terms.json`.
- `gfm-words.test.mjs`: every word of the bar, the sign-in pages and messages, and the three dashboards (from
  `../dashboards/*.json`) has a translation in every language; PMG labels inside our titles; numbers and % kept;
  names within DataEase's 100 characters.
- `translate.test.mjs`: the translate function on a small stand-in DOM (values, plurals, colon, middle dot,
  bracket, the three attributes, nothing in inputs or editors, batching, 30 000 nodes, German/English/Arabic start).
- `wiring.test.mjs`: `../web/default.conf` includes `web-i18n.conf` and adds the script to the app pages next to
  boot.js; `/gfm-start` passes `?gfmLang=`; `../compose.yml` mounts this folder read-only; the sign-in pages load it.
- `../tests/copies.test.mjs`, `../tests/gate.test.mjs`: the id rule, the copies of the three exported dashboards
  (new ids everywhere, same datasets, every word translated, placeholders kept), and the gate opening the copy.
- `nginx -t` of the real config in a throw-away `nginx:alpine`:
  `docker run --rm --network none -v "<repo>\dataease\web\default.conf:/etc/nginx/conf.d/default.conf:ro" -v "<repo>\dataease\web\gfm:/usr/share/nginx/gfm:ro" -v "<repo>\dataease\i18n:/etc/nginx/gfm-i18n:ro" nginx:alpine nginx -t`
- `edge_i18n.ps1` (PowerShell 7, against a DataEase with the copies made): German and Arabic sign-in pages, the
  copies opened by `/gfm-start?gfmLang=`, the bar, titles and filter labels, DataEase's list page, the page script
  on an English dashboard, English unchanged; screenshots.
