-- Migration 056 (round 14, 14 Oct 2026): the Facebook / social-media Weekly Planning section is deleted for real on an
-- installed system: its saved answers, show/hide rules, answer choices, grid rows, questions and the section. No change log,
-- no backup copy (owner: beta, delete instead of archive; the normal nightly backup is the only way back).
-- A fresh install never has these rows (baseline cleaned in round 13; release/scan.sh and
-- portal/tests/no-social-media-seed-check.cjs fail if they come back). On a database without them it does nothing.
-- Also drops portal.presentation_access_v2_removed (the copy table of 053).
-- Replaces the optional 054 of round 13 (which refused to run while answers existed and logged every row for a rollback).
-- Run as supabase_admin; then 019_restrict_public_functions.sql. Rollback: none (by design; restore the nightly backup).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.planning_question_sections') IS NULL OR to_regclass('public.weekly_planning_answers') IS NULL THEN
    RAISE EXCEPTION 'Migration 056 needs the planning catalogue (migration 024) and its answers table.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = 'public.planning_questions_guard()'::regprocedure
                 AND p.prosrc LIKE '%planning_catalog.allow_delete%') THEN
    RAISE EXCEPTION 'Migration 056 needs migration 048 (the planning_catalog.allow_delete switch of planning_questions_guard).';
  END IF;
END $$;

SET LOCAL ROLE postgres;

-- 1. The checks (nothing is changed before all three pass). ----------------------------------------------------------------
DO $$
DECLARE
  v_keys text[];
  v_sections bigint[];
  v_active text;
  v_outside text;
BEGIN
  SELECT coalesce(array_agg(id), '{}') INTO v_sections FROM public.planning_question_sections WHERE section_key = 'social_media';
  IF cardinality(v_sections) = 0 THEN
    RAISE NOTICE 'Migration 056: there is no social_media section here (a fresh install). Nothing to do.';
    RETURN;
  END IF;
  SELECT coalesce(array_agg(question_key), '{}') INTO v_keys FROM public.planning_questions WHERE section_id = ANY (v_sections);


  SELECT string_agg(question_key, ', ') INTO v_active FROM public.planning_questions
   WHERE section_id = ANY (v_sections) AND (active OR protected);
  IF v_active IS NOT NULL THEN
    RAISE EXCEPTION 'Migration 056 STOPPED, nothing was changed: still active or protected: %. Apply migration 038 first (it retires them).', v_active;
  END IF;

  SELECT string_agg(r.child_question_key || ' <- ' || r.parent_question_key, ', ') INTO v_outside
    FROM public.planning_question_visibility_rules r
   WHERE (r.child_question_key = ANY (v_keys)) <> (r.parent_question_key = ANY (v_keys));
  IF v_outside IS NOT NULL THEN
    RAISE EXCEPTION 'Migration 056 STOPPED, nothing was changed: a show/hide rule ties a social-media question to another section (%). Look at it in DA Management first.', v_outside;
  END IF;
END $$;

-- 2. Delete the saved answers to these questions (owner, 14 Oct 2026: gone for real, no copies kept). -------------------
DELETE FROM public.weekly_planning_answers
 WHERE question_key IN (SELECT q.question_key FROM public.planning_questions q
                        JOIN public.planning_question_sections s ON s.id = q.section_id WHERE s.section_key = 'social_media')
    OR question_key IN ('facebook_finding_days', 'facebook_friends_found', 'findechristus_interactions', 'social_media_plan');

-- 3. Delete (the guards of 024 / 048 stay on, see the header). ------------------------------------------------------------
DELETE FROM public.planning_question_visibility_rules
 WHERE child_question_key IN (SELECT question_key FROM public.planning_questions q JOIN public.planning_question_sections s ON s.id = q.section_id WHERE s.section_key = 'social_media');
DELETE FROM public.planning_question_options o USING public.planning_questions q, public.planning_question_sections s
 WHERE q.id = o.question_id AND s.id = q.section_id AND s.section_key = 'social_media';
DELETE FROM public.planning_question_grid_rows g USING public.planning_questions q, public.planning_question_sections s
 WHERE q.id = g.question_id AND s.id = q.section_id AND s.section_key = 'social_media';

SET LOCAL planning_catalog.allow_delete = 'on';
DELETE FROM public.planning_questions q USING public.planning_question_sections s
 WHERE s.id = q.section_id AND s.section_key = 'social_media';
SET LOCAL planning_catalog.allow_delete = 'off';

ALTER TABLE public.planning_question_sections DISABLE TRIGGER planning_catalog_guard;
DELETE FROM public.planning_question_sections WHERE section_key = 'social_media';
ALTER TABLE public.planning_question_sections ENABLE TRIGGER planning_catalog_guard;

-- 3b. The Presentations V2 copy table left by 053 goes too (owner: no archive copies in beta). ---------------------------
DROP TABLE IF EXISTS portal.presentation_access_v2_removed;

-- 4. Check. -----------------------------------------------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.planning_question_sections WHERE section_key = 'social_media')
     OR EXISTS (SELECT 1 FROM public.planning_questions WHERE question_key IN ('facebook_finding_days', 'facebook_friends_found', 'findechristus_interactions', 'social_media_plan')) THEN
    RAISE EXCEPTION 'Check failed: social-media catalogue rows are still there.';
  END IF;
  IF (SELECT count(*) FROM pg_trigger WHERE tgrelid = 'public.planning_question_sections'::regclass
        AND tgname = 'planning_catalog_guard' AND tgenabled = 'O') <> 1 THEN
    RAISE EXCEPTION 'Check failed: the guard trigger of planning_question_sections is not switched on.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE NOT EXISTS (SELECT 1 FROM public.planning_question_sections s WHERE s.id = q.section_id)) THEN
    RAISE EXCEPTION 'Check failed: a question has no section.';
  END IF;
END $$;

COMMIT;