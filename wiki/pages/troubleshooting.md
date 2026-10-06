---
title: Troubleshooting
slug: troubleshooting
lead: collects common problems and first checks for portal users and analysts.
summary: Common problems and first checks.
status: full
navboxes: [admin]
infobox_title: Troubleshooting
icon: "🔧"
infobox_rows: ["First step|health.ps1", "Logs|docker logs --tail 50 …", "Data safety|Backup before risky fixes"]
tags: [admin, users, ops]
---

## First checks (analysts)

1. Run [health.ps1](health-check.html) — read which row failed.
2. Check that Docker Desktop is running; if the PC rebooted badly, run `start-gfm.ps1`.
3. Look at logs for the failing part: `docker logs --tail 50 <container>`.
4. If a change just went live, consider rolling back only that part (see ops start-here guide in the repo).

## Portal users

| Symptom | Likely cause / action |
| --- | --- |
| Cannot sign in | Account inactive or wrong email — ask Data Analyst |
| Wrong menu items | Role/stewardship — see [Roles](roles-and-permissions.html) |
| Plan read-only | Submitted — ask DL/ZL/manager to unlock |
| No push reminders on phone | Need https or localhost |
| Presentations signed out | Slidev restart — wait for portal renew |
| Screen mirroring unavailable | Insecure http on LAN — present without mirror or use localhost/https |

## Dashboards / Presentations

| Symptom | Action |
| --- | --- |
| Dashboards won’t open | Manager role? Health row for DataEase / sign-in boundary |
| Language copy stale | Re-run translate script after English dashboard edits |
| PDF missing | Use Download PDF / export on published deck |
| Chart interactions differ on two windows | Expected — see [Presentation Library](presentation-library.html) |

## Data / imports

| Symptom | Action |
| --- | --- |
| Undo blocked | Later edits — use backup path if critical |
| Closed place reopened | Roster wins — see [Places](management.html) |
| People not carried | Carry-forward rules / upload week coverage |

## Known soft spots (not always “bugs”)

- Manager Overview can feel slow on a phone (chart library).
- All backups currently on one computer (no off-site copy yet).
- Older unused Supabase stack may still appear in health until fully retired.

:::needs-checking
Refresh this list against the latest `docs/handoff/11_KNOWN_ISSUES.md` after each major round.
:::

## See also

- [Health check](health-check.html)
- [Server overview](server-overview.html)
- [Signing in](signing-in.html)
