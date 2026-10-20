---
title: Presentation Library
slug: presentation-library
lead: is where leaders open, edit, publish, and present Slidev decks (including zone decks and charts from the database).
summary: Presentations library, Studio, presenter view, second screen.
status: full
navboxes: [using]
infobox_title: Presentation Library
icon: "🎬"
infobox_rows: ["Who|Managers; ZL/STL; DL (shared)", "Library port|3030", "Deck address|8089", "Engine|Slidev + Studio"]
tags: [users, presentations]
---

## Usage

1. Open **Presentations** in the portal (people with presentation rights).
2. **+ New Presentation** (managers, ZL, STL) asks only for a name and makes a blank deck: one title slide with that name. It opens in the editor. Every install also gets the showcase deck **Everything a deck can do** once (managers see it first): every chart type and trick, with made-up numbers. Duplicate it to experiment; delete it if you don't need it, and it won't come back.
3. In the **library**, open a deck from its card, or use the menu for Edit, Rename, Duplicate, Delete, Manage access, **Download PDF**, Download source.
4. **Edit** opens Studio (`/studio/<deck>`): slides, layout, components (including charts), Publish now, Source (Markdown).
5. **Publish now** rebuilds the live deck. A failed build leaves the last good publish live.
6. Open a published deck to present to an audience.

### Present on a second screen

A practical way to present:

1. Open the published deck in one browser window on the **projector / audience** display.
2. In the **same browser**, open a second window to the deck’s **presenter** view (`/presenter` on that deck’s address).
3. Put the presenter window on your laptop screen.

**Slide navigation** follows the presenter tools. **Chart interactions do not sync** between the two windows — if you click or filter a chart in one window, the other does not mirror those chart clicks. Plan chart walkthroughs accordingly (reset views before presenting, or narrate without relying on synced chart state).

:::needs-checking
Confirm the exact presenter URL shape on the live deck address (8089) for a published deck (for example `/p/<deck>/presenter/…`) during a dry run, and whether Slidev’s built-in slide sync is enabled for your browser pair.
:::

### Screen mirroring (optional)

The presenter view can also **mirror** another monitor (live picture of the projector) when the browser treats the address as secure (`http://localhost` on the server, https, or a special browser policy on LAN http). On plain office LAN http, the panel explains why mirroring is unavailable and how to present without it (use the Slides tab).

### Morphing charts and lists in a deck

- **One chart that morphs, click by click.** Give a `<MissionChart>` a `steps` list; each click is the next step, and the shapes really change into each other (lines → bars → funnel → pie), back again when you click back. The showcase deck's "A data story" slide shows it; copy it from there.
- **Lists.** `<MissionList>` shows a table: rows you type (names of people are always typed, never loaded) or live numbers per zone, district, area or week, with the same permissions as live charts. It can sort, group, limit, page through long lists (by click or automatically) and bring rows in one click at a time. Example:
  `<MissionList :rows="['Name, Zone', 'Anna Beispiel, Frankfurt']" group-by="Zone" reveal />`
- Live charts and lists can carry `sample` rows that are shown, with a note, when the live numbers cannot load.

## How it works

- Manager address **3030**: library, Studio, APIs, sign-in cookie.
- Deck address **8089**: published decks and deck editor; uses a **deck pass**, not the manager cookie.
- Charts pull stewardship-scoped numbers from portal-api. Zone decks show that zone’s numbers even to managers.
- PDF download uses the browser print dialog on the deck’s export page.

## Permissions

| Who | May |
| --- | --- |
| AP, President, Data Analyst | All decks; create mission decks |
| ZL, STL | Their zone’s decks; create zone decks |
| DL | Only decks shared with them (district numbers); cannot create |
| Missionary, Office | No Presentations |

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Mirroring button dead / message about insecure address | Present from `localhost` on the server, or use https / browser policy; or present without mirroring |
| Signed out of Presentations after update | Wait for portal renew (minutes) after Slidev restart |
| Chart numbers look too small / hidden | Stewardship rules hide tiny area people counts (below 3) |
| Chart clicks differ on two screens | Expected — interactions do not sync across windows |

## History

| Date | Note |
| --- | --- |
| Round 2 | Library, Studio, charts |
| Round 6 | PDF; screen mirroring messages; display-capture on frames |
| Round 7–8 | Zone decks; separate deck origin 8089 |
| Round 9 / Studio cache work | Editor performance (see recent commits) |

## See also

- [Roles and permissions](roles-and-permissions.html)
- [Dashboards](dashboards.html)
- [Server overview](server-overview.html)
