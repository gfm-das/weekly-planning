---
title: Tutorial
slug: tutorial
lead: is the step-by-step walk through the portal, the same one the guided tour in the portal shows.
summary: A short tutorial for new users, by role, matching the guided tour in the portal.
status: full
navboxes: [using]
infobox_title: Tutorial
icon: "🧭"
infobox_rows: ["Who|Everyone, steps differ by role", "Time|About one minute", "Where|Settings > Tour in the portal header", "Languages|14 interface languages"]
tags: [users, tutorial, tour]
---

## Usage

The portal offers a **guided tour** once, the first time you sign in on a device. It dims the page, lights up one part of the menu at a time and says in a few words what it is for.

- **Next** and **Back** move through the steps. **Skip tour** closes it. The arrow keys work, and **Esc** closes it.
- The portal remembers on that device that you have seen it, so it does not come back by itself.
- To see it again, open **Settings** (the gear in the header) and press **Tour** (on a phone: open the menu with ☰, then **Settings** above Sign Out).
- On a phone the menu slides open for the menu steps and closes again at the end. In Arabic and Persian everything is mirrored, from right to left.
- The tour only points at what you may open. Steps for parts of the portal you do not have are left out.

## The steps

Everyone gets these. The tour follows the menu, top to bottom, and ends on Settings.

| Step | What it shows |
| --- | --- |
| Welcome | A short hello. The text fits your role |
| **Overview** | Start here: your week at a glance, with the key indicators, the AP Tip of the Week, announcements and your plan |
| **Weekly Planning** | Plan your week: key indicators first, then goals and action plans. Submit it when it is ready |
| **Calendar** | Meetings and events for your role and zone |
| **Announcements** | News from your leaders |
| **Settings** | Change your language or theme, or start the tour again |

## By role

Which extra steps you get follows [Roles and permissions](roles-and-permissions.html).

| You are | Extra steps |
| --- | --- |
| Missionary | None. The steps above are your tour |
| DL or ZL | **Call-ins** (report and follow up for the district or zone) and **Insights > Presentations** |
| STL | **Insights > Presentations** (no Call-ins) |
| Office (main or additional role) | **Office tools** (add and edit calendar events and announcements) and **Insights > Vollzogen** |
| Manager (AP, President, Data Analyst) | **Call-ins**, **Insights** with **Dashboards**, **Archetypal Health**, **Vollzogen**, **Whiteboard** and **Presentations**, then **Wiki**, **Mission drive** (when set up) and **DA Management** |

## How it works

- The tour is a small script in the portal (`portal/tour.js` and `portal/tour.css`). It has no outside library and sends nothing anywhere.
- It reads the menu to decide what to show, so it can never point at something you cannot open. It does not give or take away any right: that stays with the database and `portal-api`.
- "Seen it" is kept in the browser's local storage under your account number on that device. A private window or cleared site data simply shows the tour again.
- Every text is in all 14 interface languages. Translations are first drafts and need review by a native speaker, like the rest of the portal.

## Permissions

Everyone with an account sees the tour. The steps follow the role.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| The tour did not start | It starts by itself only once per device. Open **Settings** and press **Tour** |
| It starts every time | The browser does not keep site data (private window). Use a normal window |
| A step is missing | The part is not in your menu. Check your role with a Data Analyst |
| The card hides the part on a small screen | Press **Next**; the card moves to the other side of the screen for each step |

## History

| Date | Note |
| --- | --- |
| Round 13 | Guided tour and this tutorial |
| Round 21 | The tour follows today's menu from top to bottom (no more jumps between sections), ends on the Settings menu instead of pointing into it while it is closed, scrolls a long phone menu to the part it shows, and has shorter texts. A check (`portal/tests/tour-check.cjs`) makes sure every step points at a part the portal really has |

## See also

- [Signing in](signing-in.html)
- [Overview](overview.html)
- [Weekly Planning](weekly-planning.html)
- [Roles and permissions](roles-and-permissions.html)
