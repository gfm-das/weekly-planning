-- Rollback of 028_new_people_being_taught.sql. Run on Beta only, as supabase_admin.
--
-- What it restores: every label, section description and help text that 028 changed, read from the rows 028
-- wrote to planning_catalog_changes (actor 'Migration 028'), but only where the text is still the one 028 wrote.
-- A text that someone changed in DA Management after 028 is kept and named in a NOTICE. The keys never changed,
-- so saved plans, reports, Dashboards and Presentations are not affected either way.
-- The history keeps 028's rows; this file adds one row per text it puts back (actor 'Migration 028 rollback'), so
-- DA Management's change history shows both. Running 028 again afterwards applies it again.
-- Roll back the code of the same round too if the old name should come back everywhere (DA Management, Grafana
-- and the portal pages show their own labels); the database part alone only changes the planning form's wording.
--
-- Apply:
--   Get-Content portal-api/migrations/028_new_people_being_taught_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/028_new_people_being_taught_rollback.sql | docker exec -i ...)
-- Then run 019 again as a check (it must end with COMMIT). Safe to run again: a second run finds nothing to put
-- back. The last block checks the result and stops on any problem.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regclass('public.planning_catalog_changes') IS NULL THEN
    RAISE EXCEPTION 'There is no change history (024 is not applied), so there is nothing of 028 to roll back.';
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- The latest 028 value of each field, and what it replaced. A field that a later rollback already put back (and
-- 028 did not change again afterwards) is skipped.
CREATE TEMP TABLE m028_undo ON COMMIT DROP AS
WITH written AS (
  SELECT c.id, c.table_name, c.row_key, f.field, c.before_row->>f.field AS before_text, c.after_row->>f.field AS after_text
  FROM public.planning_catalog_changes c
  CROSS JOIN LATERAL jsonb_object_keys(c.after_row) AS f(field)
  WHERE c.actor = 'Migration 028' AND c.table_name IN ('planning_questions', 'planning_question_sections')
    AND f.field IN ('question_label', 'help_text', 'description')
), latest AS (
  SELECT DISTINCT ON (table_name, row_key, field) * FROM written ORDER BY table_name, row_key, field, id DESC
)
SELECT l.* FROM latest l
WHERE NOT EXISTS (SELECT 1 FROM public.planning_catalog_changes r
                  WHERE r.actor = 'Migration 028 rollback' AND r.id > l.id AND r.table_name = l.table_name
                    AND r.row_key = l.row_key AND r.before_row ? l.field);

-- Questions: labels (one statement), then help texts (another), so no row is updated twice in one statement.
WITH todo AS (
  SELECT q.id, u.row_key, u.before_text, u.after_text FROM m028_undo u
  JOIN public.planning_questions q ON u.table_name = 'planning_questions' AND q.question_key = u.row_key->>'question_key'
  WHERE u.field = 'question_label' AND u.before_text IS NOT NULL AND q.question_label = u.after_text
  FOR UPDATE OF q
), changed AS (
  UPDATE public.planning_questions q SET question_label = t.before_text
  FROM todo t WHERE q.id = t.id
  RETURNING q.id
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028 rollback', 'planning_questions', t.row_key, jsonb_build_object('question_label', t.after_text),
       jsonb_build_object('question_label', t.before_text), 'Rollback of migration 028: the wording before it.'
FROM todo t WHERE t.id IN (SELECT id FROM changed);

WITH todo AS (
  SELECT q.id, u.row_key, u.before_text, u.after_text FROM m028_undo u
  JOIN public.planning_questions q ON u.table_name = 'planning_questions' AND q.question_key = u.row_key->>'question_key'
  WHERE u.field = 'help_text' AND q.help_text IS NOT DISTINCT FROM u.after_text
  FOR UPDATE OF q
), changed AS (
  UPDATE public.planning_questions q SET help_text = t.before_text
  FROM todo t WHERE q.id = t.id
  RETURNING q.id
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028 rollback', 'planning_questions', t.row_key, jsonb_build_object('help_text', t.after_text),
       jsonb_build_object('help_text', t.before_text), 'Rollback of migration 028: the wording before it.'
FROM todo t WHERE t.id IN (SELECT id FROM changed);

-- Sections: descriptions.
WITH todo AS (
  SELECT s.id, u.row_key, u.before_text, u.after_text FROM m028_undo u
  JOIN public.planning_question_sections s ON u.table_name = 'planning_question_sections'
    AND s.section_key = u.row_key->>'section_key'
  WHERE u.field = 'description' AND s.description IS NOT DISTINCT FROM u.after_text
  FOR UPDATE OF s
), changed AS (
  UPDATE public.planning_question_sections s SET description = t.before_text
  FROM todo t WHERE s.id = t.id
  RETURNING s.id
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028 rollback', 'planning_question_sections', t.row_key, jsonb_build_object('description', t.after_text),
       jsonb_build_object('description', t.before_text), 'Rollback of migration 028: the wording before it.'
FROM todo t WHERE t.id IN (SELECT id FROM changed);

DO $$
DECLARE
  kept text;
BEGIN
  -- Texts that were changed after 028 are kept (listed, not an error).
  SELECT string_agg(coalesce(u.row_key->>'question_key', u.row_key->>'section_key') || ' ' || u.field, ', ') INTO kept
  FROM m028_undo u
  WHERE NOT EXISTS (SELECT 1 FROM public.planning_catalog_changes r WHERE r.actor = 'Migration 028 rollback'
                    AND r.table_name = u.table_name AND r.row_key = u.row_key AND r.before_row ? u.field AND r.id > u.id);
  IF kept IS NOT NULL THEN
    RAISE NOTICE 'Kept as they are (changed after 028, or already put back): %', kept;
  END IF;
  -- The keys, protection and form place of the key indicator questions are what they were.
  IF (SELECT count(*) FROM public.planning_questions WHERE question_key IN ('friends_found_actual', 'friends_found_goal',
      'friends_found_plan') AND protected AND active) <> 3 THEN
    RAISE EXCEPTION 'Check failed: the three friends_found questions must stay protected and active.';
  END IF;
  -- Every text 028 wrote that is still in place was put back, and what was put back is the text before 028.
  IF EXISTS (
    SELECT 1 FROM m028_undo u
    LEFT JOIN public.planning_questions q ON u.table_name = 'planning_questions' AND q.question_key = u.row_key->>'question_key'
    LEFT JOIN public.planning_question_sections s ON u.table_name = 'planning_question_sections'
      AND s.section_key = u.row_key->>'section_key'
    CROSS JOIN LATERAL (SELECT CASE u.field WHEN 'question_label' THEN q.question_label WHEN 'help_text' THEN q.help_text
                                            ELSE s.description END AS now_text) n
    CROSS JOIN LATERAL (SELECT EXISTS (SELECT 1 FROM public.planning_catalog_changes r
                                       WHERE r.actor = 'Migration 028 rollback' AND r.id > u.id AND r.table_name = u.table_name
                                         AND r.row_key = u.row_key AND r.before_row ? u.field) AS put_back) p
    WHERE (p.put_back AND n.now_text IS DISTINCT FROM u.before_text)
       OR (NOT p.put_back AND n.now_text IS NOT DISTINCT FROM u.after_text)) THEN
    RAISE EXCEPTION 'Check failed: a text written by 028 is still in place, or was not put back as it was.';
  END IF;
  RAISE NOTICE 'Rollback of 028: % text(s) put back in this run.',
    (SELECT count(*) FROM public.planning_catalog_changes WHERE actor = 'Migration 028 rollback'
       AND changed_at = now());
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
