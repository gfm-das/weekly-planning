-- Migration 040 (Oct 2026): Import history knows the batch kind PLACES (DA Management > Places: closing and reopening
-- zones, districts and areas, with where the districts or areas inside go). Run on Beta only, as supabase_admin.
-- Nothing else changes. Rollback: 040_places_admin_rollback.sql (undo and remove PLACES batches in Import history first).
BEGIN;
ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (
  'TRANSFER', 'HISTORICAL', 'ACCOUNT',
  'AREA_DATA', 'FINDING', 'ZONE_HISTORY', 'REFERRAL_ARCHIVE', 'RATES', 'BAPTISMS', 'PEOPLE', 'PLACES'));
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%PLACES%') THEN
    RAISE EXCEPTION 'Check failed: the batch kind PLACES is not allowed.';
  END IF;
END $$;
COMMIT;
