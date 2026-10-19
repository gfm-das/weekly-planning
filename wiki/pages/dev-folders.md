---
title: Folders and services
slug: dev-folders
lead: lists what every folder of the repository holds and which container each service runs in.
summary: Repository folder map and service table.
status: full
navboxes: [dev]
access: private
infobox_title: Folders
icon: "🗂️"
infobox_rows: ["Server folder|~/weekly-planning", "Containers|Docker Compose, one project per part", "Network|gfm-network"]
tags: [dev]
---

## Usage

Find the folder for a task, then read that folder's own `README.md`.

| Folder or file | What it holds |
| --- | --- |
| `portal/` | The portal's pages (one `.html` per page), the shell (`index.template.html`, `portal-enhancements.js`), styles, the 14 catalogs (`i18n/`), the Whiteboard (`whiteboard/`, built from `whiteboard-build/`), nginx settings, `deploy.sh` |
| `portal-api/` | The API: `app.py`, `roles.py` (every role decision), `planning.py`, `callins.py`, `charts.py`, `dashboard.py`, `archetypes.py`, `whiteboards.py`, `reminders.py`; `migrations/` (numbered, with `_rollback.sql` partners; `history/` holds 010 to 040); `baseline/` (the schema of a fresh install); `tests/` |
| `roster-importer/` | DA Management: imports, accounts, planning questions, data uploads, Places, Import history with Undo, Updates; its own `migrations/` and `tests/` |
| `slidev/` | Presentations: `manager/` (server, library, Studio, `gfm-addon`), `package.json` (pinned versions), `tests/` |
| `dataease/` | Dashboards: compose file, sign-in gate, nginx front, dashboard descriptions, `seed-dashboards.sh`, `translate-dashboards.sh`, `i18n/`, `tests/` |
| `supabase/` | The Supabase stack: compose files, database start-up SQL, Kong settings, edge functions |
| `nightly-backup/` | The nightly database backup container (`nightly.sh`, tests) |
| `cloudflared/` | The optional Cloudflare tunnel container |
| `updater/` | `gfm-updater.sh`, `quick-tests.sh`, `register-watcher.sh`, settings example, tests (the `.ps1` files are the old Windows twins) |
| `install/` | The installer: `install.sh`, `run-install.sh`, the setup form (`app/`), `sql/`, tests |
| `release/` | How a public release is made: `build-release.sh`, `scan.sh`, `verify.sh`, `publish.sh`, notes, tests (kept out of releases) |
| `tools/` | Helpers for Data Analysts: `add-analyst-login.sh`, `notebooks/starter.ipynb` |
| `wiki/` | This wiki: Markdown in `pages/`, `build.py`, the built `out/` and `out-private/` |
| `docs/` | `README-start-here.md`, `CHANGE-HISTORY.md`, `DBEAVER.md`, `handoff/` (history of every round) |
| `health.sh`, `start-gfm.sh` | The health check; start-up after an unclean Docker stop |

## How it works

Services (container names are settings; the names below are the installer's defaults):

| Service | Purpose | Compose files (project) | Ports |
| --- | --- | --- | --- |
| Portal | The pages | `portal/portal-compose.yml` + `portal/local-override.yml` (`portal`) | 8070 |
| portal-api, portal-reminders | The API behind `/api/`; push reminders | `portal-api/compose.yml` (`gfm-portal`) | 8091 inside the network |
| DA Management | Management and imports | `roster-importer/docker-compose.yml` (`roster-importer`) | 8090 |
| Presentations | Library, Studio, decks | `slidev/slidev-compose.yml` + `slidev/local-override.yml` (`slidev`) | 3030 (library, Studio, API), 8089 (decks) |
| Dashboards | DataEase and its helpers | `dataease/compose.yml` (`gfm-dataease`) | 8088 |
| Nightly backup | Dumps at 02:30 | `nightly-backup/backup-compose.yml` (`gfm-backup`) | none |
| Database stack | PostgreSQL, Auth, REST, edge functions | `supabase/supabase-compose.yml` + `supabase/beta-override.yml` (`gfm-beta`, `--env-file supabase/.env`); database container `gfm-beta-supabase-db-1` | database on `127.0.0.1:54322` (server only) |
| Tunnel (optional) | Cloudflare tunnel | `cloudflared/compose.yml` (`gfm-cloudflared`) | none |

The old Frankfurt server's container names differ in places (they carry generated suffixes); `health.sh` reads the real names from `portal/.env` and `slidev/.env`.

## Permissions

Never commit `.env` files, `answers.json`, dumps, spreadsheets or a `secrets/` folder; `release/scan.sh` refuses a release that holds one. `backups/` exists only on the server and is ignored by Git.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Not sure which compose project a container belongs to | `docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' <container>` |
| A file looks active but is not | `docs/handoff/17_FILES_THAT_LOOK_ACTIVE.md` |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | Collected from `docs/handoff/14_FILE_AND_SERVICE_MAP.md` for Ubuntu (round 13) |

## See also

- [Architecture](dev-architecture.html)
- [Server overview](server-overview.html)
