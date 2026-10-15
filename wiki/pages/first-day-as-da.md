---
title: First day as a Data Analyst
slug: first-day-as-da
lead: is the checklist for a new Data Analyst who starts from nothing - get access, sign in, find every tool, and know the daily and weekly routine.
summary: Day-one checklist, tool map, daily and weekly routine, who to ask.
status: full
navboxes: [install]
infobox_title: First day
icon: "🧭"
infobox_rows: ["For|New Data Analyst", "Time|About half a day", "Need|A browser and an account", "Later|Server access (SSH)"]
tags: [start, analyst, onboarding]
---

## Usage

### Part 1 - Get access (before you can do anything)

1. Ask the President, an AP or a current Data Analyst to make your account. They do it in **DA Management > People > Account Manager** and give you the role **Data Analyst**. See [Accounts](accounts.html).
2. You get an email address and a first password. Keep them private.
3. Ask for the portal address. It looks like `https://<your-domain>`. In the office you can also use the server's own address on port 8070.
4. For the database (later, not on day one): ask for a database login and an SSH account on the server. See [DBeaver access](dbeaver-access.html).

### Part 2 - Sign in and look around (about an hour)

1. Open the portal in your browser and sign in. See [Signing in](signing-in.html).
2. Take the guided tour (the **Tour** button in the header). The same steps are in the [Tutorial](tutorial.html).
3. Open **Wiki** in the side menu. This is the manual. Bookmark it.
4. Open each tool in the table below once, so you know where it is.
5. Read [Roles and permissions](roles-and-permissions.html) and the [Glossary](glossary.html).

### Where each tool is

| I want to... | Open this | Wiki page |
| --- | --- | --- |
| See the mission's week and goals | Portal > **Overview** | [Overview](overview.html) |
| See the plans of companionships | Portal > **Weekly Planning**, **Call-ins** | [Weekly Planning](weekly-planning.html) |
| Load the roster or other files | **DA Management > Uploads** | [Uploads / Importer](uploads-importer.html), [Roster](roster.html) |
| Close or reopen a zone, district or area | **DA Management > Places** | [Management](management.html) |
| Make or change an account | **DA Management > People** | [Accounts](accounts.html) |
| Undo an import | **DA Management > Import history** | [Uploads / Importer](uploads-importer.html) |
| Install a new version | **DA Management > Updates** | [Releases and updates](releases-and-updates.html) |
| Look at charts and trends | Portal > **Dashboards** | [Dashboards](dashboards.html), [Dashboards operations](dashboards-ops.html) |
| Make or show slides | Portal > **Presentations** | [Presentation Library](presentation-library.html), [Presentations operations](presentations-ops.html) |
| Read the database directly | DBeaver, through an SSH tunnel | [DBeaver access](dbeaver-access.html) |
| Check the whole system | `bash health.sh` on the server | [Health check](health-check.html) |
| Check last night's backup | `bash health.sh`, first row | [Nightly backup](nightly-backup.html) |
| Change this wiki | **Edit** tab on any wiki page | [Editing the wiki](editing-the-wiki.html) |

### Part 3 - The routine

**Every day (5 minutes)**

1. Open the portal and look at Overview. Does it show this week's numbers?
2. If you can reach the server: `bash health.sh`. Every row should say OK.
3. Answer questions from missionaries and leaders (sign-in problems, wrong role, plan is locked). Most of these are fixed in DA Management > People. See [Troubleshooting](troubleshooting.html).

**Every week**

1. After transfers or changes, upload the **roster** (DA Management > Uploads). Check the preview, then Apply. See [Roster](roster.html).
2. Upload any other files that came in (historical CSV, people, Geo data). One file is one batch, and every batch can be undone.
3. Look at Import history. Is anything odd or unexpected?
4. Open Dashboards. Do the six dashboards show the new week?
5. Read the nightly backup row in `bash health.sh`. It must be OK.

**Now and then**

- Open DA Management > Updates. If a new release is shown, read what is new and install it at a quiet time. See [Releases and updates](releases-and-updates.html).
- Test a restore on a throw-away database. See [Backups and restore](backups-and-restore.html).
- Fix or add to the wiki when you learn something new.

### Part 4 - Server access (when you are ready)

The system runs in Docker on one Ubuntu server, in the folder `~/weekly-planning`. Ask the owner for an SSH account. Then read [Server overview](server-overview.html) and [Deploy and roll back on Ubuntu](dev-deploy-ubuntu.html).

Rules to remember:

- Never edit the live folder. Make a Git worktree, test there, and ship a release.
- Back up before any database change.
- Never put passwords or `.env` values in chat, in Git or in the wiki.
- Never run `docker compose down -v` on anything that holds data. The `-v` deletes the data.
- Do not delete anything for good without the owner. Move it to a `_to-delete-<date>` folder.

### Who to ask

| Question | Ask |
| --- | --- |
| I cannot sign in, or my role is wrong | A current Data Analyst, the President or an AP |
| Which data is right (a place, a person, a number) | The AP or the President |
| The server is down or a health row says FAIL | The senior Data Analyst, then the owner of the system |
| I want to change a rule or delete something for good | The owner of the system |

The names change with every transfer. Write the current names on your own copy of this page (use the Edit tab).

## How it works

This page does not add any tool. It collects the pages you need on day one, in the order you need them. All facts are taken from the other pages and from the repository's README files.

## Permissions

Anyone may read this page. The tools it points to follow the rules in [Roles and permissions](roles-and-permissions.html).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| I have no account yet | Ask the President, an AP or a Data Analyst (Part 1) |
| I cannot see DA Management or Dashboards | Your account needs the Data Analyst role: ask for it |
| `bash health.sh` has a FAIL row | [Troubleshooting](troubleshooting.html) |
| I am not sure what to do next | Read [Analyst onboarding](analyst-onboarding.html) and ask |

## History

| Date | Note |
| --- | --- |
| Oct 2026 | Written in round 15 so a new Data Analyst can start without an AI helper |

## See also

- [Analyst onboarding](analyst-onboarding.html)
- [Releases and updates](releases-and-updates.html)
- [Troubleshooting](troubleshooting.html)
- [Glossary](glossary.html)
