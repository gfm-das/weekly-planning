---
title: Installer overview
slug: installer-overview
lead: describes the planned cross-platform installer so other missions can set up Weekly Planning 3.0 with Docker.
summary: Planned installer for other missions (stub).
status: stub
stub: true
navboxes: [install]
infobox_title: Installer
icon: "📦"
infobox_rows: ["Status|Planned / not built yet", "Target|Anything that runs Docker", "UI|Local setup web form + CLI"]
tags: [install, planned]
---

## Planned behaviour

Other missions will run **one start command** that:

1. Opens a **simple setup web page** (or a fully terminal/CLI mode on headless machines).
2. Asks for mission name (and short code), default language (from the 14 existing catalogs), and the **first Data Analyst** account.
3. Optionally collects email settings, public domain, timezone, and a Cloudflare tunnel token.
4. Writes `.env` files (never committed), creates Docker network/volumes, starts stacks in a safe order, loads the database baseline + migrations, creates the mission row and first analyst account.
5. Ends with a health check all OK and prints the portal URL.

**Not** asked during setup: the roster (upload later in DA Management).

Dashboards and Presentations are **not** optional — full install.

Updates for installed copies are planned to follow a **public release repository** (versioned), not the private working repo — with a simple landing page for non-technical download.

## Current reality

Today, a new system is installed by following the written steps in `docs/SETUP-STEPS.md` (manual PowerShell). The installer prompt dated 5 Oct 2026 tracks phases A–E (inventory, shell, Cloudflare, public release, Windows test).

## See also

- [Requirements](requirements.html)
- [Glossary](glossary.html)
- [Server overview](server-overview.html)
