-- Rollback of migration 035 (zone presentations): removes the owner of every presentation.
-- Afterwards every deck belongs to the mission again: only managers change it, and ZLs and STLs open only the decks
-- whose access rule shares them. The deck folders are not touched. Roll back the portal-api and presentation manager
-- code first (the round 7 code reads this column). Safe to run twice.
BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'portal' AND table_name = 'presentation_access' AND column_name = 'owner_zone_id') THEN
    RAISE NOTICE 'Rollback 035: % presentation(s) owned by a zone go back to the mission',
      (SELECT count(*) FROM portal.presentation_access WHERE owner_zone_id IS NOT NULL);
  END IF;
END $$;

ALTER TABLE portal.presentation_access DROP COLUMN IF EXISTS owner_zone_id;

COMMIT;
