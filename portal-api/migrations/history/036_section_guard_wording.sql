-- Migration 036 (round 9): the database's refusal to retire the key indicator section no longer names Beta.
--
-- Why: Beta (Appsmith) was removed on 29 Sep 2026. Migration 024's guard public.planning_question_sections_guard()
-- still said "the Key Indicators and Beta depend on it" when someone tries to retire the section
-- key_indicators_conversion. DA Management checks this first and shows its own sentence, so people normally never see
-- the database's text; but a stale page or a hand-made request can reach it, and it should be true.
--
-- What changes: only that one sentence. The function is written again exactly as 024 wrote it (same owner postgres,
-- SECURITY DEFINER, search_path, rights and trigger), with the new text:
--   before: The section "%" stays active: the Key Indicators and Beta depend on it.
--   now:    The section "%" stays active: it holds the key indicators that Dashboards, Call-ins and Presentations read
--           every week.
-- The rules themselves (sections are never deleted, keys never change, the key indicator section and sections with
-- protected questions stay active) do not change.
--
-- Apply as supabase_admin (the function belongs to postgres). The file is plain ASCII:
--   Get-Content portal-api/migrations/036_section_guard_wording.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Safe to run again. No code needs it first: portal-api and DA Management never read the text.
-- Rollback: 036_section_guard_wording_rollback.sql (the 024 sentence again).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regprocedure('public.planning_question_sections_guard()') IS NULL THEN
    RAISE EXCEPTION 'Migration 036 needs migration 024 (public.planning_question_sections_guard is missing).';
  END IF;
END $$;
SET LOCAL ROLE postgres;

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
      RAISE EXCEPTION 'The section "%" stays active: it holds the key indicators that Dashboards, Call-ins and Presentations read every week.', OLD.section_title;
    END IF;
    IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.section_id = OLD.id AND q.active AND q.protected) THEN
      RAISE EXCEPTION 'The section "%" holds protected questions, so it stays active. Move them to another section first.', OLD.section_title;
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- Check: the new sentence is in place, Beta is not, and the function kept its owner and settings (its rights
-- stay as they were: CREATE OR REPLACE keeps them).
DO $$
DECLARE
  f record;
BEGIN
  SELECT p.prosrc, pg_get_userbyid(p.proowner) AS owner, p.prosecdef, p.proconfig
    INTO f FROM pg_proc p WHERE p.oid = 'public.planning_question_sections_guard()'::regprocedure;
  IF position('Dashboards, Call-ins and Presentations read every week' IN f.prosrc) = 0 OR position('Beta' IN f.prosrc) > 0 THEN
    RAISE EXCEPTION 'Migration 036: the guard does not hold the new sentence.';
  END IF;
  IF f.owner <> 'postgres' OR NOT f.prosecdef OR f.proconfig IS DISTINCT FROM ARRAY['search_path=public, pg_temp'] THEN
    RAISE EXCEPTION 'Migration 036: the guard changed owner, SECURITY DEFINER or search_path (%, %, %).', f.owner, f.prosecdef, f.proconfig;
  END IF;
  RAISE NOTICE 'Migration 036: the section guard names Dashboards, Call-ins and Presentations.';
END $$;

COMMIT;
