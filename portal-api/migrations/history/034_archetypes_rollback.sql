-- Rollback of 034_archetypes.sql. Run on Beta only, as supabase_admin, AFTER the portal-api code rollback.
--
-- Removes what 034 added: the two dashboards views, the function behind them, and the three tables with the
-- Archetypal Health settings, their change history and the leader notes. THE SETTINGS, THEIR HISTORY AND THE NOTES ARE
-- LOST: back them up first if they should be kept, e.g.
--   docker exec gfm-beta-supabase-db-1 pg_dump -U postgres -d postgres -Fc -t public.archetype_settings
--     -t public.archetype_settings_history -t public.archetype_notes -f /tmp/archetypes-before-rollback.dump
-- Nothing else changes (033's uploads and every other table stay as they are).
--
-- Apply:
--   (Get-Content portal-api/migrations/034_archetypes_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again (it must end with COMMIT). Safe to run again (IF EXISTS everywhere).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;

SET LOCAL ROLE postgres;

DROP VIEW IF EXISTS dashboards.archetype_area_week;
DROP VIEW IF EXISTS dashboards.archetype_area_profile;
DROP FUNCTION IF EXISTS dashboards.archetype_plan_rows();
DROP TABLE IF EXISTS public.archetype_notes;
DROP TABLE IF EXISTS public.archetype_settings_history;
DROP TABLE IF EXISTS public.archetype_settings;

DO $$
BEGIN
  IF to_regclass('dashboards.archetype_area_week') IS NOT NULL OR to_regclass('public.archetype_notes') IS NOT NULL
     OR to_regclass('public.archetype_settings') IS NOT NULL OR to_regclass('public.archetype_settings_history') IS NOT NULL
     OR to_regprocedure('dashboards.archetype_plan_rows()') IS NOT NULL THEN
    RAISE EXCEPTION 'Rollback check failed: an archetype object is still there.';
  END IF;
END $$;

COMMIT;
