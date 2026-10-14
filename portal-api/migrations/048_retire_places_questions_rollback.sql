-- Rollback of 048_retire_places_questions.sql. Run on Beta only, as supabase_admin.
--
-- What it does: puts the guard of migration 024 back (a planning question can never be deleted again) and takes RETIRE out of
-- the list of batch kinds (the other kinds are kept). Import history entries of kind RETIRE are deleted with it: their rows
-- would no longer be allowed.
-- FIRST Undo every RETIRE entry in DA Management > Import history that you still want to undo: afterwards the entries are
-- gone and a deleted question or place can only come back from the backup that the entry names (the file is in the backups
-- folder of this computer).
-- Do it together with the code rollback (the DA Management image before this change).
--
-- Apply:
--   (Get-Content portal-api/migrations/048_retire_places_questions_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check. Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

DELETE FROM public.roster_import_batches WHERE kind = 'RETIRE';

DO $$
DECLARE
  kinds text[];
BEGIN
  SELECT array_agg(DISTINCT m[1] ORDER BY m[1]) INTO kinds
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') AS m
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.conname = 'roster_import_batches_kind_check';
  IF kinds IS NULL OR NOT ('TRANSFER' = ANY (kinds)) THEN
    RAISE EXCEPTION 'The list of batch kinds could not be read from roster_import_batches_kind_check (found: %).', kinds;
  END IF;
  IF 'RETIRE' = ANY (kinds) THEN
    kinds := array_remove(kinds, 'RETIRE');
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

SET LOCAL ROLE postgres;

-- The guard of migration 024 (as the baseline has it).
CREATE OR REPLACE FUNCTION public.planning_questions_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
END $function$;

REVOKE ALL ON FUNCTION public.planning_questions_guard() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.planning_questions_guard() TO authenticated, service_role;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
             AND pg_get_constraintdef(oid) LIKE '%RETIRE%') THEN
    RAISE EXCEPTION 'Rollback check failed: RETIRE is still an allowed batch kind.';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = 'public.planning_questions_guard()'::regprocedure
             AND p.prosrc LIKE '%planning_catalog.allow_delete%') THEN
    RAISE EXCEPTION 'Rollback check failed: the guard still knows allow_delete.';
  END IF;
END $$;

COMMIT;
