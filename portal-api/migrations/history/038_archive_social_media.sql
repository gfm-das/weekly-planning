-- Migration 038 (round 11): Facebook, social media and FindeChristus are archived. Run on Beta only, as supabase_admin.
--
-- Why: the mission no longer does Facebook finding or FindeChristus. Missionaries should no longer see the Social
-- Media section in Weekly Planning, leaders no longer old Social Media Action Plans in Call-ins, and Archetypal Health
-- no longer the FindeChristus tip. Nothing is deleted: saved answers, imported spreadsheet answers, uploads and the
-- FindeChristus counting views all stay, and so does every question, choice and grid row (only retired).
--
-- What changes (each catalogue change is written to planning_catalog_changes with actor 'Migration 038', which the
-- rollback reads):
-- 1. Weekly Planning: every question of the section social_media that is still active or protected is retired
--    (active = false) and loses its protection (protected = false). On 2 Oct 2026 that is facebook_finding_days and
--    facebook_friends_found (both protected since 024); findechristus_interactions and social_media_plan were already
--    retired in DA Management that morning, so 038 leaves them (and the rollback does not bring them back). The
--    protection is removed the documented way (024: SET LOCAL planning_catalog.unprotect = 'on'), only for those two
--    keys: any other protected question in the section stops the file. Then the section social_media is retired.
--    The portal's Weekly Planning form reads only active questions in active sections, so the section disappears from
--    the form for the next plan (open forms see it gone once they reload the questions: the catalogue version goes up).
-- 2. Call-ins: public.call_in_planning_details lists every saved *_plan text as an action plan, also of retired
--    questions. It now leaves out social_media_plan as well as weekly_action_plan (an explicit list; other retired
--    *_plan questions still show). The view is written again from its own definition with only that condition
--    changed (same columns, owner, rights and security_invoker); the file stops if the condition is not found exactly
--    once. On 2 Oct 2026 no saved plan has a Social Media Action Plan text, so nothing visible changes today.
-- 3. Archetypal Health: saved settings that still hold the tip "Follow up on FindeChristus referrals within a day."
--    lose it (only that exact text, only where at least one other step stays). Version + 1 and a history row
--    (action 'save', by 'Migration 038'), as a save on the Settings page does. Scores do not change: tips are text.
--    Weights are not touched; on 2 Oct 2026 no mission weights a Facebook or FindeChristus number.
--
-- Apply (back up Beta first, e.g. backups/beta-pre-038-<date>.dump). The file is plain ASCII:
--   Get-Content portal-api/migrations/038_archive_social_media.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- It briefly locks the catalogue tables, the view and the archetype settings. If a long query holds them, the file
-- stops after 10 seconds (lock timeout) and changes nothing; run it again. Safe to run again: it changes only what is
-- still to change. No code needs it first, and it needs no code first.
-- Rollback: 038_archive_social_media_rollback.sql.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regclass('public.planning_catalog_changes') IS NULL THEN
    RAISE EXCEPTION 'Migration 038 needs migration 024 (public.planning_catalog_changes is missing).';
  END IF;
  IF to_regclass('public.archetype_settings_history') IS NULL THEN
    RAISE EXCEPTION 'Migration 038 needs migration 034 (public.archetype_settings_history is missing).';
  END IF;
  IF to_regclass('public.call_in_planning_details') IS NULL THEN
    RAISE EXCEPTION 'Migration 038 needs the Call-ins view public.call_in_planning_details (migrations 014 and 020).';
  END IF;
END $$;

-- 2. Call-ins (as supabase_admin, so the view keeps its owner) -----------------------------------------------------
DO $$
DECLARE
  v_def text := pg_get_viewdef('public.call_in_planning_details'::regclass);
  v_old constant text := '<> ''weekly_action_plan''::text';
  v_new constant text := '<> ALL (ARRAY[''weekly_action_plan''::text, ''social_media_plan''::text])';
  v_hits integer;
BEGIN
  IF position(v_new IN v_def) > 0 THEN
    RAISE NOTICE 'Call-ins already leave out social_media_plan; the view is unchanged.';
    RETURN;
  END IF;
  SELECT count(*) INTO v_hits FROM regexp_matches(v_def, '<> ''weekly_action_plan''::text', 'g');
  IF v_hits <> 1 THEN
    RAISE EXCEPTION 'public.call_in_planning_details: expected the condition % once, found it % times. Nothing was changed.', v_old, v_hits;
  END IF;
  v_def := rtrim(replace(v_def, v_old, v_new), E'; \n');
  EXECUTE 'CREATE OR REPLACE VIEW public.call_in_planning_details WITH (security_invoker = true) AS ' || v_def;
END $$;

-- Everything below belongs to postgres (the catalogue, its history and the archetype settings).
SET LOCAL ROLE postgres;

-- 1. Weekly Planning -------------------------------------------------------------------------------------------------
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(q.question_key, ', ' ORDER BY q.question_key) INTO found
  FROM public.planning_questions q JOIN public.planning_question_sections s ON s.id = q.section_id
  WHERE s.section_key = 'social_media' AND q.protected
    AND q.question_key NOT IN ('facebook_finding_days', 'facebook_friends_found');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'The Social Media section holds other protected questions (%). Check what reads them first. Nothing was changed.', found;
  END IF;
END $$;

