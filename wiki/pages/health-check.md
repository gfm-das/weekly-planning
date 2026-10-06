---
title: Health check
slug: health-check
lead: is the PowerShell script that checks every major part of the mission system and prints one OK/FAIL row each.
summary: How to run health.ps1.
status: full
navboxes: [admin]
infobox_title: health.ps1
icon: "❤️"
infobox_rows: ["Changes data?|No — read only", "When|After every change", "Exit code|1 if any FAIL"]
tags: [admin, ops]
---

## Usage

From the live repository folder on the server:

```
powershell -NoProfile -ExecutionPolicy Bypass -File health.ps1
```

Every row should say **OK**. Typical rows include: nightly backup; legacy stack ports; Beta stack; DA Management; Presentations; portal / API / sign-in boundary; Dashboards / sign-in boundary; deck address guards; unhealthy or restarting containers.

## How it works

The script only looks — it does not deploy or write. Exit code **1** when any row is FAIL.

## Permissions

Anyone who can run PowerShell on the server account that reaches Docker.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| One FAIL row | Check that part’s `docker logs --tail 50 <container>` |
| Many FAILs after reboot | Run `start-gfm.ps1` to bring Docker Desktop and stacks up |
| Nightly backup FAIL | See [Backups and restore](backups-and-restore.html) |

## History

| Date | Note |
| --- | --- |
| Ongoing | Expanded as new parts (DataEase, deck origin) were added |

## See also

- [Server overview](server-overview.html)
- [Troubleshooting](troubleshooting.html)
- [Backups and restore](backups-and-restore.html)
