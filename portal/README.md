# The mission portal (`portal/`)

The portal is the website missionaries and leaders open every week: **http://localhost:8070** on the server and
**http://192.168.1.20:8070** on the mission's network. Everything in this folder is plain HTML, CSS and JavaScript:
nothing is built or installed, nginx hands the files to the browser as they are.

From anywhere it is also **https://example.org** (and `www.`): a Cloudflare tunnel (the Windows
service `cloudflared`, set up in the Cloudflare dashboard) brings that address to port 8070. The tunnel carries only
the portal's port, so on that address the shell sends its Supabase sign-in through the portal itself (nginx.conf,
"Supabase sign-in"), and Presentations and DA Management, which run on their own ports, show `office-only.html`
("opens only in the mission office") instead. Dashboards open from their own public name,
https://dashboards.example.org (a second tunnel route, to 8088; `docs/handoff/round10/public-dashboards.md`).
The Whiteboard opens, but its live charts (drawn by Presentations) do not. Details, deploy and rollback:
`docs/handoff/round10/public-domain.md`.

## The big picture

Think of the portal as a picture frame on a wall:

- **The frame** is the *shell* (`index.template.html` + `portal-enhancements.js`): the sign-in card, the menu on the
  left, the header with its buttons, and one big window in the middle.
- **The pictures** are the *pages* that open inside that window, one at a time: the Overview, Weekly Planning,
  Call-ins, the calendar and so on.
- **The back room** is *portal-api*, a separate program. The pages ask it questions (`GET /api/overview`) and send it
  changes (`PUT /api/mission-focus`). It checks who is asking and what they may see **every time**; hiding a menu entry
  is only a convenience.

```
 browser                                   the server
 ┌────────────────────────────────┐        ┌──────────────────────────────────────┐
 │ shell (index.html)             │        │ nginx (port 8070, nginx.conf)        │
 │  menu · header · ┌──────────┐  │ files  │  hands out the files of this folder  │
 │                  │  a page  │◄─┼────────┤                                      │
 │                  │ home.html│  │ /api/  │  passes /api/… to portal-api ──► DB  │
 │                  └──────────┘──┼───────►│                                      │
 └────────────────────────────────┘        └──────────────────────────────────────┘
      sign-in: Supabase (port 18000)        other programs on other ports: DataEase
                                            (8088), Presentations (3030, decks 8089),
                                            DA Management (8090)
```

How a visit goes, step by step:

1. The shell shows the sign-in card. Supabase (port 18000) checks the email and password and gives the browser a
   short-lived *pass* (access token) and a *ticket* to get a new one (refresh token). `portal-session.js` keeps the
   pass fresh. Someone already signed in on this device does not see the card at all (unless that sign-in has ended).
2. The shell asks who the person is (`current_user_context`) and builds the menu for their role (the entries not
   everyone has stay hidden until then).
3. A click in the menu opens a page in the window. The page gets the pass in its address (`?portal_token=…`);
   `portal-client.js` takes it out of the address at once and uses it for every question to portal-api.
4. The shell tells the page the theme (mission, light, dark) and the language; `i18n.js` shows every English text in
   the chosen language (14 languages, right to left for Persian and Arabic).

## The files

