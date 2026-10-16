---
title: Updater
slug: updater
lead: is the small program on the server that installs a new version only when a person asks, tests it first, and goes back by itself if it fails.
summary: How the updater works, its settings, its files and a manual roll back.
status: full
navboxes: [admin]
infobox_title: Updater
icon: "🔄"
infobox_rows: ["Program|updater/gfm-updater.sh", "Starts|Only when a person asks", "Settings|updater/settings.json", "Logs|updater/logs/"]
tags: [admin, ops, update]
---

## Usage

**Normal use:** DA Management > Updates, then **Check for updates** and **Update now**. See [Releases and updates](releases-and-updates.html).

**In a terminal** (from `~/weekly-planning`):

```bash
bash updater/gfm-updater.sh check      # ask what is new; changes nothing
bash updater/gfm-updater.sh update     # install it; you type UPDATE to confirm
bash updater/gfm-updater.sh status     # print what it found and did
bash updater/gfm-updater.sh watch      # keep answering the Updates page
bash updater/register-watcher.sh       # make the computer start "watch" by itself (crontab on Linux)
bash updater/register-watcher.sh --dry-run   # show what it would do
bash updater/register-watcher.sh --remove    # take it away (pauses updates from the page)
```

**Settings** are in `updater/settings.json`. Copy `updater/settings.example.json` if it does not exist:

```json
{"Remote": "origin", "Branch": "main", "Track": "tags", "CheckEveryHours": 6}
```

- `Track: "tags"` follows the releases (the newest tag like `v1.10.0`). New missions use this.
- `Track: "branch"` follows the newest commit of `Remote/Branch`.

## How it works

The web page and the updater never talk directly. The page leaves a small request file. The updater reads it, checks every field, deletes it, and writes its answer to a status file that the page may only read. The updater accepts two requests only: `check`, and `update` for the exact version the person saw.

An update, step by step:

1. **Only forward.** It refuses if this computer has changes GitHub does not have, if files were changed by hand, or if a new migration says `updater: install by hand`.
2. **Quick tests** on a copy of the new version. If they fail, nothing changes.
3. **Health first.** An update only starts from a healthy system.
4. **A way back is saved:** the current commit, a database backup, rollback copies of the images, a copy of the portal pages. All in `backups/updater/<time>/`.
5. **Install:** the new code, the new migrations in order (each followed by migration 019, the rights check), then only the parts that changed: portal-api, DA Management, Presentations (a new container when its settings changed), Dashboards (new web and gate containers; new dashboards after a DataEase backup), the portal pages.
6. **Health again**, 6 tries, 30 seconds apart. If it fails, the old version is put back by itself and the page says so. If even that fails, the page says "needs a person".

It does not install changes to Dashboards (`dataease/`), the nightly backup (`nightly-backup/`) or the database stack (`supabase/`). The Updates page lists such changes for a person.

Folders it makes in the repository (not in Git): `updater/requests/`, `updater/status/` (the file `status.json`), `updater/logs/` (one log per month), and `backups/updater/<time>/`. Passwords and tokens are never written to the log.

### Roll back by hand

Only needed when the page says "needs a person".

1. Read the newest log in `updater/logs/` to see which step failed.
2. Everything you need is in `backups/updater/<time>/`: `repo-head.txt` (the old commit), `portal-html` (the old portal pages) and `rollback-sql`.
3. Also there: the image tags `*-rollback:upd-<time>` and the dump `backups/beta-pre-update-<time>.dump`.
4. Put the code back to the commit in `repo-head.txt`, restore the rollback images, redeploy the portal pages (`bash portal/deploy.sh`), apply the rollback SQL files (then migration 019), and run `bash health.sh`.
5. Restore the database dump only into an **empty** database, never over the running one. See [Nightly backup](nightly-backup.html).

If you are not sure, stop and ask a developer. Do this only after a backup of the current state.

## Permissions

| Who | What |
| --- | --- |
| AP, President, Data Analyst | Use the Updates page |
| Anyone with a shell on the server | Run the commands above |

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Updates page shows nothing new, or an old time | Is `watch` running? `bash updater/gfm-updater.sh status`; if needed `bash updater/register-watcher.sh` |
| "Quick tests did not pass" | The new version is faulty. Nothing was changed. Tell the makers |
| "Not healthy, update not started" | Run `bash health.sh`, fix the FAIL row first |
| "Refused: files changed by hand" | Someone edited the live folder. Ask a developer to look at `git status` |
| Went back by itself | The old version is running. Read `updater/logs/updater-<year>-<month>.log` |
| "Needs a person" | Roll back by hand (above) |
| Pause updates | `bash updater/register-watcher.sh --remove`; start again with `bash updater/register-watcher.sh` |

## History

| Date | Note |
| --- | --- |
| Round 7 | First updater (PowerShell, Windows) |
| Round 13 | Shell updater for new installs; `Track: tags` follows releases |
| Oct 2026 | Page written from `updater/README.md` |

## See also

- [Releases and updates](releases-and-updates.html)
- [Deploy and roll back on Ubuntu](dev-deploy-ubuntu.html)
- [Health check](health-check.html)
- [Nightly backup](nightly-backup.html)
