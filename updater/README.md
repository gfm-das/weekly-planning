# The updater (DA Management > Updates)

The updater brings the mission system on this computer up to date from GitHub, **only when a person asks** (the
**Update now** button in DA Management > Updates, or a command in a terminal). Before it changes anything it tests
the new version, checks that the system is healthy, and saves a way back. If the new version does not work, it puts
the old one back by itself.

It runs on the Windows computer itself (not in a container), because it needs Git and Docker.

## The files in this folder

| File | What it does |
|---|---|
| `gfm-updater.ps1` | The updater. Modes: `Check` (what is new on GitHub?), `Update` (install it), `Watch` (keep running and answer the Updates page), `Status` (print the status file). |
| `quick-tests.ps1` | The tests it runs on a copy of the new version before installing (about a minute, no network). |
| `register-task.ps1` | Creates the Windows scheduled task "GFM Updater", which keeps `gfm-updater.ps1 -Mode Watch` running. Run once. |
| `settings.example.json` | The settings you may change (which remote and branch to follow, how often to check). Copy it to `settings.json`. |
| `tests/test-updater.ps1` | The updater's own tests (58 checks, no Docker, no network: a local Git folder stands in for GitHub). |

## The shell updater and the releases (new installs)

A new mission's computer (Windows, Mac or Linux) uses the **shell updater**; the Frankfurt server keeps the PowerShell one. They do the same thing
step by step, write the same status file and read the same request file, so DA Management > Updates works with either.

| File | What it does |
|---|---|
| `gfm-updater.sh` | The shell updater: `check`, `update` (add `--confirmed` to skip the typed question), `watch`, `status`. Needs only bash, git and docker. |
| `quick-tests.sh` | The quick tests it runs on a copy of the new version (the shell twin of `quick-tests.ps1`). |
| `register-watcher.sh` | Makes the computer's own scheduler keep `watch` running, without administrator rights: a Task Scheduler task on Windows, two crontab lines on Linux, a launch agent on Mac. `--remove` takes it away, `--dry-run` shows what it would do. |
| `tests/test-updater.sh` | Its tests (about 50 checks, no Docker, no network: a local folder stands in for GitHub and a fake `docker` writes down what it is asked). |

**What it follows** is set in `settings.json` (copy `settings.example.json`):
`{"Remote": "origin", "Branch": "main", "Track": "tags", "CheckEveryHours": 6}`.
`Track: "branch"` (the default, and the Frankfurt way) follows the newest commit of `Remote/Branch`. `Track: "tags"` follows the **releases** of the
remote: the newest tag of the form `vX.Y.Z` (`v1.10.0` after `v1.9.0`; other tags such as `v2-beta` are not releases). The installer writes
`"Track": "tags"`; the public repository has one commit per release in a line, so every release is a plain step forward.

Windows note: the shell updater runs in Git Bash (Git for Windows). Folder names are given to git and docker in the form `C:/Users/...` (they do not
understand Git Bash's `/c/Users/...`).

Folders the updater makes on this computer (not in Git): `requests/` (the Updates page leaves a request here),
`status/` (the updater writes what it found and did; the page may only read it), `logs/` (one log per month), and
`backups\updater\<time>\` in the repository (the way back of each update).

## How it works

```
 DA Management > Updates (web page, in a container)            The updater (PowerShell on this computer)
 ---------------------------------------------------           ------------------------------------------
 "Check for updates"  --writes--> updater\requests\request.json --> reads it once, checks every field, deletes it
 "Update now" (type UPDATE)                                          git fetch / tests / backup / install / health
 shows version, what is new,  <--reads--  updater\status\status.json <-- writes what it found and did
 the last result                         (read-only for the page)
```

The web page never runs a program. It only leaves a tiny request file. The updater accepts exactly two requests,
`check` and `update`, and an update only for the exact version the person saw.

An update, step by step:

1. **Only forward.** It refuses when this computer has changes GitHub does not have, when files were changed by hand,
   or when a new database migration says `updater: install by hand` in its header.
2. **Quick tests** on a copy of the new version (`quick-tests.ps1`). If they fail, nothing changes.
3. **Health first** (`health.ps1`): an update starts only from a healthy system.
4. **Way back saved:** the current version (commit), a database backup, rollback copies of the images, and a copy of
   the portal's pages, in `backups\updater\<time>\`.
5. **Install:** the new code, the new migrations in order (each followed by migration 019, the rights check), then
   only the parts that changed: portal-api, DA Management, Presentations (Slidev), the portal pages (`portal\deploy.ps1`).
6. **Health again** (6 tries, 30 s apart). If it does not pass, the updater puts the old version back by itself and the
   page says so. If even that fails, the page says "needs a person" and the log lists every step.

Everything is written to `updater\logs\updater-<year>-<month>.log`. Passwords and tokens are never written.

## Everyday use

- The page: DA Management > Updates (for the AP, the President and the Data Analyst).
- In a terminal: `powershell -NoProfile -ExecutionPolicy Bypass -File updater\gfm-updater.ps1 -Mode Check`
  (or `-Mode Update`, which shows the list and asks you to type UPDATE).
- Pause it: `Disable-ScheduledTask -TaskName 'GFM Updater'` (and `Enable-ScheduledTask` to start again).

The one-time setup (connecting this computer to GitHub, the owner's decision about pushing the code to a private
repository, the settings, the scheduled task) is in `docs/handoff/round7/updater.md`.

## Roll back an update by hand

Only needed when the page says "needs a person". Everything is in `backups\updater\<time>\` (`repo-head.txt`,
`portal-html`, `rollback-sql`), the image tags `*-rollback:upd-<time>` and `backups\beta-pre-update-<time>.dump`. The
steps are the ones in the log, in the order of `Undo-Update` in `gfm-updater.ps1`. Restore a database dump only into
an empty database (`nightly-backup/README.md`).

## Test

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File updater\tests\test-updater.ps1     # 58 checks, about 40 s
pwsh -NoProfile -File updater\tests\test-updater.ps1                                   # the same in PowerShell 7
```

`quick-tests.ps1` itself runs as the updater runs it: `git archive` a version into a folder, then
`quick-tests.ps1 -Root <that folder>` (it needs Docker and the local images `node:24-alpine`, `python:3.12-alpine`
and `roster-importer-roster-importer`).

**Save PowerShell files with letters beyond English as "UTF-8 with BOM".** The updater runs in Windows PowerShell 5.1,
which reads a `.ps1` without a BOM as ANSI. Letters such as ä are only shown wrongly, but Arabic or Chinese text can
break the script, and then the parse check stops every update ("Quick tests that did not pass: PowerShell
<name>.ps1"). This happened once, with `dataease/i18n/tests/edge_i18n.ps1` (fixed in round 9).
