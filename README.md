# Weekly Planning

A weekly planning and reporting portal for a mission: weekly planning, Call-ins, Overview, calendar, announcements, Whiteboard, Archetypal
Health, Presentations, Dashboards and DA Management (accounts, roster and data uploads), in 14 languages. It runs on one computer, in Docker.

**Not a developer? Start on the website: https://gfm-das.github.io/weekly-planning**  (big download buttons, what you need, plain steps).

## Install it in one command
You need Docker (Docker Desktop on Windows and Mac, Docker Engine on Linux) and, on Windows, Git for Windows.

- Windows: download `install-windows.cmd` from the [latest release](https://github.com/gfm-das/weekly-planning/releases/latest) and double-click it.
- Mac and Linux: download `install-weekly-planning.sh` from the same page, then run `bash install-weekly-planning.sh`.
- Or by hand: `git clone https://github.com/gfm-das/weekly-planning` and run `./install/install.sh` (on Windows `install\install.cmd`).

A page opens in your browser and asks a few questions: the mission's name, the default language, the first Data Analyst's account, and
(optionally) email, a web address and a Cloudflare tunnel. A computer without a screen is asked the same questions in the terminal.
A few minutes later the portal is running and you can sign in. Load the roster afterwards in DA Management.

## Updates
New versions are published here as releases (`v1.0.0`, `v1.1.0` ...). An installed copy follows them: DA Management > Updates shows
what is new and installs it only when a person asks, after testing it, saving a way back and checking the system's health.

## What is in this repository
`install/` the installer, `portal/` the pages, `portal-api/` the server and database baseline and migrations, `roster-importer/` DA Management,
`slidev/` Presentations, `dataease/` Dashboards, `supabase/` the database stack, `nightly-backup/`, `cloudflared/`, `updater/`, `wiki/` the manual.
Start with `install/README.md`. Third-party software and content: `NOTICE.md`. Licence: MIT (`LICENSE`).

This repository is a published copy: it is updated only by releases. Please report problems as issues.
