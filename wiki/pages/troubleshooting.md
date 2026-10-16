---
title: Troubleshooting
slug: troubleshooting
lead: collects common problems and first checks for portal users and analysts.
summary: Common problems and first checks.
status: full
navboxes: [admin]
infobox_title: Troubleshooting
icon: "🔧"
infobox_rows: ["First step|bash health.sh", "Logs|docker logs --tail 50 …", "Data safety|Backup before risky fixes"]
tags: [admin, users, ops]
---

## First checks (analysts)

1. Run [health.sh](health-check.html) (`bash health.sh`) — read which row failed.
2. Check that Docker is running; if the server rebooted badly, run `bash start-gfm.sh`, then `bash health.sh --wait 180`.
3. Look at logs for the failing part: `docker logs --tail 50 <container>`.
4. If a change just went live, consider rolling back only that part (see ops start-here guide in the repo).

## Portal users

| Symptom | Likely cause / action |
| --- | --- |
| Cannot sign in | Account inactive or wrong email — ask Data Analyst |
| Wrong menu items | Role/stewardship — see [Roles](roles-and-permissions.html) |
| Invitation or password emails do not arrive | See [Email (Brevo)](email-brevo.html) |
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

## Updates and releases

| Symptom | Action |
| --- | --- |
| Updates page shows nothing, or an old time | The updater is not watching. `bash updater/gfm-updater.sh status`, then `bash updater/register-watcher.sh` — see [Updater](updater.html) |
| "Quick tests did not pass" | The new version is faulty; nothing was changed. Tell the makers |
| Update refused: changes GitHub does not have, or files changed by hand | Someone edited the live folder. A developer checks `git status` |
| Update refused: install by hand | A migration needs a person. Ask a developer |
| Update went back by itself | The old version runs. Read `updater/logs/` |
| Page says "needs a person" | [Updater](updater.html), "Roll back by hand" |
| Release build stops at the scan or verify step | See [Releases and updates](releases-and-updates.html) |

## Backups

| Symptom | Action |
| --- | --- |
| Nightly backup row FAIL | `cat backups/nightly/last-run.txt`, `docker logs gfm-backup` — see [Nightly backup](nightly-backup.html) |
| Row says "waiting" on a new install | First run is at 02:30; or `docker exec gfm-backup /backup/nightly.sh --now` |
| Password errors in the backup log | Rewrite the password file with the current database password (no trailing newline) |
| Need an old state back | Restore into a new empty database, never `--clean` over the live one |

## Dashboards (server side)

| Symptom | Action |
| --- | --- |
| "Dashboards are starting" or not available | Wait a minute; `bash health.sh --wait 180`; `docker logs --tail 50 gfm-dataease` |
| Per-resident charts empty | Upload Geo data; check migration 046 — see [Dashboards operations](dashboards-ops.html) |
| Other languages show old chart words | `bash dataease/translate-dashboards.sh` |
| Every chart should answer | `bash dataease/seed-dashboards.sh --check` |
| Never | `docker compose ... down -v` on DataEase (deletes every dashboard) |

## Presentations (server side)

| Symptom | Action |
| --- | --- |
| Deck shows an old version | **Publish now** in the editor; look for a failed build in the container log |
| Editor slow or too many editors | Lower `SLIDEV_MAX_RUNNING` / `SLIDEV_IDLE_MINUTES`, restart — see [Presentations operations](presentations-ops.html) |
| Presentations signed out after a restart | Wait for the portal to renew the sign-in |

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
- [First day as a Data Analyst](first-day-as-da.html)
- [Updater](updater.html)
- [Email (Brevo)](email-brevo.html)
- [Nightly backup](nightly-backup.html)
