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

### Deleting a closed place for good

A place that is **closed** (and, for an area, has nobody serving in it) can be deleted for good from **DA Management → Places → Delete a closed place for good** (the page *Delete retired*). The page shows what is attached to it (plans, people, Call-ins, uploaded numbers), lets you **move** all of it onto the place that replaced it, makes a **database backup** first (its file name is written into the batch), asks you to **type the name**, and then deletes it as one **RETIRE** batch in Import history that **Undo** can put back. Plans, people and history are never deleted by this page: they must be moved. A retired Weekly Planning question is deleted from the same page (see [Uploads / Importer](uploads-importer.html)).

## Links to web services

**DA Management → Links to web services** (a tab for managers only) has one card per outside service the mission system relies on, each with a short line on what it is for and an *Open* button that opens the service in a new tab:

| Service | What it is for |
| --- | --- |
| Brevo | Sends the system's emails (invitations and password emails). |
| Porkbun | Holds the mission's web domain name: renewals and the DNS records. |
| Cloudflare | Connects the web address to the system safely (the tunnel) and manages DNS and protection. |

The addresses are **settings**, not code: `WEB_LINK_BREVO`, `WEB_LINK_PORKBUN` and `WEB_LINK_CLOUDFLARE` in `roster-importer/.env` (empty keeps the service's public sign-in page, `off` hides the card). **No password, key or token is stored here** and an address that contains one is not shown. You sign in at the service with your own account.

## Wiki button

The mission wiki lives in the portal side menu under **Information → Wiki** (everyone signed in). It opens inside the portal frame in the navy and gold theme. DA Docs was removed; the guide is this wiki (start at [Data analyst onboarding](analyst-onboarding.html)).

The address is a **setting**, not code: `WEB_LINK_WIKI` in `roster-importer/.env`. Empty works it out (the name you reached DA Management by, on the portal's port `PORTAL_PORT`, default 8070, then `/wiki/`; on the internet name the public portal address); `off` hides the button. An address with a password or key in it is not shown.

## Unlocking a locked planning question

Some Weekly Planning questions are **locked** (Dashboards, Call-ins, Presentations or Archetypal Health read them by their key). A manager (AP, President, Data Analyst) can unlock one on purpose in **DA Management → Planning questions →** the question → **Unlock this question**: write why and type the question's key. The unlock is in the **Change history** with who did it and why. An unlocked question can be changed or retired like any other; a question that reports read can be **locked again** with one button.

## Permissions

Same as DA Management: AP, President, Data Analyst. Only a manager signed in through the portal may delete a place or question (the old shared password may not).

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
