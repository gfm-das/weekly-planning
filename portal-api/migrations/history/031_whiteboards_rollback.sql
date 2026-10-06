-- Rollback of 031_whiteboards.sql: removes the whiteboard tables with every board and picture in them.
-- Run as postgres, only after the portal no longer offers the Whiteboard (portal files and portal-api rolled back,
-- docs/handoff/round6/whiteboard2.md "Rollback"). Keep the boards first if they matter:
--   docker exec gfm-beta-supabase-db-1 pg_dump -U postgres -d postgres -Fc -t portal.whiteboards -t portal.whiteboard_files > backups/whiteboards-<date>.dump
--   (Get-Content portal-api/migrations/031_whiteboards_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
BEGIN;
SET LOCAL lock_timeout = '10s';
DROP TABLE IF EXISTS portal.whiteboard_files;
DROP TABLE IF EXISTS portal.whiteboards;
COMMIT;
