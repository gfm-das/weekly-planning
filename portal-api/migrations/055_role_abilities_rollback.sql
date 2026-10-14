-- Rollback of 055_role_abilities.sql. Run on Beta only, as supabase_admin.
--
-- What it does: drops public.role_has_ability, the three tables (public.role_abilities, public.role_abilities_log, public.ability_catalog)
-- WITH THEIR ROWS, the trigger functions and public.role_ability_ok. Nothing else is touched. After this the code (roles.py in
-- portal-api and DA Management) cannot read the table and uses its built-in matrix, which is today's behaviour as it was before any
-- switch was changed: every switch a manager changed is forgotten. The change log goes with the tables: take a backup first
-- (or copy the log: SELECT * FROM public.role_abilities_log) if it should be kept.
-- Do it together with the code rollback (the images without the Role abilities screen), or that page shows an error.
-- Order: nothing in the database depends on these objects yet (no policy calls role_has_ability); if a later migration made a policy
-- depend on it, roll that one back first (this file stops with a "depends on" error otherwise, and changes nothing).
--
-- Apply:
--   (Get-Content portal-api/migrations/055_role_abilities_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check. Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.role_has_ability(text);
DROP TABLE IF EXISTS public.role_abilities_log;
DROP TABLE IF EXISTS public.role_abilities;
DROP TABLE IF EXISTS public.ability_catalog;
DROP FUNCTION IF EXISTS public.role_abilities_guard();
DROP FUNCTION IF EXISTS public.role_abilities_write_log();
DROP FUNCTION IF EXISTS public.role_abilities_log_append_only();
DROP FUNCTION IF EXISTS public.role_ability_ok(text, text, boolean);

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(n.nspname || '.' || c.relname, ', ') INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relname IN ('ability_catalog', 'role_abilities', 'role_abilities_log');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: still there: %', found; END IF;
  SELECT string_agg(p.proname, ', ') INTO found
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.proname IN ('role_has_ability', 'role_ability_ok', 'role_abilities_guard', 'role_abilities_write_log', 'role_abilities_log_append_only');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: functions still there: %', found; END IF;
END $$;

COMMIT;
