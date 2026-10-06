-- Rollback of migration 040. Run on Beta as supabase_admin. Undo and remove every PLACES batch in Import history first:
-- the old constraint does not know the kind.
BEGIN;
ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (
  'TRANSFER', 'HISTORICAL', 'ACCOUNT',
  'AREA_DATA', 'FINDING', 'ZONE_HISTORY', 'REFERRAL_ARCHIVE', 'RATES', 'BAPTISMS', 'PEOPLE'));
COMMIT;
