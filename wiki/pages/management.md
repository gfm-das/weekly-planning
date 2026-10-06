---
title: Management (Places)
slug: management
lead: is the DA Management area for opening and closing zones, districts, and areas, and related place structure.
summary: Places admin — close/open zones, districts, areas.
status: full
navboxes: [admin]
infobox_title: Places
icon: "🗺️"
infobox_rows: ["Where|DA Management → Places", "Who|AP, President, Data Analyst", "Migration|040 PLACES batches"]
tags: [admin, places]
---

## Usage

In **DA Management → Places** (menu label **Places**):

### Closing

- Closing a **zone** or **district** does **not** automatically close what is inside it.
- The page asks where each open child goes (another open zone or district) and saves nothing until every child has a destination.
- Numbers follow the move so old plans show under where the area belongs **today**.

### Reopening

- Reopen in order: a district cannot reopen inside a closed zone; an area cannot reopen inside a closed district.
- Places that were moved stay where they were moved.

### Other rules

- The last open zone cannot be closed.
- Nothing moves into a closed place.
- An area where missionaries serve needs the serving tick.
- Duplicate names under one parent are refused (all or nothing).
- Each change is one **PLACES** batch in Import history (Undo while safe).

### Roster wins

A place closed by hand stays closed **only until** a [roster](roster.html) names it or missionaries serve there again. Roster upload reopens as needed.

## Permissions

Same as DA Management: AP, President, Data Analyst.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Cannot close last zone | By design |
| Closed area came back | Check recent roster upload |
| Undo refused | Later edits; restore from backup if critical |

## History

| Date | Note |
| --- | --- |
| Round 12 / migration 040 | Places admin |
| 4 Oct 2026 | Owner rule: roster uploads win over hand closes |

## See also

- [Roster](roster.html)
- [Uploads / Importer](uploads-importer.html)
- [Accounts](accounts.html)
