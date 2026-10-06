---
title: DBeaver access
slug: dbeaver-access
lead: explains how Data Analysts connect to the mission PostgreSQL database with their own login (no passwords in this wiki).
summary: DBeaver connection settings for analysts.
status: full
navboxes: [admin]
infobox_title: DBeaver
icon: "🗄️"
infobox_rows: ["Port|54322", "Database|postgres", "Group role|gfm_db_analysts", "SSL|disable on LAN"]
tags: [admin, database]
---

## Usage

1. Install [DBeaver](https://dbeaver.io/) (or another PostgreSQL client).
2. New connection → PostgreSQL.
3. Fill in:

| Field | Value |
| --- | --- |
| Host | Office server LAN address (or Tailscale address later) |
| Port | `54322` |
| Database | `postgres` |
| Username | Your personal login (first example name historically: `analyst_admin`) |
| Password | Given privately (stored only in the server secrets folder — **never in Git**) |
| SSL | `disable` on the office path (Tailscale encrypts in transit when used) |

4. Useful schemas: `public` (planning data), `portal`, `dashboards` (views behind Dashboards).

## How it works

- Beta database container publishes PostgreSQL on **54322**.
- Each login is in group `gfm_db_analysts` (migration 043): full rights on those schemas, **BYPASSRLS**, not a superuser.
- Changes are **live data**. Try risky SQL inside `BEGIN; … ROLLBACK;` first.
- Nightly backup is the recovery path.

### Adding a login (admins on the server)

Create roles with `psql` as `supabase_admin` inside the database container. Store the password in `/path/to\secrets\` only. Do not paste passwords into chat, tickets, or this wiki.

## Permissions

Only provisioned analyst logins. Never forward 54322 on the router or put it on the Cloudflare tunnel.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Connection refused | Firewall rule for office / Tailscale ranges; confirm container healthy |
| Permission denied on auth/storage | Expected — those Supabase schemas stay protected |
| Need a new password | `ALTER ROLE … PASSWORD` on the server; update secrets folder |

## History

| Date | Note |
| --- | --- |
| Migration 043 | `gfm_db_analysts` group role |

## See also

- [Backups and restore](backups-and-restore.html)
- [Server overview](server-overview.html)
- [Health check](health-check.html)
