---
title: Dashboards
slug: dashboards
lead: are interactive DataEase reports for key indicators, zones and districts, and covenant-path counts.
summary: DataEase Dashboards for managers.
status: full
navboxes: [using]
infobox_title: Dashboards
icon: "📊"
infobox_rows: ["Who|AP, President, Data Analyst", "Engine|DataEase v2", "Port|8088", "Languages|14"]
tags: [users, managers, analytics]
---

## Usage

1. Open **Dashboards** in the portal menu (managers only).
2. The portal signs you in with a short-lived cookie â€” no separate DataEase password.
3. Use the slim bar to switch between the three mission dashboards and **All dashboards and Edit**.
4. Filter by zone, district, and weeks as needed.

### The three dashboards

| Dashboard | What it shows |
| --- | --- |
| Key indicators | Six tiles (New People Being Taught first) plus trend charts vs goal |
| Zones & districts | Zones vs goals, heat maps, districts that may need help, district table |
| Covenant path | Counts only: new members, baptismal-date friends, high-potential friends |

## How it works

- DataEase reads **only** the `dashboards` database views through a read-only login and dbproxy.
- Everyone shares one DataEase account labelled **Mission**; the gate logs who opened or changed what.
- Chart labels in other languages come from translated copies â€” after editing **English** dashboards, analysts must run the translate script.

## Permissions

AP, President, and Data Analyst only (same group as Glimpse). Cookie lasts about 15 minutes and renews while Dashboards stays open.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Cannot open Dashboards | Confirm manager role; run [health check](health-check.html) |
| Other languages look old | Re-run `dataease/translate-dashboards.ps1` after English edits |
| Share / public links | Intentionally disabled |
| Second device | Confirm from a second device on the current public or LAN setup (needs checking). |

## History

| Date | Note |
| --- | --- |
| Round 6 | DataEase replaces Grafana/Superset |
| Round 8â€“9 | 14 languages; speed tidy-up |

## See also

- [Glimpse](glimpse.html)
- [Roles and permissions](roles-and-permissions.html)
- [Server overview](server-overview.html)

