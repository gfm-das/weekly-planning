-- Rollback of migration 038 (Facebook, social media and FindeChristus archived). Run on Beta only, as supabase_admin.
--
-- What it undoes, from what 038 wrote (actor 'Migration 038' in planning_catalog_changes, changed_by_name
-- 'Migration 038' in archetype_settings_history):
-- 1. The section social_media is active again, and so is every question 038 retired, with the protection it had
--    (facebook_finding_days and facebook_friends_found protected again). Questions that were already retired before
--    038 (findechristus_interactions, social_media_plan: retired in DA Management on 2 Oct 2026) stay retired. A
--    question that is active again by now is left as it is. Each change is written to planning_catalog_changes with
--    actor 'Migration 038 rollback'.
-- 2. Call-ins show Social Media Action Plans again (the view condition of 020).
-- 3. Archetypal Health: where 038 took the FindeChristus tip out of a mission's settings, it comes back: the steps of
--    that diagnosis as they were before 038 if nobody changed them since, otherwise the tip is added at the end (when
--    the diagnosis has fewer than three steps; else a NOTICE says it was left out). Version + 1 and a history row by
--    'Migration 038 rollback'. Scores do not change.
-- Saved answers were never touched, so nothing else needs restoring. Roll back the code of the same round too
-- (git revert), or the Data uploads and Archetypal Health pages stay as 038 expects; both work with either.
--
-- Apply:
--   Get-Content portal-api/migrations/038_archive_social_media_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again (it must end with COMMIT). Safe to run again; 038 can be applied again afterwards.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;

-- 2. Call-ins (as supabase_admin, so the view keeps its owner) -----------------------------------------------------
DO $$
DECLARE
  v_def text := pg_get_viewdef('public.call_in_planning_details'::regclass);
  v_old constant text := '<> ALL (ARRAY[''weekly_action_plan''::text, ''social_media_plan''::text])';
  v_new constant text := '<> ''weekly_action_plan''::text';
  v_hits integer;
BEGIN
  SELECT count(*) INTO v_hits FROM regexp_matches(v_def, '<> ALL \(ARRAY\[''weekly_action_plan''::text, ''social_media_plan''::text\]\)', 'g');
  IF v_hits = 0 THEN
    RAISE NOTICE 'Call-ins already show Social Media Action Plans; the view is unchanged.';
    RETURN;
  ELSIF v_hits <> 1 THEN
    RAISE EXCEPTION 'public.call_in_planning_details: expected the condition of 038 once, found it % times. Nothing was changed.', v_hits;
  END IF;
  v_def := rtrim(replace(v_def, v_old, v_new), E'; \n');
  EXECUTE 'CREATE OR REPLACE VIEW public.call_in_planning_details WITH (security_invoker = true) AS ' || v_def;
END $$;

SET LOCAL ROLE postgres;

