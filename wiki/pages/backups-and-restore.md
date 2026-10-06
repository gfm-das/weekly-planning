---
title: Backups and restore
slug: backups-and-restore
lead: describes automated nightly copies of the database (and DataEase) and how restore is meant to work safely.
summary: Nightly backups and restore caution.
status: full
navboxes: [admin]
infobox_title: Backups
icon: "💾"
infobox_rows: ["Nightly|02:30 Europe/Berlin", "Keep|14 days", "Folder|backups\\nightly", "DataEase backup|02:15"]
tags: [admin, ops]
---

## Usage

### Automatic

| Job | When | Where |
| --- | --- | --- |
| Database dump (`gfm-backup`) | 02:30 | `backups\nightly` |
| DataEase backup | 02:15 | same folder |
| Health row | Next morning | [Health check](health-check.html) “Nightly backup” |

### Before risky work

Before a migration or major change, take a named dump into `backups\beta-pre-<what>-<stamp>.dump` and verify with `pg_restore --list`.

### Restore (high level)

- Restore into a **new empty database** and swap in carefully.
- **Never** `pg_restore --clean` over the live database.
- Detailed tested commands live in operations notes (`nightly-backup/README.md`, round-6 ops handoff).

:::needs-checking
Walk through a restore drill on a throw-away database periodically; this wiki does not duplicate every shell flag.
:::

## How it works

- Container `gfm-backup` uses PostgreSQL client tools, password file under `nightly-backup\secrets\` (not in Git).
- Keeps 14 days then deletes older nightly files.
- **All backups are on this one computer today** — there is no automatic off-site copy (known open item).

## Permissions

Server operators / Data Analysts with access to the office machine.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Health FAIL on Nightly backup | Read `gfm-backup` logs; confirm secrets password file; check disk space |
| Missing DataEase backup | Check `gfm-dataease-backup` and nightly hooks |

## History

| Date | Note |
| --- | --- |
| Round 6 | Nightly backup container introduced |

## See also

- [Health check](health-check.html)
- [Server overview](server-overview.html)
- [DBeaver access](dbeaver-access.html)