| File | What it is |
|---|---|
| `index.template.html` | The shell's page: sign-in card, menu, header, the window (`#appFrame`). `deploy.ps1` writes the public Supabase key into it and saves it as `index.html`. |
| `portal-enhancements.js` | The shell's main script: the full menu for each role, the header buttons (language, Library, Customize, Full screen, Reload, reminders), the theme, push reminders, and the extra sign-ins Presentations and Dashboards need. Its sections are numbered 1–14. |
| `portal.css` | The look of the shell. |
| `portal-session.js` | Keeps the sign-in fresh (`ensureMissionSession()`). |
| `portal-client.js` | Shared by the pages: `portalAPI()` (questions to portal-api), `escapeHTML()`, attachments, uploads, `portalConfirm()` (the "are you sure?" dialog). |
| `home.html`, `home.css` | **Overview**: welcome, key indicators, goals, plans, events, announcements, mission focus, stewardship planning; movable cards. |
| `glimpse.js`, `glimpse.css` | The **mission glimpse** at the top of the managers' Overview (charts with the vendored `echarts.min.js`). |
| `planning.html` | **Weekly Planning** (see that file's own overview). |
| `callins.html` | **Call-ins**: Mission > Zone > District > Area. |
| `calendar.html` | **Calendar**: events for your role and zone; editors create, edit, delete and record attendance. (The announcements are on the Overview and their own page.) |
| `announcements.html` | **Announcements** from the leaders; read receipts. |
| `archetypes.html`, `archetype-settings.html`, `archetypes-common.js`, `archetypes.css` | **Archetypal Health** and its Settings (managers). |
| `whiteboard/` | The **Whiteboard** (managers): `index.html`, `whiteboard.js` (the page), `board-core.js` (its rules), `whiteboard.css`, and `vendor/` (Excalidraw, built by `whiteboard-build/`; never edit it by hand). |
| `workspace.css` | The shared look of Weekly Planning, Call-ins, the calendar and announcements. |
| `i18n.js`, `i18n/` | Translation: the 14 catalogs (`en.json`, `de.json` …), `catalogs.json` (the list of languages) and `rtl.css` (right-to-left fixes). See `i18n/README.md`. |
| `service-worker.js` | Shows the push reminders on a device. |
| `manifest.webmanifest`, `mission-icon.svg` | Let a phone add the portal to its home screen. |
| `echarts.min.js`, `Sortable.min.js` | Libraries from other people (Apache ECharts 6.0.0, SortableJS 1.15.6). Left exactly as they are. |
| `nginx.conf` | The web server's rules (see below). |
| `deploy.ps1`, `portal-compose.yml`, `local-override.yml` | Putting the files live (see "Deploying"). |
| `tests/` | The checks (see "Testing"). |

Which page is which menu entry, and which address it has, is written in one place: section 1 of
`portal-enhancements.js` (`URLS` and `TITLES`).

Weekly Planning and Call-ins have their own plain guide (files, how the data travels, how to test):
`README-planning-callins.md`.

Appsmith Beta (Weekly Planning - Beta, Call-ins - Beta), Superset and Grafana are no longer linked from the portal
(round 6, `docs/handoff/round6/portalx.md`); an old `#planning_beta` or `#callins_beta` link opens the Overview, and
an old `/grafana/…` address leads to Dashboards.

## Who sees what

Who sees which menu entry and who may change what is decided in one place, `portal-api/roles.py`, and described in
`docs/handoff/04_AUTH_ROLES_AND_PERMISSIONS.md`. In short: everyone has Overview, Weekly Planning, Calendar and
Announcements; DLs and ZLs have Call-ins; ZLs, STLs and DLs have Presentations; APs, the
President and Data Analysts can use and manage everything in their mission (Dashboards, Whiteboard, DA Management
too); Office can edit the calendar and publish mission-wide announcements. Stewardship: a ZL sees their own zone, a DL their own district, a missionary
their own area, the managers the whole mission. portal-api and the database check every request.

## Calendar and announcements

Calendar editors (Office, APs, the President, Data Analysts) create, edit and delete events. A repeating event can
lose one date ("Only this one") or all of them; both ask first in the page. Deleting an event also deletes its
attachments and recorded attendance. Office publishes announcements mission-wide; leaders publish within their stewardship; the author or a manager
may edit or delete one. Attachments (up to 16 MB each) can be removed by whoever may edit the event or announcement.
File names keep letters such as ä, é or ł; files are stored under a random name.

## Push reminders

`portal-reminders` (the same program as portal-api) checks every minute. Incomplete companionship plans receive one
reminder per person and week on **Sunday from 18:00** Europe/Berlin, unless a companion was working on the plan in the
previous five minutes. Meeting reminders follow the event's reminder time and go to the event's audience only.

- Reminders are **per device**: every browser where someone chose **Enable reminders** gets them.
- **Turn off reminders** in the header stops them on this device only.
- **Sign out** removes this device's reminders, so the next person on a shared phone or computer does not get them.
  When someone signs in on a device that still has the previous person's reminders, those are removed.
- A device the push service reports as gone (404/410) is forgotten. A network error does not remove anything.

Browsers require the person to allow notifications, and push needs HTTPS or `localhost`: over plain http on the LAN
address it does not work (on the public https address it can; not yet tried there) (see `docs/CHANGE-HISTORY.md` for the old note). On iOS use the installed
home-screen web app. Never copy an API key, subscription endpoint or token into a screenshot or report.

The same loop also ends the follow-up of New Members baptized a year ago or more, once a day from 03:00 Berlin time.

## Sign-out

Sign-out ends the Supabase session in this browser (`POST /auth/v1/logout?scope=local`), so the stored refresh token
stops working, and also signs out of Presentations, Dashboards and DA Management.

## nginx (`nginx.conf`)

- `/api/` goes to portal-api; its answers are never kept by the browser.
- **Every text answer travels compressed** (gzip level 5): pages, scripts, styles, the translation catalogs and the
  API's JSON, at about a quarter of their size (`en.json`: 229 KB becomes 64 KB; Archetypal Health's answer: 144 KB
  becomes 12 KB). Pictures, fonts and attachments are left as they are.
