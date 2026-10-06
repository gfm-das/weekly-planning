-- Weekly Planning questions managed in DA Management ("Planning questions" page). Run on Beta only, as supabase_admin.
--
-- Why: the planning question catalogue (sections, questions, answer choices, grid rows and show/hide rules) is
-- already in the database and Beta (Appsmith) builds its form from it. The portal's Weekly Planning page now does
-- too, and DA Management gets a page to change the questions. Saved answers point at a question only by its key
-- (weekly_planning_answers has no foreign key), and Dashboards, Call-ins, Presentations and Beta read some keys by
-- name, so the database itself must refuse the changes that would break saved plans or reports, also from
-- Supabase Studio. And the show/hide rules table had row-level security turned off while anon and authenticated
-- could write it, so anyone with the public anon key could change or delete the rules through PostgREST.
--
-- What changes:
-- 1. Security. Row-level security on planning_question_visibility_rules, with a read policy for signed-in users
--    (active rules whose parent question is on the form: active and in an active section, as the portal reads
--    them; Beta reads them through this policy). anon and authenticated lose INSERT, UPDATE, DELETE, TRUNCATE,
--    REFERENCES and TRIGGER on the five catalogue tables and USAGE/UPDATE on their id sequences; they keep
--    SELECT. service_role and postgres keep everything. Beta only reads the catalogue, so it keeps working.
-- 2. New question settings on planning_questions: min_value and max_value (NUMBER; an empty min_value means 0),
--    integer_only (NUMBER, default true), placeholder, value_when_hidden (saved by the portal when a show/hide
--    rule hides the question and its parent question is answered) and protected (see 4). Plus updated_at on all
--    five tables (created_at on sections), kept by a trigger, and checks: question and section keys match
--    ^[a-z][a-z0-9_]{2,62}$, min_value <= max_value, whole limits for whole-number questions, and a rule never
--    names the same question twice. An index on weekly_planning_answers (question_key) for counting answers.
-- 3. planning_catalog_version: one row whose number goes up with every change to the five tables (statement
--    triggers). The portal sends it with each save and re-reads the questions when it changed.
--    planning_catalog_changes: the change history (who, when, table, key, before and after, note). The DA
--    Management page writes it in the same transaction as each change. Only postgres (its owner) can read it.
-- 4. Protection triggers (they also hold in Supabase Studio and for service_role):
--    - question and section keys never change; questions and sections are never deleted (retire them with
--      active = false); the catalogue tables cannot be truncated;
--    - a question's type changes only while no saved plan has answered it;
--    - an answer choice's value and a grid row's key never change once a saved plan used them, and such a choice
--      or row can be retired but not deleted;
--    - a protected question (reports, Call-ins, Presentations or Beta read it by key) stays active, keeps its
--      type and stays required if it is required; its answer choices and grid rows stay exactly as they are
--      (no new ones, same values and keys, all active); its show/hide rules stay exactly as they are (none can be
--      added, changed, turned off or deleted), so a rule can never hide it; it has no value saved while hidden;
--      a section holding an active protected question stays active; the section key_indicators_conversion (Beta
--      shows it first) stays active; none of the five tables can be truncated;
--    - a show/hide rule cannot make a question depend on itself, directly or through other rules.
--    To remove the protection from a question on purpose (after checking every report that reads it), run as
--    postgres: BEGIN; SET LOCAL planning_catalog.unprotect = 'on'; UPDATE public.planning_questions SET
--    protected = false WHERE question_key = '...'; COMMIT; To change a protected question's choices, rows or
--    rules on purpose, do that in the same transaction, then set protected = true again before COMMIT.
-- 5. Data (each change is written to planning_catalog_changes with actor 'Migration 024', which the rollback
--    reads):
--    - protected = true for the load-bearing keys (the six Key Indicators actual and goal keys, the six *_plan
--      keys, weekly_action_plan, information_up_chain, ward_coordination_held, ward_coordination_attendance,
--      facebook_finding_days, facebook_friends_found, long_term_service, member_meals_*, member_visits_*);
--    - "1st Time 1st Week" is shown only when "1st Time" is above 0 too (a second rule; the portal already did
--      this), and both follow-ups save 0 while hidden because a count above them is 0 (value_when_hidden '0');
--    - their help texts "Only show when ..." (notes about the rules, now shown to missionaries) are cleared, and
--      the same note on "Who was there?";
--    - grid answers stored as an empty JSON list [] (two, on one draft plan) become {} (the shape Beta and the
--      DL Call-ins read).
-- Nothing else changes: the view active_planning_questions, the answer tables' policies and every function that
-- reads the catalogue stay as they are. The Call-ins summaries (migration 020) read only active questions and do
-- not read the rules table, so their written access checks still match the policies.
--
-- Apply (back up Beta first, e.g. backups/beta-pre-024-<date>.dump; the portal-api and DA Management code of the
-- same round needs these columns, so apply this first). The file is plain ASCII:
--   Get-Content portal-api/migrations/024_planning_catalog.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- It briefly locks the five catalogue tables. If a long query holds them, the file stops after 10 seconds
-- (lock timeout) and changes nothing; run it again.
-- Safe to run again: IF NOT EXISTS, DROP ... IF EXISTS before CREATE, and data changes only where still needed.
-- The last block checks the result (and tries each forbidden change) and stops on any problem.
-- Second version (27 Sep, after review; the first one went live at 12:50 the same day): no new answer choices or
-- grid rows on protected questions (they were allowed and then could never be removed), the show/hide rules and
-- value saved while hidden of protected questions are fixed, the rules table cannot be truncated either, and
-- planning_option_used runs with the caller's rights (it was SECURITY DEFINER and could be called by every
-- signed-in user, so it told them whether any plan in the mission held a given text). Running this file again
-- over the first version applies exactly these changes and nothing else; it warns (and changes nothing) if
-- choices, grid rows, rules or a value saved while hidden were added to protected questions in the meantime.
-- Third version (27 Sep, evening, after a second review; the second one went live at 17:49): signed-in users
-- (Beta) no longer read a rule whose parent question is retired or in a retired section, which the portal
-- already ignored (Beta kept the child hidden, the portal showed and required it); a whole-number question
-- needs whole limits (planning_questions_whole_limits; with a lowest number of 0.5 no whole number fitted the
-- box); and saved answers get an index by question key (DA Management counted them with one full scan per
-- question). Running this file again over the first or second version applies these changes and nothing else.
-- Rollback: 024_planning_catalog_rollback.sql (restores the grants, the rules table without row-level security,
-- the columns, the help texts, the rules and the [] grid answers; it drops the change history and the index).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
-- Everything below is created as postgres, which owns the other catalogue tables and is the login of portal-api
-- and DA Management.
SET LOCAL ROLE postgres;

