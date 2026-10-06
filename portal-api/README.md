# portal-api

The mission portal's back end. The web pages in `portal/` show things; this folder is where the portal asks
questions ("what is my plan this week?") and saves answers ("here is my plan"). It is written in Python with
Flask and talks to the mission's Postgres database (Supabase).

Two small programs are built from this folder (one Docker image, see `Dockerfile` and `compose.yml`):

| Container | Command | What it does |
|---|---|---|
| `portal-api` | `gunicorn app:app` (port 8091) | Answers every `/api/...` request of the portal, and the `/internal/...` requests of the Presentations manager. |
| `portal-reminders` | `python reminders.py` | Runs on its own, once a minute: sends push reminders (Weekly Planning on Sunday from 18:00 Berlin time, calendar meetings) and once a day ends the follow-up of New Members baptized a year ago. |

## How one request travels

```
browser page (portal/planning.html)
   |  fetch('/api/planning/form', with the sign-in token)
   v
nginx (portal container)  -- passes every /api/ request on -->  portal-api (app.py)
   1. authenticate()      Is this really a signed-in person? (asks Supabase; origin_guard.py first checks the
                          request comes from a portal page and not from a presentation)
   2. context_for()       Who are they? Their main role, extra roles, area, district, zone, mission (= "c")
   3. the route           e.g. planning_form_get() in app.py
   4. roles.py            May this person do this? (manager? leader of this zone?)
   5. planning.py         Does the work: reads and writes the database
   6. the database        Row-level security checks once more who may see which rows
   v
JSON answer  -->  the page shows it
```

Two ways to reach the database (both in `app.py`):

- `db()` uses the service's own database account. The code itself checks the rights (stewardship, roles).
- `user_db()` acts *as the signed-in person*, so the database's own rules (row-level security) decide as well.
  Weekly Planning and Call-ins use it; the mission glimpse uses it only to ask which areas count (see Speed). It
  gives plain rows; `helpers.fetch_rows` turns them into dicts.

Every error becomes `{"error": "a plain sentence"}` with the right status (400 wrong input, 401 not signed in,
403 not allowed, 404 not found, 409 someone else changed it, 413 too large, 503 try again).

## The files

| File | What it is | Used by |
|---|---|---|
| `app.py` | The front door: sign-in, the database connections, and the routes for calendar, announcements, attachments, Overview, mission focus, languages, push devices, Weekly Planning (thin), and Presentations access. Its top lists its 12 parts. | every portal page, the Slidev manager |
| `roles.py` | Who someone is (main role and extra roles) and what they may do. The one place for role rules. | everything |
| `origin_guard.py` | Refuses `/api/` requests that do not come from the portal's own pages (for example a presentation on port 8089). | `app.py` |
| `planning.py` | Weekly Planning: the plan, its questions (from the database), answers, the people cards (edit, move area, end follow-up, baptized, drop, remove if added by mistake), the New Member form rules, submit and unlock; the Overview's planning numbers. | `app.py` |
| `callins.py` | Call-ins: Mission > Zone > District > Area, notes, area updates, Complete / Reopen, the People and GEMIKO tabs. | `portal/callins.html` |
| `dashboard.py` | The mission glimpse: the six key indicators by finished week and zone for the managers' Overview. | `app.py` (`/api/dashboard`) |
| `archetypes.py` | Archetypal Health: who sees which zones, districts and areas; notes; the settings page. | `portal/archetypes.html`, `portal/archetype-settings.html` |
| `archetype_model.py` | The Archetypal Health sums (no database, no web): scores, bands, labels, diagnoses, settings checks. | `archetypes.py` |
| `charts.py` | The numbers behind charts on slides and in the chart builder, always inside the viewer's stewardship. | the Slidev manager |
| `whiteboards.py` | The Whiteboard tab: list, create, open, save, rename and delete boards; checks sizes and pictures. | `portal/whiteboard/` |
| `dataease_auth.py` | The Dashboards (DataEase) sign-in cookie for managers. | the portal's Dashboards button |
| `church_links.py` | Puts the reader's language into links to churchofjesuschrist.org. | `app.py` |
| `push_texts.py` | The words of push reminders in the portal's 14 languages. | `reminders.py` |
| `reminders.py` | The reminder worker (see above). | runs by itself |
| `helpers.py` | Small shared tools: `fetch_rows`, `fetch_one`, `json_ready`, `dashboard_reader`. | several files |
| `migrations/` | Numbered SQL files that change the database, each with a `_rollback.sql`. | the coordinator, by hand |
| `tools/remove_test_data.py` | Removes named test entries from the database, using the app's own rules. | the coordinator, by hand |
| `tests/` | Checks (see below). | developers |

Who may see what (the "stewardship") is the same everywhere: managers (AP, President, Data Analyst) see the whole
mission; a ZL or STL their own zone; a DL their own district; a missionary their own area. `roles.py` answers the
role questions; each file checks the stewardship on every request, and the database checks again.

