# The installer (install/)

What it is: the one command that sets up a mission's own copy of Weekly Planning 3.0. Only Docker is needed on the
computer (Windows, Mac or Linux). Work in progress: everything up to a working portal, with the optional Cloudflare tunnel, is built; the updater and the public release come next.

## Start it
- Mac, Linux, Windows with Git Bash: `./install/install.sh`
- Windows: double-click `install\install.cmd` (it finds Git Bash and runs the same script)
- No screen (a Linux server, or over SSH) starts the terminal questions by itself; `--cli` asks for them on any computer.
  The same questions and rules as the form; passwords and the tunnel token are not shown while you type.
- No questions, from a file: `./install/install.sh --answers my-answers.json`
- `--port 8100` if 8099 is busy, `--no-open` to not open the browser yourself.

## What happens
1. `install.sh` checks that Docker runs, then starts a small throw-away container (`node:24-alpine`, already used by the
   tests) that serves the form at `http://localhost:8099`. The form answers on this computer only (127.0.0.1, and it
   refuses any other host name or website), because it carries a password.
2. The form asks, in this order: mission name (with a short code made from the first letters, and an optional logo), the
   default language (the 14 in `portal/i18n/catalogs.json`, plus "request another language"), the first Data Analyst
   (name, email, password), the optional email, web address and time zone, and the optional Cloudflare tunnel token. It
   never asks for the roster: that is loaded afterwards in DA Management.
3. The answers are checked (`app/validate.mjs`) and saved in `install/.work/answers.json` (and the logo next to it, a
   language request in `language-request.txt`). That folder is ignored by Git and holds the first password: the installer
   deletes it when the installation is finished.
4. Then `run-install.sh` builds the system from `answers.json`, one step after the other (it stops at the first error):
   1. writes the settings files of every part with new secrets (`app/generate.mjs`; it never replaces a file that exists,
      so it cannot damage a computer that already runs the system),
   2. the Docker network and volumes,
   3. the database stack (Supabase),
   4. the database: `portal-api/baseline/000_baseline.sql`, then every migration newer than 040, each followed by
      `019_restrict_public_functions.sql` (as the updater does),
   5. the mission (number 1, `sql/mission.sql`) and the first Data Analyst (`app/first-account.mjs` makes the sign-in in
      Supabase Auth, already confirmed; the profile gets the role Data Analyst),
   6. the programs: portal-api and reminders, DA Management, Presentations, the portal and its pages (`portal/deploy.sh`), the
      nightly backup,
   7. Dashboards (DataEase): its read-only database login, the three dashboards and their 13 language copies,
   8. the Cloudflare tunnel, only when a token was given (`cloudflared/`: a container that restarts by itself; the token is checked
      in the form and needs the public web name; the routes to enter in Cloudflare are printed and kept in `cloudflared/ROUTES.txt`),
   9. the health check (`health.sh`), then the answers file (with the password) is deleted and the addresses are shown.
   Not built yet: the updater on the new computer (phase D).

## The files
| File | What it does |
|---|---|
| `install.sh` | The entry command: checks Docker, starts the form (or checks an answers file), hands over to the build |
| `install.cmd` | Windows: finds Git Bash and runs `install.sh` |
| `app/setup.mjs` | The form's small server, and the saving of the answers |
| `app/validate.mjs` | The rules for every answer, shared by the form and the terminal mode |
| `app/cli.mjs` | The terminal questions (asks again at once for a wrong answer) |
| `app/form.html` | The form itself |
| `app/generate.mjs` | Writes the `.env` files with new secrets (and `.work/install.env`, plain settings for the shell) |
| `app/first-account.mjs` | Makes the first sign-in in Supabase Auth |
| `sql/mission.sql` | Makes mission 1 from the baseline's example row |
| `run-install.sh` | The build, step by step |

Also part of the installer, next to the PowerShell scripts they mirror: `health.sh`, `start-gfm.sh`, `portal/deploy.sh`,
`dataease/set-reader-password.sh`, `dataease/seed-dashboards.sh`, `dataease/translate-dashboards.sh`.
| `tests/*.test.mjs` | Tests of the rules, the terminal mode, the settings files and the first account (no Docker needed) |
| `tests/test-install.sh` | Runs the whole installer for real next to a live system, under other names and ports (`tests/_isolated.sh`, `tests/overrides/`), checks the result, removes everything, and checks the live containers did not change (about 6 minutes, 2 GB) |
| `tests/test-cloudflared.sh` | The tunnel step with no token and with a made-up one: nothing written / the container, settings and routes list, health row (a few minutes, 30 MB) |
| `tests/test-dataease.sh` | The same for Dashboards (DataEase) alone (about 6 minutes, 1.5 GB) |

## Test
`docker run --rm --network none -v "${PWD}:/r" -w /r/install node:24-alpine node --test tests/*.test.mjs` (from the repository root), and
`bash install/tests/test-install.sh` and `bash install/tests/test-dataease.sh` for the real runs.

`*.sh` files keep Unix line endings on Windows too (`.gitattributes`), or Git Bash cannot run them.
