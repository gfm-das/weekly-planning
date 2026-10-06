# Operations tests

The tests of the scripts that keep the mission system running: the portal deploy (`portal/deploy.ps1`), the health
check (`health.ps1`), the updater (`updater/`), the nightly backup (`nightly-backup/`) and the Dashboards (DataEase)
scripts and backup (`dataease/`).

**Nothing real is touched.** The tests use stand-ins ("pretend" versions) of `docker`, of the web and of the database
tools, so no container, volume, database or web page is changed or even asked.

## Run them all

From the repository root, in Windows PowerShell 5.1 or PowerShell 7:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ops-tests\run-all.ps1
```

It prints one line per part and a total, for example:

```
PASS  portal/deploy.ps1  (Deploy tests: 36 passed, 0 did not pass.)
PASS  health.ps1  (Health tests: 26 passed, 0 did not pass.)
PASS  updater  (Updater tests: 58 passed, 0 did not pass.)
PASS  nightly backup  (Nightly backup tests: 37 passed, 0 did not pass.)
PASS  Dashboards (DataEase) scripts  (tests 42; pass 42; fail 0)
PASS  Dashboards (DataEase) backup  (DataEase backup tests: 21 passed, 0 did not pass.)

Operations tests: 6 of 6 parts passed.
```

A part that does not pass shows its last 40 lines, and the exit code is 1. About two minutes in all.

It needs Docker for the two Linux parts (they run in throw-away containers with **no network**, on the local images
`postgres:15-alpine` and `node:24-alpine`). Nothing is downloaded.

## The files in this folder

| File | What it tests |
|---|---|
| `run-all.ps1` | Runs every part below and adds up the result. |
| `test-deploy.ps1` | `portal/deploy.ps1`: which `docker` commands it gives, in which order; that it stops (and copies nothing, or reloads nothing) on a missing network, unreadable compose files, a missing key or a failed copy; the retired paths it removes (such as the old nested `html/i18n/i18n` folder). |
| `test-dataease-backup.ps1` | `dataease/backup-dataease.ps1`: a backup (dump in one snapshot, file volumes read only, nothing stopped), an almost empty or failed backup, and a restore (backup first, then stop, load, start again; started again even when loading fails). |
| `test-health.ps1` | `health.ps1`: every state of the "Nightly backup" row (OK, waiting, SKIPPED, FAIL), a web check, the row order and the exit code. |

The other parts keep their tests next to their code: `updater/tests/test-updater.ps1`,
`nightly-backup/tests/test-nightly.sh` and `dataease/tests/*.test.mjs`. Each folder's README says how to run it alone.

## Add a test

Each test file puts a stand-in in front of the real program (a PowerShell function called `docker` wins over
`docker.exe`), loads the script with `-NoRun` (only its functions, nothing is run) or runs it on a temporary folder,
and checks what came out with `Assert-That <true or false> '<what should be true>'`. Copy one of the existing checks
and change it.
