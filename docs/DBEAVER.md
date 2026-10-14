# DBeaver and Jupyter: the Data Analysts' own logins to the database (Ubuntu server)

Data Analysts are also the data managers: they get **full control** of the mission's data (read, write, create), with a **personal
login** each, in DBeaver, in Jupyter notebooks, or in any PostgreSQL tool. It is not a read-only access.

(This page replaces the Windows version of 2026: the office address, the Windows firewall rule and the Windows secrets folder are gone.)

## How it is reached: an SSH tunnel, never an open port
On the Ubuntu server the database (PostgreSQL in the container `gfm-beta-supabase-db-1`) listens on **127.0.0.1:54322 of the server only**
(`GFM_DB_BIND=127.0.0.1` in `supabase/.env`, which the installer writes; `supabase/beta-override.yml` publishes `54322` on that address).
So nobody can reach it from the network, and nothing needs a firewall rule. An analyst opens an **SSH tunnel** from their own computer,
and the database then appears on their computer's own `127.0.0.1:54322`:

```bash
ssh -L 54322:127.0.0.1:54322 <your-server-user>@<the-server>
```

Leave that window open while you work (add `-N` to open the tunnel without a shell). If port 54322 is busy on your computer, use another
local port (`-L 54323:127.0.0.1:54322`) and put it in the settings below. On Windows the same command works in PowerShell or Windows
Terminal (OpenSSH is part of Windows 11).

Check on the server that the port is closed to the network: `ss -ltn | grep 54322` must show `127.0.0.1:54322`, not `0.0.0.0:54322`.
Never forward 54322 on the router and never add it to the Cloudflare tunnel.

## Connection settings (DBeaver, with the tunnel open)
New connection, PostgreSQL:

| Field | Value |
|---|---|
| Host | `127.0.0.1` (the tunnel's end on your computer) |
| Port | `54322` (or the local port you chose) |
| Database | `postgres` |
| Username | your own login (made for you by a Data Analyst, see below) |
| Password | given to you privately; keep it in your password manager, never in Git, chat or email |
| SSL | `disable` is fine: the tunnel is encrypted by SSH, and the database has no certificate |

The useful schemas are `public` (planning data), `portal` and `dashboards` (the views behind the Dashboards).

## What a login may do
Every login is a member of the group role `gfm_db_analysts` (migration `043_dbeaver_analyst_role.sql`, part of every install): full rights on
every table, view, sequence and function in `public`, `portal` and `dashboards`, including the ones later migrations add, and it may create
its own tables there. Each login also has BYPASSRLS, so it sees every row. It is not a superuser and cannot change Supabase's own schemas
(`auth`, `storage`, ...) or create roles. **Changes are live data**: try anything risky inside `BEGIN; ... ROLLBACK;` first. The nightly
backup (`backups/nightly`) is the way back.

## Add a login for a person (on the server; needs the owner's "go")
The analyst logins do **not exist yet** on the Ubuntu server (the old `analyst_admin` login belonged to the Windows computer and was not
carried over). A Data Analyst with shell access to the server makes one per person, from the repository folder (`~/weekly-planning`):

```bash
bash tools/add-analyst-login.sh anna_k --dry-run     # look first: it changes nothing
bash tools/add-analyst-login.sh anna_k               # asks you to type the name again, then makes the login
bash tools/add-analyst-login.sh anna_k --reset       # later: a new password
```

What the script does (`tools/add-analyst-login.sh` and `install/sql/add-analyst-login.sql`):
- makes a long random password and writes it to **`~/gfm-secrets/analyst-<name>.txt`** (mode 600, outside the repository, never printed on
  the screen, never in Git; `--secrets-dir` or `GFM_SECRETS_DIR` choose another folder, one inside the repository is refused);
- makes the login with `LOGIN BYPASSRLS`, member of `gfm_db_analysts`, at most 10 connections, not a superuser (the group role itself comes
  from migration 043: if it is missing the script says so and stops);
- checks that the new login can connect and create, write and drop a table in `public`;
- changes nothing when anything is wrong (name rules: small letters, digits and `_`, 3 to 31 characters; system names are refused).

Give the file's content to the person privately. Remove a person: `DROP OWNED BY <name>; DROP ROLE <name>;` as `supabase_admin` inside the
database container (`REASSIGN OWNED BY <name> TO postgres;` first if the person made tables that must stay).

The script is tested against a fake `docker` (`bash tools/tests/test-add-analyst-login.sh`) and, where Docker is available, on a throw-away
database (`bash install/tests/test-analyst-login.sh`). It has **not** been run on the live server.

## Jupyter notebooks
A starter notebook is in **`tools/notebooks/starter.ipynb`**: it connects through the tunnel (host `127.0.0.1`, port `54322`), asks for your
password when it runs (nothing is saved in the file), opens a **read-only** session by default, lists the schemas and the Dashboards views,
runs example queries and draws a chart. A switch in its first cell turns writing on.

Setup on your own computer (Python 3.10 or newer):

```bash
python3 -m venv ~/gfm-notebooks && . ~/gfm-notebooks/bin/activate
pip install jupyterlab pandas sqlalchemy psycopg2-binary matplotlib
ssh -N -L 54322:127.0.0.1:54322 <your-server-user>@<the-server> &     # the tunnel
jupyter lab tools/notebooks/starter.ipynb
```

(Windows: `py -m venv gfm-notebooks`, `.\gfm-notebooks\Scripts\activate`, the same `pip install`, and the tunnel in a second window.)
The notebook reads these optional settings from the environment: `GFM_DB_HOST`, `GFM_DB_PORT`, `GFM_DB_NAME`, `GFM_DB_USER`,
`GFM_DB_PASSWORD` (set the last one only in your own shell, never in a file in Git).

With a container instead of a local install, any Jupyter image that has pandas, SQLAlchemy and psycopg2 works; the notebook must reach the
tunnel on your computer, so set `GFM_DB_HOST=host.docker.internal` (Docker Desktop) or run the container with `--network host` (Linux). This
way was not tested.

Keep exported files with people's names (CSV, Excel) out of the repository; `release/scan.sh` refuses `.csv` and `.xlsx` files in a release.

## Troubleshooting
| Problem | What to try |
|---|---|
| Connection refused on 127.0.0.1:54322 | The tunnel is not open (start the `ssh -L ...` command), or the local port is busy: use another one |
| `password authentication failed` | Wrong or old password: ask for a reset (`--reset`); the old password stops working at once |
| `permission denied for schema auth` (or `storage`) | Expected: those Supabase schemas stay protected |
| `too many connections for role` | A login may hold 10 connections; close idle DBeaver or Jupyter sessions |
| The server shows `0.0.0.0:54322` | `GFM_DB_BIND` is not `127.0.0.1` in `supabase/.env`: set it and recreate the database container (`docker compose -p gfm-beta --env-file supabase/.env -f supabase/supabase-compose.yml -f supabase/beta-override.yml up -d --no-deps supabase-db`, about 15 seconds of downtime) |
