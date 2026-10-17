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

Open **DA Management → Uploads** (portal menu or port 8090). There is **one page and one drop zone** for every file: roster, historical CSV, people, Vollzogen, geo data, the Church finding export and zone history. (The Baptism history upload was removed in October 2026; the baptisms uploaded before stay in the dashboards, and their old entries stay in Import history, where they can still be undone.)

1. Drop the file (CSV or XLSX). Leave **What is in the file?** on *Find out from the file*, or choose the kind yourself.
2. The page reads only the heading row. If it clearly is one kind, you go straight to that kind's check page.
3. If the file could be more than one kind (a Vollzogen sheet also looks like a people list) the page says so and **asks**; it never guesses. Choose the kind and send the file again.
4. For a roster, set the *Transfer effective date* under **Only for a roster or a historical CSV**; for a historical CSV the same place has the duplicate-report choice.
5. Check page, then Apply (one batch in Import history).

Each kind has a short card under the drop zone with its template download and the date of the last upload. The old addresses (`/historical`, `/people-upload`, `/uploads/<kind>`) lead to this page. The kinds:

### Historical CSV

Imports past weekly forms. Can also read people named on each form (new members, baptismal-date friends, high-potential friends) and place them on the matching weekly plans.

In **Places → Area mappings** each old label stands for **one area**; numbers of two areas are never added together. Choose **Closed area** for an area that no longer exists (also when it is already closed): its history stays under the closed area. Only a label marked **Combined companionship** (one companionship served both areas) is added to another area, and **Separate** takes those numbers apart again from the original import rows; Separate is one batch in Import history with Undo.

New labels of an upload come with a **suggestion** already chosen in their list, marked **Suggested** with the reason: remembered from an earlier upload, the same name, the same name without the zone prefix, or a similar spelling (another number is never similar: *Beta 12* is not *Beta 1*). When the match is an area that is already closed, **Closed area** is chosen. Without a good guess the list stays on *Choose current area*. Check each suggestion: nothing is saved or imported until you press **Save**, and *Combined companionship* and *Close old area* are never ticked for you.

### People upload

Spreadsheet upload for **new members** (office templates / “Vollzogen” / New Member Database Raw layouts). Area is resolved from area name or from ward/branch when only one open area serves it. Unclear rows are left out and counted — not guessed.

### Geo data

**Data uploads → Geo data** brings in **population, size (km²), density and households per area**, plus the **urban type** and **assignment type** that Archetypal Health uses to find similar areas, each row with its **source** and the **date the figures are from**. Download the template (it lists every area with what is saved), fill it in and upload it; an empty cell keeps what is saved, and a new population or size without a density makes the density be worked out again. Figures are stored by the stable area id, shown in a table per area that can be edited by hand (*Edit the area table*), and available to dashboards, (`dashboards.area_geo_data`, and `dashboards.area_week_per_capita` with the key indicators per 10,000 residents). One upload is one batch in Import history with Undo. German numbers such as 21.000 are read as 21000.

### FC number

The People upload reads an optional **FC number** column (the FindeChristus number). It is the **first and exact** way to recognise a person: the same number is always the same person, whatever the name or area, and two different numbers are never joined by name alone. A number is saved only where there was none and a saved number is never overwritten. The check page flags the same number for different names, and one number saved for two people (they are not joined). Undo takes the number back with the rest of the batch.

### Same person?

When names might match existing people, the check page **asks** before Apply. Answers are remembered. Typed answers on a person are never overwritten; only empty fields are filled.

### Delete retired places and questions

From **Places** and **Planning questions** (link *Delete … for good*, page *Delete retired*), a manager signed in through the portal can delete a **closed** zone, district or area, or a **retired** Weekly Planning question that is no longer needed (for example after a rename): (1) an **impact preview** counts everything attached (plans, people, Call-ins, saved answers, uploaded history); (2) an optional **merge** moves it onto the item that replaced it, and the check says when both have data for the same week or plan; (3) a **database backup** (pg_dump) is made and read back first and its file name is written into the batch, and if it fails nothing is deleted; (4) you **type the name** (or the question key); (5) the delete is **one batch** (kind RETIRE) in Import history with Undo. Locked questions (read by Dashboards, Call-ins, Presentations or Archetypal Health), open places and areas with missionaries serving are refused, also by the database. A question's saved answers may instead be deleted with it on purpose; plans, people and history of a place are only ever moved.

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