-- 1. Security ------------------------------------------------------------------------------------------------
ALTER TABLE public.planning_question_visibility_rules ENABLE ROW LEVEL SECURITY;
-- Signed-in users (Beta) read the active rules whose parent question is on the form (active, in an active
-- section), like the portal (planning.CATALOG_SQL). A rule whose parent is retired is ignored in both until the
-- parent comes back; Beta would otherwise keep the child hidden, as its unanswered parent fails the rule.
DROP POLICY IF EXISTS "Authenticated users can read planning visibility rules" ON public.planning_question_visibility_rules;
CREATE POLICY "Authenticated users can read planning visibility rules" ON public.planning_question_visibility_rules
  FOR SELECT TO authenticated USING (
    active = true AND EXISTS (
      SELECT 1 FROM public.planning_questions p JOIN public.planning_question_sections s ON s.id = p.section_id
      WHERE p.question_key = planning_question_visibility_rules.parent_question_key AND p.active AND s.active));

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON
  public.planning_question_sections, public.planning_questions, public.planning_question_options,
  public.planning_question_grid_rows, public.planning_question_visibility_rules
FROM anon, authenticated;
REVOKE USAGE, UPDATE ON SEQUENCE
  public.planning_question_sections_id_seq, public.planning_questions_id_seq, public.planning_question_options_id_seq,
  public.planning_question_grid_rows_id_seq, public.planning_question_visibility_rules_id_seq
FROM anon, authenticated;

-- 2. New settings and checks ------------------------------------------------------------------------------------
ALTER TABLE public.planning_questions
  ADD COLUMN IF NOT EXISTS min_value numeric,
  ADD COLUMN IF NOT EXISTS max_value numeric,
  ADD COLUMN IF NOT EXISTS integer_only boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS placeholder text,
  ADD COLUMN IF NOT EXISTS value_when_hidden text,
  ADD COLUMN IF NOT EXISTS protected boolean NOT NULL DEFAULT false;
ALTER TABLE public.planning_question_sections
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.planning_question_options ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.planning_question_grid_rows ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.planning_question_visibility_rules ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

COMMENT ON COLUMN public.planning_questions.min_value IS 'NUMBER: lowest allowed answer. Empty means 0.';
COMMENT ON COLUMN public.planning_questions.max_value IS 'NUMBER: highest allowed answer. Empty means no limit.';
COMMENT ON COLUMN public.planning_questions.integer_only IS 'NUMBER: only whole numbers.';
COMMENT ON COLUMN public.planning_questions.placeholder IS 'Hint shown inside an empty box.';
COMMENT ON COLUMN public.planning_questions.value_when_hidden IS 'Saved by the portal when a show/hide rule hides the question and its parent question is answered (blank when the parent is blank).';
COMMENT ON COLUMN public.planning_questions.protected IS 'Reports, Call-ins, Presentations or Beta read this key: it stays active, keeps its type and stays required. See migration 024.';

ALTER TABLE public.planning_questions DROP CONSTRAINT IF EXISTS planning_questions_key_format;
ALTER TABLE public.planning_questions ADD CONSTRAINT planning_questions_key_format
  CHECK (question_key ~ '^[a-z][a-z0-9_]{2,62}$');
ALTER TABLE public.planning_questions DROP CONSTRAINT IF EXISTS planning_questions_limits_order;
ALTER TABLE public.planning_questions ADD CONSTRAINT planning_questions_limits_order
  CHECK (min_value IS NULL OR max_value IS NULL OR min_value <= max_value);
ALTER TABLE public.planning_question_sections DROP CONSTRAINT IF EXISTS planning_question_sections_key_format;
ALTER TABLE public.planning_question_sections ADD CONSTRAINT planning_question_sections_key_format
  CHECK (section_key ~ '^[a-z][a-z0-9_]{2,62}$');
ALTER TABLE public.planning_question_visibility_rules DROP CONSTRAINT IF EXISTS planning_visibility_not_self;
ALTER TABLE public.planning_question_visibility_rules ADD CONSTRAINT planning_visibility_not_self
  CHECK (child_question_key <> parent_question_key);
-- A whole-number box counts its steps from its lowest number, so with 0.5 no whole number would be accepted.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(question_key, ', ' ORDER BY question_key) INTO found FROM public.planning_questions
  WHERE integer_only AND (min_value <> trunc(min_value) OR max_value <> trunc(max_value));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These questions take whole numbers only but have a lowest or highest number that is not whole: %. Fix them in DA Management (whole limits, or untick "Whole numbers only"), then run this file again.', found;
  END IF;
