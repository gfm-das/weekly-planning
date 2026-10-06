# Nightly backup

Every night at **02:30** (German time) a small container called `gfm-backup` makes a copy of the mission's database
and puts it in the folder `/path/to/weekly-planning\backups\nightly`. It keeps the copies for **14 days** and then deletes
them. If something goes wrong, `health.ps1` shows a red **FAIL** in its "Nightly backup" row the next morning.

Think of it as a photocopier that wakes up every night, copies the mission's notebook, checks that the copy can be
read, puts it in a drawer, and throws away copies older than two weeks.

## The files in this folder

| File | What it does |
|---|---|
| `backup-compose.yml` | Describes the `gfm-backup` container: which image (PostgreSQL 15's own tools), the time (`BACKUP_AT`), how many days to keep (`KEEP_DAYS`), which databases (`BACKUP_TARGETS`) and which folders it may use. |
| `nightly.sh` | The program inside the container. It waits for 02:30, makes the copies, checks them, cleans up and writes what happened. |
| `set-db-password.ps1` | Writes the database password into `secrets\db-password` (never printed, never in Git). Run it once, and again after a password change. |
| `hooks.d/` | Small extra jobs that run after the copies. Today: the check that DataEase (Dashboards) made its own backup. See `hooks.d/README.md`. |
| `tests/test-nightly.sh` | The tests (see below). |
| `.gitignore`, `.gitattributes` | Keep `secrets/` out of Git, and keep `*.sh` files with Linux line endings (the container needs them). |

## How the data flows

```
 02:15  gfm-dataease-backup  --> backups\nightly\dataease-<date>.sql.gz   (Dashboards; dataease/backup/nightly.sh)
 02:30  gfm-backup (nightly.sh)
          1. pg_dump of each database   --> backups\nightly\beta-<date>.dump         (the Beta database)
                                            backups\nightly\production-<date>.dump   (the older second stack)
          2. its roles (no passwords)   --> backups\nightly\beta-roles-<date>.sql.gz ...
          3. the hooks in hooks.d/      --> e.g. checks that the DataEase file from 02:15 is there and readable
          4. a part that failed is tried again every 15 minutes, 3 times
          5. files older than 14 days are deleted (only files named like the ones above)
          6. backups\nightly\last-run.txt  = "OK <time>" or "FAILED <time>: <parts>"
             backups\nightly\nightly.log   = a few lines per night
 morning  health.ps1 reads last-run.txt and the newest beta-*.dump: OK, waiting, SKIPPED or FAIL
```

Every copy is first written as `<name>.partial`. Only when `pg_restore` can read it and it holds table data is it
renamed to `<name>.dump`. So a file called `*.dump` is always complete.

## Everyday checks

- `powershell -ExecutionPolicy Bypass -File health.ps1`: the first row, "Nightly backup", says `OK (beta-...dump, 4.5 MB, 3 h old)`.
- `Get-Content backups\nightly\nightly.log -Tail 20`: what the last nights did.
- `docker logs gfm-backup`: the same lines, from the container.
- One backup right now (for example after a change): `docker exec gfm-backup /backup/nightly.sh --now`.

## Restore (bring a copy back)

Always restore into an **empty** database, never with `pg_restore --clean` into the running one (that makes the
database rights wider; it was tested). The exact, tested commands are in `docs/handoff/round6/ops.md`, section
"Restore (commands)":

1. Look at a copy, or take single rows out of it: restore it into a new database on the throw-away test server.
2. Replace the whole Beta database: take a dump of the current state first, restore the nightly file into a new
   database `postgres_restored`, stop everything that uses the database, swap the names, restart, run `health.ps1`.

## Change something

- **Time, days to keep, databases:** edit `backup-compose.yml`, then
  `docker compose -p gfm-backup -f nightly-backup/backup-compose.yml up -d`.
- **`nightly.sh`:** the container reads it when it starts, so after a change: `docker restart gfm-backup`.
- **A hook or a password file:** read every night; nothing to restart.
- **The second Supabase stack** (`production=...` in `BACKUP_TARGETS`): when that stack is switched off, remove it
  there and its network below, or every night fails on purpose.

## Deploy and roll back

- Deploy (once; it has run on the server since round 6): `set-db-password.ps1`, then
  `docker compose -p gfm-backup -f nightly-backup/backup-compose.yml up -d --pull never`, then `--now` once.
- Roll back: `docker compose -p gfm-backup -f nightly-backup/backup-compose.yml down` (the backups stay in
  `backups\nightly`). The health row then says FAIL while backup files exist without the container, so also take the
  "Nightly backup" part out of `health.ps1` if the backups are stopped for good.

## Test

The tests use stand-ins for the database tools, so they need no database and no network. They run in the same image
as the real container:

```powershell
docker run --rm --network none -v "${PWD}\nightly-backup:/backup:ro" postgres:15-alpine bash /backup/tests/test-nightly.sh
```

(from the repository root; `ops-tests\run-all.ps1` runs it with all other operations tests). It checks the file
names, the password without a Windows line ending, a target that cannot be reached, the retry of only the failed
parts, hooks (also one saved with Windows line endings), a dump without table data, the lock, the 14-day clean-up,
the first start and `--now`.
