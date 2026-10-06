-- Rollback of 024_planning_catalog.sql. Run on Beta only, as supabase_admin, and only together with the code
-- rollback (portal-api, portal planning.html and DA Management of the same round need the 024 columns).
--
-- What it restores (the state before 024, read from the live database on 27 Sep 2026):
-- - planning_question_visibility_rules without row-level security and without its read policy;
-- - anon and authenticated with INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER on the five catalogue
--   tables, and USAGE and UPDATE on their id sequences (SELECT was never removed);
-- - the catalogue tables without the 024 columns (min_value, max_value, integer_only, placeholder,
--   value_when_hidden, protected; updated_at on sections, options, grid rows and rules; created_at on sections),
--   checks and triggers;
-- - the data 024 changed, from the rows it wrote to planning_catalog_changes (actor 'Migration 024'): the three
--   "Only show when ..." help texts (where still empty), the rule "1st Time 1st Week" when "1st Time" > 0
--   (deleted if 024 added it) and the grid answers it turned from [] into {} (where still {}).
-- It drops planning_catalog_version and planning_catalog_changes (the change history made in DA Management is
-- lost) and the index weekly_planning_answers_question_key_idx (third version). Keep a copy first if it is needed:
--   docker exec gfm-beta-supabase-db-1 pg_dump -U postgres -d postgres --data-only -t public.planning_catalog_changes > backups/planning-catalog-changes-<date>.sql
-- Changes made in DA Management after 024 (labels, new questions, rules, retired items) are kept as they are.
--
-- Apply:
--   Get-Content portal-api/migrations/024_planning_catalog_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Safe to run again. The last block checks the result and stops on any problem.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- 1. Triggers first, so the data below can be put back.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['planning_question_sections', 'planning_questions', 'planning_question_options',
                           'planning_question_grid_rows', 'planning_question_visibility_rules'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_touch ON public.%I', t);
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_version ON public.%I', t);
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_no_truncate ON public.%I', t);
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_guard ON public.%I', t);
  END LOOP;
END $$;

-- 2. Data changed by 024 (only while the history table still exists, i.e. on the first run).
DO $$
BEGIN
  IF to_regclass('public.planning_catalog_changes') IS NULL THEN
    RETURN;
  END IF;
  -- As postgres without request claims: a trusted write for the answers guard (the plans' updated_at stays).
  UPDATE public.weekly_planning_answers a SET answer_json = '[]'::jsonb
  FROM public.planning_catalog_changes c
  WHERE c.actor = 'Migration 024' AND c.table_name = 'weekly_planning_answers'
    AND a.id = (c.row_key->>'id')::bigint AND a.answer_json = '{}'::jsonb;
  DELETE FROM public.planning_question_visibility_rules r
  USING public.planning_catalog_changes c
  WHERE c.actor = 'Migration 024' AND c.table_name = 'planning_question_visibility_rules' AND c.before_row IS NULL
    AND r.id = (c.row_key->>'id')::bigint
    AND r.child_question_key = 'sacrament_first_time_first_week' AND r.parent_question_key = 'sacrament_first_time';
  UPDATE public.planning_questions q SET help_text = c.before_row->>'help_text'
  FROM public.planning_catalog_changes c
  WHERE c.actor = 'Migration 024' AND c.table_name = 'planning_questions' AND c.before_row ? 'help_text'
    AND q.question_key = c.row_key->>'question_key' AND q.help_text IS NULL;
END $$;

-- 3. Functions and tables added by 024.
DROP FUNCTION IF EXISTS public.planning_catalog_touch();
DROP FUNCTION IF EXISTS public.planning_catalog_bump_version();
DROP FUNCTION IF EXISTS public.planning_catalog_no_truncate();
DROP FUNCTION IF EXISTS public.planning_option_used(text, text);
DROP FUNCTION IF EXISTS public.planning_question_sections_guard();
DROP FUNCTION IF EXISTS public.planning_questions_guard();
DROP FUNCTION IF EXISTS public.planning_question_options_guard();
DROP FUNCTION IF EXISTS public.planning_question_grid_rows_guard();
DROP FUNCTION IF EXISTS public.planning_visibility_rules_guard();
DROP TABLE IF EXISTS public.planning_catalog_version;
DROP TABLE IF EXISTS public.planning_catalog_changes;
DROP INDEX IF EXISTS public.weekly_planning_answers_question_key_idx;

-- 4. Columns and checks.
ALTER TABLE public.planning_questions DROP CONSTRAINT IF EXISTS planning_questions_key_format;
ALTER TABLE public.planning_questions DROP CONSTRAINT IF EXISTS planning_questions_limits_order;
ALTER TABLE public.planning_questions DROP CONSTRAINT IF EXISTS planning_questions_whole_limits;
ALTER TABLE public.planning_question_sections DROP CONSTRAINT IF EXISTS planning_question_sections_key_format;
ALTER TABLE public.planning_question_visibility_rules DROP CONSTRAINT IF EXISTS planning_visibility_not_self;
ALTER TABLE public.planning_questions
  DROP COLUMN IF EXISTS min_value,
  DROP COLUMN IF EXISTS max_value,
  DROP COLUMN IF EXISTS integer_only,
  DROP COLUMN IF EXISTS placeholder,
  DROP COLUMN IF EXISTS value_when_hidden,
  DROP COLUMN IF EXISTS protected;
ALTER TABLE public.planning_question_sections DROP COLUMN IF EXISTS created_at, DROP COLUMN IF EXISTS updated_at;
ALTER TABLE public.planning_question_options DROP COLUMN IF EXISTS updated_at;
ALTER TABLE public.planning_question_grid_rows DROP COLUMN IF EXISTS updated_at;
ALTER TABLE public.planning_question_visibility_rules DROP COLUMN IF EXISTS updated_at;

-- 5. Security as it was.
DROP POLICY IF EXISTS "Authenticated users can read planning visibility rules" ON public.planning_question_visibility_rules;
ALTER TABLE public.planning_question_visibility_rules DISABLE ROW LEVEL SECURITY;
GRANT INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON
  public.planning_question_sections, public.planning_questions, public.planning_question_options,
  public.planning_question_grid_rows, public.planning_question_visibility_rules
TO anon, authenticated;
GRANT USAGE, UPDATE ON SEQUENCE
  public.planning_question_sections_id_seq, public.planning_questions_id_seq, public.planning_question_options_id_seq,
  public.planning_question_grid_rows_id_seq, public.planning_question_visibility_rules_id_seq
TO anon, authenticated;

-- 6. Check.
DO $$
DECLARE
  found text;
BEGIN
  IF to_regclass('public.planning_catalog_version') IS NOT NULL OR to_regclass('public.planning_catalog_changes') IS NOT NULL THEN
    RAISE EXCEPTION 'Rollback check failed: a 024 table is still there.';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'planning_catalog_%') THEN
    RAISE EXCEPTION 'Rollback check failed: a 024 trigger is still there.';
  END IF;
  IF to_regclass('public.weekly_planning_answers_question_key_idx') IS NOT NULL THEN
    RAISE EXCEPTION 'Rollback check failed: the 024 index on saved answers is still there.';
  END IF;
  SELECT string_agg(table_name || '.' || column_name, ', ') INTO found FROM information_schema.columns
  WHERE table_schema = 'public' AND (
    (table_name = 'planning_questions' AND column_name IN ('min_value', 'max_value', 'integer_only', 'placeholder', 'value_when_hidden', 'protected'))
    OR (table_name = 'planning_question_sections' AND column_name IN ('created_at', 'updated_at'))
    OR (table_name IN ('planning_question_options', 'planning_question_grid_rows', 'planning_question_visibility_rules') AND column_name = 'updated_at'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: columns still there: %', found; END IF;
  IF (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.planning_question_visibility_rules'::regclass) THEN
    RAISE EXCEPTION 'Rollback check failed: row-level security is still on for the rules.';
  END IF;
  SELECT string_agg(format('%s on %s', r.rolname, c.relname), ', ') INTO found
  FROM pg_class c CROSS JOIN (VALUES ('anon'), ('authenticated')) r(rolname)
  WHERE c.oid IN ('public.planning_question_sections'::regclass, 'public.planning_questions'::regclass,
                  'public.planning_question_options'::regclass, 'public.planning_question_grid_rows'::regclass,
                  'public.planning_question_visibility_rules'::regclass)
    AND NOT (has_table_privilege(r.rolname, c.oid, 'SELECT') AND has_table_privilege(r.rolname, c.oid, 'INSERT')
             AND has_table_privilege(r.rolname, c.oid, 'UPDATE') AND has_table_privilege(r.rolname, c.oid, 'DELETE')
             AND has_table_privilege(r.rolname, c.oid, 'TRUNCATE'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: old grants missing for %', found; END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
