# DA Management (the `roster-importer` folder)

DA Management is the "back office" of the mission portal. The portal shows it inside a frame (menu: DA
Management). It is a small Python web server (Flask). Only the managers of the mission can open it:

- the **President** (a role set by hand),
- a **Data Analyst** (set by hand, usually as an *additional* role on top of the main role),
- an **AP**, but only while their AP assignment is in force.

Office gives no access here. A saved role "AP" alone never gives access either: the AP assignment must be in force.

## What you can do here (the menu)

| Menu | What it does |
| --- | --- |
| Roster Import | Upload the complete transfer roster (CSV or XLSX), check what would change, apply it. |
| Account Manager | Every missionary serving now and the state of their sign-in; send invitations and password emails. Each missionary has a settings page: role, Account active, area (with a date), languages. |
| Planning questions | Change the questions of Weekly Planning (sections, questions, answer choices, show/hide rules). |
| Historical CSV | Import the old Weekly Planning form export (from before the portal) into the reports, and the new members, friends with a baptismal date and high-potential friends named in them. |
| Area mappings | Say which current area each old area name of the Historical CSV stands for. "Close old area" is written to Import history and can be undone. |
| Places | Close and reopen zones, districts and areas. Closing a zone or district moves what is inside it first (you choose where each goes); every change is in Import history with Undo. A roster upload wins over a change made here. |
| Staff accounts | Sign-ins for the President, office staff and Data Analysts who are not missionaries. |
| Data uploads | Numbers the portal does not collect: area data, the finding export, zone history, referral archive, rates, baptism history. |
| People upload | New members (names and details) from a spreadsheet such as the office's Vollzogen sheets or the New Member Database Raw form. |
| Import history | Everything that was imported or changed, with who did it, and **Undo**. |
| DA Docs | A short guide. |
| Updates | This computer's version, "Check for updates", "Update now". |

Three promises hold everywhere:

1. **Check first, then apply.** Every import shows what it would change before anything is saved.
2. **Everything can be undone.** Every import and every account change is one *batch* in Import history, with every
   row it changed as it was before and after. Undo puts the rows back, or refuses (and changes nothing) when a row
   was changed again later.
3. **No email by surprise.** An import never sends email. Only Account Manager and Staff accounts send email, after
   the manager has seen and confirmed the list.

## Which file does what

Every file starts with a short explanation. The big picture:

**Putting it together**

