-- Rollback of 054_delete_social_media_catalogue.sql. Run on Beta only, as supabase_admin.
--
-- What it does: puts the section 'social_media', its questions, choices, grid rows and rules back, with their old ids and as they
-- were (retired), from the rows that migration 054 wrote to public.planning_catalog_changes (actor 'Migration 054', column
-- before_row). It can restore only what that log still holds: if the log rows were removed, restore from a database backup
-- (CLAUDE.md, "Before any database change"). It stops, changing nothing, if a social-media section or question is already there.
-- The guards of migration 024 allow these inserts (an unprotected retired question, an unused choice). Afterwards the rows are
-- exactly as migration 038 left them. The log rows themselves stay as history. A fresh install's baseline is NOT changed by this file.
--
-- Apply:
--   (Get-Content portal-api/migrations/054_delete_social_media_catalogue_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019_restrict_public_functions.sql again as a check (it must end with COMMIT).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.planning_catalog_changes WHERE actor = 'Migration 054' AND table_name = 'planning_question_sections') THEN
    RAISE EXCEPTION 'The log of migration 054 holds no section row: nothing to restore from (restore from a database backup instead).';
  END IF;
  IF EXISTS (SELECT 1 FROM public.planning_question_sections WHERE section_key = 'social_media') THEN
    RAISE EXCEPTION 'A social_media section exists already. Nothing was changed.';
  END IF;
END $$;

SET LOCAL ROLE postgres;

INSERT INTO public.planning_question_sections
SELECT (jsonb_populate_record(NULL::public.planning_question_sections, c.before_row)).*
FROM public.planning_catalog_changes c
WHERE c.actor = 'Migration 054' AND c.table_name = 'planning_question_sections' ORDER BY c.id;

INSERT INTO public.planning_questions
SELECT (jsonb_populate_record(NULL::public.planning_questions, c.before_row)).*
FROM public.planning_catalog_changes c
WHERE c.actor = 'Migration 054' AND c.table_name = 'planning_questions' ORDER BY c.id;

INSERT INTO public.planning_question_options
SELECT (jsonb_populate_record(NULL::public.planning_question_options, c.before_row)).*
FROM public.planning_catalog_changes c
WHERE c.actor = 'Migration 054' AND c.table_name = 'planning_question_options' ORDER BY c.id;

INSERT INTO public.planning_question_grid_rows
SELECT (jsonb_populate_record(NULL::public.planning_question_grid_rows, c.before_row)).*
FROM public.planning_catalog_changes c
WHERE c.actor = 'Migration 054' AND c.table_name = 'planning_question_grid_rows' ORDER BY c.id;

INSERT INTO public.planning_question_visibility_rules
SELECT (jsonb_populate_record(NULL::public.planning_question_visibility_rules, c.before_row)).*
FROM public.planning_catalog_changes c
WHERE c.actor = 'Migration 054' AND c.table_name = 'planning_question_visibility_rules' ORDER BY c.id;

INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 054 rollback', 'planning_question_sections', jsonb_build_object('section_key', section_key), NULL, to_jsonb(s),
       'Social media rows put back from the log of migration 054 (retired, as before).'
FROM public.planning_question_sections s WHERE s.section_key = 'social_media';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.planning_question_sections WHERE section_key = 'social_media' AND NOT active) THEN
    RAISE EXCEPTION 'Check failed: the social_media section is not back (or not retired).';
  END IF;
  IF EXISTS (SELECT 1 FROM public.planning_questions q JOIN public.planning_question_sections s ON s.id = q.section_id
             WHERE s.section_key = 'social_media' AND (q.active OR q.protected)) THEN
    RAISE EXCEPTION 'Check failed: a restored question is active or protected.';
  END IF;
END $$;

COMMIT;