SET LOCAL planning_catalog.unprotect = 'on';
WITH old AS (
  SELECT q.id, q.question_key, q.active, q.protected
  FROM public.planning_questions q JOIN public.planning_question_sections s ON s.id = q.section_id
  WHERE s.section_key = 'social_media' AND (q.active OR q.protected)
  FOR UPDATE OF q
), retired AS (
  UPDATE public.planning_questions q SET active = false, protected = false FROM old WHERE q.id = old.id
  RETURNING old.question_key, old.active, old.protected
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 038', 'planning_questions', jsonb_build_object('question_key', question_key),
       jsonb_build_object('active', active, 'protected', protected), jsonb_build_object('active', false, 'protected', false),
       'Social media archived: question retired (saved answers stay).'
FROM retired;
SET LOCAL planning_catalog.unprotect = 'off';

WITH old AS (
  SELECT id, section_key FROM public.planning_question_sections WHERE section_key = 'social_media' AND active FOR UPDATE
), retired AS (
  UPDATE public.planning_question_sections s SET active = false FROM old WHERE s.id = old.id RETURNING old.section_key
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 038', 'planning_question_sections', jsonb_build_object('section_key', section_key),
       jsonb_build_object('active', true), jsonb_build_object('active', false),
       'Social media archived: section retired (saved answers stay).'
FROM retired;

-- 3. Archetypal Health -----------------------------------------------------------------------------------------------
DO $$
DECLARE
  tip constant jsonb := to_jsonb('Follow up on FindeChristus referrals within a day.'::text);
  r record;
  v_patterns jsonb;
  v_new jsonb;
BEGIN
  FOR r IN SELECT mission_id, settings, version FROM public.archetype_settings
           WHERE jsonb_typeof(settings->'diagnoses'->'patterns') = 'object' ORDER BY mission_id FOR UPDATE LOOP
    SELECT jsonb_object_agg(p.key, CASE
             WHEN jsonb_typeof(p.value->'steps') = 'array' AND p.value->'steps' @> jsonb_build_array(tip)
                  AND EXISTS (SELECT 1 FROM jsonb_array_elements(p.value->'steps') e(s) WHERE e.s <> tip)
             THEN jsonb_set(p.value, '{steps}', (SELECT jsonb_agg(e.s ORDER BY e.n)
                                                 FROM jsonb_array_elements(p.value->'steps') WITH ORDINALITY e(s, n)
                                                 WHERE e.s <> tip))
             ELSE p.value END)
      INTO v_patterns FROM jsonb_each(r.settings->'diagnoses'->'patterns') p;
    v_new := jsonb_set(r.settings, '{diagnoses,patterns}', v_patterns);
    IF v_new IS DISTINCT FROM r.settings THEN
      UPDATE public.archetype_settings SET settings = v_new, version = r.version + 1, updated_at = now(),
             updated_by = NULL, updated_by_name = 'Migration 038'
      WHERE mission_id = r.mission_id;
      INSERT INTO public.archetype_settings_history (mission_id, version, action, summary, settings, changed_by, changed_by_name)
      VALUES (r.mission_id, r.version + 1, 'save',
              'Removed the archived tip "Follow up on FindeChristus referrals within a day." (FindeChristus is archived). Scores do not change.',
              v_new, NULL, 'Migration 038');
    END IF;
  END LOOP;
END $$;

-- 4. Check -----------------------------------------------------------------------------------------------------------
DO $$
DECLARE
  found text;
  v_def text := pg_get_viewdef('public.call_in_planning_details'::regclass);
BEGIN
  IF EXISTS (SELECT 1 FROM public.planning_question_sections WHERE section_key = 'social_media' AND active) THEN
    RAISE EXCEPTION 'Check failed: the Social Media section is still active.';
  END IF;
  SELECT string_agg(q.question_key, ', ') INTO found
  FROM public.planning_questions q JOIN public.planning_question_sections s ON s.id = q.section_id
  WHERE s.section_key = 'social_media' AND (q.active OR q.protected);
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: still active or protected: %', found; END IF;
  IF EXISTS (SELECT 1 FROM public.active_planning_questions a JOIN public.planning_questions q ON q.question_key = a.question_key
             JOIN public.planning_question_sections s ON s.id = q.section_id WHERE s.section_key = 'social_media') THEN
    RAISE EXCEPTION 'Check failed: the form still lists Social Media questions.';
  END IF;
  IF position('''social_media_plan''::text' IN v_def) = 0 OR position('''weekly_action_plan''::text' IN v_def) = 0 THEN
    RAISE EXCEPTION 'Check failed: Call-ins do not leave out social_media_plan.';
  END IF;
  IF NOT coalesce((SELECT 'security_invoker=true' = ANY(reloptions) FROM pg_class
                   WHERE oid = 'public.call_in_planning_details'::regclass), false) THEN
    RAISE EXCEPTION 'Check failed: the Call-ins view lost security_invoker.';
  END IF;
  IF NOT has_table_privilege('authenticated', 'public.call_in_planning_details', 'SELECT')
     OR has_table_privilege('anon', 'public.call_in_planning_details', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: the rights on the Call-ins view changed.';
  END IF;
  SELECT string_agg(mission_id::text, ', ') INTO found FROM public.archetype_settings s,
       LATERAL jsonb_each(s.settings->'diagnoses'->'patterns') p
  WHERE jsonb_typeof(s.settings->'diagnoses'->'patterns') = 'object'
    AND p.value->'steps' @> '["Follow up on FindeChristus referrals within a day."]'::jsonb
    AND jsonb_array_length(p.value->'steps') > 1;
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: missions % still hold the FindeChristus tip.', found; END IF;
END $$;

COMMIT;
