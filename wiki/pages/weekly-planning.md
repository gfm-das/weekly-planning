---
title: Weekly Planning
slug: weekly-planning
lead: is where a companionship plans its week: key indicators, goals, action plans, and people lists.
summary: How to use Weekly Planning including new members, baptismal dates, high potentials, and key indicators.
status: full
navboxes: [using]
infobox_title: Weekly Planning
icon: "📅"
infobox_rows: ["Who|Companionships (missionaries)", "Leaders|View / unlock by stewardship", "Submit by|Sunday 18:00 (reminders)", "Page|planning.html"]
tags: [users, planning]
---

## Usage

1. Open **Weekly Planning** from the portal menu.
2. Answer the **planning questions** (results, goals, and plans). The six **key indicators** come first; other goals and action plans stay available.
3. Keep the people sections up to date:
   - **Friends with a baptismal date**
   - **New Members** (first year after baptism)
   - **High-potential friends**
4. Work through the coloured **section bar** at the top; it shows what is still incomplete.
5. When the plan is ready, **Submit**. A submitted plan is read-only until a leader unlocks it.
6. Two companions can type at the same time: the page saves only what each person changed, a moment after the last keystroke.

### People: New members, baptismal dates, high potentials

| List | Meaning (system rules) |
| --- | --- |
| New members | Tracked until one year after the baptism date (or while on last/this week's plan when no date) |
| Friends with a baptismal date | Only while on **last week's** plan and the date has not passed |
| High-potential friends | Only while on **last week's** plan of the same area and ward |

You can add people with **+ New member** / **+ Add person on date**, edit cards, move area, end follow-up, mark baptized, drop, or remove if added by mistake (rights permitting).

:::needs-checking
Exact button labels and which remove actions are allowed after migration 041 (`no_new_member_delete`) should be confirmed on the live page before training materials quote them.
:::

### Key indicators

The six key indicators are the mission's main weekly numbers (Preach My Gospel wording). One of them is shown as **New People Being Taught** (database key historically `friends_found`). Goals set **this week** apply to **next week**; a finished week is measured against the goal set the week before.

## How it works

- Questions come from the database and are edited in **DA Management → Planning questions**.
- Saves go to portal-api (`planning.py`): answers and people changes send only what changed.
- Submit locks the plan; unlock is checked by role and stewardship in the API and database.
- Push reminders for unfinished plans run from Sunday 18:00 (on devices where reminders were allowed).

## Permissions

| Who | May |
| --- | --- |
| Missionaries | Edit their area's current plan |
| DL / ZL | View their district/zone; unlock submitted plans in scope |
| AP / President / Data Analyst | Mission-wide view and unlock |
| STL | No Call-ins role; planning view follows assignment |

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Cannot edit | Plan may be submitted; ask DL/ZL/manager to unlock |
| Companion overwrote answers | Should no longer happen with change-only saves; refresh and retry |
| People missing after upload | Check carry-forward rules (last week / dates); see [Uploads](uploads-importer.html) |
| Save refused for last week | Expected — edits into last week's plan are refused with a clear message |

## History

| Date | Note |
| --- | --- |
| Round 2–3 | People forms, planning questions from DB, wording |
| Round 7 | Section bar |
| Round 12 | Upload-driven people fill and current-week carry-forward (migration 039) |

## See also

- [Roles and permissions](roles-and-permissions.html)
- [Glimpse](glimpse.html)
- [Uploads / Importer](uploads-importer.html)
