# Start here (for a new Data Analyst)

Welcome. This page explains the mission system in plain words: what each part is, where it lives, how to put a change
live ("deploy") and how to go back if something goes wrong ("roll back"). Read it once from top to bottom; after that
you can jump to the part you need.

Written 29 September 2026 (round 9). The detailed history of every change is in `docs/handoff/` (its index is
`docs/handoff/00_START_HERE.md`).

## 1. What the mission system is

It is one website for the Frankfurt mission, called **the portal**. Missionaries, district leaders (DL), zone leaders
(ZL), sister training leaders (STL), the assistants (AP), the office, the mission president and the Data Analysts all
use it. They open it in a browser on a phone or a computer:

- on the office computer itself: `http://localhost:8070`
- from another device in the office network: `http://192.168.1.20:8070`

Everything runs on **one Windows computer** in the office, in **Docker containers**. A container is like a small,
sealed box with one program inside. Docker Desktop starts the boxes and connects them with a private network called
`gfm-network`.

The code of every box is in one Git folder: **`/path/to/weekly-planning`** (the "live" folder). Never experiment there:
make changes in a separate Git worktree (for example `/path/to\gfm-worktrees\<name>`), test them, then merge.

## 2. The parts, and where each one lives

```
 Browser (phone or computer)
   |
   +--> Portal  :8070  (nginx: the pages)  --/api/-->  portal-api  -->  Beta database (Supabase / PostgreSQL)
   |                                                      ^
   |                                                      |  portal-reminders (push reminders, same code)
   +--> DA Management  :8090  ----------------------------+--> Beta database
   +--> Presentations  :3030 (library, editor)  and  :8089 (the decks themselves)
   +--> Dashboards     :8088  (DataEase, reads the database through one read-only login)
```

The portal shows the other parts inside its own frame, so people only ever see one website.

| What people see | What it really is | Code (in `/path/to/weekly-planning`) | Container(s) | Port |
|---|---|---|---|---|
| The portal: Overview, Weekly Planning, Call-ins, Calendar, Announcements, Whiteboard, Archetypal Health | Web pages served by nginx | `portal/` (one `.html` per page; the 14 languages in `portal/i18n/`) | `portal-ydpgd5zwrjrvz5aa188sa60u` | 8070 |
| (behind the pages) | The portal's server program (Python, Flask): sign-in, rights, reading and saving | `portal-api/` (`app.py`, `planning.py`, `callins.py`, `archetypes.py`, `whiteboards.py`, ...) | `portal-api` | none (only through the portal, `/api/`) |
| Push reminders (Sunday 18:00, meeting reminders) | The same program in a second box, doing timed jobs | `portal-api/reminders.py` | `portal-reminders` | none |
| DA Management (accounts, staff accounts, planning questions, data uploads, import history with Undo, Updates) | A second Flask program | `roster-importer/` | `roster-importer-roster-importer-1` | 8090 |
| Presentations (library, Studio, Source, charts, Publish, PDF, screen mirroring, zone decks) | Slidev and its manager (Node) | `slidev/` (`slidev/manager/server.mjs`) | `slidev-j5iyrpjbsssqlilqhw9axugx` | 3030 and 8089 (the deck address) |
| Dashboards (AP, President, Data Analyst; 14 languages) | DataEase v2 Community Edition, with a small sign-in gate in front | `dataease/` | `gfm-dataease` and `gfm-dataease-*` (mysql, gate, web, dbproxy, backup) | 8088 |
| (the data) | The **Beta** Supabase stack: PostgreSQL, sign-in (GoTrue), REST | `supabase/`; database changes in `portal-api/migrations/` | `gfm-beta-*` (the database: `gfm-beta-supabase-db-1`) | 13000 (Studio), 18000 (API), 54322 (PostgreSQL for DBeaver, `docs/DBEAVER.md`) |

"Beta" is just the name the main database got when it was set up; it **is** the real data.

### Things that run by themselves

