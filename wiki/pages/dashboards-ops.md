---
title: Dashboards operations
slug: dashboards-ops
lead: is the admin guide to the Dashboards (DataEase) containers, how a visit works, and how to check, change, back up and restore them.
summary: DataEase containers, sign-in gate, the six dashboards, translations, backup and checks.
status: full
navboxes: [admin]
infobox_title: Dashboards ops
icon: "📈"
infobox_rows: ["Engine|DataEase v2 Community", "Port|8088", "Compose project|gfm-dataease", "Backup|02:15 nightly"]
tags: [admin, ops, dashboards]
---

## Usage

For what the dashboards show and who may open them, see [Dashboards](dashboards.html). This page is for the person who keeps them running.

**Check them** (from `~/weekly-planning`):

```bash
bash health.sh                          # rows "Dashboards (DataEase)" and "DataEase Sign-in Boundary"
bash dataease/seed-dashboards.sh --check   # every chart answers
docker logs --tail 50 gfm-dataease-gate    # who opened Dashboards and every change
```

**The six dashboards** (in the order of the bar): Key indicators, Zones & districts, Areas, Trend, Per 10,000 residents, Covenant path. They show the portal's six key indicators. They hold numbers and organisation names only, never the names of people.

**Change a dashboard:**

1. Open Dashboards, then **All dashboards and Edit**, then Edit. Change it. DataEase keeps the change in its own database (backed up every night).
2. Run `bash dataease/translate-dashboards.sh` so the other 13 languages follow. Never edit a language copy: it is replaced the next time.

**After a new release that adds dashboards or datasets:**

```bash
bash dataease/seed-dashboards.sh        # adds new datasets and dashboards
bash dataease/translate-dashboards.sh   # makes the 78 language copies (6 dashboards x 13 languages)
bash dataease/seed-dashboards.sh --check
bash dataease/translate-dashboards.sh --check
```

The "Per 10,000 residents" charts need database migration 046 and uploaded Geo data. Until Geo data is uploaded in DA Management, they are empty. That is expected.

**Back up and restore:** the nightly job (02:15) puts a copy in `backups/nightly`. The "backup now" and "restore" helper is `dataease/backup-dataease.ps1`, which has no `.sh` twin yet. On Ubuntu, take a copy by waiting for the nightly job, or ask a developer to run the container's backup program (`dataease/backup/nightly.sh`).

## How it works

Six containers. Only nginx is open to the network.

| Container | What it does |
| --- | --- |
| `gfm-dataease` | DataEase itself (Java). No internet, no other services |
| `gfm-dataease-mysql` | DataEase's own notebook: dashboards, charts, datasets |
| `gfm-dataease-web` | nginx on port 8088, the only open door. Every request needs the portal's sign-in |
| `gfm-dataease-gate` | Checks the portal's sign-in cookie and holds DataEase's own sign-in |
| `gfm-dataease-dbproxy` | A pipe to the database port, and nothing else |
| `gfm-dataease-backup` | Every night at 02:15 copies DataEase's notebook into `backups/nightly` |

A visit: the portal asks portal-api "is this an AP, the President or a Data Analyst?". If yes, the browser gets a signed cookie (15 minutes, renewed while Dashboards is open). nginx asks the gate if the cookie is good, adds DataEase's own sign-in (never sent to the browser), and DataEase reads the database through one read-only login (`gfm_dashboard_reader`) that can see only the `dashboards` views.

- The free DataEase has one account and no single sign-on. That is why the portal's cookie and the gate stand in. DataEase's own sign-in page is switched off.
- DataEase is always told "English", or it would start in Chinese after a restart. The words are then shown in the viewer's language. Chart words that DataEase draws as pictures come from the translated copies of the dashboards.
- Settings are in `dataease/.env` (made by the installer, secret, not in Git).

## Permissions

AP, President and Data Analyst, through the portal only. Running the scripts needs a shell on the server.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Dashboards say "not available right now" or "starting" | DataEase needs a minute after a start. `bash health.sh --wait 180` |
| Health row for DataEase FAIL | `docker logs --tail 50 gfm-dataease` and `docker ps` for the six containers |
| Cannot open Dashboards | Is your role AP, President or Data Analyst? See [Roles and permissions](roles-and-permissions.html) |
| Other languages show old chart words | Run `bash dataease/translate-dashboards.sh` after English edits |
| Per-resident charts are empty | Upload Geo data (DA Management > Uploads) and check migration 046 is applied |
| Reader login cannot read | `bash dataease/set-reader-password.sh`, then `bash dataease/seed-dashboards.sh --check` |
| A change to the SQL of a dataset only | Back up first, then `bash dataease/seed-dashboards.sh` (updates in place) |
| Dashboards were reset | Restore the nightly DataEase copy. Ask a developer |

**Never** run `docker compose ... down -v` here. The `-v` deletes the volumes, and with them every dashboard people built.

## History

| Date | Note |
| --- | --- |
| Round 6 | DataEase replaces Grafana and Superset |
| Round 8-9 | 14 languages, speed tidy-up |
| Round 13 | Six dashboards on the six key indicators (13 Oct 2026) |
| Oct 2026 | Page written from `dataease/README.md` |

## See also

- [Dashboards](dashboards.html)
- [Nightly backup](nightly-backup.html)
- [Health check](health-check.html)
- [Server overview](server-overview.html)
