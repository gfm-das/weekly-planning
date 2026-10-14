---
title: DBeaver access
slug: dbeaver-access
lead: explains how Data Analysts connect to the mission PostgreSQL database with their own login, through an SSH tunnel (no passwords in this wiki).
summary: DBeaver and Jupyter connection settings for analysts.
status: full
navboxes: [admin]
infobox_title: DBeaver
icon: "🗄️"
infobox_rows: ["Host|127.0.0.1 (SSH tunnel)", "Port|54322", "Database|postgres", "Group role|gfm_db_analysts", "SSL|disable (SSH encrypts)"]
tags: [admin, database]
---

## Usage

The database is **not open to the network**: on the Ubuntu server it listens on `127.0.0.1:54322` of the server only. You reach it through an SSH tunnel from your own computer.

1. Open the tunnel and leave the window open:

   ```
   ssh -L 54322:127.0.0.1:54322 <your-server-user>@<the-server>
   ```

2. Install [DBeaver](https://dbeaver.io/) (or another PostgreSQL client). New connection → PostgreSQL.
3. Fill in:

| Field | Value |
| --- | --- |
| Host | `127.0.0.1` (the end of the tunnel on your computer) |
| Port | `54322` (or the local port you chose for the tunnel) |
| Database | `postgres` |
| Username | Your personal login |
| Password | Given privately (kept only in the server's secrets folder and your password manager — **never in Git, chat or email**) |
| SSL | `disable` (the SSH tunnel is the encryption) |

4. Useful schemas: `public` (planning data), `portal`, `dashboards` (views behind Dashboards).

## How it works

- Each login is in the group `gfm_db_analysts` (migration 043): **full read, write and create** rights in `public`, `portal` and `dashboards`, **BYPASSRLS** (sees every row), not a superuser, no access to Supabase's own schemas (`auth`, `storage`).
- Changes are **live data**. Try risky SQL inside `BEGIN; … ROLLBACK;` first.
- The nightly backup is the recovery path.

### Adding a login (a Data Analyst on the server, after the owner's go)

On the server, from the repository folder:

```
bash tools/add-analyst-login.sh <name> --dry-run   # look first
bash tools/add-analyst-login.sh <name>             # make the login
bash tools/add-analyst-login.sh <name> --reset     # a new password later
```

The script makes a long random password and writes it to a private file **outside the repository** (`~/gfm-secrets/analyst-<name>.txt`); it never prints the password. Hand the file's content over privately. Details: `docs/DBEAVER.md`.

### Jupyter

`tools/notebooks/starter.ipynb` connects through the same tunnel, asks for your password when it runs, starts in a read-only session and has example queries. Setup (a virtual environment with `jupyterlab pandas sqlalchemy psycopg2-binary`) is in `docs/DBEAVER.md`.

## Permissions

Only provisioned analyst logins. Never forward 54322 on the router or put it on the Cloudflare tunnel. On the server `ss -ltn | grep 54322` must show `127.0.0.1:54322`.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Connection refused | The tunnel is not open (run the `ssh -L …` command), or the local port is busy: use another one |
| Password authentication failed | Wrong or old password; ask for a reset (`--reset`) |
| Permission denied on auth/storage | Expected — those Supabase schemas stay protected |
| Server shows `0.0.0.0:54322` | Set `GFM_DB_BIND=127.0.0.1` in `supabase/.env` and recreate the database container |

## History

| Date | Note |
| --- | --- |
| Migration 043 | `gfm_db_analysts` group role |
| Oct 2026 | Rewritten for the Ubuntu server: SSH tunnel, per-analyst login script, starter notebook |

## See also

- [Backups and restore](backups-and-restore.html)
- [Server overview](server-overview.html)
- [Health check](health-check.html)
