---
title: Releases and updates
slug: releases-and-updates
lead: explains in plain English how a new version is built, published and installed from DA Management > Updates, and how to go back.
summary: Build, publish, install and roll back a release.
status: full
navboxes: [admin]
infobox_title: Releases
icon: "📦"
infobox_rows: ["Install from|DA Management > Updates", "Version form|vMAJOR.MINOR.PATCH", "Runs on|Ubuntu, bash", "Way back|Automatic, or by hand"]
tags: [admin, ops, release, update]
---

## Usage

### Install a new version (any Data Analyst)

1. Open **DA Management > Updates**.
2. Press **Check for updates**. The page shows the version you have, the newest release and what is new.
3. Read what is new. Choose a quiet time (not Sunday evening, when plans are being filled).
4. Press **Update now** and type `UPDATE` to confirm.
5. Wait. The page shows the steps. It takes a few minutes.
6. The page says it worked, or that it went back to the old version. Then open the portal and click through Overview and Weekly Planning.

Only the AP, the President and the Data Analyst can open this page.

### The same in a terminal on the server

```bash
bash updater/gfm-updater.sh check      # what is new?
bash updater/gfm-updater.sh update     # install it (asks you to type UPDATE)
bash updater/gfm-updater.sh status     # what it found and did
bash health.sh                          # every row must say OK
```

### Make and publish a release (the makers)

Do this from a worktree, never in the live folder.

```bash
bash release/build-release.sh v1.1.0   # 1. build (about 10 minutes, it runs the tests twice)
# 2. read backups/release/v1.1.0/RELEASE-NOTES.md
#    (put your own text in release/notes/v1.1.0.md first, then build again)
bash release/publish.sh v1.1.0         # 3. shows the plan, changes nothing
bash release/publish.sh v1.1.0 --go    # 4. publishes - only after the owner says go
```

Version numbers are `vMAJOR.MINOR.PATCH`:

| Part | Use it for |
| --- | --- |
| PATCH (v1.0.**5**) | Fixes |
| MINOR (v1.**1**.0) | New things that install by themselves, including new database migrations |
| MAJOR (v**2**.0.0) | A change that needs a person, for example a new database server version |

A published version is never replaced. A mistake is fixed by the next version.

### Roll back

- **Automatic:** if the health check fails after an update, the updater puts the old version back by itself. The Updates page says so.
- **Page says "needs a person":** follow [Updater](updater.html), section "Roll back by hand".
- **A bad release nobody has installed yet:** delete the GitHub Release and its tag, then publish the corrected version under the same number and say so in the notes (needs a person with admin rights on the public repository).
- **A bad release that people installed:** publish the next PATCH. Never rewrite an installed release.

## How it works

**Building** (`release/build-release.sh`):

1. Takes the committed files of the private repository. Work that is not committed never goes in.
2. Leaves out files that are only for us (the server's notes, the release folder, the website source).
3. Adds the public README, the licence, the notices and the version file.
4. Replaces this mission's own names, addresses and paths with neutral ones.
5. **Scans** the result for names, keys, tokens, `.env` files and dumps (`release/scan.sh`). One hit stops the build.
6. **Verifies**: runs the tests on the original and on the release, and compares. If they differ, a rewrite broke something and the build stops.
7. Packs the release: a `.tar.gz`, the two starter scripts, a checksum list and the release notes.

**Publishing** (`release/publish.sh`): checks the build and that the version is new, then commits `Release vX.Y.Z` to the public repository, tags it, makes the GitHub Release with the files and notes, and updates the website. It does nothing until you add `--go`. Nothing is ever pushed to the private repository's branches or tags.

**Installing:** every installed copy follows the public releases (`Track: tags` in `updater/settings.json`). The public repository has one commit per release, so each update is a plain step forward. The updater tests the new version, checks health, saves a way back, installs, and checks health again. Details: [Updater](updater.html).

## Permissions

| Who | What |
| --- | --- |
| AP, President, Data Analyst | See and use DA Management > Updates |
| The makers (with the owner's go) | Run `publish.sh --go` (needs the GitHub `gh` program, signed in) |

The page never runs a program. It only leaves a small request file that the updater checks.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Updates page shows no version or no status | The updater is not running. See [Updater](updater.html) |
| "Refused: changes GitHub does not have" | Someone edited files on the server by hand. A developer must clean that first |
| "Refused: install by hand" | The new release has a migration that needs a person. Ask a developer |
| "The way back could not be saved" (refused, `rollback_point_failed`), version 1.0.6 | Old quick-test folders in `backups/updater/` hold files the updater cannot delete. Remove them once, then press Update now again: `docker run --rm -v ~/weekly-planning/backups/updater:/b node:24-alpine sh -c 'rm -rf /b/*-tests'`. Version 1.0.8 and newer clean up after themselves |
| Update went back by itself | Read the last lines of the log in `updater/logs/`. The old version is running and healthy |
| Page says "needs a person" | [Updater](updater.html), "Roll back by hand" |
| Build stops at the scan | A forbidden name or file is in the release. The message names the file |
| Build stops at verify | A test fails in the source, or the release differs from it. Fix the test or add it to `release/exclude.txt` with a reason |

## History

| Date | Note |
| --- | --- |
| 6 Oct 2026 | Public release repository and licence decided |
| Oct 2026 | Page written from `release/README.md` and `updater/README.md` |
| 15 Oct 2026 | The refused-update fix of version 1.0.8 and its one-time clean-up added |

## See also

- [Updater](updater.html)
- [Deploy and roll back on Ubuntu](dev-deploy-ubuntu.html)
- [Backups and restore](backups-and-restore.html)
- [Health check](health-check.html)