| What | When | Where it is explained |
|---|---|---|
| Nightly database backup (container `gfm-backup`) | every night 02:30, keeps 14 days, in `backups\nightly` | `nightly-backup/README.md` |
| Dashboards backup (container `gfm-dataease-backup`) | every night 02:15, same folder | `dataease/README.md` |
| Push reminders (container `portal-reminders`) | every minute; weekly plans Sunday from 18:00 | `portal/README.md` |
| The updater (Windows scheduled task "GFM Updater") | waits for a person to press **Update now** in DA Management > Updates | `updater/README.md` |

### Tools you run yourself

| File | What it does |
|---|---|
| `health.ps1` | Checks every part and prints one row per check (OK, SKIPPED, waiting or FAIL). It changes nothing. Run it after every change. |
| `portal/deploy.ps1` | Puts the portal's pages live (copies `portal/` into the portal container, then reloads nginx). |
| `start-gfm.ps1` | After Windows or Docker Desktop stopped badly: starts Docker Desktop and waits until the parts answer. |
| `ops-tests/run-all.ps1` | Runs the tests of the operations scripts (nothing real is touched). |

### Retired parts

Appsmith, Grafana, Superset and the first (Coolify) Supabase stack are gone: switched off in round 6 and removed in
round 12 (their folders are in the git history, see `docs/CHANGE-HISTORY.md`). Port 8088 belongs to DataEase and port 8089
to the Presentations deck address.

### Secrets