END $$;
ALTER TABLE public.planning_questions DROP CONSTRAINT IF EXISTS planning_questions_whole_limits;
ALTER TABLE public.planning_questions ADD CONSTRAINT planning_questions_whole_limits
  CHECK (NOT integer_only OR ((min_value IS NULL OR min_value = trunc(min_value)) AND (max_value IS NULL OR max_value = trunc(max_value))));
-- DA Management counts the saved answers of each question, and the guards below look for answers by key.
CREATE INDEX IF NOT EXISTS weekly_planning_answers_question_key_idx ON public.weekly_planning_answers (question_key);

-- 3. Version and change history ----------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.planning_catalog_version (
  id boolean PRIMARY KEY DEFAULT true CONSTRAINT planning_catalog_version_one_row CHECK (id),
  version bigint NOT NULL DEFAULT 1,
  changed_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.planning_catalog_version (id) VALUES (true) ON CONFLICT (id) DO NOTHING;
COMMENT ON TABLE public.planning_catalog_version IS 'Goes up with every change to the planning question tables (migration 024). The portal re-reads the questions when it changed.';
ALTER TABLE public.planning_catalog_version ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Authenticated users can read the planning catalogue version" ON public.planning_catalog_version;
CREATE POLICY "Authenticated users can read the planning catalogue version" ON public.planning_catalog_version
  FOR SELECT TO authenticated USING (true);
REVOKE ALL ON public.planning_catalog_version FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.planning_catalog_version TO authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.planning_catalog_changes (
  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  changed_at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  actor_user_id uuid,
  table_name text NOT NULL CONSTRAINT planning_catalog_changes_table_check CHECK (table_name IN (
    'planning_question_sections', 'planning_questions', 'planning_question_options',
    'planning_question_grid_rows', 'planning_question_visibility_rules', 'weekly_planning_answers')),
  row_key jsonb NOT NULL,
  before_row jsonb,
  after_row jsonb,
  note text
);
CREATE INDEX IF NOT EXISTS planning_catalog_changes_changed_at_idx ON public.planning_catalog_changes (changed_at DESC, id DESC);
COMMENT ON TABLE public.planning_catalog_changes IS 'Who changed which planning question setting, when, before and after (DA Management "Planning questions"; migration 024).';
ALTER TABLE public.planning_catalog_changes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.planning_catalog_changes FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.planning_catalog_changes_id_seq FROM PUBLIC, anon, authenticated, service_role;
-- Older read-only logins get every new table by default; they need neither.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_readonly') THEN
    EXECUTE 'REVOKE ALL ON public.planning_catalog_changes, public.planning_catalog_version FROM grafana_readonly';
  END IF;
END $$;

-- 4. Triggers ------------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.planning_catalog_touch()
RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW IS DISTINCT FROM OLD THEN
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.planning_catalog_bump_version()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  UPDATE public.planning_catalog_version SET version = version + 1, changed_at = now();
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.planning_catalog_no_truncate()
RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  RAISE EXCEPTION 'The planning questions cannot be emptied (%): saved plans and reports depend on them. Retire items instead (active = false).', TG_TABLE_NAME;
END $$;

-- True when a saved plan used this answer choice of this question (as a choice, in a checkbox list or in a grid).
-- It runs with the caller's rights (SECURITY INVOKER): its callers are the guard triggers below (SECURITY DEFINER,
-- so they run it as postgres) and DA Management (postgres), which see every plan. Nobody else may run it.
CREATE OR REPLACE FUNCTION public.planning_option_used(target_question_key text, target_value text)
RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.weekly_planning_answers a
    WHERE a.question_key = target_question_key
      AND (a.answer_text = target_value
           OR CASE jsonb_typeof(a.answer_json)
                WHEN 'array' THEN a.answer_json ? target_value
                WHEN 'object' THEN EXISTS (SELECT 1 FROM jsonb_each_text(a.answer_json) e WHERE e.value = target_value)
                ELSE false
              END));
$$;

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

