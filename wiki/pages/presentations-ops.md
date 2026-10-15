---
title: Presentations operations
slug: presentations-ops
lead: is the admin guide to the Presentations (Slidev) container - the two addresses, publishing, editors, settings and what to do when it misbehaves.
summary: Slidev manager: ports, publishing, editors, sign-in rules, settings, restart.
status: full
navboxes: [admin]
infobox_title: Presentations ops
icon: "🎞️"
infobox_rows: ["Library and editor|Port 3030", "Published decks|Port 8089", "Compose project|slidev", "Code|slidev/manager"]
tags: [admin, ops, presentations]
---

## Usage

For making and showing slides, see [Presentation Library](presentation-library.html). This page is for the person who keeps it running.

**Restart after a change** (the manager folder is mounted into the container, so a restart is enough):

```bash
docker compose -p slidev -f slidev/slidev-compose.yml -f slidev/local-override.yml up -d --no-deps slidev
docker logs --tail 50 <the slidev container>      # find the name with: docker ps
bash health.sh
```

**What people do** (all in the portal): open the library (a card per deck), open a deck to present it, open the editor (**/studio/<deck>**), press **Publish now**, download a PDF.

- A deck is a folder with a `slides.md` file written in Markdown.
- The editor saves `slides.md` after every change but does **not** publish. A deck is published by **Publish now**, when the editor page is left, or when an idle editor stops.
- If a build fails, viewers keep the last good copy. A failed build never takes a deck away.

## How it works

There are two addresses on purpose:

| Address | Port | What |
| --- | --- | --- |
| Manager | 3030 | The library, the editor page, the chart builder, the Whiteboard's chart frames |
| Decks | 8089 | Published decks and the editors. The manager's sign-in is never accepted here |

A deck can run JavaScript in the browser of whoever opens it, and Zone Leaders write decks too. So decks live on a second address and get a short **deck pass** for one deck instead of the manager's sign-in.

- **Who may do what** is asked from portal-api on every request (and remembered for 15 seconds). Leaders see only their own stewardship's numbers. People numbers are counts, never names.
- **Charts** in a deck get their mission numbers only for charts written in that deck's slides.
- **Editors:** one Slidev editor runs per deck being edited. At most 10 run at once. An unused one stops after 40 minutes.
- **Faster decks:** compressed copies are kept; the editor of a deck can start ahead of time.
- **Chart add-on:** a change to the add-on or chart libraries makes published decks rebuild by themselves (one at a time, a minute after the start).

### Settings

Set in the container's environment (`slidev/slidev-compose.yml` and `slidev/.env`). Each has a default.

| Setting | Default | What it is |
| --- | --- | --- |
| `PRESENTATIONS_PUBLIC_PORT`, `PRESENTATIONS_DECK_PORT` | 3030, 8089 | The ports browsers use |
| `PRESENTATIONS_PORTAL_ORIGINS` | the portal on 8070 | The only addresses that may sign in and frame the pages |
| `PRESENTATION_ACL_API_URL`, `PORTAL_SERVICE_KEY` | portal-api | Where to ask who may do what, and the key that proves it |
| `SLIDEV_MAX_RUNNING`, `SLIDEV_IDLE_MINUTES` | 10, 40 | How many editors may run; when an unused one stops |
| `SLIDEV_PRESTART` | on | `0` turns off starting an editor ahead of time |
| `SLIDEV_ADDON_REBUILD` | on | `0` turns off the automatic rebuild after a new chart add-on |
| `SLIDEV_BUILD_CONCURRENCY` | 1 | Builds at once (at most 2) |

Keys and passwords stay in `slidev/.env`, never in Git or in chat.

## Permissions

| Who | What |
| --- | --- |
| AP, President, Data Analyst | All decks, make, publish |
| ZL, STL | Zone presentations |
| DL | Decks shared with them |

Portal-api decides each time. Running the commands above needs a shell on the server.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Presentations sign you out | The Slidev container restarted. Wait a minute for the portal to renew the sign-in |
| Library empty or "not allowed" | Check your role. See [Roles and permissions](roles-and-permissions.html) |
| A deck shows the old version | Press **Publish now** in the editor. Check the container log for a failed build |
| The editor is slow to open | Normal for the first open. The library menu can start it ahead of time |
| Screen mirroring unavailable | Needs https or localhost. Plain http on the office network cannot mirror |
| PDF missing | Use Download PDF on the published deck |
| Chart is empty in a deck | The chart must be written in that deck's slides. Check the query and your stewardship |
| Many editors, slow server | Lower `SLIDEV_MAX_RUNNING` or `SLIDEV_IDLE_MINUTES`, then restart the container |
| Health row for Presentations or "deck address guards" FAIL | `docker logs --tail 50` of the Slidev container. Both ports 3030 and 8089 must answer |

## History

| Date | Note |
| --- | --- |
| Earlier rounds | Presentation manager, Studio and publishing built |
| Oct 2026 | Page written from `slidev/manager/README.md` |

## See also

- [Presentation Library](presentation-library.html)
- [Server overview](server-overview.html)
- [Health check](health-check.html)
- [Troubleshooting](troubleshooting.html)