Passwords and keys are in `.env` files (`portal-api\.env`, `roster-importer\.env`, `slidev\.env`, `dataease\.env`,
`supabase\.env`) and in `nightly-backup\secrets\`. They are **never** in Git, never printed, never pasted into a chat,
a screenshot or a report. Every folder has a `.env.example` that lists the names without the values.

## 3. Everyday checks

1. `powershell -NoProfile -ExecutionPolicy Bypass -File health.ps1` (in `/path/to/weekly-planning`). Every row should say
   OK. The first row is the nightly backup.
2. Something looks wrong on one page? Look at that part's log: `docker logs --tail 50 portal-api` (or the container
   name from the table above).
3. The computer was restarted and nothing answers? `powershell -ExecutionPolicy Bypass -File start-gfm.ps1`.

## 4. Deploy (put a change live)

### Before you start

- Test the change in your worktree: each folder's README says how. Tests that need a database use the **throw-away
  test server** `gfm-test-r2-db`, never the live database.
- Read the change's handoff note (`docs/handoff/round<N>/<name>.md`): it lists its deploy steps in order.
- If the change has a database migration: back up the database first:
  `docker exec gfm-beta-supabase-db-1 pg_dump -U postgres -d postgres -Fc -f /tmp/before.dump`, then
  `docker cp gfm-beta-supabase-db-1:/tmp/before.dump backups\beta-pre-<what>-<date>.dump`.
- Pick a quiet time. A rebuild of portal-api or DA Management interrupts them for a few seconds.

### The normal way: the Update button

When the change is on GitHub (branch `main`), an AP, the President or a Data Analyst opens **DA Management >
Updates**, presses **Check for updates**, then **Update now** and types UPDATE. The updater tests the new version,
checks health, saves a way back, installs only the parts that changed (portal-api, DA Management, Presentations, the
portal pages and new migrations), and checks health again. If that fails it goes back by itself. Details:
`updater/README.md`.

The updater does **not** install `dataease/`, `nightly-backup/`, `supabase/` or the retired folders. When an update
changes one of those, the Updates page lists it, and a person follows the handoff note.

### By hand (from `/path/to/weekly-planning`, after `git merge`)

Only the parts that changed, in this order, then `health.ps1`:

**1. Database migrations first** (after the backup above), each one like this, and then `019` the same way (019 is
the rights check; it runs again after every migration):

```powershell
docker cp portal-api\migrations\NNN_name.sql gfm-beta-supabase-db-1:/tmp/migration.sql
docker exec gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -f /tmp/migration.sql
```

The file is copied in (not piped through PowerShell) so that letters such as ä or é arrive as written.
`ON_ERROR_STOP=1` stops at the first error, and each migration is one transaction, so a failed one changes nothing.
The first lines of a migration say when it needs another user than `supabase_admin`.

**2. Then the programs:**

| Part | Command |
|---|---|
| portal-api and reminders | `docker compose -p gfm-portal -f portal-api/compose.yml up -d --build` |
| DA Management | `docker compose -p roster-importer -f roster-importer/docker-compose.yml up -d --build --no-deps roster-importer` |
| Presentations | `docker restart slidev-j5iyrpjbsssqlilqhw9axugx` (a change of ports or mounts: `docker compose -p slidev -f slidev/slidev-compose.yml -f slidev/local-override.yml up -d --no-deps slidev`) |
| Portal pages | `powershell -NoProfile -ExecutionPolicy Bypass -File portal/deploy.ps1` |
| Dashboards (DataEase) | A change in `dataease/gate/` or `dataease/lib/`: `docker restart gfm-dataease-gate`. In `dataease/web/` or `dataease/i18n/`: `docker exec gfm-dataease-web nginx -t` (must say "successful"), then `docker restart gfm-dataease-web`. In `dataease/compose.yml`: `docker compose -p gfm-dataease -f dataease/compose.yml up -d`. The dashboards themselves: `dataease/README.md`, "Change the dashboards". |
| Nightly backup | `docker restart gfm-backup` (only after a change of `nightly-backup/nightly.sh`) |

Before a rebuild, keep a copy of the old image so you can go back quickly, for example
`docker tag gfm-portal-portal-api portal-api-rollback:<date>`.

## 5. Roll back (go back to how it was)

First decide **what** to take back: only the part that is broken. Then:

1. **Code:** `git log --oneline -5` shows the version before the change. Take that part's files back with
   `git checkout <that version> -- <folder>` and deploy that part again with the command from the table above.
   The portal pages: `git checkout <that version> -- portal`, then `portal/deploy.ps1`.
2. **A rebuilt image, quickly:** `docker tag portal-api-rollback:<date> gfm-portal-portal-api`, then the part's
   `docker compose ... up -d --no-build --no-deps --force-recreate <service>`.
3. **A database migration:** most migrations have a partner file `NNN_name_rollback.sql` next to them. Run it like a
   migration (as supabase_admin, `ON_ERROR_STOP=1`), then `019_restrict_public_functions.sql` again. Newest first
   when there are several.
4. **The whole database** (only if data was lost): restore a dump into a **new, empty** database and swap it in,
   never with `pg_restore --clean` over the running one. The tested steps are in `docs/handoff/round6/ops.md`,
   "Restore (commands)". Ask the owner first.
5. **An update from the Update button** that could not go back by itself ("needs a person"): `updater/README.md`,
   "Roll back an update by hand".

Always finish with `health.ps1`, and write down what you did (date, commands, result) in the handoff note.

## 6. Golden rules

- Never run `docker compose down -v`: the `-v` deletes the data volumes.
- Never touch the live database, containers or files to "try something". Use a worktree and the throw-away test
  server `gfm-test-r2-db`.
- Back up the database before every migration. Restore only into an empty database.
- Never print or share a secret (`.env`, `secrets\`, tokens, keys).
- Hiding a button is not security: portal-api and the database check every request (`portal-api/roles.py`).
- Every text people read is in the language catalogs (`portal/i18n/`, 14 languages, German with "du", Spanish with
  "tú"). A new text needs all 14.
- Keep Preach My Gospel words ("New people being taught", "covenant path", ...) as they are.
- A PowerShell file (`.ps1`) with letters beyond English is saved as "UTF-8 with BOM", or the Update button stops
  (`updater/README.md`, "Test").

## 7. Where to read more

| Question | Read |
|---|---|
| How does one folder work? | Its `README.md` (`portal/`, `roster-importer/`, `slidev/`, `dataease/`, `nightly-backup/`, `updater/`, `ops-tests/`) |
| Why is something the way it is? What changed when? | `docs/handoff/00_START_HERE.md` (the index) and the round notes `docs/handoff/round2` ... `round9` |
| Who may see and change what? | `docs/handoff/04_AUTH_ROLES_AND_PERMISSIONS.md` and `portal-api/roles.py` |
| Which files look active but are not? | `docs/handoff/17_FILES_THAT_LOOK_ACTIVE.md` |
| The first operations guide (20 Sep) | Removed in round 12 (it described Appsmith and Superset); it is in the git history |
