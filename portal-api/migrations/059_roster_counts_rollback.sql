-- Rollback of 059_roster_counts.sql. Run on Beta only, as supabase_admin.
-- What it does: drops dashboards.roster_area_week. Do it together with the code rollback (the portal-api image
-- without roster charts), or roster charts in decks say their numbers could not load. Safe to run again.
--   (Get-Content portal-api/migrations/059_roster_counts_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
BEGIN;
SET LOCAL lock_timeout = '10s';
DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;
DROP VIEW IF EXISTS dashboards.roster_area_week;
COMMIT;
