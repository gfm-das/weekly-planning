# Weekly Planning and Call-ins

Two pages of the mission portal, written so that anyone can follow them. If you only read one section, read
"How the data travels".

## In one minute

- **Weekly Planning** (`planning.html`) is where two missionaries who work together (a *companionship*) plan their
  week. They answer the planning questions (their key indicators: results, goals and plans), and they keep three
  lists of people they are helping: **friends with a baptismal date**, **New Members** (their first year after
  baptism) and **high-potential friends**. They submit the plan by Sunday 18:00. If it is not finished then, they
  get a reminder on every phone or computer where they turned reminders on.
- **Call-ins** (`callins.html`) is where leaders look at those plans in the weekly call-in. A district leader sees
  their district, a zone leader their zone, the managers (APs, the President, Data Analysts) the whole mission. They
  move **Mission > Zone > District > Area**, write notes for each other, and the district leader marks the call-in
  **complete** (or **reopens** it).

## The files

| File | What it does |
|---|---|
| `planning.html` | The Weekly Planning page: its look (CSS), its skeleton (HTML) and its script, in 15 numbered parts. |
| `callins.html` | The Call-ins page, the same way, in 13 numbered parts. |
| `portal-client.js` | Shared by all pages: `portalAPI()` talks to portal-api with the sign-in, `escapeHTML()` makes text safe to show. |
| `i18n.js`, `i18n/*.json` | Shared: shows every English text of a page in the reader's language (14 languages). |
| `workspace.css` | Shared: the colours, buttons and panels every portal page uses. |
| `tests/planning-rules-check.cjs` | Runs parts of `planning.html` without a browser: the show/hide rules (like the server's), two companions saving one grid, number boxes, the person cards, the pop-up form's checks. |
| `tests/callins-check.cjs` | Runs parts of `callins.html` without a browser: the address, the status chips, sorting the big table, where each note is saved, GEMIKO. |

The server side lives in `portal-api/`: `planning.py` (Weekly Planning), `callins.py` (Call-ins) and `roles.py` (who
may do what).

## How the data travels

```
 Missionary                      portal-api (planning.py)              database
 ----------                      ------------------------              --------
 opens Weekly Planning  ------>  GET  planning/form           ------>  questions, saved answers, people
 types an answer        ------>  PUT  planning/reports/1/answers  --->  saves only what changed
 changes a person card  ------>  PUT  planning/reports/1/people   --->  saves only what changed
 Baptized / Transfer /  ------>  POST planning/reports/1/people/...  -> the database does the move
 End follow-up / Delete
 Submit                 ------>  POST planning/reports/1/submit  ---->  plan is SUBMITTED (read only)

 District leader                 portal-api (callins.py)
 ---------------                 -----------------------
 opens Call-ins         ------>  GET  callins?level=district&id=51  ->  numbers and plans from Weekly Planning
 opens People / GEMIKO  ------>  GET  callins/people?...  callins/gemiko?...
 writes DL notes, Save  ------>  PUT  callins/districts/51/dl-notes
 Complete call-in       ------>  POST callins/districts/51/complete  (Reopen: .../reopen)
```

A few things worth knowing:

1. **The questions come from the database.** Data Analysts change them in DA Management > Planning questions. The page
   draws whatever it gets, including show/hide rules ("ask this only when that answer is more than 0").
2. **Two companions can type in the same plan at the same time.** The page remembers *what* changed and sends only
   that, a moment after the last change. The server answers with the whole saved plan, and the page shows the
   companion's newest answers without touching the box you are typing in. So there is no Save button to press: one
   appears in the bar only when a save did not go through, to try again.
3. **Nothing typed in Call-ins is lost.** Text that is not saved yet is kept as a *draft*. If the call-in was marked
   complete before you saved, your text stays on the page (read-only, with *Copy text* and *Discard*) until the
   call-in is reopened.
4. **The pages never decide who may do what.** portal-api (`roles.py`) and the database decide and check every
   request: a zone leader only their own zone, a district leader only their own district, a missionary only their
   own area, the managers the whole mission. The page only shows what it is given.

## Speed

Measured in round 9 (the numbers are in `docs/handoff/round9/portal-a.md`):

- The pages themselves are quick. Weekly Planning draws a whole plan in about 15 ms on a computer (about 80 ms on a
  slow phone) and a keystroke costs under 10 ms; Call-ins draws a call-in in about 4 ms. Keep it that way: draw the
  page once from the data, change only what changed while someone types, and load the People tab and GEMIKO only when
  they are opened.
- Most of the waiting is elsewhere. Opening Weekly Planning waits about 0.7 s for `GET planning/form`, and most of
  that is the database finding the viewer's ward or branch (`public.current_user_area_units`). The pages also travel
  uncompressed (about 160 and 95 KB), which a slow phone connection feels. Both are fixed outside these pages.

## Words and languages

Every text on these pages is written in English in the page itself. `i18n.js` swaps it for the reader's language
from `portal/i18n/<language>.json`. So:

- a new or changed text needs the same key in **all 14** catalogs (German and Spanish speak informally: *du*, *tú*);
- `node portal/tests/i18n-check.cjs` fails when a page shows a text that is not in the catalogs;
- keep the words of *Preach My Gospel* and the mission (key indicators, New People Being Taught, baptismal date,
  New Member, GEMIKO, covenant path).

## How the code is laid out

Each page starts with a short note (what it is, who uses it, how it fits), then its CSS, then its HTML skeleton,
then its script. Each script starts with "HOW THIS SCRIPT WORKS" and is split into numbered parts with a title line
in capitals, for example `// 5. DRAWING THE QUESTION SECTIONS`. The tests find the parts by those title lines, so
keep them when you change a page.

| Weekly Planning (`planning.html`) | Call-ins (`callins.html`) |
|---|---|
| 1. The page's parts and what the script remembers | 1. Words and settings |
| 2. Show/hide rules | 2. What the page remembers |
| 3. Reading and writing the answers on the page | 3. Small helpers for numbers, dates and answers |
| 4. People: the questions and choices the server knows too | 4. Moving around: the address, Back and Forward, loading |
| 5. Drawing the question sections | 5. Drawing the page: header, week and status chips |
| 6. Drawing the people sections (one tab per person) | 6. The tabs: Overview, People and Notes |
| 7. Drawing the whole plan | 7. The Overview tab: numbers, the big table, the cards |
| 8. The section bar (the coloured buttons at the top) | 8. The Notes tab |
| 9. What is still to answer, the progress bar, the checks | 9. Saving notes and area updates, Complete / Reopen |
| 10. Saving: only what changed | 10. The bar at the bottom |
| 11. Showing what the server saved | 11. GEMIKO |
| 12. Loading the plan | 12. The People tab |
| 13. The people pop-ups | 13. Clicks and typing anywhere, and the start |
| 14. Typing and clicking in the form | |
| 15. The buttons, the pop-up forms and the start | |

## How to test

Replace `<repo>` with the folder of your checkout (for example `/path/to/weekly-planning`). Nothing here touches the live
portal or the live database.

**1. Quick checks, no browser, no database** (a few seconds):

```powershell
docker run --rm --network none -v <repo>:/repo -w /repo node:24-alpine node portal/tests/planning-rules-check.cjs
docker run --rm --network none -v <repo>:/repo -w /repo node:24-alpine node portal/tests/callins-check.cjs
docker run --rm --network none -v <repo>:/repo -w /repo node:24-alpine node portal/tests/i18n-check.cjs
docker run --rm --network none -v <repo>:/repo:ro -w /repo/portal-api gfm-portal-portal-api python tests/test_wording.py
```

`test_callins.py`, `test_planning_people.py` and `test_small_fixes.py` also read the pages; run them the same way.

**2. In a real browser with made-up people** (headless Edge, no database, no personal data). Start a stub server
that serves `portal/` and answers the API with made-up data, then run the check:

```powershell
docker run --rm -d --name gfm-test-planning --memory 256m -p 127.0.0.1:18297:8080 `
  -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/planning_stub_api.py
pwsh -File portal-api/tests/edge_planning_nav.ps1 -Base http://127.0.0.1:18297 -Out <folder for screenshots>
pwsh -File portal-api/tests/edge_planning_wording.ps1 -Base http://127.0.0.1:18297 -Out <folder for screenshots>
```

For Call-ins, `portal-api/tests/callins_stub_api.py` behind nginx and `edge_callins_checks.ps1` (the first lines of
each script say how to start it). `edge_i18n.ps1` opens both pages in several languages, right to left too. Look at
the screenshots, and start the stub fresh before each run (it keeps changes in memory).

**3. The server side on a throw-away database**: `portal-api/tests/planning_*_db.py` and `callins_db.py` run
portal-api against a copy of the database whose name contains `test` (they refuse anything else). The first lines
of each file say how to make the copy and run it.

## Rules for changing these pages

- Keep everything the owner asked for: the dynamic questions, the people management (Edit details, Transfer, End
  follow-up, Baptized, No longer on date, Delete when added by mistake), the New Member form's rules, the
  covenant-path questions, the coloured section buttons pinned at the top, and in Call-ins the Mission > Zone >
  District > Area drill-down, the notes and Complete / Reopen.
- Never decide permissions in the page; never throw away text someone typed.
- One button for each thing: no second button that does what another one on the same screen (or the automatic save)
  already does, and no list with only one choice (show the choice as text). Round 9 took the extra ones out.
- A tap target is at least 44 px and an input's text at least 16 px (phones), and nothing may scroll sideways.
- After a change, run the quick checks, and the browser check of the page you changed.
