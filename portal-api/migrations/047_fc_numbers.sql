-- Migration 047 (Oct 2026): the FindeChristus (FC) number of a person. Run on Beta only, as supabase_admin.
--
-- Why: the People upload (DA Management) recognised "the same person?" by name, area and baptism date, and asked a manager
-- when it was not sure. The FindeChristus number is exact: the same number is always the same person, whatever the
-- spelling of the name or the area. DA Management now reads an "FC number" column, stores it with the person and uses it as
-- the first, exact match key (roster-importer/people_match.py). A number is stored only where there was none, a stored number
-- is never overwritten, and the same number for two stored people is flagged on the check page (it is NOT forbidden here:
-- the data may already have such a case, and the owner decides which record is right).
--
-- What changes (two columns, a check and two partial indexes; no data is changed):
-- 1. public.new_members.fc_number text and public.baptismal_date_people.fc_number text. Empty = not known. The check
--    allows what DA Management writes: capitals, digits and dashes, 3 to 30 characters (it removes a leading "FC" and
--    spaces before saving).
-- 2. A partial index on each (fc_number where it is not empty) for the exact lookup.
-- It is a number that belongs to a named person, so it is as visible as that person's name already is: whoever may read the
-- person's row may read the number. No dashboard view reads it.
--
-- Apply (back up Beta first; after 039). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/047_fc_numbers.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Apply this BEFORE the new DA Management image: its People upload and Historical CSV pages read the column.
-- Safe to run again: IF NOT EXISTS, then a check that stops on any problem.
-- Rollback: 047_fc_numbers_rollback.sql (removes the numbers; take a backup first if they should be kept).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.new_members') IS NULL OR to_regclass('public.baptismal_date_people') IS NULL THEN
    RAISE EXCEPTION 'The people tables are missing (baseline or migration 023).';
  END IF;
END $$;

ALTER TABLE public.new_members ADD COLUMN IF NOT EXISTS fc_number text;
ALTER TABLE public.baptismal_date_people ADD COLUMN IF NOT EXISTS fc_number text;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'new_members_fc_number_check'
                 AND conrelid = 'public.new_members'::regclass) THEN
    ALTER TABLE public.new_members ADD CONSTRAINT new_members_fc_number_check
      CHECK (fc_number IS NULL OR fc_number ~ '^[A-Z0-9-]{3,30}$');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'baptismal_date_people_fc_number_check'
                 AND conrelid = 'public.baptismal_date_people'::regclass) THEN
    ALTER TABLE public.baptismal_date_people ADD CONSTRAINT baptismal_date_people_fc_number_check
      CHECK (fc_number IS NULL OR fc_number ~ '^[A-Z0-9-]{3,30}$');
  END IF;
END $$;

COMMENT ON COLUMN public.new_members.fc_number IS 'The FindeChristus (FC) number: the exact key DA Management uses to recognise the same person. Capitals, digits, dashes. Never overwritten by an upload.';
COMMENT ON COLUMN public.baptismal_date_people.fc_number IS 'The FindeChristus (FC) number: the exact key DA Management uses to recognise the same person. Capitals, digits, dashes. Never overwritten by an upload.';

CREATE INDEX IF NOT EXISTS new_members_fc_number_idx ON public.new_members (fc_number) WHERE fc_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS baptismal_date_people_fc_number_idx ON public.baptismal_date_people (fc_number) WHERE fc_number IS NOT NULL;

-- Check: the columns, the rules and the indexes are there, and no dashboards view shows the number.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(t, ', ') INTO found
  FROM unnest(ARRAY['new_members', 'baptismal_date_people']) t
  WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = t AND column_name = 'fc_number')
     OR to_regclass('public.' || t || '_fc_number_idx') IS NULL
     OR NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_fc_number_check'
                    AND conrelid = ('public.' || t)::regclass);
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: fc_number is not set up on %', found; END IF;

  SELECT string_agg(c.table_name, ', ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'dashboards' AND c.column_name = 'fc_number';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a dashboards view shows the FC number: %', found; END IF;
END $$;

COMMIT;