-- 1. Weekly Planning -------------------------------------------------------------------------------------------------
WITH old AS (
  SELECT id FROM public.planning_question_sections WHERE section_key = 'social_media' AND NOT active
    AND EXISTS (SELECT 1 FROM public.planning_catalog_changes c WHERE c.actor = 'Migration 038'
                AND c.table_name = 'planning_question_sections' AND c.row_key = '{"section_key": "social_media"}'::jsonb)
  FOR UPDATE
), restored AS (
  UPDATE public.planning_question_sections s SET active = true FROM old WHERE s.id = old.id RETURNING s.section_key
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 038 rollback', 'planning_question_sections', jsonb_build_object('section_key', section_key),
       jsonb_build_object('active', false), jsonb_build_object('active', true), 'Rollback of 038: section active again.'
FROM restored;

WITH last038 AS (
  SELECT DISTINCT ON (c.row_key->>'question_key') c.row_key->>'question_key' AS question_key,
         (c.before_row->>'active')::boolean AS active, (c.before_row->>'protected')::boolean AS protected
  FROM public.planning_catalog_changes c
  WHERE c.actor = 'Migration 038' AND c.table_name = 'planning_questions' AND c.row_key ? 'question_key'
  ORDER BY c.row_key->>'question_key', c.changed_at DESC, c.id DESC
), old AS (
  SELECT q.id, q.question_key, l.active, l.protected FROM public.planning_questions q JOIN last038 l USING (question_key)
  WHERE NOT q.active AND NOT q.protected AND (l.active OR l.protected)
  FOR UPDATE OF q
), restored AS (
  UPDATE public.planning_questions q SET active = old.active, protected = old.protected FROM old WHERE q.id = old.id
  RETURNING old.question_key, old.active, old.protected
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 038 rollback', 'planning_questions', jsonb_build_object('question_key', question_key),
       jsonb_build_object('active', false, 'protected', false), jsonb_build_object('active', active, 'protected', protected),
       'Rollback of 038: question as before 038.'
FROM restored;

-- 3. Archetypal Health -----------------------------------------------------------------------------------------------
DO $$
DECLARE
  tip constant jsonb := to_jsonb('Follow up on FindeChristus referrals within a day.'::text);
  r record;
  p record;
  v_before jsonb;
  v_settings jsonb;
  v_steps jsonb;
BEGIN
  FOR r IN SELECT s.mission_id, s.settings, s.version, h.version AS v038
           FROM public.archetype_settings s
           JOIN LATERAL (SELECT h.version FROM public.archetype_settings_history h
                         WHERE h.mission_id = s.mission_id AND h.changed_by_name = 'Migration 038'
                         ORDER BY h.version DESC, h.id DESC LIMIT 1) h ON true
           WHERE NOT EXISTS (SELECT 1 FROM public.archetype_settings_history b
                             WHERE b.mission_id = s.mission_id AND b.changed_by_name = 'Migration 038 rollback'
                               AND b.version > h.version)
           ORDER BY s.mission_id FOR UPDATE OF s LOOP
    SELECT h.settings INTO v_before FROM public.archetype_settings_history h
    WHERE h.mission_id = r.mission_id AND h.version = r.v038 - 1 ORDER BY h.id DESC LIMIT 1;
    v_settings := r.settings;
    FOR p IN SELECT key, value FROM jsonb_each(r.settings->'diagnoses'->'patterns') LOOP
      CONTINUE WHEN jsonb_typeof(p.value->'steps') <> 'array' OR p.value->'steps' @> jsonb_build_array(tip);
      v_steps := v_before->'diagnoses'->'patterns'->p.key->'steps';
      IF v_before IS NULL THEN
        -- No history row before 038 (should not happen): only the pattern the tip came from.
        CONTINUE WHEN p.key <> 'finding_low_teaching_strong';
        v_steps := NULL;
      ELSIF jsonb_typeof(v_steps) IS DISTINCT FROM 'array' OR NOT v_steps @> jsonb_build_array(tip) THEN
        CONTINUE;  -- 038 did not take the tip out of this diagnosis
      END IF;
      IF v_steps IS NOT NULL AND (SELECT coalesce(jsonb_agg(e.s ORDER BY e.n), '[]'::jsonb)
                                  FROM jsonb_array_elements(v_steps) WITH ORDINALITY e(s, n) WHERE e.s <> tip) = p.value->'steps' THEN
        v_settings := jsonb_set(v_settings, ARRAY['diagnoses', 'patterns', p.key, 'steps'], v_steps);
      ELSIF jsonb_array_length(p.value->'steps') < 3 THEN
        v_settings := jsonb_set(v_settings, ARRAY['diagnoses', 'patterns', p.key, 'steps'], (p.value->'steps') || jsonb_build_array(tip));
      ELSE
        RAISE NOTICE 'Mission %: the diagnosis % has three steps by now, so the FindeChristus tip was not added back.', r.mission_id, p.key;
      END IF;
    END LOOP;
    IF v_settings IS DISTINCT FROM r.settings THEN
      UPDATE public.archetype_settings SET settings = v_settings, version = r.version + 1, updated_at = now(),
             updated_by = NULL, updated_by_name = 'Migration 038 rollback'
      WHERE mission_id = r.mission_id;
      INSERT INTO public.archetype_settings_history (mission_id, version, action, summary, settings, changed_by, changed_by_name)
      VALUES (r.mission_id, r.version + 1, 'save',
              'Added back the tip "Follow up on FindeChristus referrals within a day." (rollback of migration 038). Scores do not change.',
              v_settings, NULL, 'Migration 038 rollback');
    END IF;
  END LOOP;
END $$;

-- 4. Check -----------------------------------------------------------------------------------------------------------
DO $$
BEGIN
  IF position('''social_media_plan''::text' IN pg_get_viewdef('public.call_in_planning_details'::regclass)) > 0 THEN
    RAISE EXCEPTION 'Check failed: Call-ins still leave out social_media_plan.';
  END IF;
  IF NOT coalesce((SELECT 'security_invoker=true' = ANY(reloptions) FROM pg_class
                   WHERE oid = 'public.call_in_planning_details'::regclass), false) THEN
    RAISE EXCEPTION 'Check failed: the Call-ins view lost security_invoker.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.planning_catalog_changes WHERE actor = 'Migration 038')
     AND NOT EXISTS (SELECT 1 FROM public.planning_question_sections WHERE section_key = 'social_media' AND active) THEN
    RAISE EXCEPTION 'Check failed: the Social Media section is still retired.';
  END IF;
END $$;

COMMIT;
