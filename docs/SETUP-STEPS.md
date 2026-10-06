# Setting up a new system, step by step

For a new computer (or a second mission). Everything is run from the repository folder in Windows PowerShell. This is the
written list for the installer that may come later; each step names the file that holds the details. Names in `<angle
brackets>` are yours to choose. Never print or commit a `.env` file.

## 0. What you need
- Windows 11 with Docker Desktop (WSL 2), Git, and a Windows account that stays signed in (Docker Desktop and the updater
  run in it).
- The repository: `git clone https://github.com/gfm-das/weekly-planning <folder>`. Use any folder; the scripts find their own
  place. Work on changes in a worktree, never in this folder (`CLAUDE.md`).
- Optional names and the office address (settings, not code). Set them as Windows environment variables for every script, or
  in the `.env` of the folder that uses them, **before the first start**: `GFM_PORTAL_CONTAINER`, `GFM_PORTAL_VOLUME`,
  `GFM_SLIDEV_CONTAINER`, `GFM_SLIDEV_VOLUME`, `GFM_HOST_IP` (this computer's address in the office network). The defaults are
  this server's values. Each folder's `.env.example` lists its names.

## 1. Docker network and volumes
```powershell
docker network create gfm-network
docker volume create <portal volume>      # default name ydpgd5zwrjrvz5aa188sa60u_portal-data, or your GFM_PORTAL_VOLUME
docker volume create <slidev volume>      # default j5iyrpjbsssqlilqhw9axugx_slidev-data, or your GFM_SLIDEV_VOLUME
```

## 2. The settings files
Copy each `.env.example` to `.env` in the same folder and fill in the values (a comment says what each is):
`supabase\.env`, `portal-api\.env`, `roster-importer\.env`, `slidev\.env`. DataEase writes its own: step 7. The service role
key and the JWT secrets come from the Supabase settings; `PORTAL_SERVICE_KEY` must be the same in `portal-api\.env` and
`slidev\.env`. The portal itself has no secrets (`portal\.env.example` only lists the optional names).

## 3. The database stack (Supabase)
```powershell
docker compose -p gfm-beta --env-file supabase/.env -f supabase/supabase-compose.yml -f supabase/beta-override.yml up -d
docker ps --filter name=gfm-beta     # wait until the database container gfm-beta-supabase-db-1 is "healthy"
```

## 4. The database (baseline, then newer migrations)
Back up first if the database is not new. On an **empty** database, as `supabase_admin`:
```powershell
Get-Content portal-api/baseline/000_baseline.sql -Raw | docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 --single-transaction
Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw | docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
```
The baseline is the whole schema as of migration 040 plus the mission and the planning questions. Any migration with a higher
number than 040 is applied after it, each followed by 019. Check the baseline against a running system with
`portal-api/baseline/check-baseline.ps1`. Then set the mission's name and number if it is not Frankfurt (table
`public.missions`, and `MISSION_ID` in `roster-importer\.env`).

## 5. The programs
```powershell
docker compose -p gfm-portal -f portal-api/compose.yml up -d --build                                        # portal-api and reminders
docker compose -p roster-importer -f roster-importer/docker-compose.yml up -d --build --no-deps roster-importer   # DA Management
docker compose -p slidev -f slidev/slidev-compose.yml -f slidev/local-override.yml up -d --no-deps slidev          # Presentations
docker compose -p portal -f portal/portal-compose.yml -f portal/local-override.yml up -d --no-deps portal           # the portal (nginx)
powershell -NoProfile -ExecutionPolicy Bypass -File portal/deploy.ps1                                       # the portal's pages
```

## 6. The first sign-in
Open DA Management (`http://<address>:8090`) with the shared password from `roster-importer\.env`
(`IMPORTER_PASSWORD`). Create the first staff accounts (President, Data Analysts) under *Staff accounts*, then load the roster
(*Roster Import*). From then on people sign in through the portal at `http://<address>:8070`.

## 7. Dashboards (DataEase)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File dataease/init-env.ps1 -SyncPortalApi     # writes dataease\.env and portal-api's matching secret
powershell -NoProfile -ExecutionPolicy Bypass -File dataease/set-reader-password.ps1         # the read-only database login
docker compose -p gfm-dataease -f dataease/compose.yml up -d                                  # wait about a minute
powershell -NoProfile -ExecutionPolicy Bypass -File dataease/seed-dashboards.ps1              # the three dashboards
powershell -NoProfile -ExecutionPolicy Bypass -File dataease/translate-dashboards.ps1         # their 14 language copies
```
After a DataEase update, rebuild `dataease/web/gfm/preload.js` (`dataease/web/make-preload.mjs`).

## 8. Backups
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File nightly-backup/set-db-password.ps1       # the password file for the nightly backup
docker compose -p gfm-backup -f nightly-backup/backup-compose.yml up -d
```
DataEase backs itself up (`dataease/backup-dataease.ps1`, container `gfm-dataease-backup`). Backups land in `backups\`.

## 9. The updater (Update button)
```powershell
Copy-Item updater/settings.example.json updater/settings.json       # which GitHub remote and branch to follow
powershell -NoProfile -ExecutionPolicy Bypass -File updater/register-task.ps1
```

## 10. Starting after a restart
`start-gfm.ps1` starts Docker Desktop and waits until every part answers; make it run when the Windows account signs in
(a scheduled task, or a shortcut in the Startup folder).

## 11. The public address (optional)
For a public name (for example `https://<your domain>` for the portal and `https://dashboards.<your domain>` for
Dashboards): a Cloudflare tunnel (the Windows service `cloudflared`, set up in the Cloudflare dashboard) with one route per
name to `http://localhost:8070` (portal), `http://localhost:8088` (Dashboards) and the others listed in
`docs/handoff/round10/public-everything.md`. The Windows firewall rule for the office network must allow ports 8070, 8088,
8089, 8090 and 3030. Then set the public names in the `.env` files (each `.env.example` has the lines).

## 12. Check
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File health.ps1       # every row must say OK
```