| File | Job |
| --- | --- |
| `app.py` | Builds the web server: the checks before every page, every group of pages, and gzip on the way out. |
| `settings.py` | The settings from the environment (`.env`), in one place. |
| `database.py` | Opening the database (`database.connect()`, `database.cursor(conn)`). Keeps a few connections open and lends them again. |
| `page.py` | The frame of every page: menu, colours, translations (the portal's `i18n.js`), and small HTML helpers. |
| `sign_in.py` | Who may use DA Management: sign-in from the portal, the old shared password, the form token. `/login`, `/logout`. |
| `roles.py` | The roles, and who may give which role. |
| `supabase_auth.py` | Talking to Supabase Auth (invitations, password emails, moving a sign-in to a new email). |
| `batches.py` | Writing every change down as a batch, so Import history can show and undo it. |
| `places.py` | The current areas of the mission (the area lists on the pages). |

**The pages** (each file has one Flask "Blueprint" called `pages`)

| Menu | Page file | Its rules |
| --- | --- | --- |
| Roster Import | `transfer_pages.py` | `roster_file.py` (reading the file), `transfer.py` (compare and save) |
| Account Manager | `account_manager.py`, `account_page.py` | `account_links.py` (which sign-in, what to send), `account_roles.py` (the role plan), `account_changes.py` (history, undo rules), `account_moves.py` (a move saved for a later day) |
| Planning questions | `planning_questions_pages.py` | `planning_questions.py` |
| Historical CSV | `historical_pages.py` | `historical_import.py` (reading and staging), `historical_units.py` (wards and branches), `historical_preview.py` (the check), `historical_apply.py` (Apply) |
| Area mappings | `mappings_page.py` | (in the same file) |
| Places | `places_admin.py` | (in the same file: the rules are `change_place()`) |
| Staff accounts | `staff_accounts.py` | (in the same file) |
| Data uploads | `data_upload_pages.py` | `data_uploads.py`, `data_files.py`, `data_types.py`, `data_names.py`, `data_text.py` (every text) |
| People upload | `people_upload_pages.py` | `people_upload.py` (placing rows, Apply), `data_types.parse_people` (reading the sheet) |
| People in uploads (both) | `people_pages.py` (the "same person?" questions) | `people_match.py` (who is the same person), `people_csv.py` (the people in a Historical CSV row), `people_write.py` (saving them and loading the current week) |
| Import history | `import_history.py` | `undo.py` |
| DA Docs | `docs_page.py` | |
| Updates | `updates_page.py` | (talks to `updater/gfm-updater.ps1` through two folders) |

## How the data flows (two examples)

**A transfer roster.** `transfer_pages.py` saves the uploaded file for a moment → `roster_file.read_roster()` turns
it into one row per missionary → `transfer.preview()` compares the rows with the database and lists every change →
the manager ticks "I reviewed" → `transfer.apply_roster_batch()` locks the tables, takes a snapshot, writes
everything in one transaction, and records every changed row (`batches.py`) → the batch is in Import history,
where `undo.py` can put everything back.

**A missionary's account page.** `account_page.py` shows the page → while the manager chooses a role, area or date,
the page asks `/accounts/<id>/role-plan` and shows "What saving will change" (`account_roles.role_plan()`) → Save
runs the same plan again, checks who may do it (`roles.py`), saves, and writes an ACCOUNT batch
(`account_changes.py`) → Import history can undo it.

## Settings (`.env`, next to `docker-compose.yml`)

| Name | What it is |
| --- | --- |
| `DATABASE_URL` | Where the mission database is. Needed. |
| `MISSION_ID` | The mission shown when a person's own mission is not known (Frankfurt: 2). |
| `SECRET_KEY` | Signs the session cookie. Long and random. |
| `IMPORTER_PASSWORD` | The old shared password. Empty: no password sign-in, only through the portal. |
| `SUPABASE_AUTH_INTERNAL_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Supabase Auth, for sign-ins and emails. |
| `PASSWORD_REDIRECT_URL` | Where the link in an invitation or password email leads (the portal). |
| `PERSON_KEY_SECRET` | Turns Church person ids of the finding export into codes. Set once, never change it. |
| `UPLOAD_DIR`, `UPDATES_DIR`, `PORTAL_I18N_SRC` | Folders and the translation script's address (the defaults are right). |

Secrets are only read, never printed. `.env` and backups are never committed.

## Running it

```powershell
docker compose -p roster-importer -f roster-importer/docker-compose.yml up -d --build --no-deps roster-importer
```

The page is on port 8090. `/health` answers `{"status": "ok"}` while the program runs (it does not look at the
database). The Dockerfile copies every `*.py` file of this folder (not `tests/`).

## Database

DA Management uses the portal's database. Its own migrations are in `migrations/` (001 to 003, applied long ago);
the later ones it needs are the portal's (`portal-api/migrations/`, for example 021 additional roles, 024 planning
questions, 027 staff accounts, 033 data uploads). The pages expect all of them (they no longer check for 001, 021
and 027 on every page). Back up before running any migration, and run them as `supabase_admin`.

## Testing

All tests use made-up data. They never touch the live database: the database tests refuse to run unless the
database name says it is a throw-away test copy.

1. **Without a database** (fast):
   ```
   docker run --rm --network none -v <repo>:/repo -w /repo/roster-importer
     -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer
     python -m unittest tests.test_rules tests.test_historical_rules tests.test_data_files tests.test_updates_page tests.test_page_words
   ```
2. **DA Management with a database** (`test_management`, `test_accounts`, `test_data_uploads`): a throw-away copy
   whose name starts with `roster_management_test_`, reached under the name `gfm-beta-supabase-db-1`
   (`--add-host gfm-beta-supabase-db-1:<test server IP>`), with `MANAGEMENT_TEST_DATABASE=<that name>`,
   `PERSON_KEY_SECRET`, `IMPORTER_PASSWORD` and a dummy `SUPABASE_SERVICE_ROLE_KEY` set, and the whole repository
   mounted (some tests read `portal/`). The tests replace the email sender with one that fails, so no email can go out.
3. **Planning questions** (`test_planning_questions`): a throw-away database whose name contains `test`, with
   `PLANQ_TEST_THROWAWAY=yes` (see the top of that file).

The texts of the pages are checked by the portal's translation test (`node portal/tests/i18n-check.cjs`): every
text a person sees must be in the 14 catalogs of `portal/i18n/`.

## Details worth knowing

### Speed

Measured in round 9 (see `docs/handoff/round9/dam.md`). What keeps the pages quick:

- `database.connect()` lends a kept connection instead of opening a new one (opening one took longer than most pages
  need for all their questions). A kept connection is reset (DISCARD ALL) before it is lent again.
- Pages go out packed with gzip (`app.pack`): Account Manager is 12 KB on the way instead of 107 KB.
- The page frame is read once (`page.frame`), not for every page.
- Area mappings sends each row's area list short (only the chosen area) and fills in the whole list the first time a
  row's list is used, so the page is 115 KB instead of 935 KB.

### Transfer roster

Headings: Missionary, ID, Type, Assignment, Status, Zone, District, Area, Unit, Email, Arrival Date, Release Date,
Position, Position Abbr. `Ecclesiastical Unit` is read as Unit. ID is the missionary's lasting key. Only Active and
In-field rows are read.

The roster must be **complete**: a missionary who is not in it is released. DL, ZL, STL and AP come from Position
Abbr; President, Data Analyst and Office are never changed by a roster. An account whose saved role is DL, ZL, STL or
AP but whom the roster no longer gives that role goes back to Missionary (the preview lists them; Undo restores them).
A roster dated ahead changes assignments on its date; everyone keeps today's area and role until then. A roster for
a date that already has a transfer replaces it; a roster cannot go underneath a change recorded for a later day.
When the roster ends the signed-in AP's own access, the preview says so, and applying it today needs an extra tick.

### Account page

The Main role list preselects the role the account has today, so saving with the same role and area never ends a
leadership assignment. "What saving will change" says, before saving, which assignment a change ends or starts and
on which day, and asks before one ends. A DL/ZL/STL/AP role is never recorded before its assignment starts, and AP
never while the AP assignment has an end date. A page opened before its rows changed is not saved (reload it).
Ending your own DA Management access needs the "I understand" tick.

### Historical CSV

The first version reads the original Weekly Planning form export (Timestamp, Email Address, companionship,
Ward/Branch, reporting Sunday). The latest form per companionship, Sunday and ward/branch counts. Reports are kept
per area, unit and Sunday, like the portal: a companionship serving two units sent one form per unit, and both are
imported. The check shows each Ward/Branch answer with the unit it was matched to, and lets you correct it.
Labels that differ only by punctuation or spacing would share a report key: you keep one or combine them. With
*Combine*, several old areas of the same current area, unit and week are added up; without it, you choose. With
*Replace*, an existing report of that unit and week is replaced (never merged, so importing the same file twice gives
the same result); with *Stop*, the check waits until you resolve it. A label imported earlier into another area is
moved in the same batch, so it never counts twice. Apply works the check out again under lock and refuses anything
that changed since you looked (a signed state token).

Original labels, every answer and the person cards are kept in the staging tables and `historical_planning_details`.
Historical person details are kept for review, not merged into today's people.