CREATE OR REPLACE FUNCTION public.planning_questions_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Planning questions are never deleted ("%"): saved plans keep their answers. Retire it instead.', OLD.question_key;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.question_key IS DISTINCT FROM OLD.question_key THEN
      RAISE EXCEPTION 'The key of a question never changes ("%"): saved answers are linked by it. Change its label, or add a new question.', OLD.question_key;
    END IF;
    IF OLD.protected AND NOT NEW.protected
       AND coalesce(current_setting('planning_catalog.unprotect', true), '') <> 'on' THEN
      RAISE EXCEPTION '"%" is protected because reports read it. See migration 024 to remove the protection on purpose.', OLD.question_key;
    END IF;
    IF NEW.question_type IS DISTINCT FROM OLD.question_type THEN
      IF NEW.protected THEN
        RAISE EXCEPTION '"%" is protected because reports read it, so its type stays %.', OLD.question_key, OLD.question_type;
      END IF;
      IF EXISTS (SELECT 1 FROM public.weekly_planning_answers a WHERE a.question_key = OLD.question_key) THEN
        RAISE EXCEPTION 'Saved plans already answered "%", so its type stays %. Add a new question instead.', OLD.question_key, OLD.question_type;
      END IF;
    END IF;
    IF NEW.protected AND OLD.required AND NOT NEW.required THEN
      RAISE EXCEPTION '"%" is protected because reports read it, so it stays required.', OLD.question_key;
    END IF;
  END IF;
  IF NEW.protected THEN
    IF NOT NEW.active THEN
      RAISE EXCEPTION '"%" is protected because reports read it, so it stays on the form.', NEW.question_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.planning_question_sections s WHERE s.id = NEW.section_id AND s.active) THEN
      RAISE EXCEPTION '"%" is protected because reports read it, so it must be in an active section.', NEW.question_key;
    END IF;
    -- A value saved while hidden would put an answer into reports that nobody gave. It can always be cleared.
    IF NEW.value_when_hidden IS NOT NULL THEN
      IF TG_OP = 'INSERT' THEN
        RAISE EXCEPTION '"%" is protected because reports read it, so nothing is saved for it while hidden.', NEW.question_key;
      ELSIF NOT OLD.protected OR NEW.value_when_hidden IS DISTINCT FROM OLD.value_when_hidden THEN
        RAISE EXCEPTION '"%" is protected because reports read it, so nothing is saved for it while hidden. Clear "value saved while hidden" first.', NEW.question_key;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.planning_question_options_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_key text;
  v_protected boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = NEW.question_id;
    IF v_protected THEN
      RAISE EXCEPTION 'The answer choices of "%" are fixed because reports read them, so no choice can be added.', v_key;
    END IF;
    RETURN NEW;
  END IF;
  SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = OLD.question_id;
  IF TG_OP = 'UPDATE' AND NEW.question_id IS DISTINCT FROM OLD.question_id THEN
    RAISE EXCEPTION 'An answer choice cannot move to another question. Add it there instead.';
  END IF;
  IF v_protected AND (TG_OP = 'DELETE' OR NEW.option_value IS DISTINCT FROM OLD.option_value OR (OLD.active AND NOT NEW.active)) THEN
    RAISE EXCEPTION 'The answer choices of "%" are fixed because reports read them. You can change their labels.', v_key;
  END IF;
  IF (TG_OP = 'DELETE' OR NEW.option_value IS DISTINCT FROM OLD.option_value)
     AND public.planning_option_used(v_key, OLD.option_value) THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Saved plans already chose "%" for "%", so it cannot be deleted. Retire it instead.', OLD.option_label, v_key;
    END IF;
    RAISE EXCEPTION 'Saved plans already chose "%" for "%", so its value stays. You can change its label.', OLD.option_label, v_key;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.planning_question_grid_rows_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_key text;
  v_protected boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = NEW.question_id;
    IF v_protected THEN
      RAISE EXCEPTION 'The rows of "%" are fixed because reports read them, so no row can be added.', v_key;
    END IF;
    RETURN NEW;
  END IF;
  SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = OLD.question_id;
  IF TG_OP = 'UPDATE' AND NEW.question_id IS DISTINCT FROM OLD.question_id THEN
    RAISE EXCEPTION 'A grid row cannot move to another question. Add it there instead.';
  END IF;
  IF v_protected AND (TG_OP = 'DELETE' OR NEW.row_key IS DISTINCT FROM OLD.row_key OR (OLD.active AND NOT NEW.active)) THEN
    RAISE EXCEPTION 'The rows of "%" are fixed because reports read them. You can change their labels.', v_key;
  END IF;
  IF (TG_OP = 'DELETE' OR NEW.row_key IS DISTINCT FROM OLD.row_key)
     AND EXISTS (SELECT 1 FROM public.weekly_planning_answers a
                 WHERE a.question_key = v_key
                   AND CASE WHEN jsonb_typeof(a.answer_json) = 'object' THEN a.answer_json ? OLD.row_key ELSE false END) THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Saved plans already answered the row "%" of "%", so it cannot be deleted. Retire it instead.', OLD.row_label, v_key;
    END IF;
    RAISE EXCEPTION 'Saved plans already answered the row "%" of "%", so its key stays. You can change its label.', OLD.row_label, v_key;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.planning_visibility_rules_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- The rules of a protected question are fixed: a rule could hide it, and a hidden question is neither asked nor
  -- required. (The ward coordination grid keeps its rule "shown when the meeting was held".)
  IF TG_OP <> 'INSERT' THEN
    IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.question_key = OLD.child_question_key AND q.protected) THEN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so this rule cannot be deleted.', OLD.child_question_key;
      END IF;
      IF (NEW.child_question_key, NEW.parent_question_key, NEW.operator, NEW.comparison_value, NEW.active)
         IS DISTINCT FROM (OLD.child_question_key, OLD.parent_question_key, OLD.operator, OLD.comparison_value, OLD.active) THEN
        RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so this rule cannot be changed or turned off.', OLD.child_question_key;
      END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
      RETURN OLD;
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.question_key = NEW.child_question_key AND q.protected) THEN
    IF TG_OP = 'INSERT' THEN
      RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so no rule can be added. It is always shown.', NEW.child_question_key;
    ELSIF NEW.child_question_key IS DISTINCT FROM OLD.child_question_key THEN
      RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so no rule can be moved to it.', NEW.child_question_key;
    END IF;
  END IF;
  IF NEW.active AND EXISTS (
    WITH RECURSIVE parents(question_key) AS (
      SELECT NEW.parent_question_key
      UNION
      SELECT r.parent_question_key
      FROM public.planning_question_visibility_rules r JOIN parents p ON r.child_question_key = p.question_key
      WHERE r.active AND r.id IS DISTINCT FROM NEW.id
    )
    SELECT 1 FROM parents WHERE question_key = NEW.child_question_key
  ) THEN
    RAISE EXCEPTION 'This rule would make "%" depend on itself (through "%"). Choose another question.', NEW.child_question_key, NEW.parent_question_key;
  END IF;
  RETURN NEW;
END $$;

-- Who may run them: nobody needs to call these directly (triggers run them); written down by name like 019.
REVOKE ALL ON FUNCTION
  public.planning_catalog_touch(), public.planning_catalog_bump_version(), public.planning_catalog_no_truncate(),
  public.planning_question_sections_guard(), public.planning_questions_guard(),
  public.planning_question_options_guard(), public.planning_question_grid_rows_guard(), public.planning_visibility_rules_guard()
FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
  public.planning_catalog_touch(), public.planning_catalog_bump_version(), public.planning_catalog_no_truncate(),
  public.planning_question_sections_guard(), public.planning_questions_guard(),
  public.planning_question_options_guard(), public.planning_question_grid_rows_guard(), public.planning_visibility_rules_guard()
TO authenticated, service_role;
-- Only its owner (postgres: the triggers above and DA Management) runs this one.
REVOKE ALL ON FUNCTION public.planning_option_used(text, text) FROM PUBLIC, anon, authenticated, service_role;

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['planning_question_sections', 'planning_questions', 'planning_question_options',
                           'planning_question_grid_rows', 'planning_question_visibility_rules'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_touch ON public.%I', t);
    EXECUTE format('CREATE TRIGGER planning_catalog_touch BEFORE UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.planning_catalog_touch()', t);
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_version ON public.%I', t);
    EXECUTE format('CREATE TRIGGER planning_catalog_version AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_bump_version()', t);
    EXECUTE format('DROP TRIGGER IF EXISTS planning_catalog_no_truncate ON public.%I', t);
    EXECUTE format('CREATE TRIGGER planning_catalog_no_truncate BEFORE TRUNCATE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_no_truncate()', t);
  END LOOP;
END $$;
DROP TRIGGER IF EXISTS planning_catalog_guard ON public.planning_question_sections;
CREATE TRIGGER planning_catalog_guard BEFORE UPDATE OR DELETE ON public.planning_question_sections
  FOR EACH ROW EXECUTE FUNCTION public.planning_question_sections_guard();
DROP TRIGGER IF EXISTS planning_catalog_guard ON public.planning_questions;
CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR UPDATE OR DELETE ON public.planning_questions
  FOR EACH ROW EXECUTE FUNCTION public.planning_questions_guard();
DROP TRIGGER IF EXISTS planning_catalog_guard ON public.planning_question_options;
CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR UPDATE OR DELETE ON public.planning_question_options
  FOR EACH ROW EXECUTE FUNCTION public.planning_question_options_guard();
DROP TRIGGER IF EXISTS planning_catalog_guard ON public.planning_question_grid_rows;
CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR UPDATE OR DELETE ON public.planning_question_grid_rows
  FOR EACH ROW EXECUTE FUNCTION public.planning_question_grid_rows_guard();
DROP TRIGGER IF EXISTS planning_catalog_guard ON public.planning_question_visibility_rules;
CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR UPDATE OR DELETE ON public.planning_question_visibility_rules
  FOR EACH ROW EXECUTE FUNCTION public.planning_visibility_rules_guard();

-- 5. Data --------------------------------------------------------------------------------------------------------
WITH marked AS (
  UPDATE public.planning_questions SET protected = true
  WHERE NOT protected AND question_key = ANY (ARRAY[
    'nm_sacrament_attendance', 'nm_sacrament_attendance_goal', 'baptisms_confirmations_actual', 'baptisms_confirmations_goal',
    'baptismal_dates_actual', 'baptismal_dates_goal', 'sacrament_attendance_actual', 'sacrament_attendance_goal',
    'members_at_lessons_actual', 'members_at_lessons_goal', 'friends_found_actual', 'friends_found_goal',
    'nm_sacrament_attendance_plan', 'baptisms_confirmations_plan', 'baptismal_dates_plan', 'sacrament_attendance_plan',
    'members_at_lessons_plan', 'friends_found_plan', 'weekly_action_plan', 'information_up_chain',
    'ward_coordination_held', 'ward_coordination_attendance', 'facebook_finding_days', 'facebook_friends_found',
    'long_term_service', 'member_meals_active_actual', 'member_meals_less_active_actual', 'member_meals_part_member_actual',
    'member_meals_goal', 'member_visits_active_actual', 'member_visits_less_active_actual', 'member_visits_part_member_actual',
    'member_visits_goal'])
  RETURNING question_key
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 024', 'planning_questions', jsonb_build_object('question_keys', jsonb_agg(question_key ORDER BY question_key)),
       jsonb_build_object('protected', false), jsonb_build_object('protected', true),
       'Protected: Dashboards, Call-ins, Presentations or Beta read these keys.'
FROM marked HAVING count(*) > 0;

WITH hidden AS (
  UPDATE public.planning_questions SET value_when_hidden = '0'
  WHERE value_when_hidden IS NULL AND question_key IN ('sacrament_first_time', 'sacrament_first_time_first_week')
  RETURNING question_key
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 024', 'planning_questions', jsonb_build_object('question_key', question_key),
       jsonb_build_object('value_when_hidden', NULL), jsonb_build_object('value_when_hidden', '0'),
       'Saves 0 while hidden because a count above it is 0 (as the portal already did).'
FROM hidden;

WITH old AS (
  SELECT id, question_key, help_text FROM public.planning_questions
  WHERE question_key IN ('sacrament_first_time', 'sacrament_first_time_first_week', 'ward_coordination_attendance')
    AND help_text LIKE 'Only show when %'
  FOR UPDATE
), cleared AS (
  UPDATE public.planning_questions q SET help_text = NULL FROM old WHERE q.id = old.id
  RETURNING old.question_key, old.help_text
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 024', 'planning_questions', jsonb_build_object('question_key', question_key),
       jsonb_build_object('help_text', help_text), jsonb_build_object('help_text', NULL),
       'Help text was a note about the show/hide rule, which is now kept in the rules.'
FROM cleared;

WITH added AS (
  INSERT INTO public.planning_question_visibility_rules (child_question_key, parent_question_key, operator, comparison_value, active)
  SELECT 'sacrament_first_time_first_week', 'sacrament_first_time', 'greater_than', '0', true
  WHERE EXISTS (SELECT 1 FROM public.planning_questions WHERE question_key = 'sacrament_first_time_first_week')
    AND EXISTS (SELECT 1 FROM public.planning_questions WHERE question_key = 'sacrament_first_time')
  ON CONFLICT ON CONSTRAINT planning_visibility_unique DO NOTHING
  RETURNING *
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 024', 'planning_question_visibility_rules', jsonb_build_object('id', id), NULL, to_jsonb(added),
       '"1st Time 1st Week" is shown only when "1st Time" is above 0 (as the portal already did).'
FROM added;

-- Runs as postgres without request claims, which the answers guard (guard_shared_planning_child) treats as a
-- trusted write: the plan's own updated_at stays as it is.
WITH old AS (
  SELECT a.id, a.weekly_area_report_id, a.question_key, a.answer_json FROM public.weekly_planning_answers a
  JOIN public.planning_questions q ON q.question_key = a.question_key AND q.question_type = 'GRID'
  WHERE a.answer_json = '[]'::jsonb
  FOR UPDATE OF a
), converted AS (
  UPDATE public.weekly_planning_answers a SET answer_json = '{}'::jsonb FROM old WHERE a.id = old.id
  RETURNING old.id, old.weekly_area_report_id, old.question_key
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 024', 'weekly_planning_answers', jsonb_build_object('id', id),
       jsonb_build_object('weekly_area_report_id', weekly_area_report_id, 'question_key', question_key, 'answer_json', '[]'::jsonb),
       jsonb_build_object('weekly_area_report_id', weekly_area_report_id, 'question_key', question_key, 'answer_json', '{}'::jsonb),
       'Empty grid answer stored as a list; grids are stored as {row: choice}.'
FROM converted;

-- 6. Check ---------------------------------------------------------------------------------------------------------
DO $$
DECLARE
  found text;
  refused boolean;
  protected_keys text[] := ARRAY[
    'nm_sacrament_attendance', 'nm_sacrament_attendance_goal', 'baptisms_confirmations_actual', 'baptisms_confirmations_goal',
    'baptismal_dates_actual', 'baptismal_dates_goal', 'sacrament_attendance_actual', 'sacrament_attendance_goal',
    'members_at_lessons_actual', 'members_at_lessons_goal', 'friends_found_actual', 'friends_found_goal',
    'nm_sacrament_attendance_plan', 'baptisms_confirmations_plan', 'baptismal_dates_plan', 'sacrament_attendance_plan',
    'members_at_lessons_plan', 'friends_found_plan', 'weekly_action_plan', 'information_up_chain',
    'ward_coordination_held', 'ward_coordination_attendance', 'facebook_finding_days', 'facebook_friends_found',
    'long_term_service', 'member_meals_active_actual', 'member_meals_less_active_actual', 'member_meals_part_member_actual',
    'member_meals_goal', 'member_visits_active_actual', 'member_visits_less_active_actual', 'member_visits_part_member_actual',
    'member_visits_goal'];
  probe text;
  probes text[] := ARRAY[
    $p$UPDATE public.planning_questions SET question_key = 'friends_found_renamed' WHERE question_key = 'friends_found_actual'$p$,
    $p$DELETE FROM public.planning_questions WHERE question_key = 'social_media_plan'$p$,
    $p$UPDATE public.planning_questions SET active = false WHERE question_key = 'friends_found_goal'$p$,
    $p$UPDATE public.planning_questions SET question_type = 'TEXT' WHERE question_key = 'weekly_action_plan'$p$,
    $p$UPDATE public.planning_questions SET required = false WHERE question_key = 'sacrament_attendance_actual'$p$,
    $p$UPDATE public.planning_questions SET protected = false WHERE question_key = 'long_term_service'$p$,
    $p$UPDATE public.planning_question_sections SET section_key = 'key_indicators' WHERE section_key = 'key_indicators_conversion'$p$,
    $p$UPDATE public.planning_question_sections SET active = false WHERE section_key = 'key_indicators_conversion'$p$,
    $p$DELETE FROM public.planning_question_sections WHERE section_key = 'weekly_plans'$p$,
    $p$DELETE FROM public.planning_question_options o USING public.planning_questions q WHERE q.id = o.question_id AND q.question_key = 'ward_coordination_attendance'$p$,
    $p$UPDATE public.planning_question_grid_rows r SET row_key = r.row_key || '_x' FROM public.planning_questions q WHERE q.id = r.question_id AND q.question_key = 'ward_coordination_attendance'$p$,
    $p$INSERT INTO public.planning_question_visibility_rules (child_question_key, parent_question_key, operator, comparison_value) VALUES ('sacrament_attendance_actual', 'sacrament_first_time_first_week', 'greater_than', '0')$p$,
    $p$TRUNCATE public.planning_question_options$p$,
    $p$TRUNCATE public.planning_question_visibility_rules$p$,
    $p$INSERT INTO public.planning_question_options (question_id, option_value, option_label) SELECT id, 'maybe', 'Maybe' FROM public.planning_questions WHERE question_key = 'ward_coordination_attendance'$p$,
    $p$INSERT INTO public.planning_question_grid_rows (question_id, row_key, row_label) SELECT id, 'bishop', 'Bishop' FROM public.planning_questions WHERE question_key = 'ward_coordination_attendance'$p$,
    $p$INSERT INTO public.planning_question_visibility_rules (child_question_key, parent_question_key, operator, comparison_value) VALUES ('friends_found_goal', 'ward_coordination_held', 'equals', 'true')$p$,
    $p$UPDATE public.planning_question_visibility_rules SET active = false WHERE child_question_key = 'ward_coordination_attendance'$p$,
    $p$DELETE FROM public.planning_question_visibility_rules WHERE child_question_key = 'ward_coordination_attendance'$p$,
    $p$UPDATE public.planning_questions SET value_when_hidden = '0' WHERE question_key = 'friends_found_goal'$p$,
    $p$UPDATE public.planning_questions SET integer_only = true, min_value = 0.5 WHERE question_key = 'friends_found_goal'$p$];
  ward_rules_seen bigint;
  retired_parent_rules_seen bigint;
  known_rows text[] := ARRAY['elders_quorum_representative', 'relief_society_representative', 'primary_presidency_representative',
    'ward_missionaries', 'priests_quorum_assistant', 'oldest_young_women_presidency', 'senior_service_missionaries', 'gemiko_leader'];
BEGIN
  SELECT string_agg(c.relname, ', ') INTO found FROM pg_class c
  WHERE c.oid IN ('public.planning_question_sections'::regclass, 'public.planning_questions'::regclass,
                  'public.planning_question_options'::regclass, 'public.planning_question_grid_rows'::regclass,
                  'public.planning_question_visibility_rules'::regclass, 'public.planning_catalog_version'::regclass,
                  'public.planning_catalog_changes'::regclass)
    AND NOT c.relrowsecurity;
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: row-level security is off on %', found; END IF;

  SELECT string_agg(format('%s on %s', r.rolname, c.relname), ', ') INTO found
  FROM pg_class c CROSS JOIN (VALUES ('anon'), ('authenticated')) r(rolname)
  WHERE c.oid IN ('public.planning_question_sections'::regclass, 'public.planning_questions'::regclass,
                  'public.planning_question_options'::regclass, 'public.planning_question_grid_rows'::regclass,
                  'public.planning_question_visibility_rules'::regclass, 'public.planning_catalog_version'::regclass,
                  'public.planning_catalog_changes'::regclass)
    AND (has_table_privilege(r.rolname, c.oid, 'INSERT') OR has_table_privilege(r.rolname, c.oid, 'UPDATE')
         OR has_table_privilege(r.rolname, c.oid, 'DELETE') OR has_table_privilege(r.rolname, c.oid, 'TRUNCATE'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may still change the catalogue: %', found; END IF;
  IF has_table_privilege('authenticated', 'public.planning_catalog_changes', 'SELECT')
     OR has_table_privilege('anon', 'public.planning_catalog_changes', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: signed-in users can read the change history.';
  END IF;
  IF NOT has_table_privilege('authenticated', 'public.planning_question_visibility_rules', 'SELECT')
     OR NOT has_table_privilege('authenticated', 'public.planning_catalog_version', 'SELECT')
     OR NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'planning_question_visibility_rules'
                    AND cmd = 'SELECT' AND 'authenticated' = ANY (roles)) THEN
    RAISE EXCEPTION 'Check failed: signed-in users (Beta and the portal) cannot read the rules or the version.';
  END IF;

  SELECT string_agg(format('%s(%s)', p.proname, pg_get_function_identity_arguments(p.oid)), ', ') INTO found
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.proname IN ('planning_catalog_touch', 'planning_catalog_bump_version',
        'planning_catalog_no_truncate', 'planning_option_used', 'planning_question_sections_guard', 'planning_questions_guard',
        'planning_question_options_guard', 'planning_question_grid_rows_guard', 'planning_visibility_rules_guard')
    AND (has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT coalesce(p.proconfig @> ARRAY['search_path=public, pg_temp'], false)
         OR pg_get_userbyid(p.proowner) <> 'postgres');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: grants, owner or search_path of %', found; END IF;
  IF (SELECT p.prosecdef FROM pg_proc p WHERE p.oid = 'public.planning_option_used(text, text)'::regprocedure)
     OR has_function_privilege('authenticated', 'public.planning_option_used(text, text)', 'EXECUTE')
     OR has_function_privilege('service_role', 'public.planning_option_used(text, text)', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: planning_option_used must run with the caller''s rights and only for postgres.';
  END IF;

  IF (SELECT count(*) FROM pg_trigger t WHERE NOT t.tgisinternal AND t.tgname LIKE 'planning_catalog_%'
        AND t.tgrelid IN ('public.planning_question_sections'::regclass, 'public.planning_questions'::regclass,
                          'public.planning_question_options'::regclass, 'public.planning_question_grid_rows'::regclass,
                          'public.planning_question_visibility_rules'::regclass)) <> 20 THEN
    RAISE EXCEPTION 'Check failed: expected 20 catalogue triggers.';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgname = 'planning_catalog_guard' AND NOT t.tgisinternal
               AND t.tgrelid IN ('public.planning_question_options'::regclass, 'public.planning_question_grid_rows'::regclass,
                                 'public.planning_question_visibility_rules'::regclass)
               AND (t.tgtype & 28) <> 28) THEN  -- 4 INSERT + 8 DELETE + 16 UPDATE
    RAISE EXCEPTION 'Check failed: the choices, grid rows and rules guards must run on insert, update and delete.';
  END IF;
  IF (SELECT count(*) FROM public.planning_catalog_version) <> 1 THEN
    RAISE EXCEPTION 'Check failed: planning_catalog_version needs exactly one row.';
  END IF;
  IF to_regclass('public.weekly_planning_answers_question_key_idx') IS NULL THEN
    RAISE EXCEPTION 'Check failed: the index of saved answers by question key is missing.';
  END IF;
  -- As a signed-in user (Beta): the ward coordination rule is read; a rule whose parent question was just retired
  -- is not (the retire is undone at once).
  BEGIN
    EXECUTE 'SET LOCAL ROLE authenticated';
    SELECT count(*) INTO ward_rules_seen FROM public.planning_question_visibility_rules
    WHERE child_question_key = 'ward_coordination_attendance' AND parent_question_key = 'ward_coordination_held';
    EXECUTE 'SET LOCAL ROLE postgres';
    UPDATE public.planning_questions SET active = false WHERE question_key = 'sacrament_first_time';
    EXECUTE 'SET LOCAL ROLE authenticated';
    SELECT count(*) INTO retired_parent_rules_seen FROM public.planning_question_visibility_rules
    WHERE parent_question_key = 'sacrament_first_time';
    RAISE EXCEPTION USING ERRCODE = 'P0003', MESSAGE = 'undo the probe';
  EXCEPTION WHEN SQLSTATE 'P0003' THEN
    NULL;
  END;
  IF current_user <> 'postgres' OR ward_rules_seen IS DISTINCT FROM 1 OR retired_parent_rules_seen IS DISTINCT FROM 0 THEN
    RAISE EXCEPTION 'Check failed: signed-in users must read the active rules, except those whose parent question is retired (seen: %, %).',
      ward_rules_seen, retired_parent_rules_seen;
  END IF;

  SELECT string_agg(k, ', ') INTO found FROM unnest(protected_keys) k
  WHERE NOT EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.question_key = k AND q.protected AND q.active);
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: not protected or not active: %', found; END IF;
  -- The ward coordination grid keeps the 8 rows, 3 choices and rule that the DL Call-ins in Beta read.
  IF (SELECT count(*) FROM public.planning_question_grid_rows r JOIN public.planning_questions q ON q.id = r.question_id
      WHERE q.question_key = 'ward_coordination_attendance' AND r.active AND r.row_key = ANY (known_rows)) <> 8
     OR (SELECT count(*) FROM public.planning_question_options o JOIN public.planning_questions q ON q.id = o.question_id
         WHERE q.question_key = 'ward_coordination_attendance' AND o.active AND o.option_value IN ('yes', 'no', 'dont_have_one')) <> 3
     OR NOT EXISTS (SELECT 1 FROM public.planning_question_visibility_rules WHERE child_question_key = 'ward_coordination_attendance'
                    AND parent_question_key = 'ward_coordination_held' AND operator = 'equals' AND lower(comparison_value) = 'true' AND active) THEN
    RAISE EXCEPTION 'Check failed: the ward coordination grid lost one of its 8 rows, 3 choices or its rule.';
  END IF;
  -- Choices, grid rows and rules that DA Management added to protected questions while the first version of this
  -- file was live are fixed now too. They are listed (nothing is changed) so they can be removed on purpose.
  SELECT string_agg(item, '; ' ORDER BY item) INTO found FROM (
    SELECT format('choice %s of %s', o.option_value, q.question_key) AS item
    FROM public.planning_catalog_changes c
    JOIN public.planning_questions q ON q.question_key = c.row_key->>'question_key' AND q.protected
    JOIN public.planning_question_options o ON o.question_id = q.id AND o.option_value = c.row_key->>'option_value'
    WHERE c.table_name = 'planning_question_options' AND c.before_row IS NULL
    UNION
    SELECT format('row %s of %s', r.row_key, q.question_key)
    FROM public.planning_catalog_changes c
    JOIN public.planning_questions q ON q.question_key = c.row_key->>'question_key' AND q.protected
    JOIN public.planning_question_grid_rows r ON r.question_id = q.id AND r.row_key = c.row_key->>'row_key'
    WHERE c.table_name = 'planning_question_grid_rows' AND c.before_row IS NULL
    UNION
    SELECT format('rule %s on %s', v.id, v.child_question_key)
    FROM public.planning_catalog_changes c
    JOIN public.planning_question_visibility_rules v ON c.row_key ? 'id' AND v.id = (c.row_key->>'id')::bigint
    JOIN public.planning_questions q ON q.question_key = v.child_question_key AND q.protected
    WHERE c.table_name = 'planning_question_visibility_rules' AND c.before_row IS NULL AND c.actor <> 'Migration 024'
    UNION
    SELECT format('value saved while hidden of %s', q.question_key) FROM public.planning_questions q
    WHERE q.protected AND q.value_when_hidden IS NOT NULL
  ) added;
  IF found IS NOT NULL THEN
    RAISE WARNING 'Added to protected questions before this version of 024 and now fixed (if one was a mistake, remove it on purpose as the header explains): %', found;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.planning_question_visibility_rules WHERE child_question_key = 'sacrament_first_time_first_week'
                 AND parent_question_key = 'sacrament_first_time' AND operator = 'greater_than' AND comparison_value = '0' AND active) THEN
    RAISE EXCEPTION 'Check failed: the rule "1st Time 1st Week" when "1st Time" > 0 is missing.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.weekly_planning_answers a JOIN public.planning_questions q ON q.question_key = a.question_key
             WHERE q.question_type = 'GRID' AND a.answer_json = '[]'::jsonb) THEN
    RAISE EXCEPTION 'Check failed: an empty grid answer is still stored as [].';
  END IF;

  -- Every forbidden change must be refused (each try is undone).
  FOREACH probe IN ARRAY probes LOOP
    refused := false;
    BEGIN
      EXECUTE probe;
    EXCEPTION WHEN raise_exception OR check_violation THEN
      refused := true;
    END;
    IF NOT refused THEN RAISE EXCEPTION 'Check failed: this change was not refused: %', probe; END IF;
  END LOOP;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
