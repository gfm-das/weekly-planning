---
title: Requirements
slug: requirements
lead: lists what you need to run Weekly Planning 3.0 on a new computer (manual setup today; installer planned).
summary: Hardware and software requirements.
status: full
navboxes: [install]
infobox_title: Requirements
icon: "✅"
infobox_rows: ["OS|Windows 11 typical today", "Runtime|Docker Desktop (WSL2)", "Also|Git", "RAM note|Tight around 16 GB on this office PC"]
tags: [install]
---

## Usage (checklist)

### Software

- **Docker** (Docker Desktop with WSL 2 on Windows; Docker Engine elsewhere once the installer exists)
- **Git**
- A user account that can stay signed in (Docker Desktop and the updater run in it on Windows)

### Optional / later

- Cloudflare tunnel token (public hostnames)
- SMTP settings for invite emails (planned)
- Tailscale or similar for remote DBeaver (planned path)

### Do not

- Commit or print `.env` values
- Experiment in the live production folder — use a Git worktree

## How it works today

Manual steps: create `gfm-network` and volumes, copy `.env.example` files, start Supabase, load baseline + migrations, start portal-api, portal, roster-importer, slidev, DataEase, backups, updater, then `health.ps1`. Details: repository `docs/SETUP-STEPS.md`.

## Permissions

Installer / server administrator.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Containers unhealthy | Wait for database healthy; re-check `.env`; run health.ps1 |
| Out of memory | Close unused stacks; 16 GB hosts are tight |

## History

| Date | Note |
| --- | --- |
| 5 Oct 2026 | SETUP-STEPS written as the list the future installer must automate |

## See also

- [Installer overview](installer-overview.html)
- [Server overview](server-overview.html)
- [Glossary](glossary.html)
