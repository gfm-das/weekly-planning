---
title: Overview
slug: overview
lead: is the portal home page with customizable cards, and for managers the mission Glimpse at the top.
summary: Portal Overview page for missionaries and managers.
status: full
navboxes: [using]
infobox_title: Overview
icon: "🏠"
infobox_rows: ["Who|Everyone signed in", "Managers also see|Glimpse", "Page file|home.html", "Cards|Drag to reorder"]
tags: [users, overview]
---

## Usage

1. After [signing in](signing-in.html), open **Overview** from the menu (managers often land here with the Glimpse already open).
2. Use the week selector when you want another reporting week.
3. Drag cards by the grip handle (or move them with the keyboard on the grip) to rearrange your layout. Visibility and order are saved for you in the browser.
4. Managers: read the [Glimpse](glimpse.html) summary, charts, and zone table at the top.

## How it works

- Overview cards live in one container. Layout is saved per user in browser storage (`gfm_overview_cards_v2`).
- The page talks to portal-api (for example Overview data and the Glimpse flag).
- Managers open Overview with `glimpse=1` so the mission Glimpse loads immediately.

## Permissions

| Who | What they see |
| --- | --- |
| Missionaries and leaders | Overview cards for their work |
| AP, President, Data Analyst | Cards **plus** the [Glimpse](glimpse.html) |

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Cards reset | Check you are on the same browser/profile; layout is local to the device |
| Glimpse missing | Only managers see it; confirm [roles](roles-and-permissions.html) |
| Slow on a phone | Chart library load can take about two seconds for managers (known soft spot) |

## History

| Date | Note |
| --- | --- |
| 26–27 Sep 2026 | Sortable cards, keyboard grip, layout v2 |
| Round 9 | Glimpse numbers always fresh via `/api/dashboard` |

## See also

- [Glimpse](glimpse.html)
- [Weekly Planning](weekly-planning.html)
- [Dashboards](dashboards.html)