- Pages, scripts and styles are **checked again on every visit** (`Cache-Control: no-cache`, a cheap "not changed"
  answer when nothing changed), so a deploy reaches everyone at once. Still raise the `?v=` number where a page loads
  a changed shared script (for example `portal-enhancements.js?v=23` in `index.template.html`).
- `echarts.min.js` and `Sortable.min.js`, and the Whiteboard bundle's parts whose names carry a fingerprint
  (`whiteboard/vendor/chunks/`, `whiteboard/vendor/assets/`), are **kept by browsers for a year**. The pages ask for the
  two libraries with their version in the address (`echarts.min.js?v=6.0.0`, `Sortable.min.js?v=1.15.6`): a new
  library version needs a new `?v=`. A new Whiteboard build brings new part names by itself.
- `favicon.png` is not in this folder: if it is missing in the container, the browser gets a short "not found" instead
  of the whole portal page.
- Only the portal may show its pages in a frame; the Whiteboard may frame Presentations (3030) only; the translation
  catalogs may be read by DA Management and Presentations; old `/grafana/…` addresses lead to Dashboards.

## Deploying

Deploy portal files with `portal/deploy.ps1`. It writes the public anon key into `index.template.html`, copies the
pages, scripts, styles, `i18n/` and `whiteboard/` into the nginx container, and reloads nginx (`nginx.conf` is mounted
from this folder, so a changed `nginx.conf` takes effect with that reload). It does not apply database migrations.

Secrets live in ignored environment files. `portal-api/.env.example` documents the required variables. VAPID keys must
stay the same between restarts, or every browser has to enable reminders again. From the project root, rebuild
portal-api **and** portal-reminders (both run the same image) with:

```powershell
docker compose -p gfm-portal -f portal-api/compose.yml up -d --build
```

If Docker Desktop was closed uncleanly and reports an inaccessible `*.sock` file, run `./start-gfm.ps1` from the
project root. Database migrations are in `portal-api/migrations/` and are applied by hand in number order, each after
a backup (see each file's header). After any migration that adds or changes a SECURITY DEFINER function, run
`019_restrict_public_functions.sql` again as a check. Never remove production/Coolify data or volumes.

Files named `original-*` or `*.before-*` next to these are old copies kept for reference, not active configuration:
see `docs/handoff/17_FILES_THAT_LOOK_ACTIVE.md`.

## Testing

Node checks (no database, no browser), from the repository root, for example in the `node:24-alpine` image:

| Command | What it checks |
|---|---|
| `node portal/tests/portal-menu-check.cjs` | The menu for every role, old links, the managers' Overview with the glimpse. |
| `node portal/tests/shell-helpers-check.cjs` | Sign-in renewal, `portalAPI`, uploads, reminder clicks, the shell's sign-in links and password rules. |
| `node portal/tests/dashboards-dataease-check.cjs` | Opening Dashboards (DataEase), keeping its sign-in, Full screen, sign-out. |
| `node portal/tests/whiteboard-shell-check.cjs` | Who gets the Whiteboard and where it opens. |
| `node portal/tests/whiteboard-core.test.mjs` | The Whiteboard's rules (saving, charts, styles). |
| `node portal/tests/glimpse-check.cjs` | "Goal reached" only at or over the goal. |
| `node portal/tests/i18n-check.cjs` | All 14 catalogs, and that no page has English text outside the catalog. |
| `bash portal/tests/nginx-check.sh` | `nginx.conf` in a throw-away nginx: compression, caching, frames, redirects. |

Browser checks (headless Edge, made-up data, see each file's header for how to start its stand-in server):
`portal-api/tests/edge_known_issues.ps1` (calendar, announcements, reminders switch, sign-out),
`edge_small_fixes.ps1` (the shell on phones), `edge_i18n.ps1` (the languages), `edge_glimpse.ps1`,
`edge_archetypes.ps1`, `edge_whiteboard.ps1`, `edge_dataease_portal.ps1`. Unit tests of portal-api:
`portal-api/tests/test_*.py` (for example `test_wording.py`, which also reads some pages). `health.ps1` in the project
root checks every running service.

## Translation coverage

APs assign primary and optional learning languages in DA Management. People can choose only assigned languages.
Interface catalogs are separate from mission data, and missing translations use English. **Every catalog except
English needs review by a native speaker.**
