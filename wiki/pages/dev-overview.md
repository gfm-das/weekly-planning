---
title: Developer docs
slug: dev-overview
lead: is the starting point for anyone who works on the code of Weekly Planning 3.0 (or uses an AI assistant to do so).
summary: Map of the developer pages: architecture, folders, database, tests, deploy on Ubuntu.
status: full
navboxes: [dev]
access: private
infobox_title: Developer docs
icon: "🧰"
infobox_rows: ["Audience|Developers, AI assistants", "Server|Ubuntu, Docker", "Rules|CLAUDE.md in the repository", "Pages|5"]
tags: [dev, admin]
---

## Usage

Read these pages in this order:

1. [Architecture](dev-architecture.html): which parts exist, how a request travels, where rights are decided.
2. [Folders and services](dev-folders.html): what every folder of the repository holds, and every container with its port.
3. [Database and migrations](dev-database.html): the baseline, numbered migrations, rollbacks, row-level security, roles.
4. [Testing](dev-testing.html): every test suite and the exact command, on Ubuntu.
5. [Deploy and roll back on Ubuntu](dev-deploy-ubuntu.html): releases, the updater, by-hand deploys, health, backups.

The rules for working in the repository (small steps, worktrees, back up before a database change, no secrets in Git) are in `CLAUDE.md` in the repository root. The history of every round, with the exact deploy and rollback steps, is under `docs/handoff/` and `docs/CHANGE-HISTORY.md`.

## How it works

These pages are written from the handoff notes (`docs/handoff/`), which stay the long version. The handoff notes of rounds 2 to 12 still show the old Windows commands; these pages show the Ubuntu ones. When a handoff note and the code disagree, the code is right.

## Permissions

Reading these pages needs a portal sign-in (they are in the Data and admin family of pages). They contain no passwords, tokens or personal data, and must never get any.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| A command here fails | Check you are in the repository folder (`~/weekly-planning` on the server) and that Docker runs: `docker ps` |
| The page and the code disagree | Trust the code; fix the page in the same change |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | First version, collected from the handoff notes (round 13) |

## See also

- [Server overview](server-overview.html)
- [Health check](health-check.html)
- [Backups and restore](backups-and-restore.html)
