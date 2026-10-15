---
title: Nightly backup
slug: nightly-backup
lead: is the container that copies the mission database every night, checks the copy, and keeps it for 14 days.
summary: How the nightly backup works, how to check it, restore from it and change it.
status: full
navboxes: [admin]
infobox_title: Nightly backup
icon: "🗃️"
infobox_rows: ["Container|gfm-backup", "Time|02:30 (DataEase 02:15)", "Keep|14 days", "Folder|backups/nightly"]
tags: [admin, ops, backup]
---

## Usage

Think of it as a photocopier that wakes up every night, copies the mission's notebook, checks that the copy can be read, puts it in a drawer, and throws away copies older than two weeks.

**Every day, check it:**

```bash
bash health.sh                              # first row, "Nightly backup", should say OK
tail -n 20 backups/nightly/nightly.log      # what the last nights did
docker logs gfm-backup                      # the same lines, from the container
cat backups/nightly/last-run.txt            # "OK <time>" or "FAILED <time>: <parts>"
```

**One backup right now** (for example before a change):

```bash
docker exec gfm-backup /backup/nightly.sh --now
```

**Before any database change**, also make a named dump. See [Backups and restore](backups-and-restore.html).

### Restore (bring a copy back)

Always restore into an **empty** database. Never use `pg_restore --clean` into the running one: it makes the database rights wider.

1. To look at a copy or take single rows out of it: restore it into a new database on a throw-away test server, look, then drop that database.
2. To replace the whole database, in this order:
   1. Take a dump of the current state first.
   2. Copy the nightly `beta-<date>.dump` into the database container (`docker cp`) and restore it into a **new** database called `postgres_restored`. It must end without errors. On a brand-new server, apply the roles file first.
   3. Stop everything that uses the database (the other `gfm-beta-*` containers, portal-api, portal-reminders, DA Management, `gfm-backup`).
   4. Rename the databases: the old one to `postgres_before_restore_<date>`, the new one to `postgres`.
   5. Restart the database container, start the others, run migration 019 again, then `bash health.sh`.
   6. Drop the old database only when everything is fine.

The exact tested commands are in `docs/handoff/round6/ops.md`, section "Restore (commands)". They were written for Windows: only the paths differ on Ubuntu. If you have never done this, do it first on a throw-away server, and ask a developer to sit with you.

## How it works

```
 02:15  gfm-dataease-backup  -> backups/nightly/dataease-<date>.sql.gz
 02:30  gfm-backup
          1. a dump of each database -> backups/nightly/beta-<date>.dump
          2. its roles (no passwords) -> beta-roles-<date>.sql.gz
          3. small extra jobs in nightly-backup/hooks.d/ (checks the DataEase file is there and readable)
          4. a part that failed is tried again every 15 minutes, 3 times
          5. files older than 14 days are deleted (only files named like the ones above)
          6. last-run.txt and nightly.log say what happened
 morning  health.sh reads last-run.txt and the newest beta-*.dump: OK, waiting, SKIPPED or FAIL
```

Every copy is first written as `<name>.partial`. Only when `pg_restore` can read it and it holds table data is it renamed to `<name>.dump`. So a file called `.dump` is always complete.

The files: `nightly-backup/backup-compose.yml` (time, days to keep, which databases), `nightly-backup/nightly.sh` (the program in the container), `nightly-backup/hooks.d/` (extra jobs), and the password file `nightly-backup/secrets/db-password` (never in Git, never printed).

**All backups are on the one server.** There is no off-site copy yet. Copy the folder `backups/nightly` somewhere else now and then.

### Change something

| To change | Do |
| --- | --- |
| Time, days to keep, databases | Edit `nightly-backup/backup-compose.yml`, then `docker compose -p gfm-backup -f nightly-backup/backup-compose.yml up -d` |
| `nightly.sh` | Then `docker restart gfm-backup` (the container reads it at start) |
| A hook or the password file | Nothing to restart; they are read every night |
| The old second database stack (`production=...` in `BACKUP_TARGETS`) | When that stack is switched off, remove it there, or every night fails on purpose |

### Switch it off for good

`docker compose -p gfm-backup -f nightly-backup/backup-compose.yml down` (the backups stay). Then the health row says FAIL while backup files exist without the container, so the "Nightly backup" part of `health.sh` must be taken out too. Ask the owner first.

## Permissions

Server operators and Data Analysts with a shell on the server. The password file must stay private.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Health row FAIL | `cat backups/nightly/last-run.txt` and `docker logs gfm-backup` say which part failed |
| Health row "waiting" | New install: the first run is at 02:30. Run `docker exec gfm-backup /backup/nightly.sh --now` |
| Every night fails for one database | That database or its network is gone. Remove it from `BACKUP_TARGETS` |
| "Password" errors in the log | The password file is wrong or has a trailing newline or Windows line ending. Rewrite `nightly-backup/secrets/db-password` with the current database password |
| Disk is full | Check `df -h` and the size of `backups/`. Move old files away (do not delete without the owner) |
| DataEase file missing | Check `docker logs gfm-dataease-backup` and `nightly-backup/hooks.d/README.md` |
| A file ends in `.partial` | That copy did not finish. It is not a backup. The next try replaces it |

## History

| Date | Note |
| --- | --- |
| Round 6 | Nightly backup container introduced |
| Oct 2026 | Page written from `nightly-backup/README.md` |

## See also

- [Backups and restore](backups-and-restore.html)
- [Health check](health-check.html)
- [Dashboards operations](dashboards-ops.html)
- [Server overview](server-overview.html)
