---
title: Editing the wiki
slug: editing-the-wiki
lead: explains how Data Analysts and managers change these docs from the browser, and how saves reach GitHub.
summary: In-browser wiki edit (analysts/managers), preview, history, deploy mounts.
status: full
navboxes: [admin]
infobox_title: Wiki editing
icon: "✏️"
infobox_rows: ["Who|AP, President, Data Analyst", "API|/api/wiki/…", "Sources|wiki/pages/*.md", "Build|wiki/build.py"]
tags: [admin, wiki, docs]
---

## Usage

1. Sign in to the mission portal as an **AP**, the **President**, or a **Data Analyst**.
2. Open any wiki article (same origin as the portal, under `/wiki/`).
3. Use the page tabs **Read | Edit | History** (Edit and History appear only when your session may edit).
4. On **Edit**: change the markdown on the left, watch the live preview on the right (same renderer as `wiki/build.py`), add a short **edit summary**, then **Save**.
5. Use **Create new page** for a new slug (`[a-z0-9-]` only). Add the page to the sidebar / navboxes in `wiki/build.py` on a later GitHub sync if it should appear in navigation forever.

Missionaries and other roles still **read** the wiki; they do not see Edit.

## How it works

- Sources stay Markdown files in `wiki/pages/`.
- portal-api (`wiki_edit.py`) checks the portal Bearer token and `roles.can_edit_wiki` (managers).
- **Save** writes the `.md` file under `WIKI_DIR` (default `/data/wiki` in the container), rebuilds `wiki/out/`, and appends a line to `wiki/edit-log.jsonl` (who, when, summary).
- **Preview** calls `POST /api/wiki/preview` so the HTML matches the static build.
- Optional `WIKI_GIT_COMMIT=1` makes the API `git commit` locally after a save (off by default). Pushing that commit to GitHub is still a deliberate ops step.

### API (managers only)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/wiki/me` | `{can_edit, role_label, …}` |
| GET | `/api/wiki/pages/<slug>` | Markdown source |
| PUT | `/api/wiki/pages/<slug>` | Save + rebuild |
| POST | `/api/wiki/pages` | Create page |
| POST | `/api/wiki/preview` | Render body HTML |
| GET | `/api/wiki/pages/<slug>/history` | Recent edits from the log |

## Permissions

| Who | What |
| --- | --- |
| AP, President, Data Analyst (also as an additional role) | Edit, create, history, preview |
| Everyone else | Read static HTML only; Edit tab hidden |

Hiding the tab is convenience. The API refuses non-managers with 403.

## Deploy notes (ops)

Documented in `wiki/README.md` and in the compose / nginx comments — not applied by this branch alone:

1. Mount the wiki folder into **portal-api** as `WIKI_DIR` (writable `pages/` + `out/` + `edit-log.jsonl`).
2. Mount `wiki/out` read-only into the **portal nginx** container and add `location /wiki/` in `portal/nginx.conf`.
3. Rebuild portal-api, reload nginx, open `https://example.org/wiki/`.

### Syncing browser edits back to GitHub

Browser saves update the live files on the server. To put them in Git:

1. On the server, in the mounted wiki / repo checkout: review `git diff`, then commit (or rely on `WIKI_GIT_COMMIT=1` commits).
2. `git push origin docs/wiki` (or merge via PR — never force-push `main` from wiki edits).
3. Prefer editing important pages in GitHub PRs when several people change the same article.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| No Edit tab | Sign in on the portal origin; confirm Data Analyst / AP / President |
| 403 on save | Role check failed — see [Roles and permissions](roles-and-permissions.html) |
| 503 “wiki folder is not mounted” | Set `WIKI_DIR` and the compose volume |
| Preview differs from Read | Hard-refresh; preview uses the same `build.py` renderer as the build |
| Edits missing from GitHub | Expected until someone syncs the server files / commits |

## History

| Date | Note |
| --- | --- |
| 5 Oct 2026 | First in-browser Edit / History / Create for managers |

## See also

- [Roles and permissions](roles-and-permissions.html)
- [Server overview](server-overview.html)
- [Accounts](accounts.html)
