-- Migration 048 (Oct 2026): DA Management can delete a retired Weekly Planning question (and a closed place), with Undo.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
-- (Numbering: 046 is Geo data and 047 the FC numbers on the same round-13 branch; renumber if another branch took 048 first.)
--
-- Why: the owner wants a Data Analyst to be able to delete an obsolete area, zone or Weekly Planning question after it was
-- retired or renamed (DA Management > Delete retired, roster-importer/retire.py). The step shows what is attached, can move
-- the history onto the item that replaced it, makes a database backup first and is one entry in Import history with Undo.
-- Places need no change in the database: the foreign keys already refuse to delete a place that something points to, and
-- DA Management moves or removes what points to it first. Questions are different: migration 024 made the database refuse
-- every delete of a planning question ("Planning questions are never deleted"), also for DA Management.
--
-- What changes:
-- 1. Import history accepts the batch kind RETIRE (one deleted place or question, with everything it moved or removed).
--    The list of kinds is read from the running constraint and RETIRE is added to it, so kinds added by other migrations
--    are kept.
-- 2. public.planning_questions_guard(): a DELETE is now allowed in ONE case: the transaction says so on purpose
--    (SET LOCAL planning_catalog.allow_delete = 'on', the way planning_catalog.unprotect works for removing protection) AND the
--    question is retired (active = false) AND it is not protected. Every other delete is refused with the same message as
--    before: a question that is on the form, or that Dashboards, Call-ins, Presentations or Archetypal Health read, is never
--    deleted. Nothing else in the function changes. The guards of the answer choices, grid rows and show/hide rules already
--    allow a delete when the question is not protected and no saved plan used the choice or row, which DA Management makes
--    true first (it moves or deletes the saved answers before the choices). Sections are still never deleted.
-- The setting can only be used by a login that may delete from public.planning_questions at all: postgres (DA Management) and
-- service_role. anon and authenticated have no DELETE right on the catalogue tables (migration 024).
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/048_retire_places_questions.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Apply this BEFORE the new DA Management image (its Undo knows the kind RETIRE).
-- Safe to run again: CREATE OR REPLACE and a kind list that already has RETIRE is kept, then a check that stops on any problem.
-- Rollback: 048_retire_places_questions_rollback.sql (Undo the RETIRE entries in Import history first).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regprocedure('public.planning_questions_guard()') IS NULL OR to_regclass('public.roster_import_batches') IS NULL THEN
    RAISE EXCEPTION 'Apply 024_planning_catalog.sql and the DA Management migrations first.';
  END IF;
END $$;

-- 1. The kind RETIRE (the constraint belongs to supabase_admin's table, so this runs before the switch to postgres).
DO $$
DECLARE
  kinds text[];
BEGIN
  SELECT array_agg(DISTINCT m[1] ORDER BY m[1]) INTO kinds
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') AS m
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.conname = 'roster_import_batches_kind_check';
  IF kinds IS NULL OR NOT ('TRANSFER' = ANY (kinds) AND 'AREA_DATA' = ANY (kinds)) THEN
    RAISE EXCEPTION 'The list of batch kinds could not be read from roster_import_batches_kind_check (found: %).', kinds;
  END IF;
  IF NOT ('RETIRE' = ANY (kinds)) THEN
    kinds := kinds || 'RETIRE'::text;
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

-- 2. The guard. It is the function of migration 024 (as the baseline has it) with the DELETE branch changed.
SET LOCAL ROLE postgres;

CREATE OR REPLACE FUNCTION public.planning_questions_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
BEGIN
  IF TG_OP = 'DELETE' THEN
    -- Only on purpose (DA Management > Delete retired sets this for its own transaction), only a retired question that no
    -- report reads. Everything else is refused as before.
    IF coalesce(current_setting('planning_catalog.allow_delete', true), '') = 'on' AND NOT OLD.active AND NOT OLD.protected THEN
      RETURN OLD;
    END IF;
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
END $function$;

-- Who may run it: nobody needs to call it directly (the trigger runs it); written down by name like migration 019.
REVOKE ALL ON FUNCTION public.planning_questions_guard() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.planning_questions_guard() TO authenticated, service_role;

-- Check: the kind is allowed, the guard knows the setting, and the guard is still SECURITY DEFINER with a fixed search_path.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%RETIRE%') THEN
    RAISE EXCEPTION 'Check failed: the batch kind RETIRE is not allowed.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = 'public.planning_questions_guard()'::regprocedure
                 AND p.prosecdef AND p.prosrc LIKE '%planning_catalog.allow_delete%'
                 AND array_to_string(p.proconfig, ',') LIKE 'search_path=%') THEN
    RAISE EXCEPTION 'Check failed: public.planning_questions_guard() is not as expected.';
  END IF;
  IF has_function_privilege('public', 'public.planning_questions_guard()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.planning_questions_guard()', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: PUBLIC or anon can run planning_questions_guard().';
  END IF;
END $$;

COMMIT;
