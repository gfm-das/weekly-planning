---
title: Testing
slug: dev-testing
lead: lists every test suite of the repository and the exact command to run it on Ubuntu.
summary: Test commands per part, and what needs a database.
status: full
navboxes: [dev]
access: private
infobox_title: Testing
icon: "🧪"
infobox_rows: ["Run from|The repository root", "Shell|bash (Ubuntu)", "Needs|Docker for most suites", "Rule|Test after every change"]
tags: [dev, tests]
---

## Usage

Run the suites of every part you touched, after every change, from the repository root. The commands below are for bash on Ubuntu (on Windows PowerShell write `${PWD}\dataease` for `$PWD/dataease`).

| Part | Command |
| --- | --- |
| DataEase (front, gate, scripts) | `docker run --rm --network none -v "$PWD/dataease:/d" -w /d node:24-alpine node --test tests/*.test.mjs` |
| DA Management, no database | `docker run --rm --network none -v "$PWD:/repo" -w /repo/roster-importer -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer python -m unittest tests.test_rules tests.test_historical_rules tests.test_data_files tests.test_updates_page tests.test_page_words` |
| DA Management, with a database | On a throw-away copy named `roster_management_test_*` (see `roster-importer/README.md`, Testing) |
| portal-api, no database | `docker run --rm --network none -v "$PWD/portal-api:/app" -v "$PWD/portal:/portal" -w /app gfm-portal-portal-api python tests/test_planning_people.py` (also `test_small_fixes.py`) |
| portal-api, with a database | The `*_db.py` files in `portal-api/tests/`; each refuses to run unless the database name contains `test` |
| Translations | `node portal/tests/i18n-check.cjs` (4 old technical false positives are known) |
| Presentations | `cd slidev && node --test tests/*.test.mjs` (or in a `node:24-alpine` container) |
| Installer | `cd install && node --test tests/*.test.mjs`; the real runs: `bash install/tests/test-install.sh` (about 6 minutes, 2 GB), `test-dataease.sh`, `test-cloudflared.sh`, `test-analyst-login.sh` |
| Release scan and builder | `bash release/tests/test-release.sh`, `bash release/tests/test-publish.sh` |
| Updater | `bash updater/tests/test-updater.sh` (about 50 checks, no Docker, no network) |
| Nightly backup | `bash nightly-backup/tests/test-nightly.sh` |
| Data Analyst login script | `bash tools/tests/test-add-analyst-login.sh` (against a fake `docker`) |

## How it works

- **A database is never touched by a test unless its name says it is a copy.** Tests that need PostgreSQL run on a disposable `supabase/postgres` container with a restored backup, and the container is removed afterwards.
- **Tests that drive a real browser against a real server address** (`edge_*.ps1`) are Windows-era and are left out of releases.
- **Four older tests** of `roster-importer/tests/test_data_uploads.py` (03, 04, 08, 09) fail on `main` today; they are not caused by recent work and do not block.
- **Two Presentations tests measure time** and can fail once on a busy server; the updater's quick tests try them a second time.
- **New behaviour gets a new test.** Report the exact results in the round note (`docs/handoff/roundN/`).

## Permissions

Tests run with no network (`--network none`) wherever they can, and never with real passwords or real people's data. Sample files with real names stay out of the repository.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| `docker: command not found` or permission denied | Install Docker Engine and add your user to the `docker` group |
| An image such as `gfm-portal-portal-api` is missing | Build it first: `docker compose -p gfm-portal -f portal-api/compose.yml build` |
| A `.sh` file fails with "no such file" or `\r` errors | It has Windows line endings; `*.sh` must keep Unix line endings (`.gitattributes`) |
| `i18n-check` fails after a text change | The new key is missing in one of the 14 catalogs in `portal/i18n/` |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | Collected from `CLAUDE.md` and the folder READMEs, shell commands for Ubuntu (round 13) |

## See also

- [Deploy and roll back on Ubuntu](dev-deploy-ubuntu.html)
- [Health check](health-check.html)
