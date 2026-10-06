---
title: Glimpse
slug: glimpse
lead: is the mission-at-a-glance panel at the top of Overview for APs, the President, and Data Analysts.
summary: Mission Glimpse for managers on Overview.
status: full
navboxes: [using]
infobox_title: Glimpse
icon: "👀"
infobox_rows: ["Who|AP, President, Data Analyst", "Where|Top of Overview", "API|GET /api/dashboard", "Charts|ECharts"]
tags: [users, managers, analytics]
---

## Usage

1. Sign in as a manager and open **Overview**.
2. Read the tiles for each key indicator (result vs goal from the week before), the short summary, trend charts, by-zone view, and table.
3. Pick a finished week and a chart span (for example 8 or 12 weeks).
4. Green with a tick means **goal reached**. There is no red “failure” colour — these are not verdicts.

## How it works

- Numbers come from `GET /api/dashboard` (`dashboard.py`), read as the signed-in person (row-level security applies).
- Only **finished** weeks are shown; the week still being planned appears once it ends.
- Charts use the vendored ECharts library; words go through the portal translation catalogs.

## Permissions

Only people with manager rights (`shows_glimpse`): **AP**, **President**, **Data Analyst** (including Data Analyst as an additional role). Everyone else sees Overview cards only. A 403 hides the Glimpse quietly.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Glimpse not shown | Confirm manager role; open Overview (not only Weekly Planning) |
| Load error | Check connection; use Try again; ask analysts if it persists |
| Looking at another area's goals | Glimpse hides while a manager inspects another area's goals |

## History

| Date | Note |
| --- | --- |
| Round 9 | Fresh numbers; glimpse-check tests |

## See also

- [Overview](overview.html)
- [Dashboards](dashboards.html)
- [Weekly Planning](weekly-planning.html)
