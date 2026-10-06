---
title: Server overview
slug: server-overview
lead: is a generic map of Docker stacks, ports, and how public access can be wired with a Cloudflare tunnel — without secrets.
summary: Docker stacks, ports, Cloudflare tunnel (generic).
status: full
navboxes: [admin]
infobox_title: Server
icon: "🖥️"
infobox_rows: ["Host|One Windows PC", "Network|Docker gfm-network", "Portal|8070", "Tunnel|Cloudflare (optional)"]
tags: [admin, ops, infra]
---

## Usage

Everything runs in **Docker Desktop** on one office Windows computer. Browsers talk to published ports; containers talk on the shared Docker network `gfm-network`.

## Docker stacks (generic)

| What people see | Port | Compose project (typical) |
| --- | --- | --- |
| Portal (nginx pages) | 8070 | `portal` |
| portal-api / reminders | (internal 8091) via `/api/` | `gfm-portal` |
| DA Management | 8090 | `roster-importer` |
| Presentations library / Studio | 3030 | `slidev` |
| Presentations decks | 8089 | `slidev` |
| Dashboards (DataEase) | 8088 | `gfm-dataease` |
| Beta database API / Studio | 18000 / 13000 | `gfm-beta` |
| PostgreSQL for DBeaver | 54322 | `gfm-beta` (override) |
| Nightly backup | (none) | `gfm-backup` |

The database is the **one source of truth**. Code lives in Git; the live checkout on the server must not be edited directly — use a worktree.

## Cloudflare tunnel (generic)

Optional public hostnames can point through a Cloudflare tunnel to `localhost` ports, for example:

| Purpose | Local target |
| --- | --- |
| Portal | `http://localhost:8070` |
| Dashboards | `http://localhost:8088` |
| Presentations | `http://localhost:3030` |
| Decks | `http://localhost:8089` |
| DA Management | `http://localhost:8090` |

Do **not** put PostgreSQL (54322) on the tunnel. Never publish secrets, tunnel tokens, or `.env` values in docs or Git.

:::needs-checking
Exact public subdomain names for this mission belong in private ops notes; this page stays generic on purpose.
:::

## How it works

- Portal nginx serves static pages and proxies `/api/` to portal-api.
- Dashboards sit behind a gate that checks a portal-signed cookie.
- The **updater** is a Windows scheduled task (not a container) driven from DA Management → Updates.

## Permissions

Server operators. Public routes should require the same auth boundaries as the office setup.

## Troubleshooting

See [Troubleshooting](troubleshooting.html) and [Health check](health-check.html).

## History

| Date | Note |
| --- | --- |
| Round 6 | Appsmith/Grafana/Superset retired |
| Round 10 | Public-everything hostname patterns documented |
| Round 12 | Appsmith removed from disk |

## See also

- [Health check](health-check.html)
- [Backups and restore](backups-and-restore.html)
- [Requirements](requirements.html)
