# Weekly Planning wiki

Static documentation site for **Weekly Planning 3.0** (Germany Frankfurt Mission portal).

Style notes (layout only - not Minecraft content or trademarks): page title + bold lead, right-hand infobox, table of contents, Usage / How it works / Permissions / Troubleshooting / History / See also, collapsible navboxes (all three sections on every page), stub notices, sidebar, light + dark mode (`?theme=dark` / `?theme=light`), client-side search, mobile sidebar menu.

Visual theme: deep navy + white + soft gold (missionary suit / shirt / accent), name-tag site brand (CSS only - no church logos or trademarked imagery), serif headings, warm "Did you know" / stub flavour text. Keep article body professional; flavour lives in notices, taglines, footer, and Did you know.

## Approach

- **Source:** Markdown files in `wiki/pages/` with a small YAML-like front matter block.
- **Build:** `wiki/build.py` (Python 3 standard library only) writes:
  - **Public** HTML into `wiki/out/` (served by portal nginx at `/wiki/`).
  - **Private** HTML for Data and admin pages into `wiki/out-private/` (not served by nginx; portal-api reads it).
- **Assets:** `wiki/assets/wiki.css`, `wiki/assets/wiki.js` (search, dark mode, private-page fetch).
- **Serve:** portal nginx aliases only `wiki/out/` at `/wiki/`. The `pages/` sources and `out-private/` folder are never exposed over HTTP.

## Public vs portal-login pages

| Section | Access |
|---|---|
| Main page, Glossary, Using the portal, Installing / Requirements | Public |
| Data and admin (Uploads, Management, Roster, Accounts, DBeaver, Backups, Health, Server, Troubleshooting, Editing the wiki) | Portal sign-in required |

Admin pages still have a public URL that shows a **Sign in to read this page** stub (with a lock icon in the sidebar/navboxes). `wiki.js` loads the real article from `GET /api/wiki/private/<slug>` using the Supabase Bearer token in `localStorage` (`mission_access_token`). Any signed-in portal user may read them. The public search index omits admin entries; signed-in users also fetch `GET /api/wiki/private/search-index`.

A page is treated as private when its `navboxes` include `admin`, it is listed under the Data and admin sidebar, or front matter sets `access: private`.

## Build

From the repository root (or from `wiki/`):

```powershell
python wiki/build.py
```

Output: `wiki/out/*.html`, `wiki/out/assets/`, `wiki/out/search-index.json`, plus `wiki/out-private/` for admin HTML and the full search index.

On the live server the wiki folder is mounted into **portal-api** (`WIKI_DIR=/data/wiki`) and into **portal** nginx (`../wiki` -> `/usr/share/nginx/wiki-src`, alias `.../out/` only). After a Save in the wiki editor, portal-api runs `build.py` so both `out/` and `out-private/` are rebuilt. To rebuild by hand:

```powershell
docker exec portal-api python /data/wiki/build.py
```

## Add a page

1. Create `wiki/pages/my-page.md`.
2. Start with front matter (see existing pages). Use `navboxes: [admin]` for Data and admin pages.
3. Add the page to the sidebar list and navboxes in `wiki/build.py` (`SIDEBAR` / `NAVBOXES`).
4. Run `python wiki/build.py`.
5. Open `wiki/out/my-page.html` in a browser (admin pages show the sign-in stub until you call the private API while signed in).

### Navbox keys

- `using` - Using the portal
- `admin` - Data and admin (private)
- `install` - Installing

## Deploy

This wiki **is** live at `https://example.org/wiki/`. Follow `CLAUDE.md`: worktree -> push `main` -> fast-forward the live folder -> rebuild wiki inside portal-api -> rebuild portal-api if `wiki_edit.py` changed -> `portal/deploy.ps1` only if `nginx.conf` changed -> `health.ps1`.

## Do not

- Put passwords, tokens, `.env` values, or personal data in pages.
- Point nginx at `wiki/` root, `pages/`, or `out-private/` — only `out/`.