## Speed

Row-level security asks "may this person see this area?" (`public.can_access_area`) for every row it hands out: a
weekly plan once, a planning answer twice. On a read of thousands of rows that question is most of the work. So:

- Read many rows of several areas once per area, not once per row: ask `can_access_area` as the person for each
  area (`dashboard.areas_open_to`), then read the numbers on `db()` for exactly those areas. The mission glimpse does
  this (round 9: 3.5 s before, 0.3 s now; with six weeks of planning answers 150 s before, 0.3 s now).
- Migration 037 runs the two access questions in plpgsql, which keeps its plan: each question costs about 0.4 ms
  instead of about 3 ms. Every page that reads through `user_db()` is faster with it.
- Do not add a cache to hide a slow read: find the slow part with `EXPLAIN ANALYZE` on a live-like copy instead.
  Numbers of every measurement are in `docs/handoff/round9/api.md`.
- Compressing the answers on the way to the phone is the portal's nginx's job (`portal/nginx.conf`, gzip for JSON),
  not this program's: JSON shrinks to about a tenth (Archetypal Health 144 KB to 12 KB).

## Migrations

The files in `migrations/` are applied by hand, in number order, as `supabase_admin`, with `ON_ERROR_STOP`. Each
file says at its top why it exists, what it changes, how to apply it and how to undo it (its `_rollback.sql`).
After a migration, run `019_restrict_public_functions.sql` again: it keeps new database functions closed to
people who are not signed in. Never edit a migration that is already live; write a new one.

## How to test

Never run a test against the live database. Tests that need a database refuse to start unless the database name
contains `test` and a `..._TEST_THROWAWAY=yes` variable is set.

**Quick checks (no database, a few seconds).** Every `tests/test_*.py`, inside the portal-api image, with the whole
repository mounted (some checks read `portal/`):

```
docker run --rm -v <repo>:/repo:ro -w /repo/portal-api gfm-portal-portal-api \
    sh -c 'for f in tests/test_*.py; do python "$f" || echo "FAILED: $f"; done'
```

Also run the portal's checks, because `portal/tests/i18n-check.cjs` reads `app.py` (the Overview's two scripture
excerpts must stay written as `'text':'...'`). The updater runs them before every install and installs nothing
when one fails:

```
docker run --rm --network none -v <repo>:/repo:ro -w /repo node:24-alpine \
    sh -c 'for f in portal/tests/*.cjs; do node "$f" || echo "FAILED: $f"; done'
```

**Database checks (`tests/*_db.py`, `tests/api_workflows.py`).** They run the real routes against a throw-away copy
of the database that looks like live:

1. Make a throw-away copy of the database: start a disposable `supabase/postgres` container, restore the latest
   `backupseta-pre-*.dump` into it (a dump of live already has every migration, 010 to 040), and
   `CREATE DATABASE gfm_test_<name> TEMPLATE postgres` (see `roster-importer/README.md`, Testing).
2. A test for a newer migration applies that migration to the copy first (as `supabase_admin` over stdin with
   `ON_ERROR_STOP`), then 019.
3. Run one test in a temporary container on the test network, for example:

```
docker run --rm --network gfm-test-r2-net -v <repo>/portal-api:/app:ro -v <repo>/portal:/portal:ro -w /app \
    -e DATABASE_URL=postgresql://postgres:<password>@gfm-test-r2-db:5432/gfm_test_<name> \
    -e CALLINS_TEST_THROWAWAY=yes gfm-portal-portal-api python tests/callins_db.py
```

   Each test's first lines say which `..._TEST_THROWAWAY` variable and which other settings it needs
   (`api_workflows.py` also needs `PORTAL_TEST_AUTH=isolated` and `PORTAL_SERVICE_KEY`; migration tests also need
   `ADMIN_DATABASE_URL` for `supabase_admin`).
4. Drop the copy afterwards (`DROP DATABASE gfm_test_<name> WITH (FORCE)`).

**Browser checks (`tests/edge_*.ps1`).** Headless Edge against a stub API or the real API on a throw-away copy;
each script explains how to start what it needs.

The quick checks and the database checks should all pass before anything is merged.

## Adding something new

- A new page area with several routes gets its own file with a Flask `Blueprint` (like `callins.py`), registered at
  the end of `app.py`. A single route can live in `app.py` in the part it belongs to.
- Start the file with a short overview: what it is, who uses it, how it fits.
- Ask `roles.py` for role rules; never compare role names in the route itself.
- The API answers in plain English. The page shows its sentences in the reader's language only when the same
  English sentence is in the portal's catalogs (`portal/i18n/en.json` and the 13 other languages), so a new
  sentence a person can see needs all 14 catalogs too (German with "du", Spanish with "tú").
- Add a quick check in `tests/`, and a database check when the route reads or writes the database.
