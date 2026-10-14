-- Rollback of 051_vollzogen_records.sql. Run on Beta only, as supabase_admin.
--
-- What it does: removes the dashboards view and the table public.vollzogen_records WITH THE LIST (names included), deletes the
-- Import history entries of kind VOLLZOGEN (their changed rows go with them: ON DELETE CASCADE), and takes VOLLZOGEN out of
-- the list of batch kinds (the other kinds are kept). Nothing else is touched. The portal's people (new_members) are not
-- changed: the upload never wrote to them.
-- Do it together with the code rollback (the DA Management image without the Vollzogen upload), or the Data uploads pages
-- show an error. Take a backup first if the list should be kept.
-- Order: roll back anything that reads dashboards.vollzogen_week or public.vollzogen_records first (a dashboard or a portal
-- page built on them); this file stops with a "depends on" error otherwise (safely: nothing is changed).
--
-- Apply:
--   (Get-Content portal-api/migrations/051_vollzogen_records_rollback.sql) -join "`n" |
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

DROP VIEW IF EXISTS dashboards.vollzogen_week;
DROP TABLE IF EXISTS public.vollzogen_records;

DELETE FROM public.roster_import_batches WHERE kind = 'VOLLZOGEN';

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
  IF 'VOLLZOGEN' = ANY (kinds) THEN
    kinds := array_remove(kinds, 'VOLLZOGEN');
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(n.nspname || '.' || c.relname, ', ') INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'dashboards' AND c.relname = 'vollzogen_week')
     OR (n.nspname = 'public' AND c.relname = 'vollzogen_records');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: still there: %', found; END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
             AND pg_get_constraintdef(oid) LIKE '%VOLLZOGEN%') THEN
    RAISE EXCEPTION 'Rollback check failed: VOLLZOGEN is still an allowed batch kind.';
  END IF;
END $$;

COMMIT;
