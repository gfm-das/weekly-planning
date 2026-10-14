---
title: Deploy and roll back on Ubuntu
slug: dev-deploy-ubuntu
lead: explains how a change gets from a branch to the Ubuntu server, and how to go back.
summary: Releases, the updater, by-hand deploys, health check, rollback and backups.
status: full
navboxes: [dev]
access: private
infobox_title: Deploy
icon: "🚀"
infobox_rows: ["Server folder|~/weekly-planning", "Normal way|Release + Updates page", "Check|bash health.sh", "Way back|Backup + rollback files"]
tags: [dev, deploy]
---

## Usage

**The normal way: a release.**

```bash
bash release/build-release.sh v1.0.5   # builds backups/release/v1.0.5 (runs the tests twice, about 10 minutes)
bash release/scan.sh <the release folder>   # must be clean (the build runs it for you)
bash release/publish.sh v1.0.5         # prints the plan, changes nothing
bash release/publish.sh v1.0.5 --go    # publishes (only after the owner's go)
```

The server follows the releases: DA Management > Updates shows the newest release and installs it on a person's request, or from the shell:

```bash
bash updater/gfm-updater.sh check      # what is new?
bash updater/gfm-updater.sh update     # install it (asks you to type UPDATE)
bash updater/gfm-updater.sh status     # what the updater found and did
```

The updater tests the new version, checks health, saves a way back (the commit, a database backup, rollback copies of the images, a copy of the portal pages in `backups/updater/<time>/`), installs the migrations (each followed by 019) and the changed parts, checks health again (6 tries, 30 seconds apart) and goes back by itself if that fails. It does not install `dataease/`, `nightly-backup/` or `supabase/`; the Updates page lists such changes for a person. `bash updater/register-watcher.sh` keeps it watching (crontab on Linux).

**By hand, only the part that changed, in this order** (from the repository folder):

```bash
# 0. before a migration: a database backup (see "Database and migrations")
# 1. each new migration, as supabase_admin, then 019 again
docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 < portal-api/migrations/NNN_name.sql
docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 < portal-api/migrations/019_restrict_public_functions.sql
# 2. the programs (keep a rollback tag first: docker tag <image> <name>-rollback:<date>)
docker compose -p gfm-portal -f portal-api/compose.yml up -d --build
docker compose -p roster-importer -f roster-importer/docker-compose.yml up -d --build --no-deps roster-importer
docker compose -p slidev -f slidev/slidev-compose.yml -f slidev/local-override.yml up -d --no-deps slidev
bash portal/deploy.sh                  # the portal pages and translations
docker exec gfm-dataease-web nginx -t && docker restart gfm-dataease-web     # only after a DataEase front change
# 3. always last
bash health.sh                         # every row must say OK
```

## How it works

- `bash health.sh` prints one row per check and exits 1 when a row says FAIL: the web addresses with the answer they must give, the nightly backup (newest dump under 26 hours old), the Cloudflare tunnel (a warning, never a failure), and that no container restarts over and over. `--wait 180` keeps checking after a start. `bash start-gfm.sh` starts everything after Docker stopped badly.
- `portal/deploy.sh` builds `index.html` from the template, writes `site-config.js` (public web name, time zone, default language), copies the pages into the portal container, removes retired files, checks `nginx.conf` and reloads nginx.
- **Settings, not fixed text:** container names, ports, the public web name and the time zone come from the `.env` files and `GFM_*` variables (see `health.sh` and `install/run-install.sh`).
- **Backups:** the container `gfm-backup` writes a `pg_dump -Fc` of the database nightly at 02:30 into `backups/nightly` and keeps 14 days; DataEase has its own backup. Before each deploy with a migration, take `backups/beta-pre-<what>-<date>.dump`. All backups are on the one server unless you copy them away.

## Roll back

- **Code:** `git checkout <version before> -- <folder>`, then that part's deploy command.
- **An image:** `docker tag <name>-rollback:<date> <image>`, then `docker compose ... up -d --no-build --no-deps --force-recreate <service>`.
- **A migration:** its `NNN_name_rollback.sql`, applied the same way, then 019.
- **An update from the Updates page:** automatic; by hand see `updater/README.md`, "Roll back an update by hand".
- **The database:** restore into a new, empty database and swap it in; never `pg_restore --clean` over the running one. Never run `docker compose down -v` on anything with data.

## Permissions

Nothing is changed on the live server without the owner's go. Secrets stay in `.env` files and the secrets folder, never in Git, output or chat. The database port is on `127.0.0.1` only: reach it with an SSH tunnel ([DBeaver access](dbeaver-access.html)).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| A `health.sh` row says FAIL | `docker ps`, `docker logs <container>`; the row names the part |
| After a reboot nothing runs | `bash start-gfm.sh`, then `bash health.sh --wait 180` |
| The Updates page says "needs a person" | `updater/README.md`, "Roll back an update by hand"; the log is in `updater/logs/` |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | Collected from `docs/handoff/08`, `updater/README.md` and `release/README.md`, shell commands for Ubuntu (round 13) |

## See also

- [Testing](dev-testing.html)
- [Backups and restore](backups-and-restore.html)
- [Health check](health-check.html)
