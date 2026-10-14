---
title: Database and migrations
slug: dev-database
lead: explains how the database schema is built, how a numbered migration is written and applied, and how rights are enforced.
summary: Baseline, migrations, rollbacks, rights check, analyst logins.
status: full
navboxes: [dev]
access: private
infobox_title: Database
icon: "🛢️"
infobox_rows: ["Engine|PostgreSQL (Supabase)", "Container|gfm-beta-supabase-db-1", "Fresh install|portal-api/baseline", "Migrations|portal-api/migrations"]
tags: [dev, database]
---

## Usage

**A new migration**

1. Look in `portal-api/migrations/` for the highest number and use the next one: `NNN_name.sql` and `NNN_name_rollback.sql`.
2. Write it as **one transaction**, applied as `supabase_admin` with `ON_ERROR_STOP=1`. Every new SECURITY DEFINER function must `REVOKE EXECUTE ... FROM PUBLIC` and grant by name.
3. Test it on a **throw-away copy**: a disposable `supabase/postgres` container with the latest backup restored into it. Never test on the live database.
4. After it, run `019_restrict_public_functions.sql` (the rights check; it must end with COMMIT).
5. If a fresh install should include it, tell the installer (`install/run-install.sh` applies every migration newer than 040) and, when needed, rebuild `portal-api/baseline/`.

**Before any change to the live database:** back up, with a way back.

```bash
docker exec gfm-beta-supabase-db-1 pg_dump -U supabase_admin -d postgres -Fc -f /tmp/b.dump
docker cp gfm-beta-supabase-db-1:/tmp/b.dump backups/beta-pre-<what>-<stamp>.dump
pg_restore --list backups/beta-pre-<what>-<stamp>.dump | head      # check that the dump is readable
```

A restore always goes into a new, empty database that is then swapped in, never `pg_restore --clean` over the running one (see [Backups and restore](backups-and-restore.html)).

## How it works

- **`portal-api/baseline/000_baseline.sql`** is the whole schema as of migration 040. It is stored byte for byte (`.gitattributes` keeps its line endings). A fresh install applies it, then every newer migration, each followed by 019.
- **`portal-api/migrations/history/`** holds 010 to 040 and their rollbacks: the story of how the database got here. They cannot be replayed on an empty database (the first tables came from an older system).
- **The updater** applies only files named `NNN_name.sql` in `portal-api/migrations/` (never `history/`), in order, each followed by 019.
- **Planning catalogue guards:** questions and sections are never deleted, only retired (`active = false`); a protected question stays on the form because reports read it. A fresh install therefore still contains the retired Facebook and social-media rows of the old catalogue, switched off; `release/scan.sh` fails if one of them is ever active.
- **Rights, second line:** row-level security and checked functions (`can_access_area`, `can_edit_planning_report`, ...). The Call-ins summaries run with owner rights and enforce access with written checks: a change to RLS policies on the planning tables must be repeated there.
- **Do not rename casually:** `current_user_context`, `current_user_scope`, `reporting_weeks`, `weekly_area_reports`, the weekly child tables, `current_reporting_sunday()`, `can_access_area()`, `portal.presentation_access`, the importer's audit tables. The key indicator "friends found" keeps its hidden names (`friends_found_*`) although it is shown as New People Being Taught.
- **Group role `gfm_db_analysts`** (migration 043): full rights on `public`, `portal` and `dashboards` for the Data Analysts' personal logins, made with `tools/add-analyst-login.sh`. See [DBeaver access](dbeaver-access.html).
- **Read-only login for Dashboards:** `gfm_dashboard_reader` sees only the `dashboards` views (organisation units and numbers, no people).

## Permissions

Applying a migration needs `supabase_admin` inside the database container. Analyst logins are for data work, not for schema changes that the application depends on: those go through a numbered migration.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| 019 does not end with COMMIT | A function is callable by PUBLIC; fix the migration, not 019 |
| Baseline differs from the live schema | `portal-api/baseline/check-baseline.ps1` compares them (PowerShell only so far) |
| A migration is not picked up by the updater | Its file must be directly in `portal-api/migrations/` and named `NNN_name.sql`; a header line `updater: install by hand` keeps it from being applied automatically |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | Collected from `docs/handoff/03`, `04` and `CLAUDE.md` for Ubuntu (round 13) |

## See also

- [Backups and restore](backups-and-restore.html)
- [DBeaver access](dbeaver-access.html)
- [Roles and permissions](roles-and-permissions.html)
