# DBeaver: the data analysts' own logins to the database

The Beta database (PostgreSQL in `gfm-beta-supabase-db-1`) is published on port **54322** of this computer
(`supabase/beta-override.yml`), so DBeaver can connect to it directly: from the office network now, over Tailscale later.

## Connection settings in DBeaver
New connection, PostgreSQL:

| Field | Value |
|---|---|
| Host | `192.168.1.20` in the office; later the Tailscale address of gfm-server (100.x.y.z) |
| Port | `54322` |
| Database | `postgres` |
| Username | the person's own login (the first one is `analyst_admin`) |
| Password | given privately; the server copy is in `/path/to\secrets\` (never in Git) |
| SSL | `disable` (the database has no certificate; Tailscale encrypts the way there) |

The useful schemas are `public` (planning data), `portal` and `dashboards` (the views behind the Dashboards).

## What a login may do
Every login is a member of the group role `gfm_db_analysts` (migration `043_dbeaver_analyst_role.sql`): full rights on
every table, view, sequence and function in `public`, `portal` and `dashboards`, including the ones later migrations
add, and it may create its own tables there. Each login also has BYPASSRLS, so it sees every row. It is not a
superuser and cannot change Supabase's own schemas (`auth`, `storage`, ...). **Changes are live data**: try anything
risky inside `BEGIN; ... ROLLBACK;` first. The nightly backup (`backups\nightly`) is the way back.

## Add a login for a person
On the server, in PowerShell (pick a name and a long random password, store it in `/path/to\secrets\`):

    docker exec -it gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres
    SET log_statement = 'none';
    CREATE ROLE <name> LOGIN BYPASSRLS CONNECTION LIMIT 10 PASSWORD '<password>' IN ROLE gfm_db_analysts;

New password: `ALTER ROLE <name> PASSWORD '<new>';`. Remove a person: `DROP ROLE <name>;` (a login owns nothing,
unless the person created own tables: then `REASSIGN OWNED BY <name> TO postgres; DROP OWNED BY <name>;` first).

## Network and firewall
- The port is published on all network cards. Logins need a password (scram-sha-256, `pg_hba.conf` of the Supabase image).
- Windows Firewall needs an inbound rule (once, in an **administrator** PowerShell):

      New-NetFirewallRule -DisplayName 'GFM Postgres DBeaver' -Direction Inbound -Protocol TCP -LocalPort 54322 -Action Allow -Profile Any -RemoteAddress 192.168.8.0/24,100.64.0.0/10

  (192.168.8.0/24 is the office network, 100.64.0.0/10 is Tailscale.)
- Never forward port 54322 on the router and never add it to the Cloudflare tunnel.
- To close it again: remove the `supabase-db` ports lines from `supabase/beta-override.yml` and recreate the database
  container (`docker compose -p gfm-beta --env-file supabase/.env -f supabase/supabase-compose.yml -f supabase/beta-override.yml up -d --no-deps supabase-db`,
  about 15 seconds of downtime).