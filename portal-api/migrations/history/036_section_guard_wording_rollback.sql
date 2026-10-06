-- Rollback of 036_section_guard_wording.sql: the section guard says again what migration 024 wrote
-- ("the Key Indicators and Beta depend on it"). Nothing else changes; the rules stay the same either way.
--
-- Apply as supabase_admin:
--   Get-Content portal-api/migrations/036_section_guard_wording_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again (it must end with COMMIT). Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regprocedure('public.planning_question_sections_guard()') IS NULL THEN
    RAISE EXCEPTION 'Nothing to roll back: public.planning_question_sections_guard is missing (migration 024).';
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- Exactly as in 024_planning_catalog.sql.
CREATE OR REPLACE FUNCTION public.planning_question_sections_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Sections are never deleted ("%"). Retire it instead: it then disappears from the form.', OLD.section_title;
  END IF;
  IF NEW.section_key IS DISTINCT FROM OLD.section_key THEN
    RAISE EXCEPTION 'The key of a section never changes ("%"). Change its title instead.', OLD.section_key;
  END IF;
  IF OLD.active AND NOT NEW.active THEN
    IF OLD.section_key = 'key_indicators_conversion' THEN
      RAISE EXCEPTION 'The section "%" stays active: the Key Indicators and Beta depend on it.', OLD.section_title;
    END IF;
    IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.section_id = OLD.id AND q.active AND q.protected) THEN
      RAISE EXCEPTION 'The section "%" holds protected questions, so it stays active. Move them to another section first.', OLD.section_title;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DO $$
BEGIN
  IF position('the Key Indicators and Beta depend on it' IN
              (SELECT prosrc FROM pg_proc WHERE oid = 'public.planning_question_sections_guard()'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'Rollback of 036: the guard does not hold the 024 sentence.';
  END IF;
  RAISE NOTICE 'Rollback of 036: the section guard says what 024 wrote.';
END $$;

COMMIT;
