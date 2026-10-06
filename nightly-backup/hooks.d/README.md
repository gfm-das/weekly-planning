# Backup hooks

Every `*.sh` file in this folder runs each night inside the `gfm-backup` container, after the database dumps
(`nightly.sh`). Files with another ending (such as `dataease-sidecar.sh.example`) do not run. The `*.sh` files are
this server's own choice and are not in Git (`../.gitignore`).

## The one hook in use: the check of DataEase's backup

DataEase (Dashboards) makes its own backup: its container `gfm-dataease-backup` (`dataease/compose.yml`) writes
`dataease-<STAMP>.sql.gz` (dashboards, data sources, settings) and `dataease-files-<STAMP>.tgz` (uploaded files) into
this same folder every night at 02:15, with the MySQL tools of DataEase's own database. The files are deleted after
14 days with the rest.

`dataease.sh` (a copy of `dataease-sidecar.sh.example`) checks each night that a DataEase dump from the last 3 hours
is there and readable, so a missing or damaged one shows in `nightly.log` and in the `health.ps1` row "Nightly
backup". Switch it on (done on this server in round 6):

    Copy-Item nightly-backup\hooks.d\dataease-sidecar.sh.example nightly-backup\hooks.d\dataease.sh

Put a DataEase backup back: `dataease/backup-dataease.ps1 -RestoreFrom <file>` (`dataease/README.md`).

## Writing another hook (the contract)

- A hook gets `BACKUP_DIR` (the host folder `backups\nightly`), `STAMP` (for example `20260929-0230`) and
  `PASSWORD_FILE`. Its own passwords are files in `/backup/secrets/` (`nightly-backup\secrets\`, gitignored), written
  with `set-db-password.ps1 -EnvFile <file> -Variable <NAME> -Name <file name>`.
- It writes `<name>-<STAMP>.<ending>` into `BACKUP_DIR`, first as `….partial`, then renamed when complete. Files
  named this way are deleted after 14 days like the database dumps; nothing else in the folder is deleted.
- Exit 0 means done; its last output line goes to `nightly.log`. Any other exit is logged as `FAILED hook <name>`,
  retried like a failed dump (every 15 minutes, 3 times), and turns the `health.ps1` row "Nightly backup" to FAIL
  until the next night succeeds.
- The container has bash, gzip, tar and the PostgreSQL 15 client (`pg_dump`, `psql`); it can reach the containers on
  `gfm-network` and on the second Supabase stack's network. A hook that needs another network or a folder adds it to
  `backup-compose.yml` (then `docker compose -p gfm-backup -f nightly-backup/backup-compose.yml up -d`).
- A new or changed hook is used from the next night on; no restart is needed. Try it at once with
  `docker exec gfm-backup /backup/nightly.sh --now` (this makes a full backup, dumps included).

Removed in round 9 (in Git history at `808029d`): `dataease.sh.example`, a hook that dumped DataEase's database
itself. It was never used here: DataEase's database is MySQL and this container has no MySQL client, so DataEase
backs itself up (above).
