---
title: Uploads / Importer
slug: uploads-importer
lead: covers DA Management tools that bring people and historical data into the database, with Import history and Undo.
summary: Data uploads, historical CSV, people upload, import history.
status: full
navboxes: [admin]
infobox_title: Uploads / Importer
icon: "⬆️"
infobox_rows: ["Where|DA Management :8090", "Who|AP, President, Data Analyst", "Undo|Import history batches"]
tags: [admin, uploads]
---

## Usage

Open **DA Management** (portal menu or port 8090). Analysts use several upload paths:

### Historical CSV

Imports past weekly forms. Can also read people named on each form (new members, baptismal-date friends, high-potential friends) and place them on the matching weekly plans.

### People upload

Spreadsheet upload for **new members** (office templates / “Vollzogen” / New Member Database Raw layouts). Area is resolved from area name or from ward/branch when only one open area serves it. Unclear rows are left out and counted — not guessed.

### Same person?

When names might match existing people, the check page **asks** before Apply. Answers are remembered. Typed answers on a person are never overwritten; only empty fields are filled.

### After Apply

- Each import is one **batch** in **Import history** (before/after rows).
- **Undo** reverses the batch while later edits have not made reversal unsafe.
- Current-week draft plans can be filled so people carry forward by the same rules as opening Weekly Planning.

## How it works

- Runs in the `roster-importer` service against the Beta database.
- People carry-forward rules match [Weekly Planning](weekly-planning.html) (new members ~1 year; baptismal / high-potential from last week’s plan).
- Never invents area membership when ward/area is unclear.

## Permissions

AP, President, Data Analyst (DA Management users).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Apply blocked | Answer outstanding “same person?” questions |
| Friends not carried this week | Newest upload may end before “last week”; check dates |
| Undo refused | Something changed after the batch; use a database backup path if needed |
| Slow large Apply | Large people batches can take tens of seconds; Undo is slow too |

## History

| Date | Note |
| --- | --- |
| Round 7 / 033 | Data uploads |
| Round 12 / 039 | People from uploads; current-week fill |

## See also

- [Management (Places)](management.html)
- [Roster](roster.html)
- [Backups and restore](backups-and-restore.html)
