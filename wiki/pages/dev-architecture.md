---
title: Architecture
slug: dev-architecture
lead: shows which parts Weekly Planning 3.0 is made of, how a request travels through them, and where the rights are decided.
summary: Parts, ports, request flow and the security boundary.
status: full
navboxes: [dev]
access: private
infobox_title: Architecture
icon: "🏗️"
infobox_rows: ["Runs on|One Ubuntu server, Docker", "Network|gfm-network (external)", "Database|PostgreSQL (Supabase stack)", "Rights|roles.py + row-level security"]
tags: [dev, architecture]
---

## Usage

Use this page to find out which part to change for a given task, and which parts a change reaches.

```text
Browser / phone
  |
Portal (nginx) :8070 ---- static pages (portal/)
  |  \-- /api/* --> portal-api :8091 --> Postgres / Supabase Auth
  |                  portal-reminders (same code: push reminders)
  +--> DA Management :8090 ----------> Postgres + Supabase Auth; leaves update requests for the updater
  +--> Presentations :3030 (library, Studio) --> portal-api rights check --> Slidev processes (3100+)
  |                  :8089 (the deck address: published decks and the deck editor)
  +--> Dashboards :8088 --> nginx front --> gate (the portal's signed cookie) --> DataEase
                                                DataEase --> dbproxy --> Postgres (read-only login)
```

The ports are defaults; each can be changed by a setting (`GFM_PORT_*`, see `health.sh`). All services use the external Docker network `gfm-network`; DataEase keeps its own internal network. The portal shows every other part inside its own frame, so people see one website.

## How it works

| Part | Folder | What it does |
| --- | --- | --- |
| Portal | `portal/` | The shell and menu, themes, the 14 languages (`portal/i18n/`), the frames, the pages, the service worker |
| portal-api | `portal-api/` | Python (Flask): sign-in, rights and stewardship (`roles.py`), Weekly Planning, Call-ins, calendar, announcements, files, Overview and glimpse, charts for Presentations, Whiteboard, Archetypal Health, the Dashboards cookie; `reminders.py` for push jobs |
| Database | `supabase/` | PostgreSQL, Auth, REST, edge functions (the Supabase stack); the data, and the second line of rights (row-level security and checked functions) |
| DA Management | `roster-importer/` | Python (Flask): accounts, planning questions, roster and historical imports, data uploads, places, import history with Undo, the Updates page |
| Presentations | `slidev/` | Node: `manager/server.mjs` (library, sessions, Studio, building and serving decks), `manager/gfm-addon` (charts) |
| Dashboards | `dataease/` | DataEase with a sign-in gate and an nginx front, dashboard descriptions, setup scripts, `i18n/` |
| Backups | `nightly-backup/` | A container that only reads the database and writes dumps |
| Updater | `updater/` | A program on the server (not a container) that installs releases on request |
| Health | `health.sh` | A script that only looks and prints one row per check |

Rules that shape the code:

- **The database is the one source of truth.** Sunday is the reporting-week key; plans are area, ward-or-branch and week scoped.
- **Rights are checked on the server, twice.** `portal-api/roles.py` (and the copy in `roster-importer/`) decide who may do what; row-level security and checked functions in the database decide again. Hiding a button is not security.
- **`portal-api` and `roster-importer` are separate images.** `roles.py` and `staff_accounts.py` exist in both and must be kept identical.
- **Every import and place change is one batch** in Import history with a before and after of each row, and Undo.
- **14 languages:** every interface text has a key in every catalog under `portal/i18n/`.
- **Decks run on their own address.** Slidev decks contain code, so published decks and the deck editor are served on the deck address (8089), not on the manager address (3030) where the sign-in lives.

## Permissions

Roles: `MISSIONARY`, `DL`, `ZL`, `STL`, `OFFICE`, `AP`, `PRESIDENT`, `DATA_ADMIN` (shown as Data Analyst). Managers are AP, President and Data Analyst. A DL sees a district, a ZL a zone, managers the mission; Office edits the calendar and announcements. The full table is on [Roles and permissions](roles-and-permissions.html).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| A page works for managers but not for a ZL | The API check in `roles.py`, then the row-level security of the table; the menu is not the cause |
| A change in `roles.py` has no effect in DA Management | The copy in `roster-importer/` was not changed too |
| A new SECURITY DEFINER function is callable by anyone | Missing `REVOKE EXECUTE ... FROM PUBLIC`; re-run `019_restrict_public_functions.sql` after every migration |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | Collected from `docs/handoff/02_ARCHITECTURE.md` for Ubuntu (round 13) |

## See also

- [Folders and services](dev-folders.html)
- [Database and migrations](dev-database.html)
- [Roles and permissions](roles-and-permissions.html)
