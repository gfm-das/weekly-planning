-- Rollback of 047_fc_numbers.sql. Run on Beta only, as supabase_admin.
--
-- What it does: removes the two indexes, the two checks and the column fc_number from public.new_members and
-- public.baptismal_date_people, WITH THE NUMBERS (take a backup first if they should be kept). It also takes the key
-- fc_number out of the before/after rows that Import history recorded for those two tables, so Undo of an older batch
-- still works after the column is gone. Nothing else is touched.
-- Do it together with the code rollback (the DA Management image before this change), or the People upload and the
-- Historical CSV pages show an error: they read the column.
--
-- Apply:
--   (Get-Content portal-api/migrations/047_fc_numbers_rollback.sql) -join "`n" |
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

UPDATE public.roster_import_changes
SET before_row = before_row - 'fc_number', after_row = after_row - 'fc_number'
WHERE table_name IN ('new_members', 'baptismal_date_people')
  AND (before_row ? 'fc_number' OR after_row ? 'fc_number');

DROP INDEX IF EXISTS public.new_members_fc_number_idx;
DROP INDEX IF EXISTS public.baptismal_date_people_fc_number_idx;
ALTER TABLE public.new_members DROP CONSTRAINT IF EXISTS new_members_fc_number_check;
ALTER TABLE public.baptismal_date_people DROP CONSTRAINT IF EXISTS baptismal_date_people_fc_number_check;
ALTER TABLE public.new_members DROP COLUMN IF EXISTS fc_number;
ALTER TABLE public.baptismal_date_people DROP COLUMN IF EXISTS fc_number;

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(table_name, ', ') INTO found
  FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name IN ('new_members', 'baptismal_date_people') AND column_name = 'fc_number';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: fc_number is still on %', found; END IF;
END $$;

COMMIT;
